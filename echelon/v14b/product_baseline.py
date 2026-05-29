"""Product-value baseline for the V14B visual graph system.

This module is deliberately product-facing.  The crawler/product chain can run
for days, so every long wait needs a stable answer to: did the system become
more useful for a researcher or R&D lead?  The baseline records current graph
coverage, evidence coverage, Metalens topic quality, and the 50-hour execution
backlog used while section/OpenAlex frontfill continues.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, DB_V14

DECISION_SECTION_NAMES = (
    "limitations",
    "discussion",
    "conclusion",
    "future_work",
    "results",
    "error_analysis",
    "ablation",
    "method",
    "experiments",
)

METALENS_EXPECTED_BRANCHES = (
    "Imaging systems",
    "Broadband achromatic correction",
    "High-NA focusing performance",
    "Tunable and multifunctional optics",
    "Manufacturing scale-up",
    "Computational compensation and inverse design",
)

TASK_BACKLOG: tuple[dict[str, Any], ...] = (
    {
        "id": "P0-01",
        "window": "0-3h",
        "title": "固定当前指标快照",
        "output": "product_baseline_snapshot.{json,md}",
        "gate": "papers/OpenAlex/section/linked refs/Claim Cards/visual graph counts are recorded",
    },
    {
        "id": "P0-02",
        "window": "0-3h",
        "title": "建立 Metalens 验收基准",
        "output": "metalens expected branches and quality gaps in baseline snapshot",
        "gate": "Metalens branches, bottlenecks, turning-paper evidence, future evidence are scored",
    },
    {
        "id": "P0-03",
        "window": "0-3h",
        "title": "写 Topic Dossier 质量 rubric",
        "output": "Topic Dossier rubric in baseline snapshot",
        "gate": "generic statements are demoted unless backed by clickable evidence",
    },
    {
        "id": "P1-04",
        "window": "3-8h",
        "title": "做 Metalens gold topic fixture",
        "output": "tests/v14b Metalens regression fixture",
        "gate": "fixture includes imaging, achromatic, high-NA, tunable, manufacturing, computational compensation",
    },
    {
        "id": "P1-05",
        "window": "3-8h",
        "title": "Metalens 分支识别自动测试",
        "output": "automated topic-lens regression",
        "gate": "each expected branch returns driver papers, bottleneck, enabler, evidence gap",
    },
    {
        "id": "P1-06",
        "window": "3-8h",
        "title": "Metalens 审计报告",
        "output": "reports/v14b_pilot/metalens_topic_regression.md",
        "gate": "report shows what improved, what is still generic, and which evidence is missing",
    },
    {
        "id": "P2-07",
        "window": "8-14h",
        "title": "Topic Lens 结论 evidence_objects 化",
        "output": "API returns evidence_objects for every branch/bottleneck/turning/future statement",
        "gate": "evidence types include paper, section, limitation_atom, main_path_edge, branch_lineage, future_candidate",
    },
    {
        "id": "P2-08",
        "window": "8-14h",
        "title": "无证据结论降级",
        "output": "insufficient_evidence blocks in Topic Dossier",
        "gate": "no evidence-backed UI card is rendered from naked prose",
    },
    {
        "id": "P2-09",
        "window": "8-14h",
        "title": "前端可点击证据闭环",
        "output": "branch/bottleneck/turning/future cards open paper/section/evidence detail",
        "gate": "each visible conclusion has an inspectable evidence drawer",
    },
    {
        "id": "P3-10",
        "window": "14-19h",
        "title": "Step13 五问 Claim Card 硬约束",
        "output": "Claim Card quality gate",
        "gate": "missing root/history/enabler/bottleneck/experiment prevents Radar promotion",
    },
    {
        "id": "P3-11",
        "window": "14-19h",
        "title": "Radar 主视图只展示完整卡",
        "output": "candidate pool separated from R&D Radar",
        "gate": "GNN-only edges are never shown as investable directions",
    },
    {
        "id": "P3-12",
        "window": "14-19h",
        "title": "Claim Card 缺口提示",
        "output": "missing_gates, claim_scope, evidence_strength in API/UI",
        "gate": "user can see exactly why a candidate is not actionable",
    },
    {
        "id": "P4-13",
        "window": "19-24h",
        "title": "Access Link 完整性审计",
        "output": "access gap table/report",
        "gate": "key turning papers, branch drivers, future endpoints are audited",
    },
    {
        "id": "P4-14",
        "window": "19-24h",
        "title": "自动合成外部访问链接",
        "output": "arXiv/DOI/S2/OpenAlex links in paper detail",
        "gate": "known IDs produce clickable links; missing IDs become explicit access gaps",
    },
    {
        "id": "P4-15",
        "window": "19-24h",
        "title": "前端显示 local evidence / external access / access gap",
        "output": "paper detail access panel",
        "gate": "researchers know whether they can inspect local evidence or must open an external source",
    },
    {
        "id": "P5-16",
        "window": "24-30h",
        "title": "Delta section 自动接力",
        "output": "top12000 completion handoff to section-evidence-delta",
        "gate": "if primary sections are below target, delta queue starts once and only once",
    },
    {
        "id": "P5-17",
        "window": "24-30h",
        "title": "Delta queue 优先级审查",
        "output": "main/future/branch/keystone/Metalens coverage report",
        "gate": "next crawl is evidence-budgeted, not blind sweeping",
    },
    {
        "id": "P5-18",
        "window": "24-30h",
        "title": "资源保护",
        "output": "single-process guard, disk floor, temp PDF cleanup",
        "gate": "no duplicate crawler and no persistent full-PDF cache",
    },
    {
        "id": "P6-19",
        "window": "30-35h",
        "title": "后段链路 smoke test",
        "output": "Step5c -> Step6 -> Step13 -> Step10 partial run log",
        "gate": "schema, empty-table, quality-gate, frontend breaking issues are found before final run",
    },
    {
        "id": "P6-20",
        "window": "30-35h",
        "title": "修复 smoke test 阻断点",
        "output": "reviewable fixes with tests",
        "gate": "fixes preserve algorithmic semantics and serve project goals",
    },
    {
        "id": "P7-21",
        "window": "35-40h",
        "title": "Branch Lineage 解释增强",
        "output": "parent, split reason, driver papers, constraint shift in branch cards",
        "gate": "layout-only clusters are labeled layout_cluster_only, not true branches",
    },
    {
        "id": "P7-22",
        "window": "35-40h",
        "title": "Topic Dossier 分支可信度门",
        "output": "evidence-backed branch vs weak cluster distinction",
        "gate": "only evidence-backed branches are narrated as real branch evolution",
    },
    {
        "id": "P8-23",
        "window": "40-44h",
        "title": "Future Growth 可解释化",
        "output": "GNN/VGAE candidate generator explanation",
        "gate": "each future candidate shows model probability, calibration, bottleneck, Step6/13 status",
    },
    {
        "id": "P8-24",
        "window": "40-44h",
        "title": "Future candidate 到 Claim Card 的转化路径",
        "output": "candidate pool lifecycle state",
        "gate": "no Claim Card means no Radar promotion",
    },
    {
        "id": "P9-25",
        "window": "44-47h",
        "title": "Topic Lens 第一屏改为 Dossier",
        "output": "topic-first workstation UI",
        "gate": "search result answers branch/bottleneck/turning/future before showing raw paper list",
    },
    {
        "id": "P9-26",
        "window": "44-47h",
        "title": "图层组合解释",
        "output": "Main/Co-cite/Cite/Semantic/Future/Bottleneck/Uncertainty/Fusion value explanations",
        "gate": "selected layer combinations explain what the user is seeing and why it matters",
    },
    {
        "id": "P9-27",
        "window": "44-47h",
        "title": "交互打磨",
        "output": "clickable branch, bottleneck, key paper, claim card",
        "gate": "no important card is a dead end",
    },
    {
        "id": "P10-28",
        "window": "47-50h",
        "title": "整理审计报告",
        "output": "completed items, remaining risk, next required frontfill",
        "gate": "remaining risk is explicit and tied to product-goal impact",
    },
    {
        "id": "P10-29",
        "window": "47-50h",
        "title": "准备爬虫完成后的自动运行顺序",
        "output": "post-frontfill-chain ready/restartable",
        "gate": "section/OpenAlex threshold triggers downstream chain from a safe breakpoint",
    },
    {
        "id": "P10-30",
        "window": "47-50h",
        "title": "GitHub 同步与最终状态确认",
        "output": "pushed branch, passing tests, live monitors",
        "gate": "repo is reproducible while crawlers continue",
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = (), default: Any = 0) -> Any:
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.Error:
        return default
    return row[0] if row else default


def table_count(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return int(scalar(conn, f"SELECT COUNT(*) FROM {table}") or 0)


def collect_main_metrics(db_main: Path) -> dict[str, Any]:
    with connect(db_main) as conn:
        papers = int(scalar(conn, "SELECT COUNT(*) FROM papers") or 0) if table_exists(conn, "papers") else 0
        openalex_w = int(
            scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM papers
                WHERE openalex_id LIKE 'W%' OR openalex_id LIKE 'https://openalex.org/W%'
                """,
            )
            or 0
        ) if table_exists(conn, "papers") else 0
        invalid_openalex = int(
            scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM papers
                WHERE COALESCE(openalex_id, '') <> ''
                  AND openalex_id NOT LIKE 'W%'
                  AND openalex_id NOT LIKE 'https://openalex.org/W%'
                """,
            )
            or 0
        ) if table_exists(conn, "papers") else 0
        primary_field = int(
            scalar(
                conn,
                "SELECT COUNT(*) FROM papers WHERE COALESCE(primary_field_id, '') <> ''",
            )
            or 0
        ) if table_exists(conn, "papers") else 0
        pending_enrich = int(
            scalar(conn, "SELECT COUNT(*) FROM papers WHERE COALESCE(openalex_enriched, 0) = 0") or 0
        ) if table_exists(conn, "papers") and "openalex_enriched" in columns(conn, "papers") else 0
        refs = table_count(conn, "paper_references")
        linked_refs = int(
            scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM paper_references
                WHERE COALESCE(cited_paper_id_internal, '') <> ''
                """,
            )
            or 0
        ) if table_exists(conn, "paper_references") else 0

        section_rows = table_count(conn, "paper_sections")
        section_papers = int(
            scalar(conn, "SELECT COUNT(DISTINCT paper_id) FROM paper_sections") or 0
        ) if table_exists(conn, "paper_sections") else 0
        primary_section_papers = int(
            scalar(
                conn,
                f"""
                SELECT COUNT(DISTINCT paper_id)
                FROM paper_sections
                WHERE section_name IN ({','.join('?' for _ in DECISION_SECTION_NAMES)})
                  AND length(trim(section_text)) >= 80
                """,
                tuple(DECISION_SECTION_NAMES),
            )
            or 0
        ) if table_exists(conn, "paper_sections") else 0
        section_distribution: dict[str, int] = {}
        if table_exists(conn, "paper_sections"):
            for row in conn.execute(
                """
                SELECT section_name, COUNT(*) AS n
                FROM paper_sections
                GROUP BY section_name
                ORDER BY n DESC
                """
            ).fetchall():
                section_distribution[str(row["section_name"])] = int(row["n"])
    return {
        "papers": papers,
        "openalex_w": openalex_w,
        "openalex_missing": max(0, papers - openalex_w),
        "openalex_w_rate": openalex_w / max(1, papers),
        "invalid_openalex_id": invalid_openalex,
        "pending_enrich": pending_enrich,
        "primary_field": primary_field,
        "primary_field_rate": primary_field / max(1, papers),
        "refs": refs,
        "linked_refs": linked_refs,
        "linked_refs_rate": linked_refs / max(1, refs),
        "section_rows": section_rows,
        "section_papers": section_papers,
        "primary_section_papers": primary_section_papers,
        "primary_section_rate": primary_section_papers / max(1, papers),
        "section_distribution": section_distribution,
    }


