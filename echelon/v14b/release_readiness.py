"""Release readiness summary for the V14B evidence decision workflow.

This report is intentionally conservative: it does not create new scientific
claims.  It consolidates the current audits into a go/no-go state so product
readiness is judged by evidence gates, not by graph renderability or test
success alone.
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
        conn = sqlite3.connect(str(db_path))
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


def _gate_by_issue(value_audit: dict[str, Any], issue: str) -> dict[str, Any]:
    for gate in value_audit.get("gates") or []:
        if gate.get("issue") == issue:
            return gate
    return {}


def _multi_topic_status_counts(multi_topic: Any) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if isinstance(multi_topic, list):
        for row in multi_topic:
            if isinstance(row, dict):
                status = str(row.get("overall_status") or row.get("status") or "unknown")
                counts[status] += 1
    elif isinstance(multi_topic, dict):
        status = str(multi_topic.get("overall_status") or multi_topic.get("status") or "unknown")
        counts[status] += 1
    return dict(sorted(counts.items()))


def _value_summary(value_audit: dict[str, Any]) -> dict[str, int]:
    raw = value_audit.get("summary") or {}
    return {str(k): int(v or 0) for k, v in raw.items()}


def _release_status(
    *,
    value_summary: dict[str, int],
    multi_topic_counts: dict[str, int],
    section_embeddings: int | None,
    high_confidence_claim_cards: int,
    path_challenge_available: bool,
    path_challenge_aligned: bool,
    evidence_repair_available: bool,
    evidence_repair_blocking_p0: int,
) -> str:
    if value_summary.get("fail", 0) or multi_topic_counts.get("fail", 0):
        return "evidence_gated_not_release_ready"
    if section_embeddings in (None, 0):
        return "post_frontfill_rebuild_required"
    if high_confidence_claim_cards <= 0:
        return "actionable_but_not_high_confidence"
    if not path_challenge_available:
        return "path_challenge_audit_missing"
    if not path_challenge_aligned:
        return "path_challenge_not_aligned"
    if not evidence_repair_available:
        return "evidence_repair_priority_missing"
    if evidence_repair_blocking_p0 > 0:
        return "evidence_repair_required"
    if value_summary.get("warn", 0):
        return "release_candidate_with_evidence_warnings"
    return "decision_grade_release_candidate"


def _next_actions(
    *,
    direction_readiness: dict[str, Any],
    value_audit: dict[str, Any],
    section_embeddings: int | None,
    multi_topic_counts: dict[str, int],
) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if section_embeddings in (None, 0):
        actions.append(
            {
                "priority": "P0",
                "action": "Wait for the active broad section ingest to reach a safe boundary, then run post-frontfill-chain.",
                "why": "Section-level fuzzy context is code-complete but not materialized; downstream Claim Cards need the rebuilt section retrieval substrate and decision-audit refresh.",
                "command": "make post-frontfill-chain",
            }
        )
    multi_gate = _gate_by_issue(value_audit, "Multi-topic Regression")
    if multi_topic_counts.get("fail", 0) or multi_gate.get("topic_gap_blocking"):
        actions.append(
            {
                "priority": "P0",
                "action": "Continue targeted benchmark-topic evidence repair before promoting Topic Dossier or Radar conclusions.",
                "why": "Multi-topic regression still has benchmark-topic decision-grade section gaps.",
                "command": "make topic-gap-repair",
            }
        )
    for blocker in direction_readiness.get("blockers") or []:
        gate = str(blocker.get("gate") or "")
        if gate == "citation_graph_bone":
            actions.append(
                {
                    "priority": "P1",
                    "action": "Process exact-ID cited-work batches, then rerun exact relinking and graph features.",
                    "why": str(blocker.get("why") or "Linked reference coverage is below the decision threshold."),
                    "command": "make cited-work-backfill && make reference-relink-apply && make graph-features",
                }
            )
        elif gate == "openalex_topic_coverage":
            actions.append(
                {
                    "priority": "P2",
                    "action": "Continue conservative OpenAlex/local field-topic repair without treating coverage as a success claim.",
                    "why": str(blocker.get("why") or "OpenAlex topic coverage remains below the cross-field confidence threshold."),
                    "command": "make openalex-backfill",
                }
            )
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for item in actions:
        key = (item["priority"], item["command"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def build_release_readiness(
    *,
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    report_dir: Path = Path("reports/v14b_pilot"),
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    value_audit = _load_json(report_dir / "value_delivery_audit.json", {})
    direction_readiness = _load_json(report_dir / "direction_readiness_audit.json", {})
    algorithm_logic = _load_json(report_dir / "algorithm_logic_audit.json", {})
    path_challenge = _load_json(report_dir / "path_challenge_audit.json", {})
    evidence_repair_priority = _load_json(report_dir / "evidence_repair_priority.json", {})
    raw_pdf = _load_json(report_dir / "raw_pdf_store_audit.json", {})
    multi_topic = _load_json(report_dir / "multi_topic_regression.json", [])

    section_embeddings = _table_count(db_main, "section_embeddings")
    section_atom_embeddings = _table_count(db_main, "section_atom_embeddings")
    section_atoms = _table_count(db_main, "section_atoms")
    paper_sections = _table_count(db_main, "paper_sections")
    direction_cards = _table_count(db_v14, "direction_claim_cards")

    direction_metrics = direction_readiness.get("metrics") or {}
    value_metrics = value_audit.get("metrics") or {}
    value_summary = _value_summary(value_audit)
    multi_topic_counts = _multi_topic_status_counts(multi_topic)
    high_confidence_claim_cards = int(direction_metrics.get("high_confidence_claim_cards") or 0)
    section_frontfill = value_metrics.get("section_frontfill_state") or {}
    evidence_repair_summary = evidence_repair_priority.get("summary") or {}
    evidence_repair_available = bool(evidence_repair_priority.get("overall_status"))
    evidence_repair_blocking_p0 = int(evidence_repair_summary.get("blocking_p0") or 0)
    path_challenge_status = path_challenge.get("overall_status") or ""
    path_challenge_available = bool(path_challenge_status)
    path_challenge_aligned = path_challenge_status == "path_aligned"
    release_status = _release_status(
        value_summary=value_summary,
        multi_topic_counts=multi_topic_counts,
        section_embeddings=section_embeddings,
        high_confidence_claim_cards=high_confidence_claim_cards,
        path_challenge_available=path_challenge_available,
        path_challenge_aligned=path_challenge_aligned,
        evidence_repair_available=evidence_repair_available,
        evidence_repair_blocking_p0=evidence_repair_blocking_p0,
    )

    legacy_gate = _gate_by_issue(value_audit, "Legacy Flow Isolation Contract")
    checks = {
        "post_frontfill_finishes_with_decision_audit": bool(
            (legacy_gate.get("checks") or {}).get("post_frontfill_runs_decision_audit")
        ),
        "section_atom_retrieval_substrate_available": bool(section_atoms and section_atom_embeddings),
        "section_embeddings_materialized": bool(section_embeddings),
        "multi_topic_regression_passed": not bool(multi_topic_counts.get("fail", 0)),
        "value_delivery_has_no_failures": not bool(value_summary.get("fail", 0)),
        "radar_has_high_confidence_claim_card": high_confidence_claim_cards > 0,
        "raw_pdf_store_available": raw_pdf.get("status") == "pass",
        "path_challenge_audit_available": path_challenge_available,
        "path_challenge_path_aligned": path_challenge_available and path_challenge_aligned,
        "evidence_repair_priority_available": evidence_repair_available,
        "evidence_repair_has_no_blocking_p0": evidence_repair_available and evidence_repair_blocking_p0 == 0,
    }
    acceptance_ready = all(checks.values())
    return {
        "generated_at": utc_now(),
        "audit_type": "v14b_release_readiness",
        "release_status": release_status,
        "acceptance_ready": acceptance_ready,
        "evidence_policy": value_audit.get("evidence_policy") or "unknown",
        "checks": checks,
        "value_delivery_summary": value_summary,
        "direction_readiness_level": direction_readiness.get("readiness_level") or "unknown",
        "algorithm_logic_status_counts": algorithm_logic.get("status_counts") or {},
        "path_challenge_status": path_challenge.get("overall_status") or "missing",
        "path_challenge_verdict_counts": path_challenge.get("verdict_counts") or {},
        "evidence_repair_priority_status": evidence_repair_priority.get("overall_status") or "missing",
        "evidence_repair_priority_summary": evidence_repair_priority.get("summary") or {},
        "evidence_repair_top_actions": [
            {
                "rank": item.get("rank"),
                "priority": item.get("priority"),
                "action_id": item.get("action_id"),
                "command": item.get("command"),
                "requires_db_writer_boundary": item.get("requires_db_writer_boundary"),
                "can_run_while_broad_ingest_active": item.get("can_run_while_broad_ingest_active"),
            }
            for item in (evidence_repair_priority.get("priority_items") or [])[:5]
            if isinstance(item, dict)
        ],
        "multi_topic_status_counts": multi_topic_counts,
        "frontfill_snapshot": {
            "section_frontfill_status": section_frontfill.get("status") or value_metrics.get("section_frontfill_status"),
            "section_frontfill_done": section_frontfill.get("done") or value_metrics.get("section_frontfill_done"),
            "section_frontfill_total": section_frontfill.get("total") or value_metrics.get("section_frontfill_total"),
            "section_current_contract_primary": section_frontfill.get("current_contract_primary_section_papers"),
            "paper_sections": paper_sections,
            "section_atoms": section_atoms,
            "section_atom_embeddings": section_atom_embeddings,
            "section_embeddings": section_embeddings,
            "direction_claim_cards": direction_cards,
            "high_confidence_claim_cards": high_confidence_claim_cards,
            "raw_pdf_store_status": raw_pdf.get("status"),
        },
        "live_blockers": direction_readiness.get("blockers") or [],
        "gate_blockers": [
            {
                "issue": gate.get("issue"),
                "status": gate.get("status"),
                "policy": gate.get("policy"),
            }
            for gate in value_audit.get("gates") or []
            if gate.get("status") != "pass"
        ],
        "next_actions": _next_actions(
            direction_readiness=direction_readiness,
            value_audit=value_audit,
            section_embeddings=section_embeddings,
            multi_topic_counts=multi_topic_counts,
        ),
        "repo_root": str(repo_root),
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# V14B Release Readiness",
        "",
        f"- generated_at: `{result['generated_at']}`",
        f"- release_status: `{result['release_status']}`",
        f"- acceptance_ready: `{str(result['acceptance_ready']).lower()}`",
        f"- evidence_policy: `{result['evidence_policy']}`",
        f"- direction_readiness_level: `{result['direction_readiness_level']}`",
        "",
        "## Readiness Checks",
        "",
        "| Check | Ready |",
        "| --- | --- |",
    ]
    for key, ready in result["checks"].items():
        lines.append(f"| {key} | {'pass' if ready else 'hold'} |")
    lines.extend(
        [
            "",
            "## Frontfill Snapshot",
            "",
        ]
    )
    for key, value in result["frontfill_snapshot"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Gate Blockers",
            "",
        ]
    )
    blockers = result.get("gate_blockers") or []
    if not blockers:
        lines.append("- none")
    for blocker in blockers:
        lines.append(f"- **{blocker.get('issue')}** `{blocker.get('status')}`: {blocker.get('policy')}")
    lines.extend(
        [
            "",
            "## Direction Blockers",
            "",
        ]
    )
    live_blockers = result.get("live_blockers") or []
    if not live_blockers:
        lines.append("- none")
    for blocker in live_blockers:
        lines.append(
            f"- **{blocker.get('gate')}** `{blocker.get('severity')}`: "
            f"{blocker.get('why')} Next: {blocker.get('next_action')}"
        )
    lines.extend(
        [
            "",
            "## Required Next Actions",
            "",
        ]
    )
    actions = result.get("next_actions") or []
    if not actions:
        lines.append("- none")
    for action in actions:
        lines.append(
            f"- **{action.get('priority')}** {action.get('action')} "
            f"Why: {action.get('why')} Command: `{action.get('command')}`"
        )
    lines.extend(
        [
            "",
            "## Evidence Repair Priority",
            "",
            f"- status: `{result.get('evidence_repair_priority_status')}`",
            f"- summary: `{json.dumps(result.get('evidence_repair_priority_summary') or {}, ensure_ascii=False, sort_keys=True)}`",
        ]
    )
    top_actions = result.get("evidence_repair_top_actions") or []
    if not top_actions:
        lines.append("- top_actions: none")
    for action in top_actions:
        lines.append(
            f"- **{action.get('priority')}** `{action.get('action_id')}` "
            f"command: `{action.get('command')}` "
            f"db_writer_boundary: `{action.get('requires_db_writer_boundary')}`"
        )
    lines.extend(
        [
            "",
            "## Product Boundary",
            "",
            "This report is a release gate, not a scientific conclusion. Green tests or graph renderability alone do not make the system decision-grade. Topic Dossier, Evolution Evidence Map, Claim Card, and R&D Radar output must remain evidence-scoped until the failed and held checks above are closed by current-state evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def run_release_readiness(
    *,
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    out_dir: Path = Path("reports/v14b_pilot"),
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = build_release_readiness(
        db_main=db_main,
        db_v14=db_v14,
        report_dir=out_dir,
        repo_root=repo_root,
    )
    (out_dir / "release_readiness.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "release_readiness.md").write_text(render_markdown(result), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the V14B release readiness summary.")
    parser.add_argument("--db", type=Path, default=DB_MAIN)
    parser.add_argument("--db-v14", type=Path, default=DB_V14)
    parser.add_argument("--out-dir", type=Path, default=Path("reports/v14b_pilot"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    result = run_release_readiness(
        db_main=args.db,
        db_v14=args.db_v14,
        out_dir=args.out_dir,
        repo_root=args.repo_root,
    )
    print(json.dumps(
        {
            "release_status": result["release_status"],
            "acceptance_ready": result["acceptance_ready"],
            "json": str(args.out_dir / "release_readiness.json"),
            "report": str(args.out_dir / "release_readiness.md"),
        },
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
