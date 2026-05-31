"""Prioritize evidence repairs across the V14B decision workflow.

This module is deliberately report-only.  It consolidates the local raw PDF
store, section atom/search substrate, topic-gap repair plan, typed-stage recall,
and citation/metadata blockers into one ordered queue.  It does not write to the
main databases and it cannot promote scientific claims.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, DB_V14, REPORT_DIR


PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _table_count(db_path: Path, table: str) -> int | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?",
                (table,),
            ).fetchone()
            if not row:
                return None
            count_row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            return int(count_row[0] or 0) if count_row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _gate_by_issue(value_audit: dict[str, Any], issue: str) -> dict[str, Any]:
    for gate in value_audit.get("gates") or []:
        if isinstance(gate, dict) and gate.get("issue") == issue:
            return gate
    return {}


def evidence_repair_contract() -> dict[str, Any]:
    return {
        "claim_scope": "evidence_repair_queue_only",
        "promotion_policy": "no_direct_promotion",
        "pipeline": [
            "raw_pdf_local_store",
            "section_ingest_local_first",
            "section_atoms",
            "exact_fts_bm25",
            "atom_embeddings_fuzzy_recall",
            "section_embeddings_fuzzy_context",
            "typed_stage_candidate_recall",
            "section_atom_chains",
            "Step5c_Step13_evidence_gates",
        ],
        "section_atomization_layer": {
            "allowed_methods": [
                "deterministic parser",
                "rules or lightweight classifier",
                "bounded LLM review only for audit/recheck",
            ],
            "forbidden_methods": ["GNN/VGAE atom generation"],
            "required_trace_fields": [
                "paper_id",
                "section",
                "page",
                "span",
                "atom_type",
                "atom_text",
                "source_storage_uri",
                "parser_contract",
            ],
        },
        "dual_retrieval_layer": {
            "exact": "IDs, DOI, arXiv, title, section name, phrase query, and FTS/BM25 are hard retrieval evidence.",
            "fuzzy": "atom embeddings and section embeddings are candidate recall only; they cannot directly close repair contracts.",
        },
        "graph_algorithm_layer": {
            "allowed_outputs": ["candidate expansion", "candidate ranking", "neighborhood discovery"],
            "forbidden_outputs": ["section atom generation", "direct Step13 conclusion", "Radar promotion"],
            "claim_scope": "retrieval_context_only",
        },
    }


def _priority_item(
    *,
    priority: str,
    action_id: str,
    title: str,
    why: str,
    command: str,
    evidence: dict[str, Any],
    blocks_release: bool,
    can_run_while_broad_ingest_active: bool,
    requires_db_writer_boundary: bool,
    immediate_safe_action: str,
    pipeline_stage: str,
    sort_order: int,
) -> dict[str, Any]:
    return {
        "priority": priority,
        "action_id": action_id,
        "title": title,
        "why": why,
        "command": command,
        "pipeline_stage": pipeline_stage,
        "evidence": evidence,
        "blocks_release": bool(blocks_release),
        "can_run_while_broad_ingest_active": bool(can_run_while_broad_ingest_active),
        "requires_db_writer_boundary": bool(requires_db_writer_boundary),
        "immediate_safe_action": immediate_safe_action,
        "claim_scope": "evidence_repair_queue_only",
        "promotion_policy": "no_direct_promotion",
        "_sort_order": sort_order,
    }


def _topic_gap_plan_summary(topic_plan: dict[str, Any]) -> dict[str, Any]:
    summary = topic_plan.get("summary") or {}
    groups = {
        str(group.get("group_id")): group
        for group in topic_plan.get("action_groups") or []
        if isinstance(group, dict)
    }
    return {
        "contracts": _as_int(summary.get("contracts")),
        "open_contracts": _as_int(summary.get("open_contracts")),
        "closed_contracts": _as_int(summary.get("closed_contracts")),
        "quick_close_contracts": _as_int(summary.get("quick_close_contracts")),
        "local_raw_pdf_ingest_contracts": _as_int(summary.get("local_raw_pdf_ingest_contracts")),
        "closure_state_counts": summary.get("closure_state_counts") or {},
        "action_group_counts": summary.get("action_group_counts") or {},
        "groups": groups,
    }


def _raw_pdf_summary(raw_pdf: dict[str, Any]) -> dict[str, Any]:
    manifest = raw_pdf.get("manifest") or {}
    coverage = raw_pdf.get("candidate_queue_coverage") or {}
    status_counts = manifest.get("status_counts") or {}
    success = _as_int(manifest.get("success_papers"))
    queued = _as_int((status_counts.get("queued") or {}).get("papers"))
    total = _as_int(manifest.get("total_manifest_rows")) or success + queued
    return {
        "status": raw_pdf.get("status") or "missing",
        "manifest_status": manifest.get("status") or "missing",
        "success_papers": success,
        "queued_papers": queued,
        "total_manifest_rows": total,
        "success_probable_pdf_rate": _as_float(manifest.get("success_probable_pdf_rate")),
        "candidate_queue_raw_pdf_available_rate": _as_float(coverage.get("raw_pdf_available_rate")),
        "candidate_queue_raw_pdf_available_papers": _as_int(coverage.get("raw_pdf_available_papers")),
        "candidate_queue_papers": _as_int(coverage.get("queue_papers")),
    }


def _items_from_state(
    *,
    db_counts: dict[str, int | None],
    value_audit: dict[str, Any],
    direction: dict[str, Any],
    release: dict[str, Any],
    raw_pdf: dict[str, Any],
    topic_plan: dict[str, Any],
    stage_recall: dict[str, Any],
    cited_queue: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    topic_gate = _gate_by_issue(value_audit, "Multi-topic Regression")
    topic_summary = _topic_gap_plan_summary(topic_plan)
    raw_summary = _raw_pdf_summary(raw_pdf)
    direction_metrics = direction.get("metrics") or {}
    stage_summary = stage_recall.get("summary") or {}
    open_topic_contracts = topic_summary["open_contracts"]
    topic_gap_blocking = bool(topic_gate.get("topic_gap_blocking")) or open_topic_contracts > 0

    if topic_gap_blocking:
        items.append(
            _priority_item(
                priority="P0",
                action_id="topic_gap_evidence_repair",
                title="Close benchmark-topic evidence gaps before promotion.",
                why=(
                    "Topic Dossier and Radar output are still gated by decision-grade section/atom/chain "
                    "coverage for benchmark topics."
                ),
                command="make topic-gap-repair",
                pipeline_stage="raw_pdf_local_store_to_section_atom_chains",
                evidence={
                    "topic_gap_gate_status": topic_gate.get("status") or "unknown",
                    "topic_gap_decision_grade_section_rate": topic_gate.get("topic_gap_decision_grade_section_rate"),
                    "open_repair_contracts": open_topic_contracts,
                    "quick_close_contracts": topic_summary["quick_close_contracts"],
                    "local_raw_pdf_ingest_contracts": topic_summary["local_raw_pdf_ingest_contracts"],
                    "closure_state_counts": topic_summary["closure_state_counts"],
                    "raw_pdf_candidate_queue_available_rate": raw_summary["candidate_queue_raw_pdf_available_rate"],
                },
                blocks_release=True,
                can_run_while_broad_ingest_active=False,
                requires_db_writer_boundary=True,
                immediate_safe_action=(
                    "Keep the broad crawler/ingest running; review the generated topic-gap repair plan now, "
                    "then run the DB-writing repair command at the next safe section-ingest boundary."
                ),
                sort_order=10,
            )
        )

    if not db_counts.get("section_embeddings"):
        items.append(
            _priority_item(
                priority="P0",
                action_id="post_frontfill_retrieval_rebuild",
                title="Materialize section-level fuzzy context and rebuild downstream gates.",
                why=(
                    "Atom exact/fuzzy search is available, but section-level fuzzy context is not materialized "
                    "in the live DB; Step5c/Step13 should consume the rebuilt retrieval substrate together."
                ),
                command="make post-frontfill-chain",
                pipeline_stage="section_atoms_to_Step5c_Step13",
                evidence={
                    "section_atoms": db_counts.get("section_atoms"),
                    "section_atom_embeddings": db_counts.get("section_atom_embeddings"),
                    "section_embeddings": db_counts.get("section_embeddings"),
                    "release_check_section_embeddings": (release.get("checks") or {}).get(
                        "section_embeddings_materialized"
                    ),
                },
                blocks_release=True,
                can_run_while_broad_ingest_active=False,
                requires_db_writer_boundary=True,
                immediate_safe_action=(
                    "Wait for active section ingest to reach a safe boundary; the post-frontfill runner "
                    "rebuilds section embeddings, atom chains, Step5c/Step6/Step13, and the audit loop."
                ),
                sort_order=20,
            )
        )

    candidate_tasks = _as_int(stage_summary.get("candidate_tasks"))
    if candidate_tasks > 0:
        items.append(
            _priority_item(
                priority="P0" if topic_gap_blocking else "P1",
                action_id="typed_stage_candidate_review",
                title="Use exact/fuzzy atom recall to inspect missing typed-chain stages.",
                why=(
                    "Partial chains already have candidate atoms; reviewer/parser tuning can focus on the "
                    "missing constraint/failure/attempt/local-fix/new-constraint stages."
                ),
                command="make topic-gap-stage-candidate-recall",
                pipeline_stage="exact_fts_bm25_plus_atom_embeddings_fuzzy_recall",
                evidence={
                    "candidate_tasks": candidate_tasks,
                    "same_paper_candidate_hits": _as_int(stage_summary.get("same_paper_candidate_hits")),
                    "tasks_with_same_paper_candidates": _as_int(
                        stage_summary.get("tasks_with_same_paper_candidates")
                    ),
                    "missing_stage_counts": stage_summary.get("missing_stage_counts") or {},
                    "cross_paper_templates_enabled": bool(stage_summary.get("cross_paper_templates_enabled")),
                },
                blocks_release=topic_gap_blocking,
                can_run_while_broad_ingest_active=True,
                requires_db_writer_boundary=False,
                immediate_safe_action=(
                    "This is read-only candidate recall; it can be refreshed while ingest runs, but any "
                    "chain rebuild still waits for the DB-writer safe boundary."
                ),
                sort_order=30,
            )
        )

    linked_ref_rate = _as_float(direction_metrics.get("linked_ref_rate"))
    queue_rows = _as_int(cited_queue.get("queue_rows"))
    if linked_ref_rate < 0.30 or queue_rows > 0:
        items.append(
            _priority_item(
                priority="P1",
                action_id="exact_cited_work_backfill",
                title="Repair the citation backbone with exact provider IDs.",
                why=(
                    "Main-path and branch-history claims remain weak while no-local-match references dominate; "
                    "the repair path is exact cited-work backfill followed by exact relinking."
                ),
                command="make cited-work-backfill && make reference-relink-apply && make graph-features",
                pipeline_stage="citation_backbone",
                evidence={
                    "linked_ref_rate": linked_ref_rate,
                    "threshold": 0.30,
                    "cited_work_queue_rows": queue_rows,
                    "provider_counts": cited_queue.get("provider_counts") or {},
                },
                blocks_release=True,
                can_run_while_broad_ingest_active=False,
                requires_db_writer_boundary=True,
                immediate_safe_action=(
                    "Keep the exact-ID queue ready; run small batches when no competing SQLite writer is active."
                ),
                sort_order=40,
            )
        )

    openalex_w_rate = _as_float(direction_metrics.get("openalex_w_rate"))
    if openalex_w_rate and openalex_w_rate < 0.70:
        items.append(
            _priority_item(
                priority="P2",
                action_id="openalex_field_topic_repair",
                title="Continue conservative field/topic coverage repair.",
                why=(
                    "OpenAlex/local field-topic context is useful for uncertainty-aware filtering, "
                    "but it cannot substitute for section evidence or linked citations."
                ),
                command="make openalex-backfill",
                pipeline_stage="field_topic_context",
                evidence={"openalex_w_rate": openalex_w_rate, "threshold": 0.70},
                blocks_release=False,
                can_run_while_broad_ingest_active=False,
                requires_db_writer_boundary=True,
                immediate_safe_action=(
                    "Run only after checking provider cooldown and local DB writer status; keep cross-field "
                    "claims uncertainty-labeled until coverage improves."
                ),
                sort_order=50,
            )
        )

    if raw_summary["queued_papers"] > 0 or raw_summary["candidate_queue_raw_pdf_available_rate"] < 0.70:
        items.append(
            _priority_item(
                priority="P2",
                action_id="raw_pdf_background_substrate",
                title="Keep the external raw PDF crawler as a background substrate.",
                why=(
                    "The crawler improves local-first section ingest, but broad crawling is supportive; "
                    "benchmark-topic evidence repair remains the promotion bottleneck."
                ),
                command="make raw-pdf-store-audit",
                pipeline_stage="raw_pdf_local_store",
                evidence=raw_summary,
                blocks_release=False,
                can_run_while_broad_ingest_active=True,
                requires_db_writer_boundary=False,
                immediate_safe_action=(
                    "Refresh the read-only raw PDF store audit; do not treat crawler progress as release readiness."
                ),
                sort_order=60,
            )
        )

    return items


def _sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        items,
        key=lambda item: (
            PRIORITY_ORDER.get(str(item.get("priority")), 99),
            int(item.get("_sort_order") or 999),
            str(item.get("action_id") or ""),
        ),
    )
    for idx, item in enumerate(ordered, start=1):
        item["rank"] = idx
        item.pop("_sort_order", None)
    return ordered


def _overall_status(items: list[dict[str, Any]], release: dict[str, Any]) -> str:
    if bool(release.get("acceptance_ready")) and not items:
        return "no_blocking_repair"
    if any(item.get("priority") == "P0" for item in items):
        return "evidence_first_repair_required"
    if items:
        return "lower_priority_repair_required"
    return "repair_state_unknown"


def build_evidence_repair_priority(
    *,
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    report_dir: Path = REPORT_DIR,
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    value_audit = _load_json(report_dir / "value_delivery_audit.json", {})
    direction = _load_json(report_dir / "direction_readiness_audit.json", {})
    release = _load_json(report_dir / "release_readiness.json", {})
    path_challenge = _load_json(report_dir / "path_challenge_audit.json", {})
    raw_pdf = _load_json(report_dir / "raw_pdf_store_audit.json", {})
    topic_plan = _load_json(report_dir / "topic_gap_repair_execution_plan.json", {})
    stage_recall = _load_json(report_dir / "topic_gap_stage_candidate_recall.json", {})
    cited_queue = _load_json(report_dir / "cited_work_backfill_queue.json", {})

    db_counts = {
        "paper_sections": _table_count(db_main, "paper_sections"),
        "section_atoms": _table_count(db_main, "section_atoms"),
        "section_atom_embeddings": _table_count(db_main, "section_atom_embeddings"),
        "section_embeddings": _table_count(db_main, "section_embeddings"),
        "section_atom_chains": _table_count(db_main, "section_atom_chains"),
        "direction_claim_cards": _table_count(db_v14, "direction_claim_cards"),
    }
    items = _sort_items(
        _items_from_state(
            db_counts=db_counts,
            value_audit=value_audit,
            direction=direction,
            release=release,
            raw_pdf=raw_pdf,
            topic_plan=topic_plan,
            stage_recall=stage_recall,
            cited_queue=cited_queue,
        )
    )
    counts_by_priority = Counter(str(item.get("priority") or "unknown") for item in items)
    writer_blocked = [item for item in items if item.get("requires_db_writer_boundary")]
    read_only_now = [item for item in items if item.get("can_run_while_broad_ingest_active")]
    return {
        "generated_at": utc_now(),
        "audit_type": "v14b_evidence_repair_priority",
        "overall_status": _overall_status(items, release),
        "claim_scope": "evidence_repair_queue_only",
        "promotion_policy": "no_direct_promotion",
        "contract": evidence_repair_contract(),
        "status_inputs": {
            "release_status": release.get("release_status") or "missing",
            "acceptance_ready": bool(release.get("acceptance_ready")),
            "path_challenge_status": path_challenge.get("overall_status") or "missing",
            "value_delivery_summary": value_audit.get("summary") or {},
            "direction_readiness_level": direction.get("readiness_level") or "missing",
            "db_counts": db_counts,
        },
        "summary": {
            "items": len(items),
            "counts_by_priority": dict(sorted(counts_by_priority.items())),
            "blocking_p0": sum(1 for item in items if item.get("priority") == "P0"),
            "requires_db_writer_boundary": len(writer_blocked),
            "can_run_while_broad_ingest_active": len(read_only_now),
            "top_action_id": items[0]["action_id"] if items else "",
            "top_command": items[0]["command"] if items else "",
        },
        "safe_boundary_policy": {
            "current_target_is_read_only": True,
            "do_not_start_competing_db_writers": True,
            "db_writing_repairs_wait_for_safe_boundary": [
                item["action_id"] for item in writer_blocked
            ],
            "read_only_repairs_can_refresh_now": [item["action_id"] for item in read_only_now],
        },
        "priority_items": items,
        "repo_root": str(repo_root),
    }


def _md(value: Any) -> str:
    return " ".join(str(value if value is not None else "").replace("|", ";").split())


def render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# V14B Evidence Repair Priority",
        "",
        f"- generated_at: `{result['generated_at']}`",
        f"- overall_status: `{result['overall_status']}`",
        f"- claim_scope: `{result['claim_scope']}`",
        f"- promotion_policy: `{result['promotion_policy']}`",
        f"- items: `{summary['items']}`; P0: `{summary['blocking_p0']}`",
        "",
        "## Contract",
        "",
        "- Section atomization remains deterministic/rules-first and traceable to PDF page/span.",
        "- Exact search is hard retrieval evidence; fuzzy vector search is candidate recall only.",
        "- GNN/VGAE may expand or rank candidates only; it cannot create atoms or promote claims.",
        "",
        "## Safe Boundary",
        "",
        f"- current_target_is_read_only: `{str(result['safe_boundary_policy']['current_target_is_read_only']).lower()}`",
        f"- do_not_start_competing_db_writers: `{str(result['safe_boundary_policy']['do_not_start_competing_db_writers']).lower()}`",
        "",
        "## Priority Queue",
        "",
        "| rank | priority | action | command | safe while broad ingest active | DB writer boundary |",
        "|---:|---|---|---|---|---|",
    ]
    for item in result.get("priority_items") or []:
        lines.append(
            f"| {int(item['rank'])} | `{item['priority']}` | {_md(item['title'])} | "
            f"`{_md(item['command'])}` | "
            f"{'yes' if item.get('can_run_while_broad_ingest_active') else 'no'} | "
            f"{'yes' if item.get('requires_db_writer_boundary') else 'no'} |"
        )
    lines.extend(["", "## Why These Actions", ""])
    for item in result.get("priority_items") or []:
        lines.extend(
            [
                f"### {item['rank']}. {item['action_id']}",
                "",
                f"- priority: `{item['priority']}`",
                f"- pipeline_stage: `{item['pipeline_stage']}`",
                f"- why: {_md(item['why'])}",
                f"- immediate_safe_action: {_md(item['immediate_safe_action'])}",
                f"- evidence: `{json.dumps(item.get('evidence') or {}, ensure_ascii=False, sort_keys=True)}`",
                "",
            ]
        )
    return "\n".join(lines)


def _write_csv(path: Path, result: dict[str, Any]) -> None:
    fields = [
        "rank",
        "priority",
        "action_id",
        "title",
        "command",
        "pipeline_stage",
        "blocks_release",
        "can_run_while_broad_ingest_active",
        "requires_db_writer_boundary",
        "immediate_safe_action",
        "evidence_json",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for item in result.get("priority_items") or []:
            writer.writerow(
                {
                    "rank": item.get("rank"),
                    "priority": item.get("priority"),
                    "action_id": item.get("action_id"),
                    "title": item.get("title"),
                    "command": item.get("command"),
                    "pipeline_stage": item.get("pipeline_stage"),
                    "blocks_release": item.get("blocks_release"),
                    "can_run_while_broad_ingest_active": item.get("can_run_while_broad_ingest_active"),
                    "requires_db_writer_boundary": item.get("requires_db_writer_boundary"),
                    "immediate_safe_action": item.get("immediate_safe_action"),
                    "evidence_json": json.dumps(item.get("evidence") or {}, ensure_ascii=False, sort_keys=True),
                }
            )


def run_evidence_repair_priority(
    *,
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    out_dir: Path = REPORT_DIR,
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = build_evidence_repair_priority(
        db_main=db_main,
        db_v14=db_v14,
        report_dir=out_dir,
        repo_root=repo_root,
    )
    json_path = out_dir / "evidence_repair_priority.json"
    md_path = out_dir / "evidence_repair_priority.md"
    csv_path = out_dir / "evidence_repair_priority.csv"
    result["outputs"] = {"json": str(json_path), "markdown": str(md_path), "csv": str(csv_path)}
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    _write_csv(csv_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the V14B evidence repair priority report.")
    parser.add_argument("--db", type=Path, default=DB_MAIN)
    parser.add_argument("--db-v14", type=Path, default=DB_V14)
    parser.add_argument("--out-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    result = run_evidence_repair_priority(
        db_main=args.db,
        db_v14=args.db_v14,
        out_dir=args.out_dir,
        repo_root=args.repo_root,
    )
    print(
        json.dumps(
            {
                "overall_status": result["overall_status"],
                "summary": result["summary"],
                "json": str(args.out_dir / "evidence_repair_priority.json"),
                "report": str(args.out_dir / "evidence_repair_priority.md"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