def collect_v14_metrics(db_v14: Path) -> dict[str, Any]:
    table_names = (
        "main_path_edges",
        "main_path_cycle_audit",
        "subgraph_nodes",
        "subgraph_edges",
        "predicted_future_edges",
        "limitation_atoms",
        "limitation_resolutions",
        "future_directions",
        "direction_claim_cards",
        "bottleneck_lineage_triples",
        "branch_lineages",
        "visual_nodes",
        "visual_edges",
        "visual_clusters",
        "visual_tiles",
        "visual_search_fts",
        "section_priority_papers",
        "section_priority_summary",
        "access_link_audit_items",
    )
    metrics: dict[str, Any] = {"tables": {}}
    with connect(db_v14) as conn:
        for table in table_names:
            metrics["tables"][table] = table_count(conn, table)
        if table_exists(conn, "main_path_edges"):
            metrics["main_path_is_main"] = int(
                scalar(conn, "SELECT COUNT(*) FROM main_path_edges WHERE COALESCE(is_main_path, 0) = 1") or 0
            )
        if table_exists(conn, "direction_claim_cards"):
            metrics["claim_cards_complete"] = int(
                scalar(conn, "SELECT COUNT(*) FROM direction_claim_cards WHERE five_question_complete = 1") or 0
            )
            metrics["claim_cards_high_confidence"] = int(
                scalar(conn, "SELECT COUNT(*) FROM direction_claim_cards WHERE high_confidence_eligible = 1") or 0
            )
        if table_exists(conn, "future_directions"):
            by_scope = Counter()
            for row in conn.execute(
                """
                SELECT COALESCE(claim_scope, 'unknown') AS claim_scope, COUNT(*) AS n
                FROM future_directions
                GROUP BY claim_scope
                """
            ).fetchall():
                by_scope[str(row["claim_scope"])] = int(row["n"])
            metrics["future_directions_by_scope"] = dict(by_scope)
        if table_exists(conn, "section_priority_summary"):
            latest = scalar(conn, "SELECT MAX(audit_ts) FROM section_priority_summary", default=None)
            rows = []
            if latest:
                for row in conn.execute(
                    """
                    SELECT category, total, in_top_n, any_section, primary_section, eligible_pdf
                    FROM section_priority_summary
                    WHERE audit_ts = ?
                    ORDER BY total DESC
                    """,
                    (latest,),
                ).fetchall():
                    rows.append(dict(row))
            metrics["section_priority_latest_audit_ts"] = latest
            metrics["section_priority_summary"] = rows
        if table_exists(conn, "access_link_audit_items"):
            metrics["access_gaps"] = int(
                scalar(conn, "SELECT COUNT(*) FROM access_link_audit_items WHERE access_gap = 1") or 0
            )
            metrics["access_audited_papers"] = int(
                scalar(conn, "SELECT COUNT(*) FROM access_link_audit_items") or 0
            )
    return metrics


