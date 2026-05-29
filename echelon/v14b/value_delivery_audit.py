"""End-to-end value-delivery gates for the V14B research decision system.

This audit maps the eight current product risks to executable checks.  It does
not pretend weak data is solved; it enforces where conclusions must be
demoted, where algorithms are present, and which frontfill or rerun is still
blocking decision-grade output.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.direction_readiness_audit import collect_metrics, scalar, table_exists
from echelon.v14b.evidence_grade import (
    claim_scope_policy,
    coverage_grade,
    grade_from_qualities,
    uncertainty_reasons,
)
from echelon.v14b.topic_regression import GOLD_TOPICS


EXPECTED_LINEAGE_STAGES = {
    ("constraint", "failure_mechanism"),
    ("failure_mechanism", "attempt_path"),
    ("attempt_path", "local_fix"),
    ("local_fix", "new_constraint"),
}

QUARTERLY_REQUIRED_TARGETS = (
    "quarterly-run",
    "quarterly-run-optics",
    "quarterly-run-cs",
    "quarterly-run-materials",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _gate_status(ok: bool, *, warn: bool = False) -> str:
    if ok:
        return "pass"
    return "warn" if warn else "fail"


def _lineage_status(payload: dict[str, Any], confidence: Any) -> str:
    explicit = str(payload.get("lineage_status") or "").strip()
    if explicit:
        return explicit
    support = int(payload.get("parent_citation_support") or 0)
    try:
        conf = float(confidence or payload.get("parent_support_ratio") or 0.0)
    except Exception:
        conf = 0.0
    if support >= 5 and conf >= 0.20:
        return "evidence_backed_split"
    if support > 0 or conf > 0:
        return "weak_split_candidate"
    return "layout_cluster_only"


def audit_evidence_bone(metrics: dict[str, Any]) -> dict[str, Any]:
    grade = coverage_grade(
        linked_ref_rate=float(metrics["linked_ref_rate"]),
        primary_section_rate=float(metrics["primary_section_rate"]),
        openalex_rate=float(metrics["openalex_w_rate"]),
    )
    reasons = uncertainty_reasons(
        linked_ref_rate=float(metrics["linked_ref_rate"]),
        primary_section_rate=float(metrics["primary_section_rate"]),
        openalex_rate=float(metrics["openalex_w_rate"]),
        has_calibration=bool(metrics.get("vgae_calibration_audit")),
    )
    return {
        "issue": "Evidence Bone",
        "status": _gate_status(
            metrics["linked_ref_rate"] >= 0.30 and metrics["primary_section_papers"] >= 8000,
            warn=True,
        ),
        "evidence_grade": grade,
        "metrics": {
            "linked_ref_rate": metrics["linked_ref_rate"],
            "primary_section_papers": metrics["primary_section_papers"],
            "openalex_w_rate": metrics["openalex_w_rate"],
        },
        "policy": "All topic, branch, bottleneck, and future conclusions must carry evidence_grade and uncertainty reasons until this gate passes.",
        "uncertainty_reasons": reasons,
    }


def audit_bottleneck_lineage(conn_v14: sqlite3.Connection) -> dict[str, Any]:
    if not table_exists(conn_v14, "bottleneck_lineage_triples"):
        return {
            "issue": "Bottleneck Lineage Graph",
            "status": "fail",
            "why": "bottleneck_lineage_triples table is missing",
            "policy": "Step13 must materialize constraint -> failure -> attempt -> local fix -> new constraint chains.",
        }
    rows = conn_v14.execute(
        """
        SELECT source_stage, target_stage, evidence_quality, evidence_page
        FROM bottleneck_lineage_triples
        """
    ).fetchall()
    stage_pairs = {(str(r[0]), str(r[1])) for r in rows}
    missing = sorted(EXPECTED_LINEAGE_STAGES - stage_pairs)
    quality_grade = grade_from_qualities([r[2] for r in rows])
    pages = sum(1 for r in rows if r[3] not in (None, ""))
    if not rows or missing:
        status = "fail" if missing else "warn"
    elif pages == 0:
        status = "warn"
    else:
        status = "pass"
    return {
        "issue": "Bottleneck Lineage Graph",
        "status": status,
        "triples": len(rows),
        "stage_pairs": sorted([f"{a}->{b}" for a, b in stage_pairs]),
        "missing_stage_pairs": [f"{a}->{b}" for a, b in missing],
        "evidence_grade": quality_grade,
        "triples_with_page": pages,
        "policy": "Lineage is evidence-backed only when triples carry section/page evidence; otherwise it remains weak historical context.",
    }


def audit_branch_lineage(conn_v14: sqlite3.Connection) -> dict[str, Any]:
    required_cols = {"parent_branch_id", "split_confidence", "split_evidence_json"}
    if not table_exists(conn_v14, "branch_lineages"):
        return {
            "issue": "Branch Lineage Validity",
            "status": "fail",
            "why": "branch_lineages table is missing",
        }
    cols = columns(conn_v14, "branch_lineages")
    rows = conn_v14.execute(
        """
        SELECT branch_id, parent_branch_id, split_confidence, split_evidence_json
        FROM branch_lineages
        """
    ).fetchall() if required_cols.issubset(cols) else []
    statuses = Counter()
    for row in rows:
        statuses[_lineage_status(_loads(row[3], {}), row[2])] += 1
    has_labeling = bool(rows) and bool(statuses)
    return {
        "issue": "Branch Lineage Validity",
        "status": _gate_status(required_cols.issubset(cols) and has_labeling, warn=has_labeling),
        "branches": len(rows),
        "status_counts": dict(statuses),
        "missing_columns": sorted(required_cols - cols),
        "policy": "Only evidence_backed_split can be narrated as scientific branch evolution; weak_split_candidate and layout_cluster_only must be labeled as such.",
    }


def audit_future_growth(conn_v14: sqlite3.Connection) -> dict[str, Any]:
    predicted = int(scalar(conn_v14, "SELECT COUNT(*) FROM predicted_future_edges") or 0) if table_exists(conn_v14, "predicted_future_edges") else 0
    calibration = int(scalar(conn_v14, "SELECT COUNT(*) FROM vgae_calibration_audit") or 0) if table_exists(conn_v14, "vgae_calibration_audit") else 0
    high_conf_bad = 0
    if table_exists(conn_v14, "direction_claim_cards"):
        high_conf_bad = int(
            scalar(
                conn_v14,
                """
                SELECT COUNT(*) FROM direction_claim_cards
                WHERE high_confidence_eligible=1 AND COALESCE(five_question_complete,0)=0
                """,
            )
            or 0
        )
    return {
        "issue": "Future Growth Calibration",
        "status": _gate_status(predicted >= 0 and high_conf_bad == 0 and calibration > 0, warn=predicted > 0),
        "predicted_future_edges": predicted,
        "calibration_audits": calibration,
        "bad_high_confidence_cards": high_conf_bad,
        "policy": "VGAE/GNN is a future candidate generator only. Radar promotion requires Step6 fusion plus Step13 complete Claim Card.",
    }


def audit_claim_card_engine(conn_v14: sqlite3.Connection) -> dict[str, Any]:
    required_cols = {
        "root_constraint_json",
        "attempts_last_10y_json",
        "enabling_conditions_json",
        "unresolved_bottleneck_json",
        "minimal_validation_experiment_json",
        "five_question_complete",
        "high_confidence_eligible",
        "quality_gate_json",
    }
    if not table_exists(conn_v14, "direction_claim_cards"):
        return {
            "issue": "Claim Card Engine",
            "status": "warn",
            "why": "direction_claim_cards table is not materialized yet",
            "policy": "Radar stays empty until Step13 creates complete five-question cards.",
        }
    cols = columns(conn_v14, "direction_claim_cards")
    total = int(scalar(conn_v14, "SELECT COUNT(*) FROM direction_claim_cards") or 0)
    complete = int(scalar(conn_v14, "SELECT COUNT(*) FROM direction_claim_cards WHERE five_question_complete=1") or 0)
    high = int(scalar(conn_v14, "SELECT COUNT(*) FROM direction_claim_cards WHERE high_confidence_eligible=1") or 0)
    bad_high = int(
        scalar(
            conn_v14,
            "SELECT COUNT(*) FROM direction_claim_cards WHERE high_confidence_eligible=1 AND five_question_complete=0",
        )
        or 0
    )
    if not required_cols.issubset(cols) or bad_high > 0:
        status = "fail"
    elif total == 0:
        status = "warn"
    else:
        status = "pass"
    return {
        "issue": "Claim Card Engine",
        "status": status,
        "cards": total,
        "complete_cards": complete,
        "high_confidence_cards": high,
        "bad_high_confidence_cards": bad_high,
        "missing_columns": sorted(required_cols - cols),
        "policy": "A card missing any of the five hard questions is candidate_pool_only and cannot enter Radar.",
    }


def audit_topic_dossier(conn_v14: sqlite3.Connection) -> dict[str, Any]:
    visual_nodes = int(scalar(conn_v14, "SELECT COUNT(*) FROM visual_nodes") or 0) if table_exists(conn_v14, "visual_nodes") else 0
    visual_edges = int(scalar(conn_v14, "SELECT COUNT(*) FROM visual_edges") or 0) if table_exists(conn_v14, "visual_edges") else 0
    has_search = table_exists(conn_v14, "visual_search_fts")
    return {
        "issue": "Topic Dossier Product Value",
        "status": _gate_status(visual_nodes > 0 and visual_edges > 0 and has_search, warn=visual_nodes > 0),
        "visual_nodes": visual_nodes,
        "visual_edges": visual_edges,
        "has_visual_search_fts": has_search,
        "policy": "Topic Lens first screen must answer branches, bottlenecks, turning papers, and validation candidates before raw graph exploration.",
    }


def audit_multi_topic_regression(report_dir: Path) -> dict[str, Any]:
    expected = {
        "metalens",
        "metasurface holography",
        "photonic crystal cavity",
        "quantum light source",
    }
    defined = set(GOLD_TOPICS)
    missing = sorted(expected - defined)
    suite_path = report_dir / "multi_topic_regression.json"
    live_results: list[dict[str, Any]] = []
    failed_topics: list[str] = []
    if suite_path.exists():
        loaded = _loads(suite_path.read_text(encoding="utf-8"), [])
        if isinstance(loaded, list):
            live_results = [r for r in loaded if isinstance(r, dict)]
            failed_topics = [
                str(r.get("topic"))
                for r in live_results
                if str(r.get("overall_status") or "") == "fail"
            ]
    live_status = "not_run"
    if live_results:
        live_status = "fail" if failed_topics else "pass"
    return {
        "issue": "Multi-topic Regression",
        "status": (
            "fail"
            if missing or failed_topics
            else ("pass" if live_results else "warn")
        ),
        "gold_topics": sorted(defined),
        "missing_topics": missing,
        "live_regression_status": live_status,
        "failed_topics": failed_topics,
        "policy": "Topic value must be tested across multiple optics themes, not tuned only for Metalens.",
    }


def audit_quarterly_multi_corpus(db_main: Path, repo_root: Path) -> dict[str, Any]:
    with sqlite3.connect(str(db_main)) as conn:
        existing_tables = {
            name
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    makefile = (repo_root / "Makefile").read_text(encoding="utf-8") if (repo_root / "Makefile").exists() else ""
    quarterly = (repo_root / "echelon/v14b/quarterly_run.py").read_text(encoding="utf-8") if (repo_root / "echelon/v14b/quarterly_run.py").exists() else ""
    missing_tables = sorted({"corpus_registry", "paper_corpora", "corpus_runs", "corpus_snapshots"} - existing_tables)
    missing_targets = [t for t in QUARTERLY_REQUIRED_TARGETS if not re.search(rf"^{re.escape(t)}:", makefile, flags=re.M)]
    supports_corpus_arg = "--corpus-id" in quarterly
    return {
        "issue": "Quarterly / Multi-corpus",
        "status": _gate_status(not missing_tables and not missing_targets and supports_corpus_arg, warn=supports_corpus_arg),
        "missing_tables": missing_tables,
        "missing_make_targets": missing_targets,
        "supports_corpus_id": supports_corpus_arg,
        "policy": "Quarterly optics/cs/materials runs must use corpus_id scoping and snapshots; no step should be hardwired to optics-only product logic.",
    }


def collect_value_gates(db_main: Path, db_v14: Path, repo_root: Path, report_dir: Path | None = None) -> dict[str, Any]:
    metrics = collect_metrics(db_main, db_v14)
    if report_dir is None:
        report_dir = repo_root / "reports/v14b_pilot"
    with sqlite3.connect(str(db_v14)) as conn_v14:
        metrics["vgae_calibration_audit"] = (
            int(scalar(conn_v14, "SELECT COUNT(*) FROM vgae_calibration_audit") or 0)
            if table_exists(conn_v14, "vgae_calibration_audit")
            else 0
        )
        gates = [
            audit_evidence_bone(metrics),
            audit_bottleneck_lineage(conn_v14),
            audit_branch_lineage(conn_v14),
            audit_future_growth(conn_v14),
            audit_claim_card_engine(conn_v14),
            audit_topic_dossier(conn_v14),
            audit_multi_topic_regression(report_dir),
            audit_quarterly_multi_corpus(db_main, repo_root),
        ]
    statuses = Counter(g["status"] for g in gates)
    evidence_policy = claim_scope_policy(
        evidence_grade=audit_evidence_bone(metrics)["evidence_grade"],
        has_complete_claim_card=bool(metrics.get("complete_claim_cards")),
        has_calibration=bool(metrics.get("vgae_calibration_audit")),
        linked_ref_rate=float(metrics["linked_ref_rate"]),
    )
    return {
        "generated_at": utc_now(),
        "summary": dict(statuses),
        "evidence_policy": evidence_policy,
        "metrics": metrics,
        "gates": gates,
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# V14B Value Delivery Audit",
        "",
        f"- generated_at: `{result['generated_at']}`",
        f"- evidence_policy: `{result['evidence_policy']}`",
        f"- gate_summary: `{json.dumps(result['summary'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Eight Product Gates",
        "",
        "| # | Gate | Status | What This Enforces |",
        "| ---: | --- | --- | --- |",
    ]
    for idx, gate in enumerate(result["gates"], start=1):
        lines.append(
            f"| {idx} | {gate['issue']} | {gate['status']} | {gate.get('policy', gate.get('why', ''))} |"
        )
    lines.extend(["", "## Gate Details", ""])
    for gate in result["gates"]:
        lines.extend(
            [
                f"### {gate['issue']}",
                "",
                "```json",
                json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## Product Rule",
            "",
            "The system may show weak evidence, but it must label it. Raw GNN edges, layout clusters, and abstract-only bottlenecks are inspection targets, not decision-grade claims.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_audit(db_main: Path, db_v14: Path, out_dir: Path, repo_root: Path) -> dict[str, Any]:
    result = collect_value_gates(db_main, db_v14, repo_root, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "value_delivery_audit.md"
    json_path = out_dir / "value_delivery_audit.json"
    md_path.write_text(render_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"report": str(md_path), "json": str(json_path), "summary": result["summary"], "evidence_policy": result["evidence_policy"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit V14B value-delivery gates.")
    parser.add_argument("--db", default="db/echelon_library.sqlite3")
    parser.add_argument("--db-v14", default="db/v14_pilot.sqlite3")
    parser.add_argument("--out-dir", default="reports/v14b_pilot")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    result = run_audit(Path(args.db), Path(args.db_v14), Path(args.out_dir), Path(args.repo_root))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
