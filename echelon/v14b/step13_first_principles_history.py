"""Step 13: 第一性原理 + 卡点历史脉络报告.

目标:
1. 把 limitation/resolution/future-growth/branch-lineage 证据汇总成可追溯结论。
2. 避免“泛泛而谈”结论: 每条结论都绑定原子证据、年份、分支和未来边。
3. 产出结构化表 + Markdown/JSON 报告,供 API/可视化继续消费。

该 step 默认不调用外部 LLM,完全基于已入库证据可重跑、可审计。
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from echelon.v14b.config import DB_MAIN, DB_V14, REPORT_DIR
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.utils import add_common_args, setup_logging

logger = logging.getLogger("echelon.v14b.step13_first_principles_history")


SEVERITY_WEIGHT = {
    "high": 1.00,
    "medium": 0.65,
    "low": 0.35,
}


@dataclass(frozen=True)
class PrincipleDef:
    principle_id: str
    name: str
    root_cause: str
    patterns: tuple[str, ...]
    cross_domain_duals: tuple[str, ...]

    def match_count(self, text: str) -> int:
        total = 0
        for p in self.patterns:
            total += len(re.findall(p, text, flags=re.I))
        return total


PRINCIPLES: tuple[PrincipleDef, ...] = (
    PrincipleDef(
        principle_id="FP_OPT_GEOM",
        name="优化几何与可训练性约束",
        root_cause="非凸地形/梯度稳定性/收敛路径受限",
        patterns=(
            r"\bnon[- ]?convex\b",
            r"\bgradient\b",
            r"\bconvergen",
            r"\bunstable\b",
            r"\btraining\b",
            r"\blocal minima\b",
            r"\boptimization\b",
        ),
        cross_domain_duals=(
            "逆向设计中的非凸搜索",
            "强化学习中的信用分配与训练震荡",
            "多模态大模型中的对齐优化不稳定",
        ),
    ),
    PrincipleDef(
        principle_id="FP_INFO_CAPACITY",
        name="信息容量与噪声约束",
        root_cause="信道容量/互信息可分辨性/噪声累积上界",
        patterns=(
            r"\bnoise\b",
            r"\bsnr\b",
            r"\bbandwidth\b",
            r"\bcapacity\b",
            r"\binformation\b",
            r"\bcompression\b",
            r"\bresolution\b",
            r"\bsignal\b",
        ),
        cross_domain_duals=(
            "光学测量中的信噪比瓶颈",
            "通信系统中的容量与误码权衡",
            "视觉表示中的压缩与判别力权衡",
        ),
    ),
    PrincipleDef(
        principle_id="FP_PHYSICAL_CONSTRAINT",
        name="物理实现与制造约束",
        root_cause="材料/热/损耗/工艺容差等硬约束",
        patterns=(
            r"\bfabricat",
            r"\bmanufactur",
            r"\bthermal\b",
            r"\bloss\b",
            r"\bcoupling\b",
            r"\bdispersion\b",
            r"\bdiffraction\b",
            r"\befficien",
        ),
        cross_domain_duals=(
            "光子器件制造容差",
            "硬件系统热设计与功耗边界",
            "实验物理中的器件稳定性",
        ),
    ),
    PrincipleDef(
        principle_id="FP_GENERALIZATION_SHIFT",
        name="泛化与分布漂移约束",
        root_cause="训练分布与部署分布不一致导致失配",
        patterns=(
            r"\bgeneralization\b",
            r"\bdomain shift\b",
            r"\bood\b",
            r"\bout[- ]of[- ]distribution\b",
            r"\bsim[- ]to[- ]real\b",
            r"\brobust",
            r"\bbias\b",
            r"\bhallucinat",
        ),
        cross_domain_duals=(
            "机器人 sim2real 泛化",
            "多模态模型跨域迁移",
            "实验环境到真实场景的稳健性落差",
        ),
    ),
    PrincipleDef(
        principle_id="FP_SCALING_INTEGRATION",
        name="规模化与系统集成约束",
        root_cause="计算/时延/内存/系统耦合成本上升",
        patterns=(
            r"\bscalab",
            r"\blatency\b",
            r"\bmemory\b",
            r"\bcomput",
            r"\bthroughput\b",
            r"\bintegration\b",
            r"\bdeployment\b",
            r"\breal[- ]time\b",
        ),
        cross_domain_duals=(
            "片上光学系统集成与吞吐瓶颈",
            "大模型推理时延与资源约束",
            "跨模块系统工程复杂度爆炸",
        ),
    ),
)

FALLBACK_PRINCIPLE = PrincipleDef(
    principle_id="FP_OTHER",
    name="其他未归类基础约束",
    root_cause="证据文本不足或跨类混合",
    patterns=(),
    cross_domain_duals=(
        "需要更多 section-level 证据后再细分",
    ),
)


def jdumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def ensure_schema(conn_v14: sqlite3.Connection) -> None:
    conn_v14.executescript(
        """
        CREATE TABLE IF NOT EXISTS first_principles_principles (
            principle_id TEXT PRIMARY KEY,
            principle_name TEXT NOT NULL,
            root_cause TEXT,
            bottleneck_score REAL NOT NULL DEFAULT 0,
            unresolved_atoms INTEGER NOT NULL DEFAULT 0,
            resolved_atoms INTEGER NOT NULL DEFAULT 0,
            emergence_year INTEGER,
            peak_backlog_year INTEGER,
            current_backlog REAL,
            evidence_quality_json TEXT,
            top_keywords_json TEXT,
            top_branches_json TEXT,
            top_papers_json TEXT,
            future_alignment_json TEXT,
            direction_tier_json TEXT,
            risk_label TEXT,
            notes_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS first_principles_history_events (
            principle_id TEXT NOT NULL,
            event_year INTEGER NOT NULL,
            opened_atoms INTEGER NOT NULL DEFAULT 0,
            resolved_atoms INTEGER NOT NULL DEFAULT 0,
            opened_score REAL NOT NULL DEFAULT 0,
            resolved_score REAL NOT NULL DEFAULT 0,
            backlog_score REAL NOT NULL DEFAULT 0,
            top_keywords_json TEXT,
            PRIMARY KEY (principle_id, event_year)
        );

        CREATE INDEX IF NOT EXISTS idx_fp_history_year
            ON first_principles_history_events(event_year);
        """
    )
    conn_v14.commit()


def classify_principle(text: str) -> PrincipleDef:
    norm = (text or "").lower()
    best: Optional[PrincipleDef] = None
    best_hits = 0
    for p in PRINCIPLES:
        hits = p.match_count(norm)
        if hits > best_hits:
            best_hits = hits
            best = p
    return best if best and best_hits > 0 else FALLBACK_PRINCIPLE


def load_atoms(conn_main: sqlite3.Connection, conn_v14: sqlite3.Connection) -> list[dict]:
    if not table_exists(conn_v14, "limitation_atoms"):
        return []

    have_visual = table_exists(conn_v14, "visual_nodes")
    visual_join = (
        "LEFT JOIN visual_nodes vn ON vn.paper_id = a.paper_id"
        if have_visual
        else ""
    )
    visual_cols = (
        "vn.branch_id AS branch_id, vn.cluster_id AS cluster_id,"
        if have_visual
        else "NULL AS branch_id, NULL AS cluster_id,"
    )

    rows = conn_v14.execute(
        f"""
        SELECT
            a.atom_id,
            a.paper_id,
            a.description,
            COALESCE(a.keyword, '') AS keyword,
            COALESCE(a.severity, 'medium') AS severity,
            COALESCE(a.evidence_source, 'unknown') AS evidence_source,
            COALESCE(a.evidence_quality, 'unknown') AS evidence_quality,
            COALESCE(a.evidence_weight, 0.35) AS evidence_weight,
            COALESCE(a.source_section_name, '') AS source_section_name,
            COALESCE(a.extractor_method, '') AS extractor_method,
            {visual_cols}
            COALESCE(a.extracted_at, '') AS extracted_at
        FROM limitation_atoms a
        {visual_join}
        """
    ).fetchall()
    if not rows:
        return []

    paper_ids = sorted({str(r["paper_id"]) for r in rows if r["paper_id"]})
    paper_meta: dict[str, dict] = {}
    if paper_ids:
        placeholders = ",".join("?" * len(paper_ids))
        p_rows = conn_main.execute(
            f"""
            SELECT id, title, publication_year, COALESCE(primary_field_id, '') AS primary_field_id
            FROM papers
            WHERE id IN ({placeholders})
            """,
            paper_ids,
        ).fetchall()
        paper_meta = {str(r["id"]): dict(r) for r in p_rows}

    resolved_map: dict[int, tuple[int, int]] = {}
    if table_exists(conn_v14, "limitation_resolutions"):
        rr = conn_v14.execute(
            """
            SELECT atom_id, MIN(COALESCE(resolution_year, 9999)) AS first_year, COUNT(*) AS n
            FROM limitation_resolutions
            WHERE COALESCE(confidence, 0) >= 0.6
            GROUP BY atom_id
            """
        ).fetchall()
        resolved_map = {
            int(r[0]): (0 if r[1] == 9999 else int(r[1]), int(r[2]))
            for r in rr
        }

    atoms: list[dict] = []
    for row in rows:
        atom = dict(row)
        meta = paper_meta.get(str(atom.get("paper_id") or ""), {})
        atom["paper_title"] = meta.get("title") or ""
        atom["publication_year"] = meta.get("publication_year")
        atom["primary_field_id"] = meta.get("primary_field_id") or ""
        atom_id = int(atom.get("atom_id") or 0)
        resolved = resolved_map.get(atom_id)
        if resolved:
            atom["is_resolved"] = 1
            atom["resolved_year"] = int(resolved[0]) if resolved[0] else None
            atom["n_resolutions"] = int(resolved[1])
        else:
            atom["is_resolved"] = 0
            atom["resolved_year"] = None
            atom["n_resolutions"] = 0
        year = atom.get("publication_year")
        atom["publication_year"] = int(year) if year else 2000
        atoms.append(atom)
    return atoms


def load_future_edges(conn_main: sqlite3.Connection, conn_v14: sqlite3.Connection) -> list[dict]:
    if not table_exists(conn_v14, "predicted_future_edges"):
        return []
    have_visual = table_exists(conn_v14, "visual_nodes")
    visual_join = (
        "LEFT JOIN visual_nodes vn ON vn.paper_id = pfe.dst_paper_id"
        if have_visual
        else ""
    )
    visual_col = "vn.branch_id AS dst_branch_id," if have_visual else "NULL AS dst_branch_id,"
    rows = conn_v14.execute(
        f"""
        SELECT
            pfe.src_paper_id,
            pfe.dst_paper_id,
            COALESCE(pfe.prediction_confidence, pfe.calibrated_prob, pfe.predicted_prob, 0) AS confidence,
            COALESCE(pfe.predicted_prob, 0) AS predicted_prob,
            COALESCE(pfe.is_cross_field, 0) AS is_cross_field,
            COALESCE(pfe.calibration_label, 'unknown') AS calibration_label,
            {visual_col}
            COALESCE(pfe.src_year, 0) AS src_year_raw,
            COALESCE(pfe.dst_year, 0) AS dst_year_raw
        FROM predicted_future_edges pfe
        {visual_join}
        """
    ).fetchall()
    if not rows:
        return []

    ids = sorted(
        {
            str(r["src_paper_id"])
            for r in rows
            if r["src_paper_id"]
        }
        | {
            str(r["dst_paper_id"])
            for r in rows
            if r["dst_paper_id"]
        }
    )
    meta: dict[str, dict] = {}
    if ids:
        placeholders = ",".join("?" * len(ids))
        p_rows = conn_main.execute(
            f"""
            SELECT
                id,
                COALESCE(publication_year, 0) AS publication_year,
                COALESCE(title, '') AS title,
                COALESCE(abstract, '') AS abstract,
                COALESCE(primary_field_id, '') AS primary_field_id
            FROM papers
            WHERE id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        meta = {str(r["id"]): dict(r) for r in p_rows}

    enriched = []
    for row in rows:
        rec = dict(row)
        src = meta.get(str(rec.get("src_paper_id") or ""), {})
        dst = meta.get(str(rec.get("dst_paper_id") or ""), {})
        rec["src_year"] = int(src.get("publication_year") or rec.get("src_year_raw") or 0)
        rec["dst_year"] = int(dst.get("publication_year") or rec.get("dst_year_raw") or 0)
        rec["dst_title"] = dst.get("title") or ""
        rec["dst_abstract"] = dst.get("abstract") or ""
        rec["dst_field"] = dst.get("primary_field_id") or ""
        enriched.append(rec)
    return enriched


def load_future_directions(conn_v14: sqlite3.Connection) -> list[dict]:
    if not table_exists(conn_v14, "future_directions"):
        return []
    rows = conn_v14.execute(
        """
        SELECT
            direction_id,
            direction_name,
            COALESCE(confidence, 0) AS confidence,
            COALESCE(evidence_tier, 'unknown') AS evidence_tier,
            COALESCE(claim_scope, 'unknown') AS claim_scope,
            COALESCE(main_path_evidence, '') AS main_path_evidence,
            COALESCE(vgae_evidence, '') AS vgae_evidence,
            COALESCE(limitation_evidence, '') AS limitation_evidence,
            COALESCE(paper_ids_json, '[]') AS paper_ids_json,
            COALESCE(evidence_json, '{}') AS evidence_json
        FROM future_directions
        """
    ).fetchall()
    return [dict(r) for r in rows]


def score_atom(atom: dict) -> float:
    severity = str(atom.get("severity") or "medium").lower()
    severity_w = SEVERITY_WEIGHT.get(severity, 0.55)
    evidence_w = float(atom.get("evidence_weight") or 0.35)
    evidence_w = min(1.0, max(0.05, evidence_w))
    return severity_w * evidence_w


def _safe_json_loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return default


def _top_counter(counter: Counter, n: int = 8) -> list[dict]:
    out = []
    for key, value in counter.most_common(n):
        out.append({"key": key, "value": value})
    return out


def _risk_label(*, unresolved: int, resolved: int, section_ratio: float, future_matches: int) -> str:
    if unresolved >= max(6, resolved * 2) and future_matches < 3:
        return "high_unresolved_pressure"
    if section_ratio < 0.40:
        return "evidence_weak_section_coverage"
    if unresolved > resolved:
        return "moderate_with_uncertainty"
    return "managed_or_resolving"


def build_principle_summary(
    atoms: list[dict],
    future_edges: list[dict],
    future_directions: list[dict],
) -> tuple[list[dict], list[dict], dict]:
    by_principle: dict[str, dict] = {}
    year_min = 9999
    year_max = 0
    total_section_level = 0

    for atom in atoms:
        text = " ".join(
            [
                str(atom.get("keyword") or ""),
                str(atom.get("description") or ""),
                str(atom.get("source_section_name") or ""),
                str(atom.get("paper_title") or ""),
            ]
        )
        p = classify_principle(text)
        pid = p.principle_id
        score = score_atom(atom)
        year = int(atom.get("publication_year") or 2000)
        year_min = min(year_min, year)
        year_max = max(year_max, year)

        entry = by_principle.setdefault(
            pid,
            {
                "principle": p,
                "score_total": 0.0,
                "resolved_atoms": 0,
                "unresolved_atoms": 0,
                "open_score_by_year": defaultdict(float),
                "resolved_score_by_year": defaultdict(float),
                "open_atoms_by_year": defaultdict(int),
                "resolved_atoms_by_year": defaultdict(int),
                "keywords": Counter(),
                "branches": Counter(),
                "qualities": Counter(),
                "fields": Counter(),
                "top_atoms": [],
                "section_level_atoms": 0,
            },
        )

        entry["score_total"] += score
        entry["open_score_by_year"][year] += score
        entry["open_atoms_by_year"][year] += 1

        kw = (atom.get("keyword") or "").strip().lower()
        if kw:
            entry["keywords"][kw] += 1

        branch_id = (atom.get("branch_id") or "").strip()
        if branch_id:
            entry["branches"][branch_id] += score

        quality = (atom.get("evidence_quality") or "unknown").strip()
        entry["qualities"][quality] += 1
        field = (atom.get("primary_field_id") or "").strip()
        if field:
            entry["fields"][field] += 1

        if quality == "section_level" or atom.get("evidence_source") == "structured_sections":
            entry["section_level_atoms"] += 1
            total_section_level += 1

        if int(atom.get("is_resolved") or 0) == 1:
            entry["resolved_atoms"] += 1
            ryear = atom.get("resolved_year")
            if ryear:
                ryear_i = int(ryear)
                entry["resolved_score_by_year"][ryear_i] += score
                entry["resolved_atoms_by_year"][ryear_i] += 1
                year_max = max(year_max, ryear_i)
        else:
            entry["unresolved_atoms"] += 1

        entry["top_atoms"].append(
            {
                "atom_id": int(atom.get("atom_id") or 0),
                "paper_id": atom.get("paper_id"),
                "paper_title": atom.get("paper_title") or "",
                "year": year,
                "score": score,
                "severity": atom.get("severity"),
                "keyword": atom.get("keyword") or "",
                "description": atom.get("description") or "",
                "branch_id": atom.get("branch_id"),
                "evidence_quality": quality,
                "is_resolved": int(atom.get("is_resolved") or 0),
            }
        )

    if year_min == 9999:
        year_min = datetime.now().year
        year_max = year_min
    year_max = max(year_max, datetime.now().year)

    # future edge / direction 归因
    future_by_principle: dict[str, list[dict]] = defaultdict(list)
    for edge in future_edges:
        text = " ".join([edge.get("dst_title") or "", edge.get("dst_abstract") or ""])
        p = classify_principle(text)
        future_by_principle[p.principle_id].append(edge)

    dir_by_principle: dict[str, Counter] = defaultdict(Counter)
    for d in future_directions:
        text = " ".join(
            [
                d.get("direction_name") or "",
                d.get("limitation_evidence") or "",
                d.get("main_path_evidence") or "",
                d.get("vgae_evidence") or "",
            ]
        )
        p = classify_principle(text)
        tier = d.get("evidence_tier") or "unknown"
        dir_by_principle[p.principle_id][tier] += 1

    principle_rows: list[dict] = []
    history_rows: list[dict] = []
    for pid, payload in sorted(by_principle.items(), key=lambda kv: kv[1]["score_total"], reverse=True):
        p = payload["principle"]
        backlog = 0.0
        peak_backlog = 0.0
        peak_year = None
        emergence_year = None
        history_keywords = _top_counter(payload["keywords"], n=5)
        for y in range(year_min, year_max + 1):
            opened_score = float(payload["open_score_by_year"].get(y, 0.0))
            resolved_score = float(payload["resolved_score_by_year"].get(y, 0.0))
            opened_atoms = int(payload["open_atoms_by_year"].get(y, 0))
            resolved_atoms = int(payload["resolved_atoms_by_year"].get(y, 0))
            backlog = max(0.0, backlog + opened_score - resolved_score)
            if opened_atoms > 0 and emergence_year is None:
                emergence_year = y
            if backlog >= peak_backlog:
                peak_backlog = backlog
                peak_year = y
            if opened_atoms == 0 and resolved_atoms == 0:
                continue
            history_rows.append(
                {
                    "principle_id": pid,
                    "event_year": y,
                    "opened_atoms": opened_atoms,
                    "resolved_atoms": resolved_atoms,
                    "opened_score": round(opened_score, 6),
                    "resolved_score": round(resolved_score, 6),
                    "backlog_score": round(backlog, 6),
                    "top_keywords_json": jdumps(history_keywords),
                }
            )

        top_atoms = sorted(
            payload["top_atoms"],
            key=lambda x: (1 - int(x["is_resolved"]), x["score"]),
            reverse=True,
        )[:8]
        future_matches = sorted(
            future_by_principle.get(pid, []),
            key=lambda x: float(x.get("confidence") or 0.0),
            reverse=True,
        )[:8]
        cross_field = sum(1 for x in future_by_principle.get(pid, []) if int(x.get("is_cross_field") or 0) == 1)
        section_ratio = payload["section_level_atoms"] / max(
            1,
            payload["resolved_atoms"] + payload["unresolved_atoms"],
        )
        risk_label = _risk_label(
            unresolved=payload["unresolved_atoms"],
            resolved=payload["resolved_atoms"],
            section_ratio=section_ratio,
            future_matches=len(future_matches),
        )
        principle_rows.append(
            {
                "principle_id": pid,
                "principle_name": p.name,
                "root_cause": p.root_cause,
                "bottleneck_score": round(float(payload["score_total"]), 6),
                "unresolved_atoms": int(payload["unresolved_atoms"]),
                "resolved_atoms": int(payload["resolved_atoms"]),
                "emergence_year": int(emergence_year) if emergence_year else None,
                "peak_backlog_year": int(peak_year) if peak_year else None,
                "current_backlog": round(float(backlog), 6),
                "evidence_quality_json": jdumps(dict(payload["qualities"])),
                "top_keywords_json": jdumps(_top_counter(payload["keywords"], n=10)),
                "top_branches_json": jdumps(_top_counter(payload["branches"], n=8)),
                "top_papers_json": jdumps(top_atoms),
                "future_alignment_json": jdumps(
                    {
                        "future_edge_matches": len(future_matches),
                        "cross_field_matches": int(cross_field),
                        "top_future_edges": [
                            {
                                "src_paper_id": e.get("src_paper_id"),
                                "dst_paper_id": e.get("dst_paper_id"),
                                "confidence": float(e.get("confidence") or 0.0),
                                "calibration_label": e.get("calibration_label"),
                                "dst_branch_id": e.get("dst_branch_id"),
                            }
                            for e in future_matches
                        ],
                        "cross_domain_duals": list(p.cross_domain_duals),
                    }
                ),
                "direction_tier_json": jdumps(dict(dir_by_principle.get(pid, Counter()))),
                "risk_label": risk_label,
                "notes_json": jdumps(
                    {
                        "section_level_ratio": round(section_ratio, 4),
                        "top_fields": _top_counter(payload["fields"], n=5),
                    }
                ),
            }
        )

    totals = {
        "atoms_total": len(atoms),
        "principles_total": len(principle_rows),
        "section_level_total": int(total_section_level),
        "future_edges_total": len(future_edges),
        "future_directions_total": len(future_directions),
        "year_min": year_min,
        "year_max": year_max,
    }
    return principle_rows, history_rows, totals


def write_db(
    conn_v14: sqlite3.Connection,
    principle_rows: list[dict],
    history_rows: list[dict],
) -> None:
    conn_v14.execute("DELETE FROM first_principles_principles")
    conn_v14.execute("DELETE FROM first_principles_history_events")
    if principle_rows:
        conn_v14.executemany(
            """
            INSERT INTO first_principles_principles (
                principle_id, principle_name, root_cause, bottleneck_score,
                unresolved_atoms, resolved_atoms, emergence_year, peak_backlog_year,
                current_backlog, evidence_quality_json, top_keywords_json,
                top_branches_json, top_papers_json, future_alignment_json,
                direction_tier_json, risk_label, notes_json
            ) VALUES (
                :principle_id, :principle_name, :root_cause, :bottleneck_score,
                :unresolved_atoms, :resolved_atoms, :emergence_year, :peak_backlog_year,
                :current_backlog, :evidence_quality_json, :top_keywords_json,
                :top_branches_json, :top_papers_json, :future_alignment_json,
                :direction_tier_json, :risk_label, :notes_json
            )
            """,
            principle_rows,
        )
    if history_rows:
        conn_v14.executemany(
            """
            INSERT INTO first_principles_history_events (
                principle_id, event_year, opened_atoms, resolved_atoms,
                opened_score, resolved_score, backlog_score, top_keywords_json
            ) VALUES (
                :principle_id, :event_year, :opened_atoms, :resolved_atoms,
                :opened_score, :resolved_score, :backlog_score, :top_keywords_json
            )
            """,
            history_rows,
        )
    conn_v14.commit()


def _format_keyword_list(raw: str, top_n: int = 4) -> str:
    items = _safe_json_loads(raw, [])
    if not isinstance(items, list):
        return "N/A"
    keys = []
    for it in items[:top_n]:
        if isinstance(it, dict):
            k = str(it.get("key") or "").strip()
            if k:
                keys.append(k)
    return ", ".join(keys) if keys else "N/A"


def build_markdown(principle_rows: list[dict], totals: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 第一性原理 + 卡点历史脉络报告（V14B）",
        "",
        f"生成时间: {now}",
        "",
        "## 结论摘要",
        "",
        f"- limitation atoms: {int(totals.get('atoms_total') or 0):,}",
        f"- principle buckets: {int(totals.get('principles_total') or 0):,}",
        f"- section-level atoms: {int(totals.get('section_level_total') or 0):,}",
        f"- future edges considered: {int(totals.get('future_edges_total') or 0):,}",
        f"- future directions considered: {int(totals.get('future_directions_total') or 0):,}",
        f"- timeline window: {totals.get('year_min')} - {totals.get('year_max')}",
        "",
        "该报告只基于当前入库证据生成，不对缺失证据区域做强推断。",
        "",
        "## 总览表",
        "",
        "| principle | score | unresolved | resolved | peak backlog year | risk | keywords |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in principle_rows:
        lines.append(
            "| {name} | {score:.2f} | {unresolved} | {resolved} | {peak} | {risk} | {kw} |".format(
                name=row.get("principle_name"),
                score=float(row.get("bottleneck_score") or 0.0),
                unresolved=int(row.get("unresolved_atoms") or 0),
                resolved=int(row.get("resolved_atoms") or 0),
                peak=row.get("peak_backlog_year") or "N/A",
                risk=row.get("risk_label") or "unknown",
                kw=_format_keyword_list(str(row.get("top_keywords_json") or "[]")),
            )
        )

    lines += [
        "",
        "## 分项脉络（证据化）",
        "",
    ]

    for row in principle_rows:
        future = _safe_json_loads(row.get("future_alignment_json") or "{}", {})
        top_papers = _safe_json_loads(row.get("top_papers_json") or "[]", [])
        branches = _safe_json_loads(row.get("top_branches_json") or "[]", [])
        tiers = _safe_json_loads(row.get("direction_tier_json") or "{}", {})
        notes = _safe_json_loads(row.get("notes_json") or "{}", {})

        lines += [
            f"### {row.get('principle_name')} ({row.get('principle_id')})",
            "",
            f"- 第一性原理根因: {row.get('root_cause')}",
            f"- 历史脉络: emergence={row.get('emergence_year') or 'N/A'}, peak_backlog={row.get('peak_backlog_year') or 'N/A'}, current_backlog={float(row.get('current_backlog') or 0):.2f}",
            f"- 未解/已解: {int(row.get('unresolved_atoms') or 0)}/{int(row.get('resolved_atoms') or 0)}",
            f"- 证据质量: `{row.get('evidence_quality_json')}`",
            f"- 分支集中度: `{row.get('top_branches_json')}`",
            f"- Future 对齐: matches={future.get('future_edge_matches', 0)}, cross_field={future.get('cross_field_matches', 0)}, tiers={tiers}",
            f"- 当前风险: {row.get('risk_label')}",
            f"- 横向对偶: {', '.join(future.get('cross_domain_duals') or []) or 'N/A'}",
            f"- section-level ratio: {notes.get('section_level_ratio', 'N/A')}",
            "",
            "证据样本（top atoms）:",
        ]
        if isinstance(top_papers, list) and top_papers:
            for atom in top_papers[:5]:
                lines.append(
                    "- paper_id={pid} year={year} score={score:.2f} kw={kw} resolved={resolved} | {desc}".format(
                        pid=atom.get("paper_id") or "N/A",
                        year=atom.get("year") or "N/A",
                        score=float(atom.get("score") or 0.0),
                        kw=(atom.get("keyword") or "N/A"),
                        resolved=int(atom.get("is_resolved") or 0),
                        desc=(atom.get("description") or "").strip()[:220],
                    )
                )
        else:
            lines.append("- 无可用 atom 证据")
        if isinstance(branches, list) and branches:
            lines.append("")
            lines.append(
                "主导分支: " + ", ".join(
                    f"{b.get('key')}({float(b.get('value') or 0):.2f})"
                    for b in branches[:4]
                    if isinstance(b, dict)
                )
            )
        lines.append("")

    lines += [
        "## 使用边界",
        "",
        "1. 本报告是 evidence-aware 诊断层,不把 exploratory 信号伪装为高置信结论。",
        "2. 若 section-level 证据比例低,卡点解释应标注为弱证据区。",
        "3. 若未来边匹配稀疏,应优先增强候选生成/校准/分支验证,而不是降低阈值。",
        "",
    ]
    return "\n".join(lines) + "\n"


def run_first_principles_history(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    out_dir: Path = REPORT_DIR,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    conn_v14 = get_v14b_conn(db_v14)

    ensure_schema(conn_v14)
    atoms = load_atoms(conn_main, conn_v14)
    future_edges = load_future_edges(conn_main, conn_v14)
    future_directions = load_future_directions(conn_v14)
    principle_rows, history_rows, totals = build_principle_summary(
        atoms=atoms,
        future_edges=future_edges,
        future_directions=future_directions,
    )
    write_db(conn_v14, principle_rows, history_rows)

    md_text = build_markdown(principle_rows, totals)
    report_md = out_dir / "第一性原理_卡点历史脉络报告.md"
    report_json = out_dir / "first_principles_bottleneck_history.json"
    report_md.write_text(md_text, encoding="utf-8")
    report_json.write_text(
        json.dumps(
            {
                "generated_at": datetime.utcnow().isoformat(),
                "totals": totals,
                "principles": principle_rows,
                "history_events": history_rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = {
        "report_md": str(report_md),
        "report_json": str(report_json),
        "principles": len(principle_rows),
        "atoms_total": int(totals.get("atoms_total") or 0),
        "history_events": len(history_rows),
    }
    upsert_step_meta(
        conn_v14,
        "step13_first_principles_history",
        "done",
        records_n=len(principle_rows),
        notes=jdumps(summary),
    )
    conn_main.close()
    conn_v14.close()
    return summary


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step13_first_principles_history",
        description="Step 13: 第一性原理 + 卡点历史脉络报告",
    )
    add_common_args(parser)
    parser.add_argument("--out-dir", default=str(REPORT_DIR))
    args = parser.parse_args(argv)

    setup_logging("step13_first_principles_history", level=getattr(logging, args.log_level))
    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14
    result = run_first_principles_history(
        db_main=db_main,
        db_v14=db_v14,
        out_dir=Path(args.out_dir),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