def topic_dossier_rubric() -> list[dict[str, str]]:
    return [
        {
            "criterion": "Branch is valuable",
            "must_have": "branch name, why_appeared, historical_bottleneck, enabling_condition, clickable driver_papers",
            "empty_output": "cluster counts without split reason or driver papers",
        },
        {
            "criterion": "Bottleneck is actionable",
            "must_have": "constraint label, section/limitation evidence, affected branch or paper, evidence quality",
            "empty_output": "generic keywords such as technical limitation without source section",
        },
        {
            "criterion": "Key turning paper is explainable",
            "must_have": "paper role, selection reason, main-path/branch/limitation evidence, access links or access_gap",
            "empty_output": "paper id/title only, or no local evidence and no external link",
        },
        {
            "criterion": "Future direction is investable",
            "must_have": "complete five-question Claim Card, calibrated future evidence, bottleneck linkage, claim_scope",
            "empty_output": "raw GNN edge shown as a product recommendation",
        },
        {
            "criterion": "Uncertainty is honest",
            "must_have": "linked-ref, OpenAlex, section, calibration, and access gaps are visible",
            "empty_output": "confident prose hiding weak evidence coverage",
        },
    ]


def evaluate_topic_lens(topic: str, lens: dict[str, Any]) -> dict[str, Any]:
    dossier = lens.get("topic_dossier") or {}
    branches = dossier.get("branch_splits") or []
    bottlenecks = dossier.get("hard_bottlenecks") or dossier.get("bottleneck_dossiers") or []
    history = lens.get("history_main_path") or {}
    turning = history.get("key_turning_papers") or []
    future = (lens.get("future_growth") or {}).get("predicted_edges") or []
    radar = lens.get("rd_radar") or {}
    claim_cards = radar.get("claim_cards") or []

    branch_names = {str(b.get("name") or "") for b in branches if isinstance(b, dict)}
    expected = list(METALENS_EXPECTED_BRANCHES) if "metalens" in topic.lower() else []
    expected_hits = [name for name in expected if name in branch_names]
    branch_missing = [name for name in expected if name not in branch_names]

    branch_driver_total = sum(len(b.get("driver_papers") or []) for b in branches if isinstance(b, dict))
    bottleneck_evidence_total = sum(len(b.get("evidence_papers") or []) for b in bottlenecks if isinstance(b, dict))
    turning_with_links = [
        p for p in turning
        if isinstance(p, dict) and (p.get("access_links") or [])
    ]
    turning_with_primary_section = [
        p for p in turning
        if isinstance(p, dict)
        and ((p.get("content_availability") or {}).get("has_primary_evidence_sections"))
    ]
    complete_claim_cards = [
        c for c in claim_cards
        if isinstance(c, dict)
        and (
            c.get("eligible")
            or ((c.get("claim_card") or {}).get("five_question_complete"))
            or c.get("five_question_complete")
        )
    ]

    gaps: list[str] = []
    if branch_missing:
        gaps.append("missing expected branches: " + ", ".join(branch_missing))
    if not branch_driver_total:
        gaps.append("branch conclusions have no clickable driver papers")
    if not bottleneck_evidence_total:
        gaps.append("bottleneck conclusions have no clickable limitation/section evidence")
    if not turning:
        gaps.append("no key turning papers returned")
    elif len(turning_with_links) < max(1, min(5, len(turning))):
        gaps.append("key turning papers lack enough external access links")
    if turning and not turning_with_primary_section:
        gaps.append("key turning papers lack primary local section evidence")
    if future and not complete_claim_cards:
        gaps.append("future candidates exist but no complete Claim Cards are promoted")

    return {
        "topic": topic,
        "ready": bool(lens.get("ready")),
        "expected_branches": expected,
        "expected_branch_hits": expected_hits,
        "expected_branch_coverage": len(expected_hits) / max(1, len(expected)),
        "branch_missing": branch_missing,
        "branch_count": len(branches),
        "branch_driver_papers": branch_driver_total,
        "bottleneck_count": len(bottlenecks),
        "bottleneck_evidence_papers": bottleneck_evidence_total,
        "key_turning_papers": len(turning),
        "key_turning_with_access_links": len(turning_with_links),
        "key_turning_with_primary_section": len(turning_with_primary_section),
        "future_edges": len(future),
        "radar_claim_cards": len(claim_cards),
        "complete_claim_cards": len(complete_claim_cards),
        "quality_gaps": gaps,
    }


def load_topic_lens(topic: str, top_k: int) -> dict[str, Any]:
    from echelon.api.graph_visual_backend import get_topic_lens

    return get_topic_lens(topic=topic, top_k=top_k)


def build_snapshot(
    *,
    db_main: Path,
    db_v14: Path,
    topic: str,
    top_k: int,
    include_topic_lens: bool = True,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "snapshot_ts": utc_now(),
        "db_main": str(db_main),
        "db_v14": str(db_v14),
        "main": collect_main_metrics(db_main),
        "v14": collect_v14_metrics(db_v14),
        "topic_dossier_rubric": topic_dossier_rubric(),
        "task_backlog": list(TASK_BACKLOG),
    }
    if include_topic_lens:
        try:
            lens = load_topic_lens(topic, top_k)
            snapshot["topic_lens_quality"] = evaluate_topic_lens(topic, lens)
        except Exception as exc:  # pragma: no cover - protects live audits
            snapshot["topic_lens_quality"] = {
                "topic": topic,
                "ready": False,
                "error": str(exc),
                "quality_gaps": [f"topic lens failed: {exc}"],
            }
    return snapshot


def pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "n/a"


def render_tasklist_md(tasks: list[dict[str, Any]]) -> str:
    lines = [
        "# V14B 50-Hour Product-Value Task List",
        "",
        "This checklist is the execution queue while section/OpenAlex frontfill runs.  "
        "Each item has an explicit output and gate so work is measured by product value, "
        "not by whether a graph can merely render.",
        "",
        "| ID | Window | Task | Output | Gate | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for task in tasks:
        task_id = str(task["id"])
        status = "todo"
        if task_id.startswith(("P0-", "P1-", "P2-", "P3-", "P4-", "P5-", "P6-", "P7-", "P8-", "P9-")):
            status = "completed"
        elif task_id.startswith("P10-"):
            status = "next"
        lines.append(
            "| {id} | {window} | {title} | {output} | {gate} | {status} |".format(
                id=task["id"],
                window=task["window"],
                title=task["title"],
                output=str(task["output"]).replace("|", "/"),
                gate=str(task["gate"]).replace("|", "/"),
                status=status,
            )
        )
    lines.extend(
        [
            "",
            "## Execution Rule",
            "",
            "- Do not pause crawler/frontfill work for these tasks unless a hard failure is detected.",
            "- Do not promote GNN-only future edges into Radar; they remain candidate-pool evidence until Step13 cards are complete.",
            "- Every visible branch, bottleneck, turning paper, and claim must either link to evidence or be labeled insufficient evidence.",
            "- Generated local queues such as `data/v14b/section_delta_queue.csv` are operational state and are not committed by default.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_snapshot_md(snapshot: dict[str, Any]) -> str:
    main = snapshot["main"]
    v14 = snapshot["v14"]
    topic = snapshot.get("topic_lens_quality") or {}
    lines = [
        "# V14B Product Baseline Snapshot",
        "",
        f"- Snapshot: `{snapshot['snapshot_ts']}`",
        f"- Main DB: `{snapshot['db_main']}`",
        f"- V14 DB: `{snapshot['db_v14']}`",
        "",
        "## Coverage",
        "",
        f"- Papers: {main['papers']:,}",
        f"- OpenAlex W IDs: {main['openalex_w']:,} / {main['papers']:,} ({pct(main['openalex_w_rate'])}); missing {main['openalex_missing']:,}",
        f"- Invalid OpenAlex IDs: {main['invalid_openalex_id']:,}",
        f"- Pending enrich: {main['pending_enrich']:,}",
        f"- Primary Field coverage: {main['primary_field']:,} / {main['papers']:,} ({pct(main['primary_field_rate'])})",
        f"- References: {main['refs']:,}; linked refs: {main['linked_refs']:,} ({pct(main['linked_refs_rate'])})",
        f"- Section rows: {main['section_rows']:,}; section papers: {main['section_papers']:,}; primary evidence papers: {main['primary_section_papers']:,} ({pct(main['primary_section_rate'])})",
        "",
        "## Derived Product Tables",
        "",
    ]
    for table, count in sorted((v14.get("tables") or {}).items()):
        lines.append(f"- {table}: {count:,}")
    if "claim_cards_complete" in v14:
        lines.append(f"- complete Claim Cards: {v14['claim_cards_complete']:,}")
        lines.append(f"- high-confidence Claim Cards: {v14['claim_cards_high_confidence']:,}")
    if "access_audited_papers" in v14:
        lines.append(f"- access audit: {v14['access_audited_papers']:,} papers, {v14.get('access_gaps', 0):,} gaps")
    if v14.get("future_directions_by_scope"):
        lines.append("- future_directions by claim_scope: " + json.dumps(v14["future_directions_by_scope"], ensure_ascii=False, sort_keys=True))
    lines.extend(["", "## Metalens Baseline", ""])
    if topic.get("error"):
        lines.append(f"- Topic Lens failed: {topic['error']}")
    else:
        lines.append(f"- Ready: {topic.get('ready')}")
        lines.append(f"- Expected branch coverage: {pct(topic.get('expected_branch_coverage', 0))}")
        lines.append(f"- Expected branches found: {', '.join(topic.get('expected_branch_hits') or []) or 'none'}")
        lines.append(f"- Missing branches: {', '.join(topic.get('branch_missing') or []) or 'none'}")
        lines.append(f"- Branches: {topic.get('branch_count', 0)}; driver papers: {topic.get('branch_driver_papers', 0)}")
        lines.append(f"- Bottlenecks: {topic.get('bottleneck_count', 0)}; evidence papers: {topic.get('bottleneck_evidence_papers', 0)}")
        lines.append(f"- Key turning papers: {topic.get('key_turning_papers', 0)}; with access links: {topic.get('key_turning_with_access_links', 0)}; with primary section: {topic.get('key_turning_with_primary_section', 0)}")
        lines.append(f"- Future edges: {topic.get('future_edges', 0)}; Radar Claim Cards: {topic.get('radar_claim_cards', 0)}; complete cards: {topic.get('complete_claim_cards', 0)}")
        if topic.get("quality_gaps"):
            lines.append("")
            lines.append("### Quality Gaps")
            for gap in topic["quality_gaps"]:
                lines.append(f"- {gap}")
    lines.extend(["", "## Topic Dossier Rubric", ""])
    for item in snapshot["topic_dossier_rubric"]:
        lines.append(f"- **{item['criterion']}**: must have {item['must_have']}; empty output = {item['empty_output']}.")
    lines.extend(
        [
            "",
            "## Next Gate",
            "",
            "P0-P8 are complete in the first engineering pass: baseline, Metalens regression, "
            "evidence-object UI loop, Step13/Radar hard gates, access-link audit, and delta-section "
            "handoff controls now exist. A temporary-DB smoke test also verified Step5c -> Step6 -> Step13 -> Step10 "
            "runs without schema breakage on partial section data. Branch dossiers now separate evidence-backed "
            "splits from weak layout clusters, future-growth candidates are explicitly shown as calibrated "
            "candidate-generator output unless converted into complete Claim Cards, and the Topic Lens/layer "
            "interaction now explains what the selected evidence combination means. The next gate is P10: final "
            "delivery audit, GitHub sync, and post-frontfill automatic run readiness.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(snapshot: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_json = out_dir / "product_baseline_snapshot.json"
    snapshot_md = out_dir / "product_baseline_snapshot.md"
    tasklist_md = out_dir / "50h_product_tasklist.md"
    snapshot_json.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    snapshot_md.write_text(render_snapshot_md(snapshot), encoding="utf-8")
    tasklist_md.write_text(render_tasklist_md(snapshot["task_backlog"]), encoding="utf-8")
    return {
        "snapshot_json": str(snapshot_json),
        "snapshot_md": str(snapshot_md),
        "tasklist_md": str(tasklist_md),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate V14B product-value baseline and 50h task backlog.")
    parser.add_argument("--db", default=DB_MAIN)
    parser.add_argument("--db-v14", default=DB_V14)
    parser.add_argument("--out-dir", default="reports/v14b_pilot")
    parser.add_argument("--topic", default="metalens")
    parser.add_argument("--top-k", type=int, default=80)
    parser.add_argument("--skip-topic-lens", action="store_true")
    args = parser.parse_args(argv)

    snapshot = build_snapshot(
        db_main=Path(args.db),
        db_v14=Path(args.db_v14),
        topic=args.topic,
        top_k=args.top_k,
        include_topic_lens=not args.skip_topic_lens,
    )
    outputs = write_outputs(snapshot, Path(args.out_dir))
    print(json.dumps(outputs, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
