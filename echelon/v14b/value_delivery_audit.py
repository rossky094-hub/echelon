"""End-to-end value-delivery gates for the V14B research decision system.

This audit maps current product risks to executable checks.  It does
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

from echelon.v14b.direction_readiness_audit import (
    collect_metrics,
    default_topic_gap_queue,
    scalar,
    select_openalex_frontfill_state,
    select_reference_relink_state,
    select_section_frontfill_state,
    table_exists,
)
from echelon.v14b.cited_work_backfill import load_cited_work_backfill_run_state
from echelon.v14b.cited_work_backfill_queue import load_cited_work_backfill_state
from echelon.v14b.evidence_grade import (
    claim_scope_policy,
    coverage_grade,
    grade_from_qualities,
    uncertainty_reasons,
)
from echelon.v14b.future_candidate_lifecycle import future_edge_calibration_context
from echelon.v14b.topic_gap_no_target_inspection import load_topic_gap_no_target_inspection_state
from echelon.v14b.topic_gap_section_evidence_audit import load_topic_gap_section_triage_state
from echelon.v14b.topic_readiness import (
    NO_LLM_PREFLIGHT_POLICY,
    build_topic_readiness_preflight,
)
from echelon.v14b.topic_regression import BENCHMARK_TOPICS


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

LEGACY_FLOW_TARGETS = (
    "enrich",
    "pilot",
    "pilot-graph",
    "pilot-visual",
    "pilot-full",
    "pilot-debug",
)

LEGACY_FLOW_DISALLOWED_CURRENT_DEPS = {
    "enrich",
    "pilot",
    "pilot-graph",
    "pilot-visual",
    "pilot-full",
}

LEGACY_ARXIV_FLOW_SCRIPTS = (
    "scripts/diff_arxiv_optics_vs_db.py",
    "scripts/fetch_missing_arxiv_optics.sh",
    "scripts/monitor_optics_full_pipeline.sh",
    "scripts/run_arxiv_optics_harvest.sh",
    "scripts/run_arxiv_optics_incremental.sh",
    "scripts/run_step1_arxiv_enrich.sh",
)

REQUIRED_TOPIC_READINESS_GATES = {
    "topic dossier evidence contract",
    "turning papers with strong/moderate section provenance",
    "five-question evidence contracts",
    "bottleneck lineage typed contracts",
    "auditable reading path",
    "complete Claim Cards",
}

REQUIRED_EVIDENCE_MAP_LAYERS = {
    "main_path",
    "citation",
    "topic",
    "semantic",
    "future",
    "bottleneck",
    "uncertainty",
    "fusion_value",
}

REQUIRED_EVIDENCE_MAP_COMBOS = {
    ("main_path",),
    ("main_path", "citation"),
    ("topic", "semantic"),
    ("main_path", "topic", "bottleneck"),
    ("future", "bottleneck"),
    ("future", "bottleneck", "uncertainty"),
    ("future", "bottleneck", "uncertainty", "fusion_value"),
}


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
    frontfill = metrics.get("section_frontfill_state") or {}
    if frontfill.get("status") in {"low_yield", "soft_stall"}:
        reasons.append(
            f"section frontfill {frontfill.get('status')}; process progress is not translating into new primary evidence"
        )
    openalex_frontfill = metrics.get("openalex_frontfill_state") or {}
    if openalex_frontfill.get("status") in {
        "cooling_down_or_stopped",
        "stalled_after_cooldown",
        "stale_without_completion",
    }:
        reasons.append(
            f"OpenAlex frontfill {openalex_frontfill.get('status')}; field/topic claims need local fallback and uncertainty"
        )
    relink = metrics.get("reference_relink_state") or {}
    cited_work_queue = metrics.get("cited_work_backfill_queue_state") or {}
    cited_work_run = metrics.get("cited_work_backfill_run_state") or {}
    if relink.get("status") == "local_corpus_gap_dominates":
        if cited_work_run.get("available") and int(cited_work_run.get("inserted_or_updated") or 0):
            reasons.append(
                "cited-work backfill inserted local works, but citation claims stay weak until exact relinking and graph features are rerun"
            )
        elif cited_work_queue.get("available") and int(cited_work_queue.get("queue_rows") or 0):
            reasons.append(
                "reference relink audit shows no-local-match refs dominate; cited-work backfill queue is ready but must be ingested before citation claims strengthen"
            )
        else:
            reasons.append(
                "reference relink audit shows no-local-match refs dominate; citation backbone needs a cited-work backfill queue, not fuzzy relinking"
            )
    section_quality = metrics.get("section_evidence_quality") or {}
    weak_only_rate = float(section_quality.get("weak_only_rate") or 0.0)
    strong_or_moderate = int(section_quality.get("strong_or_moderate_papers") or 0)
    provenance_ok = (
        int(metrics.get("primary_section_papers") or 0) == 0
        or (weak_only_rate <= 0.25 and strong_or_moderate >= 1000)
    )
    if not provenance_ok:
        reasons.append(
            "section evidence provenance is weak; loose/legacy parser matches must remain low-confidence evidence"
        )
    return {
        "issue": "Evidence Bone",
        "status": _gate_status(
            metrics["linked_ref_rate"] >= 0.30
            and metrics["primary_section_papers"] >= 8000
            and provenance_ok,
            warn=True,
        ),
        "evidence_grade": grade,
        "metrics": {
            "linked_ref_rate": metrics["linked_ref_rate"],
            "primary_section_papers": metrics["primary_section_papers"],
            "openalex_w_rate": metrics["openalex_w_rate"],
            "openalex_frontfill_status": openalex_frontfill.get("status"),
            "openalex_frontfill_processed": openalex_frontfill.get("processed"),
            "openalex_frontfill_total": openalex_frontfill.get("total"),
            "openalex_frontfill_cooldown_remaining_s": openalex_frontfill.get("cooldown_remaining_s"),
            "section_frontfill_status": frontfill.get("status"),
            "section_frontfill_done": frontfill.get("done"),
            "section_frontfill_total": frontfill.get("total"),
            "section_frontfill_progress_done": frontfill.get("progress_latest_done"),
            "section_frontfill_no_evidence_delta": frontfill.get("no_evidence_done_delta"),
            "reference_relink_status": relink.get("status"),
            "reference_relink_exact_linkable_refs": relink.get("exact_linkable_refs"),
            "reference_relink_no_local_match_refs": relink.get("no_local_match_refs"),
            "cited_work_backfill_queue_status": cited_work_queue.get("status"),
            "cited_work_backfill_queue_rows": cited_work_queue.get("queue_rows"),
            "cited_work_backfill_provider_counts": cited_work_queue.get("provider_counts"),
            "cited_work_backfill_run_status": cited_work_run.get("status"),
            "cited_work_backfill_run_processed": cited_work_run.get("processed_targets"),
            "cited_work_backfill_inserted_or_updated": cited_work_run.get("inserted_or_updated"),
            "cited_work_backfill_run_status_counts": cited_work_run.get("status_counts"),
            "section_provenance": section_quality,
        },
        "policy": "All topic, branch, bottleneck, and future conclusions must carry evidence_grade and uncertainty reasons until this gate passes.",
        "uncertainty_reasons": reasons,
    }


def audit_openalex_frontfill_guard(repo_root: Path | None = None) -> dict[str, Any]:
    """Verify OpenAlex backfill entrypoints respect cooldown and duplicate-run guards."""
    root = repo_root or Path(".")
    makefile = (root / "Makefile").read_text(encoding="utf-8") if (root / "Makefile").exists() else ""
    openalex_context = _make_target_context(makefile, "openalex-backfill", before=0, after=8)
    guard_path = root / "scripts/guard_openalex_backfill.py"
    checks = {
        "openalex_backfill_target_present": bool(re.search(r"^openalex-backfill\s*:", makefile, flags=re.M)),
        "openalex_backfill_runs_guard_before_fetch": (
            "scripts/guard_openalex_backfill.py" in openalex_context
            and openalex_context.find("scripts/guard_openalex_backfill.py")
            < openalex_context.find("echelon.v14b.step0_openalex_backfill")
        ),
        "guard_reads_openalex_frontfill_state": _source_contains(
            guard_path,
            ("select_openalex_frontfill_state", "cooling_down_or_stopped", "cooldown_remaining_s"),
        ),
        "guard_respects_429_cooldown": _source_contains(
            guard_path,
            ("active 429 cooldown detected", "V14B_ALLOW_OPENALEX_BACKFILL_DURING_COOLDOWN"),
        ),
        "guard_blocks_duplicate_backfill": _source_contains(
            guard_path,
            ("active OpenAlex backfill already detected", "V14B_ALLOW_CONCURRENT_OPENALEX_BACKFILL"),
        ),
    }
    return {
        "issue": "OpenAlex Frontfill Guard Contract",
        "status": _gate_status(all(checks.values())),
        "checks": checks,
        "policy": (
            "OpenAlex field/topic backfill must respect provider 429 cooldowns and avoid duplicate runs; "
            "cross-field conclusions remain uncertainty-labeled until coverage and cooldown health recover."
        ),
    }


def audit_bottleneck_lineage(conn_v14: sqlite3.Connection, repo_root: Path | None = None) -> dict[str, Any]:
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
    data_status = "pass"
    if not rows or missing:
        data_status = "fail" if missing else "warn"
    elif pages == 0:
        data_status = "warn"
    source_checks = {
        "api_bottleneck_constraints_carry_limits": False,
        "ui_renders_bottleneck_lineage_limits": False,
    }
    if repo_root is not None:
        source_checks = {
            "api_bottleneck_constraints_carry_limits": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _build_bottleneck_lineage",
                    '"can_explain": [',
                    '"cannot_explain": [',
                    "a proven causal root-cause chain when section-level typed triples are missing",
                    "that a bottleneck is solved without linked resolution atoms",
                ),
            ),
            "ui_renders_bottleneck_lineage_limits": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "function renderBottleneckLineage",
                    "c.can_explain",
                    "c.cannot_explain",
                    "不能说明",
                ),
            ),
        }
    checks = {
        "typed_stage_chain_complete": not missing and bool(rows),
        "typed_triples_have_page_evidence": pages > 0,
        **source_checks,
    }
    status = data_status
    if data_status == "pass" and not all(source_checks.values()):
        status = "fail"
    return {
        "issue": "Bottleneck Lineage Graph",
        "status": status,
        "checks": checks,
        "triples": len(rows),
        "stage_pairs": sorted([f"{a}->{b}" for a, b in stage_pairs]),
        "missing_stage_pairs": [f"{a}->{b}" for a, b in missing],
        "evidence_grade": quality_grade,
        "triples_with_page": pages,
        "policy": "Lineage is evidence-backed only when triples carry section/page evidence; otherwise it remains weak historical context.",
    }


def audit_branch_lineage(conn_v14: sqlite3.Connection, repo_root: Path | None = None) -> dict[str, Any]:
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
    source_checks = {
        "api_visual_clusters_carry_lineage_contract": True,
        "ui_cluster_panel_renders_lineage_contract": True,
        "ui_branch_scores_are_labeled_as_support": True,
    }
    if repo_root is not None:
        source_checks = {
            "api_visual_clusters_carry_lineage_contract": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _branch_lineage_contract",
                    "get_visual_clusters",
                    "claim_scope",
                    "evidence_grade",
                    "uncertainty_reasons",
                    "evidence_objects",
                ),
            ),
            "ui_cluster_panel_renders_lineage_contract": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "renderClusters",
                    "lineage.claim_scope",
                    "lineage.evidence_grade",
                    "lineage.uncertainty_reasons",
                    "renderEvidenceObjects(lineage.evidence_objects",
                ),
            ),
            "ui_branch_scores_are_labeled_as_support": (
                _source_contains(
                    repo_root / "web/visual-graph/app.js",
                    ("split/support", " / support "),
                )
                and _source_absent(
                    repo_root / "web/visual-graph/app.js",
                    ("split/confidence", " / confidence "),
                )
                and _source_absent(
                    repo_root / "echelon/api/graph_visual_backend.py",
                    ("model predicts", "branch split confidence and audit trail"),
                )
            ),
        }
    checks = {
        "branch_lineage_columns_present": required_cols.issubset(cols),
        "branch_lineage_statuses_present": has_labeling,
        **source_checks,
    }
    return {
        "issue": "Branch Lineage Validity",
        "status": _gate_status(all(checks.values()), warn=has_labeling and all(source_checks.values())),
        "checks": checks,
        "branches": len(rows),
        "status_counts": dict(statuses),
        "missing_columns": sorted(required_cols - cols),
        "policy": "Only evidence_backed_split can be narrated as scientific branch evolution; weak_split_candidate and layout_cluster_only must be labeled as such, and graph cluster panels must render the same evidence contract.",
    }


def future_visual_edge_contract_stats(conn_v14: sqlite3.Connection) -> dict[str, Any]:
    if not table_exists(conn_v14, "visual_edges"):
        return {"future_edges": 0, "bad_contract_edges": 0, "checked": False}
    edge_cols = columns(conn_v14, "visual_edges")
    if "edge_type" in edge_cols and "layer" in edge_cols:
        where = "(edge_type = 'future_growth' OR layer = 'future')"
    elif "edge_type" in edge_cols:
        where = "edge_type = 'future_growth'"
    elif "layer" in edge_cols:
        where = "layer = 'future'"
    else:
        return {"future_edges": 0, "bad_contract_edges": 0, "checked": False}

    future_edges = int(scalar(conn_v14, f"SELECT COUNT(*) FROM visual_edges WHERE {where}") or 0)
    if future_edges <= 0:
        return {"future_edges": 0, "bad_contract_edges": 0, "checked": True}
    if "evidence_json" not in edge_cols:
        return {"future_edges": future_edges, "bad_contract_edges": 0, "checked": False}

    rows = conn_v14.execute(
        f"""
        SELECT evidence_json
        FROM visual_edges
        WHERE {where}
        LIMIT 5000
        """
    ).fetchall()
    bad = 0
    examples: list[dict[str, Any]] = []
    for row in rows:
        evidence = _loads(row[0], {})
        reasons = evidence.get("uncertainty_reasons")
        required = evidence.get("required_evidence")
        objects = evidence.get("evidence_objects")
        bad_contract = (
            evidence.get("claim_scope") != "candidate_pool_only"
            or not evidence.get("evidence_grade")
            or not isinstance(reasons, list)
            or not required
            or not objects
            or evidence.get("candidate_score") is None
            or bool(evidence.get("radar_eligible"))
        )
        if bad_contract:
            bad += 1
            if len(examples) < 5:
                examples.append(
                    {
                        "claim_scope": evidence.get("claim_scope"),
                        "evidence_grade": evidence.get("evidence_grade"),
                        "has_uncertainty_reasons": isinstance(reasons, list),
                        "has_required_evidence": bool(required),
                        "has_evidence_objects": bool(objects),
                        "has_candidate_score": evidence.get("candidate_score") is not None,
                        "radar_eligible": bool(evidence.get("radar_eligible")),
                    }
                )
    return {
        "future_edges": future_edges,
        "bad_contract_edges": bad,
        "checked": True,
        "examples": examples,
    }


def future_visual_recommendation_contract_stats(conn_v14: sqlite3.Connection) -> dict[str, Any]:
    if not table_exists(conn_v14, "visual_recommendations"):
        return {"future_recommendations": 0, "bad_contract_recommendations": 0, "checked": False}
    rec_cols = columns(conn_v14, "visual_recommendations")
    if "mode" not in rec_cols:
        return {"future_recommendations": 0, "bad_contract_recommendations": 0, "checked": False}
    future_recommendations = int(
        scalar(conn_v14, "SELECT COUNT(*) FROM visual_recommendations WHERE mode = 'future'")
        or 0
    )
    if future_recommendations <= 0:
        return {"future_recommendations": 0, "bad_contract_recommendations": 0, "checked": True}
    if "reason_json" not in rec_cols:
        return {
            "future_recommendations": future_recommendations,
            "bad_contract_recommendations": future_recommendations,
            "checked": False,
        }
    rows = conn_v14.execute(
        """
        SELECT reason_json
        FROM visual_recommendations
        WHERE mode = 'future'
        LIMIT 5000
        """
    ).fetchall()
    bad = 0
    examples: list[dict[str, Any]] = []
    for row in rows:
        reason = _loads(row[0], {})
        reasons = reason.get("uncertainty_reasons")
        required = reason.get("required_evidence")
        objects = reason.get("evidence_objects")
        why = str(reason.get("why") or "")
        bad_contract = (
            reason.get("claim_scope") != "candidate_pool_only"
            or not reason.get("evidence_grade")
            or not isinstance(reasons, list)
            or not required
            or not objects
            or reason.get("candidate_score") is None
            or "prediction support" in why.lower()
        )
        if bad_contract:
            bad += 1
            if len(examples) < 5:
                examples.append(
                    {
                        "why": why,
                        "claim_scope": reason.get("claim_scope"),
                        "evidence_grade": reason.get("evidence_grade"),
                        "has_uncertainty_reasons": isinstance(reasons, list),
                        "has_required_evidence": bool(required),
                        "has_evidence_objects": bool(objects),
                        "has_candidate_score": reason.get("candidate_score") is not None,
                    }
                )
    return {
        "future_recommendations": future_recommendations,
        "bad_contract_recommendations": bad,
        "checked": True,
        "examples": examples,
    }


def audit_future_growth(
    conn_v14: sqlite3.Connection,
    repo_root: Path | None = None,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    predicted = int(scalar(conn_v14, "SELECT COUNT(*) FROM predicted_future_edges") or 0) if table_exists(conn_v14, "predicted_future_edges") else 0
    calibration = int(scalar(conn_v14, "SELECT COUNT(*) FROM vgae_calibration_audit") or 0) if table_exists(conn_v14, "vgae_calibration_audit") else 0
    edge_calibration = future_edge_calibration_context(conn_v14)
    future_visual_contract = future_visual_edge_contract_stats(conn_v14)
    future_recommendation_contract = future_visual_recommendation_contract_stats(conn_v14)
    lifecycle_counts: dict[str, int] = {}
    future_direction_count = 0
    future_direction_scope_counts: dict[str, int] = {}
    future_direction_calibration_status_counts: dict[str, int] = {}
    uncalibrated_promoted_directions: list[dict[str, Any]] = []
    radar_eligible = 0
    if table_exists(conn_v14, "future_candidate_lifecycle"):
        lifecycle_counts = {
            str(row[0]): int(row[1])
            for row in conn_v14.execute(
                "SELECT lifecycle_state, COUNT(*) FROM future_candidate_lifecycle GROUP BY lifecycle_state"
            ).fetchall()
        }
        radar_eligible = int(
            scalar(conn_v14, "SELECT COUNT(*) FROM future_candidate_lifecycle WHERE radar_eligible=1")
            or 0
        )
    if table_exists(conn_v14, "future_directions"):
        direction_cols = columns(conn_v14, "future_directions")
        select_cols = [
            "direction_id" if "direction_id" in direction_cols else "NULL AS direction_id",
            "direction_name" if "direction_name" in direction_cols else "NULL AS direction_name",
            "claim_scope" if "claim_scope" in direction_cols else "NULL AS claim_scope",
            "evidence_tier" if "evidence_tier" in direction_cols else "NULL AS evidence_tier",
            "calibration_label" if "calibration_label" in direction_cols else "NULL AS calibration_label",
            "evidence_json" if "evidence_json" in direction_cols else "NULL AS evidence_json",
        ]
        rows = conn_v14.execute(f"SELECT {', '.join(select_cols)} FROM future_directions").fetchall()
        future_direction_count = len(rows)
        for row in rows:
            direction_id, direction_name, claim_scope, evidence_tier, calibration_label, evidence_json = row
            evidence = _loads(evidence_json, {}) if evidence_json else {}
            status = str(evidence.get("calibration_status") or "")
            if not status:
                if calibration > 0 and calibration_label:
                    status = "calibrated_with_run_audit"
                elif calibration_label:
                    status = "edge_has_calibration_label_but_run_audit_missing"
                else:
                    status = "not_calibrated"
            scope = str(claim_scope or "candidate_pool_only")
            tier = str(evidence_tier or evidence.get("evidence_tier") or "")
            future_direction_scope_counts[scope] = future_direction_scope_counts.get(scope, 0) + 1
            future_direction_calibration_status_counts[status] = (
                future_direction_calibration_status_counts.get(status, 0) + 1
            )
            run_calibrated = status == "calibrated_with_run_audit"
            candidate_only = scope in {"candidate_pool_only", "not_for_user_claim"} or tier == "exploratory_uncalibrated_candidate"
            if not run_calibrated and not candidate_only:
                uncalibrated_promoted_directions.append(
                    {
                        "direction_id": direction_id,
                        "direction_name": direction_name,
                        "claim_scope": scope,
                        "evidence_tier": tier,
                        "calibration_status": status,
                    }
                )
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
    root = repo_root or Path(".")
    step9_path = root / "echelon/v14b/step9_report.py"
    step9_text = step9_path.read_text(encoding="utf-8") if step9_path.exists() else ""
    config_path = root / "echelon/v14b/config.py"
    step6_path = root / "echelon/v14b/step6_fusion.py"
    step10_path = root / "echelon/v14b/step10_visual_graph_builder.py"
    lifecycle_path = root / "echelon/v14b/future_candidate_lifecycle.py"
    topic_regression_path = root / "echelon/v14b/topic_regression.py"
    product_baseline_path = root / "echelon/v14b/product_baseline.py"
    direction_readiness_path = root / "echelon/v14b/direction_readiness_audit.py"
    step12_path = root / "echelon/v14b/step12_goal_alignment_audit.py"
    direction_report_base = report_dir if report_dir is not None else root / "reports/v14b_pilot"
    direction_report_path = direction_report_base / "direction_readiness_audit.md"
    direction_report_text = (
        direction_report_path.read_text(encoding="utf-8")
        if direction_report_path.exists()
        else ""
    )
    goal_alignment_report_path = direction_report_base / "goal_alignment_audit_step1_step6.md"
    goal_alignment_report_text = (
        goal_alignment_report_path.read_text(encoding="utf-8")
        if goal_alignment_report_path.exists()
        else ""
    )
    algorithm_report_path = direction_report_base / "V14B_Evidence_Decision_算法验证报告.md"
    algorithm_report_text = (
        algorithm_report_path.read_text(encoding="utf-8")
        if algorithm_report_path.exists()
        else ""
    )
    future_report_path = direction_report_base / "未来候选方向_证据合同报告.md"
    future_report_text = (
        future_report_path.read_text(encoding="utf-8")
        if future_report_path.exists()
        else ""
    )
    lifecycle_report_path = direction_report_base / "future_candidate_lifecycle_audit.md"
    lifecycle_report_text = (
        lifecycle_report_path.read_text(encoding="utf-8")
        if lifecycle_report_path.exists()
        else ""
    )
    api_path = root / "echelon/api/graph_visual_backend.py"
    app_path = root / "web/visual-graph/app.js"
    current_future_docs = (
        root / "reports/v14b_pilot/100h_product_execution_plan.md",
        root / "reports/v14b_pilot/100h_value_delivery_plan.md",
        root / "reports/v14b_pilot/algorithm_audit_step1_step6.md",
        root / "reports/v14b_pilot/end_to_end_audit_goals_20260530.md",
    )
    source_checks = {
        "step9_vgae_language_is_candidate_generator": (
            bool(step9_text)
            and "Future candidate generator 候选边数" in step9_text
            and "## 7. Future Candidate Generator" in step9_text
            and "GNN/VGAE 只生成 future candidate edges" in step9_text
            and "公开报告只显示" in step9_text
            and "candidate_score" in step9_text
            and "不是方向结论" in step9_text
            and "Step13 complete Claim Card" in step9_text
            and "VGAE 预测未来边数" not in step9_text
            and "VGAE Link Prediction" not in step9_text
            and (
                not algorithm_report_text
                or (
                    "candidate_score" in algorithm_report_text
                    and "predicted_prob" not in algorithm_report_text
                    and "calibrated_prob" not in algorithm_report_text
                    and "候选概率" not in algorithm_report_text
                )
            )
        ),
        "future_report_filename_is_candidate_contract": (
            _source_contains(config_path, ("REPORT_FUTURE_DIRECTIONS", "未来候选方向_证据合同报告.md"))
            and "未来候选方向_证据合同报告.md" in step9_text
            and "未来方向预测_交集报告.md" not in step9_text
        ),
        "future_direction_report_uses_candidate_score_labels": (
            _source_contains(
                step9_path,
                (
                    "candidate_score (候选排序分数)",
                    "calibrated_candidate_score=",
                    "raw_candidate_score=",
                    "**candidate_score**",
                ),
            )
            and (
                not future_report_text
                or (
                    "candidate_score (候选排序分数)" in future_report_text
                    and "calibrated_candidate_score=" in future_report_text
                    and "raw_candidate_score=" in future_report_text
                    and "calibrated=" not in future_report_text
                    and "raw=" not in future_report_text
                    and "| # | 候选方向 | 排序分数 |" not in future_report_text
                    and "- **排序分数**" not in future_report_text
                )
            )
        ),
        "step6_future_evidence_avoids_prediction_copy": (
            _source_contains(step6_path, ("GNN/VGAE candidate edge", "Future candidate generator"))
            and _source_contains(
                api_path,
                (
                    "_future_candidate_evidence_text",
                    "GNN/VGAE candidate edge",
                    "candidate_score=",
                    "calibrated_candidate_score=",
                    "raw_candidate_score=",
                ),
            )
            and _source_contains(step9_path, ("_future_candidate_evidence_text", "candidate_score=", "候选排序分数"))
            and _source_absent(step6_path, ("VGAE pred:", "VGAE predicted future connections", "Link Prediction"))
            and _source_absent(step9_path, ("| 源论文 | 目标论文 | 候选概率 |",))
        ),
        "step6_strong_fusion_requires_decision_grade_sections": _source_contains(
            step6_path,
            (
                "has_decision_grade_section_evidence",
                "limitation_decision_grade_section_count",
                "current parser-contract decision-grade limitation section evidence",
                "triangulated_strong",
            ),
        ),
        "current_docs_label_future_edges_as_candidates": all(
            _source_absent(
                path,
                (
                    "predicted future edges",
                    "predicted edges",
                    "VGAE predictions",
                    "cross-field predicted edges",
                    "model probability",
                    "calibrated probability product",
                    "calibrated probability",
                    "technical probability",
                ),
            )
            for path in current_future_docs
            if path.exists()
        ),
        "public_future_candidate_language_avoids_prediction_copy": (
            _source_contains(api_path, ("future candidate generator", "candidate_score"))
            and _source_contains(app_path, ("future candidate generator", "candidate score"))
            and _source_absent(
                api_path,
                (
                    "temporal link prediction",
                    "predicted link",
                    "predicted directions",
                    "direction confidence",
                    "cumulative confidence",
                ),
            )
            and _source_absent(
                app_path,
                (
                    "temporal link prediction",
                    "GNN/VGAE confidence",
                    "technical probability",
                    "calibrated probability",
                    "GNN/VGAE 预测了可能连接",
                ),
            )
        ),
        "ui_future_calibration_copy_uses_candidate_score_labels": (
            _source_contains(
                app_path,
                (
                    "function futureCalibrationCopy",
                    "calibrated_candidate_score",
                    "raw_candidate_score",
                    "candidate_score",
                ),
            )
            and _source_absent(
                app_path,
                (
                    "evidence.calibrated_prob",
                    "raw_predicted_prob",
                    " / raw ",
                ),
            )
        ),
        "public_future_model_evidence_uses_candidate_score_labels": (
            _source_contains(
                api_path,
                (
                    "calibrated_candidate_score",
                    "raw_candidate_score",
                    "calibrated_prob",
                    "raw_predicted_prob",
                ),
            )
            and _source_absent(
                api_path,
                (
                    '"calibrated_prob": evidence.get',
                    '"raw_predicted_prob": evidence.get',
                ),
            )
        ),
        "public_future_evidence_objects_use_candidate_score_labels": _source_contains(
            api_path,
            (
                'if edge_type == "future_candidate":',
                '"candidate_score": candidate_score',
                '"calibrated_candidate_score": evidence.get("calibrated_candidate_score")',
                'obj.pop("confidence", None)',
            ),
        ),
        "direction_readiness_report_uses_candidate_score_labels": (
            _source_contains(
                direction_readiness_path,
                (
                    "_public_latest_fusion_audit",
                    "candidate_ranking_score_avg",
                    "min_candidate_score_threshold",
                ),
            )
            and (
                not direction_report_text
                or (
                    "candidate_ranking_score_avg" in direction_report_text
                    and "min_candidate_score_threshold" in direction_report_text
                    and "prediction_confidence_avg" not in direction_report_text
                    and "min_vgae_confidence" not in direction_report_text
                )
            )
        ),
        "step12_goal_alignment_report_uses_candidate_score_labels": (
            _source_contains(
                step12_path,
                (
                    "candidate_ranking_score_avg",
                    "min_candidate_score_threshold",
                    "candidate_edges_used",
                    "top_candidate_edges_used",
                ),
            )
            and _source_absent(
                step12_path,
                (
                    "min_vgae_candidate_score",
                    "top_vgae_candidate_edges_used",
                ),
            )
            and (
                not goal_alignment_report_text
                or (
                    "candidate_ranking_score_avg" in goal_alignment_report_text
                    and "min_candidate_score_threshold" in goal_alignment_report_text
                    and "candidate_edges_used" in goal_alignment_report_text
                    and "top_candidate_edges_used" in goal_alignment_report_text
                    and "prediction_confidence_avg" not in goal_alignment_report_text
                    and "min_vgae_confidence" not in goal_alignment_report_text
                    and "min_vgae_candidate_score" not in goal_alignment_report_text
                    and "vgae_top_n" not in goal_alignment_report_text
                    and "top_vgae_candidate_edges_used" not in goal_alignment_report_text
                )
            )
        ),
        "topic_dossier_builders_use_candidate_edges_contract": (
            _source_contains(
                step10_path,
                (
                    '"candidate_edges": child_future',
                    "Future candidate edges and unresolved limitation bottlenecks",
                    "future_candidate_edges + limitation_atoms",
                ),
            )
            and _source_absent(
                step10_path,
                (
                    '"predicted_edges": child_future',
                    "Predicted growth arcs",
                ),
            )
            and _source_absent(topic_regression_path, ('future_growth.get("predicted_edges")',))
            and _source_absent(product_baseline_path, ('future_growth.get("predicted_edges")',))
        ),
        "future_lifecycle_uses_candidate_score_labels": (
            _source_contains(
                lifecycle_path,
                (
                    '"candidate_score": candidate_score',
                    '"raw_candidate_score": raw_candidate_score',
                    '"calibrated_candidate_score": calibrated_candidate_score',
                    "candidate_score={score:.3f}",
                ),
            )
            and _source_contains(
                step10_path,
                (
                    '"candidate_score"',
                    '"raw_candidate_score"',
                    '"calibrated_candidate_score"',
                    '"candidate_score_semantics"',
                ),
            )
            and (
                not lifecycle_report_text
                or (
                    "candidate_score=" in lifecycle_report_text
                    and ", score=" not in lifecycle_report_text
                )
            )
        ),
    }
    if (
        uncalibrated_promoted_directions
        or radar_eligible > 0
        or int(future_visual_contract.get("bad_contract_edges") or 0) > 0
        or int(future_recommendation_contract.get("bad_contract_recommendations") or 0) > 0
        or not all(source_checks.values())
    ):
        status = "fail"
    elif calibration > 0 and high_conf_bad == 0:
        status = "pass"
    elif predicted > 0 and edge_calibration.get("edge_calibrated_candidates", 0) > 0:
        status = "warn"
    else:
        status = _gate_status(predicted >= 0 and high_conf_bad == 0 and calibration > 0, warn=predicted > 0)
    return {
        "issue": "Future Growth Calibration",
        "status": status,
        "future_candidate_edge_rows": predicted,
        "calibration_audits": calibration,
        "edge_calibrated_candidates": edge_calibration.get("edge_calibrated_candidates", 0),
        "edge_calibration_rate": edge_calibration.get("edge_calibration_rate", 0.0),
        "edge_calibration_labels": edge_calibration.get("edge_calibration_labels", {}),
        "edge_calibration_methods": edge_calibration.get("edge_calibration_methods", {}),
        "calibration_gap": (
            "edge-level calibrated probabilities exist, but the run-level rolling held-out-year audit table is missing"
            if predicted > 0 and edge_calibration.get("edge_calibrated_candidates", 0) > 0 and calibration == 0
            else None
        ),
        "future_candidate_lifecycle": lifecycle_counts,
        "future_directions": future_direction_count,
        "future_direction_claim_scope_counts": future_direction_scope_counts,
        "future_direction_calibration_status_counts": future_direction_calibration_status_counts,
        "uncalibrated_promoted_direction_claims": len(uncalibrated_promoted_directions),
        "uncalibrated_promoted_examples": uncalibrated_promoted_directions[:5],
        "radar_eligible_candidates": radar_eligible,
        "future_visual_edge_contract": future_visual_contract,
        "future_visual_recommendation_contract": future_recommendation_contract,
        "bad_high_confidence_cards": high_conf_bad,
        "checks": {
            "run_level_calibration_required_for_direction_claims": not uncalibrated_promoted_directions,
            "raw_future_edges_not_radar_eligible": radar_eligible == 0,
            "visual_future_edges_carry_contract": int(future_visual_contract.get("bad_contract_edges") or 0) == 0,
            "future_recommendations_carry_contract": int(
                future_recommendation_contract.get("bad_contract_recommendations") or 0
            ) == 0,
            "edge_level_calibration_not_confused_with_run_audit": not (
                predicted > 0
                and edge_calibration.get("edge_calibrated_candidates", 0) > 0
                and calibration == 0
                and future_direction_count > 0
                and not future_direction_calibration_status_counts
            ),
            **source_checks,
        },
        "policy": "VGAE/GNN is a future candidate generator only. Direction claims require run-level rolling held-out-year calibration; Radar promotion also requires Step6 fusion plus Step13 complete Claim Card.",
    }


def audit_claim_card_engine(conn_v14: sqlite3.Connection, repo_root: Path | None = None) -> dict[str, Any]:
    required_cols = {
        "root_constraint_json",
        "attempts_last_10y_json",
        "enabling_conditions_json",
        "unresolved_bottleneck_json",
        "minimal_validation_experiment_json",
        "five_question_complete",
        "high_confidence_eligible",
        "evidence_grade",
        "claim_scope",
        "uncertainty_reasons_json",
        "evidence_objects_json",
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
    invalid_experiments: list[str] = []
    invalid_evidence_contracts: list[dict[str, Any]] = []
    if required_cols.issubset(cols):
        rows = conn_v14.execute(
            """
            SELECT claim_card_id, minimal_validation_experiment_json
            FROM direction_claim_cards
            WHERE five_question_complete=1
            LIMIT 50
            """
        ).fetchall()
        for row in rows:
            experiment = _loads(row[1], {})
            if not (
                isinstance(experiment, dict)
                and experiment.get("experiment")
                and experiment.get("cost_level")
                and experiment.get("cycle_weeks")
                and experiment.get("success_criteria")
                and experiment.get("falsification_conditions")
            ):
                invalid_experiments.append(str(row[0]))
        contract_rows = conn_v14.execute(
            """
            SELECT claim_card_id, evidence_grade, claim_scope,
                   uncertainty_reasons_json, evidence_objects_json
            FROM direction_claim_cards
            LIMIT 100
            """
        ).fetchall()
        for row in contract_rows:
            claim_card_id, evidence_grade, claim_scope, uncertainty_raw, objects_raw = row
            reasons = _loads(uncertainty_raw, None)
            objects = _loads(objects_raw, None)
            missing: list[str] = []
            if not evidence_grade:
                missing.append("evidence_grade")
            if not claim_scope:
                missing.append("claim_scope")
            if not isinstance(reasons, list):
                missing.append("uncertainty_reasons_json")
            if not isinstance(objects, list) or not objects:
                missing.append("evidence_objects_json")
            if missing:
                invalid_evidence_contracts.append({"claim_card_id": claim_card_id, "missing": missing})
    source_checks = {
        "step13_requires_success_and_falsification": False,
        "ui_renders_success_and_falsification": False,
    }
    if repo_root is not None:
        source_checks = {
            "step13_requires_success_and_falsification": _source_contains(
                repo_root / "echelon/v14b/step13_first_principles_history.py",
                (
                    "success_criteria",
                    "falsification_conditions",
                    "minimal validation experiment with success and falsification criteria",
                    "evidence_grade",
                    "uncertainty_reasons_json",
                    "evidence_objects_json",
                ),
            ),
            "ui_renders_success_and_falsification": _source_contains(
                repo_root / "web/visual-graph/app.js",
                ("Success criteria", "Falsification", "experiment.falsification_conditions"),
            ),
        }
    checks = {
        "required_columns_present": required_cols.issubset(cols),
        "no_high_confidence_without_complete_card": bad_high == 0,
        "complete_cards_have_falsifiable_validation_experiment": not invalid_experiments,
        "claim_cards_carry_persisted_evidence_contract": not invalid_evidence_contracts,
        **source_checks,
    }
    if not all(checks.values()):
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
        "invalid_minimal_validation_experiments": invalid_experiments,
        "invalid_evidence_contracts": invalid_evidence_contracts,
        "checks": checks,
        "missing_columns": sorted(required_cols - cols),
        "policy": (
            "A card missing any of the five hard questions is candidate_pool_only and cannot enter Radar. "
            "The minimal validation experiment must include cost, cycle, success criteria, and falsification conditions."
        ),
    }


def audit_claim_card_high_confidence_evidence_contract(
    conn_v14: sqlite3.Connection,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Verify high-confidence Claim Cards cannot bypass section evidence."""
    if not table_exists(conn_v14, "direction_claim_cards"):
        return {
            "issue": "Claim Card High-Confidence Evidence Contract",
            "status": "warn",
            "why": "direction_claim_cards table is not materialized yet",
            "policy": (
                "High-confidence Claim Cards require strong section evidence, strong/moderate parser provenance, "
                "and current parser-contract decision-grade section evidence."
            ),
        }
    cols = columns(conn_v14, "direction_claim_cards")
    required = {"claim_card_id", "high_confidence_eligible", "quality_gate_json"}
    missing_cols = sorted(required - cols)
    if missing_cols:
        return {
            "issue": "Claim Card High-Confidence Evidence Contract",
            "status": "fail",
            "missing_columns": missing_cols,
            "policy": "High-confidence Claim Cards require auditable quality_gate_json with section evidence gates.",
        }
    rows = conn_v14.execute(
        """
        SELECT claim_card_id, high_confidence_eligible, quality_gate_json
        FROM direction_claim_cards
        WHERE COALESCE(high_confidence_eligible, 0) = 1
        """
    ).fetchall()
    invalid: list[dict[str, Any]] = []
    for row in rows:
        gate = _loads(row["quality_gate_json"], {})
        high_gates = gate.get("high_confidence_gates") if isinstance(gate, dict) else {}
        provenance = gate.get("section_provenance") if isinstance(gate, dict) else {}
        strong_or_moderate = 0
        if isinstance(provenance, dict):
            strong_or_moderate = int(provenance.get("strong") or 0) + int(provenance.get("moderate") or 0)
        decision_grade = int(provenance.get("decision_grade") or 0) if isinstance(provenance, dict) else 0
        section_strong = bool((high_gates or {}).get("section_evidence_strong"))
        provenance_ready = bool((high_gates or {}).get("section_provenance_ready"))
        decision_grade_ready = bool((high_gates or {}).get("section_decision_grade_ready"))
        json_high = bool(gate.get("high_confidence_eligible")) if isinstance(gate, dict) else False
        missing = []
        if not section_strong:
            missing.append("section_evidence_strong")
        if not provenance_ready:
            missing.append("section_provenance_ready")
        if not decision_grade_ready:
            missing.append("section_decision_grade_ready")
        if strong_or_moderate < 1:
            missing.append("strong_or_moderate_section_provenance")
        if decision_grade < 1:
            missing.append("decision_grade_current_contract_section_evidence")
        if not json_high:
            missing.append("quality_gate_high_confidence_flag")
        if missing:
            invalid.append(
                {
                    "claim_card_id": row["claim_card_id"],
                    "missing": missing,
                    "section_evidence_strength": gate.get("section_evidence_strength") if isinstance(gate, dict) else None,
                    "section_provenance": provenance if isinstance(provenance, dict) else {},
                }
            )
    source_checks = {
        "step13_has_section_evidence_gate": False,
        "step13_uses_candidate_score_gate": False,
        "step9_does_not_recommend_threshold_relaxation": False,
    }
    if repo_root is not None:
        step13_path = repo_root / "echelon/v14b/step13_first_principles_history.py"
        source_checks = {
            "step13_has_section_evidence_gate": _source_contains(
                step13_path,
                (
                    "section_evidence_strong",
                    "section_provenance_ready",
                    "section_decision_grade_ready",
                    "SECTION_PARSER_CONTRACT_VERSION",
                    "missing_high_confidence_gates",
                ),
            ),
            "step13_uses_candidate_score_gate": (
                _source_contains(
                    step13_path,
                    ("candidate_score_ready", '"candidate_score": candidate_score', "future candidate score"),
                )
                and _source_absent(
                    step13_path,
                    (
                        "direction_confidence_ready",
                        '"direction_confidence":',
                        '"prediction_confidence": float(d.get("confidence")',
                        "future-growth graph confidence",
                    ),
                )
            ),
            "step9_does_not_recommend_threshold_relaxation": (
                _source_contains(
                    repo_root / "echelon/v14b/step9_report.py",
                    (
                        "保持 exploratory / candidate_pool",
                        "limitation/discussion/resolution section evidence",
                        "linked resolution evidence",
                        "阈值不得下调",
                    ),
                )
                and _source_absent(
                    repo_root / "echelon/v14b/step9_report.py",
                    (
                        "放宽阈值",
                        "降低阈值",
                        "调低阈值",
                        "lower thresholds blindly",
                    ),
                )
            ),
        }
    checks = {
        "no_high_confidence_card_without_section_evidence": not invalid,
        **source_checks,
    }
    return {
        "issue": "Claim Card High-Confidence Evidence Contract",
        "status": _gate_status(all(checks.values())),
        "checks": checks,
        "high_confidence_cards": len(rows),
        "invalid_high_confidence_cards": len(invalid),
        "invalid_examples": invalid[:5],
        "policy": (
            "A Claim Card can be high-confidence only when Step13 quality gates show strong section evidence "
            "strong/moderate parser provenance, and current parser-contract decision-grade section evidence; "
            "weak, stale-contract, or missing section evidence keeps it exploratory."
        ),
    }


def _source_contains(path: Path, needles: tuple[str, ...]) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return all(needle in text for needle in needles)


def _source_absent(path: Path, needles: tuple[str, ...]) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return all(needle not in text for needle in needles)


def _make_target_deps(makefile: str, target: str) -> list[str]:
    match = re.search(rf"^{re.escape(target)}\s*:\s*(.*)$", makefile, flags=re.M)
    if not match:
        return []
    return [
        dep.strip()
        for dep in match.group(1).split()
        if dep.strip() and not dep.strip().startswith("#")
    ]


def _make_target_context(makefile: str, target: str, *, before: int = 3, after: int = 8) -> str:
    lines = makefile.splitlines()
    target_re = re.compile(rf"^{re.escape(target)}\s*:")
    for idx, line in enumerate(lines):
        if target_re.search(line):
            start = max(0, idx - before)
            end = min(len(lines), idx + after + 1)
            return "\n".join(lines[start:end])
    return ""


def _context_contains_ordered_targets(context: str, targets: tuple[str, ...]) -> bool:
    last = -1
    for target in targets:
        patterns = (
            f"$(MAKE) {target}",
            f"${{MAKE}} {target}",
            f"make {target}",
        )
        positions = [
            pos
            for pattern in patterns
            for pos in [context.find(pattern, last + 1)]
            if pos >= 0
        ]
        if not positions:
            return False
        pos = min(positions)
        if pos <= last:
            return False
        last = pos
    return True


def audit_llm_evidence_boundary(conn_v14: sqlite3.Connection, repo_root: Path | None = None) -> dict[str, Any]:
    """Verify LLM outputs remain bounded to audit/naming/weak labels, not evidence conclusions."""
    llm_atoms = 0
    invalid_llm_atoms: list[dict[str, Any]] = []
    limitation_cols = columns(conn_v14, "limitation_atoms")
    limitation_required = {"extractor_method", "evidence_source", "evidence_quality", "evidence_weight"}
    if table_exists(conn_v14, "limitation_atoms") and limitation_required <= limitation_cols:
        llm_atoms = int(
            scalar(
                conn_v14,
                """
                SELECT COUNT(*) FROM limitation_atoms
                WHERE lower(COALESCE(extractor_method, '')) LIKE 'llm%'
                """,
            )
            or 0
        )
        rows = conn_v14.execute(
            """
            SELECT atom_id, paper_id, evidence_source, evidence_quality,
                   evidence_weight, extractor_method
            FROM limitation_atoms
            WHERE lower(COALESCE(extractor_method, '')) LIKE 'llm%'
              AND COALESCE(evidence_source, 'abstract') <> 'structured_sections'
              AND (
                COALESCE(evidence_quality, 'weak_abstract') NOT IN ('weak_abstract', 'metadata_only', 'unknown')
                OR COALESCE(evidence_weight, 0) > 0.350001
              )
            LIMIT 5
            """
        ).fetchall()
        invalid_llm_atoms = [dict(row) for row in rows]

    llm_citation_edges = 0
    invalid_llm_citation_edges: list[dict[str, Any]] = []
    subgraph_cols = columns(conn_v14, "subgraph_edges")
    subgraph_required = {
        "citation_function_method",
        "citation_context_available",
        "citation_function_evidence_level",
        "citation_function_weight",
    }
    if table_exists(conn_v14, "subgraph_edges") and subgraph_required <= subgraph_cols:
        llm_citation_edges = int(
            scalar(
                conn_v14,
                """
                SELECT COUNT(*) FROM subgraph_edges
                WHERE lower(COALESCE(citation_function_method, '')) LIKE 'llm%'
                """,
            )
            or 0
        )
        rows = conn_v14.execute(
            """
            SELECT citing_id, cited_id, citation_function_method,
                   citation_function_evidence_level, citation_context_available,
                   citation_function_weight
            FROM subgraph_edges
            WHERE lower(COALESCE(citation_function_method, '')) LIKE 'llm%'
              AND COALESCE(citation_context_available, 0) = 0
              AND (
                COALESCE(citation_function_evidence_level, '') <> 'weak_paper_metadata'
                OR COALESCE(citation_function_weight, 0) > 0.250001
              )
            LIMIT 5
            """
        ).fetchall()
        invalid_llm_citation_edges = [dict(row) for row in rows]

    source_checks = {
        "llm_defaults_off": False,
        "limitation_llm_traced_and_optional": False,
        "limitation_user_copy_is_section_first": False,
        "makefile_limitation_target_avoids_llm_cost_claim": False,
        "citation_llm_fallback_explicit_and_weak": False,
        "fusion_llm_naming_opt_in": False,
        "step13_non_llm_engine": False,
        "llm_edge_audit_is_capped_audit": False,
        "topic_preflight_no_llm": False,
    }
    if repo_root is not None:
        source_checks = {
            "llm_defaults_off": _source_contains(
                repo_root / "echelon/v14b/config.py",
                (
                    'V14B_LIMITATION_USE_LLM", "false"',
                    'V14B_SCIBERT_LLM_FALLBACK", "false"',
                    'V14B_FUSION_USE_LLM_NAMING", "false"',
                ),
            ),
            "limitation_llm_traced_and_optional": _source_contains(
                repo_root / "echelon/v14b/step5c_limitation.py",
                ("extractor_method", "LIMITATION_USE_LLM else None", "_limitation_evidence_common"),
            ),
            "limitation_user_copy_is_section_first": (
                _source_contains(
                    repo_root / "echelon/v14b/step5c_limitation.py",
                    (
                        "section-first Limitation",
                        "默认不调用外部 LLM",
                        "LLM opt-in",
                        "不能自动升级为决策级证据",
                    ),
                )
                and _source_absent(
                    repo_root / "echelon/v14b/step5c_limitation.py",
                    (
                        "LLM 把 limitation 段原子化",
                        "LLM 判 resolution",
                    ),
                )
            ),
            "makefile_limitation_target_avoids_llm_cost_claim": (
                _source_contains(
                    repo_root / "Makefile",
                    ("section-first limitation tracking", "LLM opt-in only"),
                )
                and _source_absent(
                    repo_root / "Makefile",
                    ("~$40 LLM", "LLM 费用"),
                )
            ),
            "citation_llm_fallback_explicit_and_weak": _source_contains(
                repo_root / "echelon/v14b/step5a_scibert.py",
                (
                    "--use-llm",
                    "LLM opt-in weak-label audit",
                    "weak-label audit mode",
                    "citation_function_evidence_level",
                    "weak_paper_metadata",
                    "Ignoring V14B_SCIBERT_LLM_FALLBACK",
                ),
            )
            and _source_contains(
                repo_root / "echelon/v14b/config.py",
                (
                    "Low-confidence edges fall",
                    "back to heuristic correction",
                    "不隐式调用 LLM",
                ),
            )
            and _source_contains(
                repo_root / "echelon/v14b/step9_report.py",
                (
                    "Citation-function evidence 覆盖率",
                    "Citation Function Evidence",
                    "capped LLM edge audit",
                    "LLM 结果只能作为弱标签",
                    "不能直接升级结论",
                ),
            )
            and _source_absent(
                repo_root / "echelon/v14b/step5a_scibert.py",
                (
                    "自动降级到 LLM 分类",
                    "降级到 LLM",
                    "LLM 降级",
                    "强制使用 LLM 分类",
                    "低置信度的降级到 LLM",
                    "将使用 LLM",
                ),
            )
            and _source_absent(
                repo_root / "echelon/v14b/config.py",
                ("降级到 LLM 分类",),
            )
            and _source_absent(
                repo_root / "echelon/v14b/step9_report.py",
                (
                    "考虑换 LLM 分类",
                    "SciBERT 分类完成率",
                    "SciBERT 引用功能分布",
                ),
            ),
            "fusion_llm_naming_opt_in": _source_contains(
                repo_root / "echelon/v14b/step6_fusion.py",
                ("FUSION_USE_LLM_NAMING", "Optional LLM naming"),
            ),
            "step13_non_llm_engine": _source_contains(
                repo_root / "echelon/v14b/step13_first_principles_history.py",
                ("默认不调用外部 LLM", "已入库证据可重跑"),
            ),
            "llm_edge_audit_is_capped_audit": _source_contains(
                repo_root / "echelon/v14b/step11_llm_edge_audit.py",
                ("Stratified LLM edge audit", "Default execution is capped"),
            ),
            "topic_preflight_no_llm": _source_contains(
                repo_root / "echelon/v14b/topic_readiness.py",
                ("NO_LLM_PREFLIGHT_POLICY", "LLM may audit/name/explain only after evidence exists"),
            ),
        }

    missing_data_contracts = []
    if table_exists(conn_v14, "limitation_atoms") and not limitation_required <= limitation_cols:
        missing_data_contracts.append("limitation_atoms extractor/evidence columns")
    if table_exists(conn_v14, "subgraph_edges") and not subgraph_required <= subgraph_cols:
        missing_data_contracts.append("subgraph_edges citation evidence columns")
    checks = {
        "abstract_llm_atoms_remain_weak": not invalid_llm_atoms,
        "llm_citation_without_context_remains_weak": not invalid_llm_citation_edges,
        "llm_data_contract_columns_present": not missing_data_contracts,
        **source_checks,
    }
    return {
        "issue": "LLM Evidence Boundary Contract",
        "status": _gate_status(all(checks.values()), warn=bool(missing_data_contracts)),
        "checks": checks,
        "llm_limitation_atoms": llm_atoms,
        "invalid_llm_atoms": len(invalid_llm_atoms),
        "invalid_llm_atom_examples": invalid_llm_atoms,
        "llm_citation_edges": llm_citation_edges,
        "invalid_llm_citation_edges": len(invalid_llm_citation_edges),
        "invalid_llm_citation_examples": invalid_llm_citation_edges,
        "missing_data_contracts": missing_data_contracts,
        "policy": (
            "LLM may audit, name, classify weak labels, or explain existing evidence; it must not create "
            "decision-grade evidence unless the claim is anchored to structured evidence and carries uncertainty."
        ),
    }


def audit_online_topic_readiness_contract(repo_root: Path | None = None) -> dict[str, Any]:
    """Verify arbitrary-topic readiness stays deterministic and surfaced online."""
    readiness = build_topic_readiness_preflight(
        topic="arbitrary photonics audit topic",
        topic_dossier={
            "claim_scope": "candidate_pool_only",
            "evidence_grade": "metadata_only",
            "uncertainty_reasons": ["audit fixture"],
            "branch_splits": [{"name": "Audit branch"}],
            "hard_bottlenecks": [{"name": "integration"}],
            "reading_path": [
                {
                    "claim_scope": "candidate_pool_only",
                    "evidence_grade": "section_backed",
                    "uncertainty_reasons": ["audit fixture"],
                    "evidence_objects": [{"type": "paper", "paper_id": f"r{i}"}],
                }
                for i in range(4)
            ],
        },
        turning_hits=[
            {
                "paper_id": "p1",
                "access_links": [{"url": "https://example.test"}],
                "content_availability": {
                    "has_primary_evidence_sections": True,
                    "has_strong_or_moderate_primary_evidence_sections": False,
                },
            }
        ],
        future_growth=[{"edge_id": "future:p1:p2"}],
        rd_radar={
            "claim_cards": [
                {
                    "eligible": False,
                    "claim_card": {"five_question_complete": True},
                }
            ]
        },
        first_principles_questions=[
            {
                "claim_scope": "candidate_pool_only",
                "evidence_grade": "section_backed",
                "uncertainty_reasons": ["audit fixture"],
                "evidence_objects": [{"type": "paper", "paper_id": f"q{i}"}],
            }
            for i in range(5)
        ],
        bottleneck_lineage={
            "constraints": [
                {
                    "claim_scope": "bottleneck_lineage_evidence",
                    "evidence_grade": "typed_section_lineage",
                    "uncertainty_reasons": ["audit fixture"],
                    "typed_chain_completeness": "full",
                    "typed_chain": [{"source_stage": "constraint", "target_stage": "failure_mechanism"}],
                    "evidence_objects": [{"type": "bottleneck_lineage_triple", "paper_id": "p1"}],
                }
            ]
        },
    )
    gate_names = {str(g.get("name")) for g in readiness.get("gates") or []}
    required_gates_present = REQUIRED_TOPIC_READINESS_GATES <= gate_names
    no_llm = readiness.get("llm_policy") == NO_LLM_PREFLIGHT_POLICY
    arbitrary_topic_ready = (
        readiness.get("audit_type") == "deterministic_topic_readiness_preflight"
        and readiness.get("readiness_level") == "claim_card_available_with_gaps"
        and readiness.get("overall_status") == "warn"
    )
    source_checks = {
        "api_exposes_topic_readiness": False,
        "api_topic_branch_splits_inherit_lineage": False,
        "api_reading_path_items_carry_limits": False,
        "api_search_hits_carry_contract": False,
        "api_evidence_atom_search_is_read_only_contract": False,
        "api_topic_bottlenecks_use_resolution_evidence": False,
        "api_limitation_atoms_carry_contract": False,
        "api_topic_validation_directions_inherit_claim_card_evidence": False,
        "api_validation_directions_carry_limits": False,
        "ui_search_fallback_is_insufficient_evidence": False,
        "ui_renders_topic_readiness": False,
        "ui_renders_reading_path_limits": False,
        "ui_paper_list_renders_hit_contract": False,
        "ui_renders_topic_dossier_branch_contracts": False,
        "ui_renders_limitation_contracts": False,
        "ui_renders_topic_bottleneck_resolution_counts": False,
        "ui_renders_validation_direction_evidence_objects": False,
        "ui_renders_validation_direction_limits": False,
        "topic_regression_uses_shared_contract": False,
    }
    if repo_root is not None:
        source_checks = {
            "api_exposes_topic_readiness": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                ("topic_readiness", "build_topic_readiness_preflight"),
            ),
            "api_topic_branch_splits_inherit_lineage": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _build_topic_branch_splits",
                    "branch_dossiers",
                    "branch_contract_by_id",
                    "parent_branch_id",
                    "lineage_status",
                    "split_confidence",
                ),
            ),
            "api_reading_path_items_carry_limits": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _reading_path_item",
                    '"can_explain": can_explain',
                    '"cannot_explain": cannot_explain',
                    "Radar promotion without complete Step13 Claim Cards",
                    "GNN/VGAE is a candidate generator, not a conclusion generator",
                ),
            ),
            "api_search_hits_carry_contract": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _paper_hit_contract",
                    "_hydrate_hits",
                    "visual_search_hit",
                    "reason.get(\"claim_scope\")",
                    "reason.get(\"evidence_objects\")",
                    "retrieval_context_only",
                    "claim_scope",
                    "evidence_grade",
                    "uncertainty_reasons",
                ),
            ),
            "api_evidence_atom_search_is_read_only_contract": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def search_evidence_atoms",
                    "_connect_main(readonly=True)",
                    "section_atoms_fts",
                    "section_atom_embeddings",
                    "search_section_atoms_hybrid",
                    "ensure_schema=False",
                    "retrieval_context_only",
                ),
            ),
            "api_topic_bottlenecks_use_resolution_evidence": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "limitation_resolutions",
                    "def _limitation_is_resolved",
                    "resolved_evidence_count",
                    "unresolved_evidence_count",
                    "resolution_status",
                ),
            ),
            "api_limitation_atoms_carry_contract": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _limitation_atom_contract",
                    "weak_bottleneck_hypothesis",
                    "section_limitation_context",
                    "claim_scope",
                    "evidence_grade",
                    "uncertainty_reasons",
                ),
            ),
            "api_topic_validation_directions_inherit_claim_card_evidence": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _claim_card_evidence_objects",
                    "minimal_validation_experiment",
                    "Step13 Claim Card",
                    '"evidence_objects": item.get("evidence_objects")',
                ),
            ),
            "api_validation_directions_carry_limits": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _build_validation_directions",
                    '"can_explain": [',
                    '"cannot_explain": [',
                    '"required_evidence": [',
                    "that the direction is ready for Radar",
                    "Radar promotion without a complete Claim Card",
                ),
            ),
            "ui_search_fallback_is_insufficient_evidence": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "buildSearchFallbackTopicLens",
                    "ui_search_fallback_readiness",
                    "insufficient_evidence",
                    "retrieval_context_only",
                    "No branch lineage, bottleneck lineage, main-path, Step6 fusion, or Step13 Claim Card",
                ),
            ),
            "ui_renders_topic_readiness": _source_contains(
                repo_root / "web/visual-graph/app.js",
                ("renderTopicReadiness", "topic_readiness"),
            ),
            "ui_renders_reading_path_limits": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "renderTopicDossier",
                    "readingPath",
                    "item.can_explain",
                    "item.cannot_explain",
                    "不能说明",
                ),
            ),
            "ui_paper_list_renders_hit_contract": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "renderPaperList",
                    "paper.claim_scope",
                    "paper.evidence_grade",
                    "paper.uncertainty_reasons",
                    "paper.required_evidence",
                    "renderEvidenceObjects(paper.evidence_objects",
                ),
            ),
            "ui_renders_topic_dossier_branch_contracts": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "renderTopicDossier",
                    "split.lineage_status",
                    "split.parent_branch_id",
                    "split.claim_scope",
                    "split.evidence_grade",
                    "split.uncertainty_reasons",
                ),
            ),
            "ui_renders_limitation_contracts": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "renderLimitations",
                    "lim.claim_scope",
                    "lim.evidence_grade",
                    "lim.uncertainty_reasons",
                    "renderEvidenceObjects(lim.evidence_objects",
                ),
            ),
            "ui_renders_topic_bottleneck_resolution_counts": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "renderTopicDossier",
                    "b.resolution_status",
                    "b.unresolved_evidence_count",
                    "b.resolved_evidence_count",
                ),
            ),
            "ui_renders_validation_direction_evidence_objects": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "renderTopicDossier",
                    "d.minimal_validation_experiment",
                    "renderEvidenceObjects(d.evidence_objects",
                ),
            ),
            "ui_renders_validation_direction_limits": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "renderTopicDossier",
                    "d.can_explain",
                    "d.cannot_explain",
                    "d.required_evidence",
                    "进入 Radar 还需要",
                ),
            ),
            "topic_regression_uses_shared_contract": _source_contains(
                repo_root / "echelon/v14b/topic_regression.py",
                ("run_topic_readiness_preflight", "build_topic_readiness_preflight"),
            ),
        }
    checks = {
        "no_llm_preflight": no_llm,
        "arbitrary_topic_not_benchmark_gated": arbitrary_topic_ready,
        "required_readiness_gates_present": required_gates_present,
        **source_checks,
    }
    return {
        "status": _gate_status(all(checks.values())),
        "checks": checks,
        "readiness_level": readiness.get("readiness_level"),
        "overall_status": readiness.get("overall_status"),
        "required_gates": sorted(REQUIRED_TOPIC_READINESS_GATES),
        "observed_gates": sorted(gate_names),
        "policy": (
            "Any topic must receive a deterministic, no-LLM readiness state; "
            "benchmark topics are regression fixtures, not a product allowlist."
        ),
    }


def audit_topic_dossier(conn_v14: sqlite3.Connection, repo_root: Path | None = None) -> dict[str, Any]:
    visual_nodes = int(scalar(conn_v14, "SELECT COUNT(*) FROM visual_nodes") or 0) if table_exists(conn_v14, "visual_nodes") else 0
    visual_edges = int(scalar(conn_v14, "SELECT COUNT(*) FROM visual_edges") or 0) if table_exists(conn_v14, "visual_edges") else 0
    has_search = table_exists(conn_v14, "visual_search_fts")
    graph_ready = visual_nodes > 0 and visual_edges > 0 and has_search
    readiness_contract = audit_online_topic_readiness_contract(repo_root)
    if graph_ready and readiness_contract["status"] == "pass":
        status = "pass"
    elif readiness_contract["status"] != "pass":
        status = "fail"
    else:
        status = "warn"
    return {
        "issue": "Topic Dossier Product Value",
        "status": status,
        "visual_nodes": visual_nodes,
        "visual_edges": visual_edges,
        "has_visual_search_fts": has_search,
        "online_readiness_contract": readiness_contract,
        "policy": "Topic Lens first screen must answer branches, bottlenecks, turning papers, and validation candidates before raw graph exploration.",
    }


def _sample_visual_value_model() -> dict[str, Any]:
    from echelon.api import graph_visual_backend as graph_backend

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE visual_edges (edge_type TEXT, layer TEXT, is_main_path INTEGER);
        CREATE TABLE future_directions (direction_id INTEGER);
        CREATE TABLE direction_claim_cards (claim_card_id TEXT);
        CREATE TABLE fusion_evidence_audit (created_at TEXT, adequacy_label TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO visual_edges VALUES (?, ?, ?)",
        [
            ("main_path", "citation", 1),
            ("citation", "citation", 0),
            ("topic", "topic", 0),
            ("semantic", "semantic", 0),
            ("future_growth", "future", 0),
        ],
    )
    conn.execute("INSERT INTO future_directions VALUES (1)")
    conn.execute("INSERT INTO direction_claim_cards VALUES ('cc1')")
    conn.execute("INSERT INTO fusion_evidence_audit VALUES ('2026-01-01T00:00:00Z', 'adequate_for_candidate_pool')")
    original_frontfill = graph_backend._frontfill_status
    graph_backend._frontfill_status = lambda _conn=None: {
        "available": True,
        "linked_ref_rate": 0.12,
        "primary_section_rate": 0.02,
        "openalex_w_rate": 0.55,
    }
    try:
        return graph_backend._visual_value_model(conn)
    finally:
        graph_backend._frontfill_status = original_frontfill
        conn.close()


def audit_evolution_evidence_map_contract(repo_root: Path | None = None) -> dict[str, Any]:
    """Verify Evolution Evidence Map layers explain use, limits, and evidence needs."""
    try:
        from echelon.api.graph_visual_backend import (
            _apply_history_main_path_contract,
            _build_evidence_map,
            _build_history_main_path_contract,
        )

        model = _sample_visual_value_model()
        sample_main_path_edges = [
            {
                "edge_id": "main:p1:p2",
                "source_paper_id": "p1",
                "target_paper_id": "p2",
                "plain_language": "sample main-path support edge",
            }
        ]
        sample_turning_hits = [{"paper_id": "p2", "title": "Sample turning paper"}]
        history_contract = _build_history_main_path_contract(
            main_path_edges=sample_main_path_edges,
            key_turning_papers=sample_turning_hits,
            broader_context_papers=[],
            value_model=model,
        )
        _apply_history_main_path_contract(sample_main_path_edges, history_contract)
        evidence_map = _build_evidence_map(
            main_path_edges=sample_main_path_edges,
            turning_hits=sample_turning_hits,
            future_growth=[],
            branch_dossiers=[],
            value_model=model,
            history_main_path_contract=history_contract,
        )
    except Exception as exc:
        return {
            "issue": "Evolution Evidence Map Contract",
            "status": "fail",
            "error": str(exc),
            "policy": "Evolution Evidence Map must expose layer meanings and combination limits as data, not only UI prose.",
        }
    layers = model.get("layers") or {}
    combos = [
        combo for combo in (model.get("layer_combinations") or [])
        if isinstance(combo, dict)
    ]
    map_main_path = evidence_map.get("main_path") or {}
    layer_names = set(layers)
    combo_sets = {tuple(combo.get("layers") or []) for combo in combos}
    missing_layers = sorted(REQUIRED_EVIDENCE_MAP_LAYERS - layer_names)
    missing_combos = [
        list(combo)
        for combo in sorted(REQUIRED_EVIDENCE_MAP_COMBOS)
        if combo not in combo_sets
    ]
    layer_contracts_ok = all(
        isinstance(layers.get(name), dict)
        and layers[name].get("algorithm")
        and layers[name].get("relationship")
        and layers[name].get("display")
        for name in REQUIRED_EVIDENCE_MAP_LAYERS
    )
    combo_contracts_ok = bool(combos) and all(
        combo.get("layers")
        and combo.get("label")
        and combo.get("question")
        and combo.get("decision_use")
        and combo.get("relationship")
        and combo.get("display")
        and combo.get("can_explain")
        and combo.get("cannot_explain")
        and combo.get("required_evidence")
        and combo.get("claim_scope")
        and combo.get("evidence_grade")
        and isinstance(combo.get("uncertainty_reasons"), list)
        for combo in combos
    )
    fusion_combo_ok = any("fusion_value" in (combo.get("layers") or []) for combo in combos)
    map_main_path_contract_ok = (
        bool(map_main_path.get("claim_scope"))
        and bool(map_main_path.get("evidence_grade"))
        and isinstance(map_main_path.get("uncertainty_reasons"), list)
        and bool(map_main_path.get("required_evidence"))
        and bool(map_main_path.get("evidence_objects"))
        and bool(map_main_path.get("can_explain"))
        and bool(map_main_path.get("cannot_explain"))
    )
    source_checks = {
        "api_returns_evidence_map": False,
        "api_evidence_map_main_path_carries_contract": False,
        "api_evidence_map_future_edges_carry_contract": False,
        "api_evidence_map_branches_carry_contract": False,
        "api_visual_edges_carry_contract": False,
        "ui_renders_evidence_map_contract": False,
        "ui_renders_evidence_map_main_path_contract": False,
        "ui_renders_future_edge_contracts": False,
        "ui_renders_local_edge_contracts": False,
        "ui_has_fusion_value_layer_control": False,
    }
    if repo_root is not None:
        source_checks = {
            "api_returns_evidence_map": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                ("_build_evidence_map", "recommended_layer_combinations", '"evidence_map": evidence_map'),
            ),
            "api_evidence_map_main_path_carries_contract": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "_build_evidence_map",
                    "history_main_path_contract",
                    '"main_path": {',
                    '"claim_scope": main_path_contract.get("claim_scope")',
                    '"evidence_grade": main_path_contract.get("evidence_grade")',
                    '"evidence_objects": main_path_contract.get("evidence_objects")',
                ),
            ),
            "api_evidence_map_future_edges_carry_contract": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _apply_future_edge_contracts",
                    "future_candidates",
                    "candidate_pool_only",
                    "required_evidence",
                    "evidence_objects",
                ),
            ),
            "api_evidence_map_branches_carry_contract": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    '"branches": [',
                    "parent_branch_id",
                    "lineage_status",
                    "claim_scope",
                    "evidence_grade",
                    "uncertainty_reasons",
                ),
            ),
            "api_visual_edges_carry_contract": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _visual_edge_contract",
                    "get_visual_edges",
                    "visual_edge",
                    "claim_scope",
                    "evidence_grade",
                    "uncertainty_reasons",
                ),
            ),
            "ui_renders_evidence_map_contract": _source_contains(
                repo_root / "web/visual-graph/app.js",
                ("renderEvidenceMapSummary", "renderComboContract", "Fusion value"),
            ),
            "ui_renders_evidence_map_main_path_contract": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "renderEvidenceMapSummary",
                    "const mainPath = evidence.main_path",
                    "Main-path evidence boundary",
                    "renderComboContract(mainPath)",
                    "renderEvidenceObjects(mainPath.evidence_objects",
                ),
            ),
            "ui_renders_future_edge_contracts": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "Future edge uncertainty",
                    "edge.claim_scope",
                    "edge.evidence_grade",
                    "edge.required_evidence",
                    "edge.uncertainty_reasons",
                    "renderEvidenceObjects(edge.evidence_objects",
                ),
            ),
            "ui_renders_local_edge_contracts": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "renderLocalEdges",
                    "localEdgeScoreCopy",
                    "candidate_score",
                    "support_score",
                    "edge.claim_scope",
                    "edge.evidence_grade",
                    "edge.uncertainty_reasons",
                    "renderEvidenceObjects(edge.evidence_objects",
                ),
            )
            and _source_absent(repo_root / "web/visual-graph/app.js", ("edge score",)),
            "ui_has_fusion_value_layer_control": _source_contains(
                repo_root / "web/visual-graph/index.html",
                ('data-layer="fusion_value"', "Fusion value"),
            ),
        }
    checks = {
        "required_layers_present": not missing_layers,
        "layer_contracts_present": layer_contracts_ok,
        "required_layer_combinations_present": not missing_combos,
        "combination_contracts_present": combo_contracts_ok,
        "fusion_value_is_auditable_layer": fusion_combo_ok,
        "evidence_map_main_path_contract_present": map_main_path_contract_ok,
        **source_checks,
    }
    return {
        "issue": "Evolution Evidence Map Contract",
        "status": _gate_status(all(checks.values())),
        "checks": checks,
        "missing_layers": missing_layers,
        "missing_required_combinations": missing_combos,
        "layer_count": len(layer_names),
        "combination_count": len(combos),
        "fusion_status": model.get("fusion_status"),
        "policy": (
            "Each Evidence Map layer, top-level Evidence Map section, and recommended layer combination must say what it shows, "
            "what it can explain, what it cannot explain, required evidence, claim_scope, evidence_grade, and uncertainty; "
            "individual visual edges must carry the same evidence boundary when exposed in API or paper detail."
        ),
    }


def audit_rd_radar_promotion_contract(repo_root: Path | None = None) -> dict[str, Any]:
    """Verify Radar promotion is Claim-Card-gated, not raw future-edge display."""
    try:
        from echelon.api.graph_visual_backend import _build_rd_radar

        radar = _build_rd_radar(
            future_directions=[
                {
                    "direction_id": 1,
                    "direction_name": "Incomplete sample direction",
                    "confidence": 0.9,
                    "claim_scope": "exploratory_incomplete_card",
                    "claim_card": {
                        "five_question_complete": False,
                        "high_confidence_eligible": False,
                        "quality_gate": {"missing_gates": ["root constraint"]},
                    },
                },
                {
                    "direction_id": 2,
                    "direction_name": "Complete sample direction",
                    "confidence": 0.72,
                    "claim_scope": "exploratory_with_claim_card",
                    "claim_card": {
                        "five_question_complete": True,
                        "high_confidence_eligible": False,
                        "quality_gate": {
                            "missing_high_confidence_gates": ["strong section-level evidence"]
                        },
                    },
                },
            ],
            future_growth=[
                {
                    "source_paper_id": "p1",
                    "target_paper_id": "p2",
                    "confidence": 0.8,
                    "evidence": {
                        "calibrated_prob": 0.75,
                        "raw_predicted_prob": 0.91,
                        "calibration_label": "calibrated_temporal_holdout",
                    },
                }
            ],
        )
    except Exception as exc:
        return {
            "issue": "R&D Radar Promotion Contract",
            "status": "fail",
            "error": str(exc),
            "policy": "Radar must be produced from complete Step13 Claim Cards; raw GNN edges stay in candidate pool.",
        }

    claim_cards = [
        c for c in (radar.get("claim_cards") or [])
        if isinstance(c, dict)
    ]
    candidate_pool = [
        c for c in (radar.get("candidate_pool") or [])
        if isinstance(c, dict)
    ]
    incomplete_cards = [
        c for c in (radar.get("incomplete_claim_cards") or [])
        if isinstance(c, dict)
    ]
    candidate_edges = [c for c in candidate_pool if c.get("kind") == "candidate_edge"]
    candidate_pool_incomplete = [c for c in candidate_pool if c.get("kind") == "incomplete_claim_card"]
    checks = {
        "complete_cards_only_in_main_radar": bool(claim_cards) and all(
            (c.get("claim_card") or {}).get("five_question_complete") is True
            and c.get("kind") == "claim_card"
            for c in claim_cards
        ),
        "incomplete_cards_are_candidate_pool_only": bool(incomplete_cards)
        and bool(candidate_pool_incomplete)
        and all(c.get("kind") != "incomplete_claim_card" for c in claim_cards),
        "raw_gnn_edges_are_candidate_pool_only": bool(candidate_edges)
        and all(c.get("kind") != "candidate_edge" for c in claim_cards)
        and all(edge.get("claim_scope") == "exploratory_candidate_pool" for edge in candidate_edges),
        "claim_cards_carry_evidence_contract": bool(claim_cards)
        and all(
            c.get("claim_scope")
            and c.get("evidence_grade")
            and isinstance(c.get("uncertainty_reasons"), list)
            and c.get("required_evidence")
            and c.get("evidence_objects")
            for c in claim_cards
        ),
        "claim_card_public_scores_are_candidate_scores": bool(claim_cards)
        and all(c.get("candidate_score") is not None and "technical_score" not in c for c in claim_cards),
        "candidate_edges_carry_evidence_contract": bool(candidate_edges)
        and all(edge.get("evidence_grade") and edge.get("uncertainty_reasons") for edge in candidate_edges),
        "candidate_pool_items_not_eligible": all(not bool(c.get("eligible")) for c in candidate_pool),
        "empty_radar_policy_present": "only promotes complete Step13 Claim Cards" in str(radar.get("summary") or ""),
    }
    source_checks = {
        "api_exposes_candidate_pool": False,
        "ui_separates_radar_from_candidate_pool": False,
        "step9_future_report_has_evidence_contract": False,
        "ui_radar_main_avoids_raw_edge_cards": False,
        "ui_renders_radar_claim_card_evidence_contract": False,
        "topic_lens_public_future_growth_uses_candidate_edges": False,
        "radar_public_scores_avoid_probability_copy": False,
    }
    if repo_root is not None:
        app_path = repo_root / "web/visual-graph/app.js"
        app_text = app_path.read_text(encoding="utf-8") if app_path.exists() else ""
        source_checks = {
            "api_exposes_candidate_pool": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                ("claim_cards", "incomplete_claim_cards", "candidate_pool", "GNN/VGAE candidate edges"),
            ),
            "ui_separates_radar_from_candidate_pool": _source_contains(
                repo_root / "web/visual-graph/app.js",
                ("renderDossierRadar", "No complete Claim Cards yet", "Future candidate generator pool"),
            ),
            "step9_future_report_has_evidence_contract": _source_contains(
                repo_root / "echelon/v14b/step9_report.py",
                ("claim_scope", "evidence_grade", "uncertainty_reasons", "candidate_pool_only"),
            ),
            "ui_radar_main_avoids_raw_edge_cards": bool(app_text)
            and "function renderRadar" in app_text
            and "els.radarPane.innerHTML = renderDossierRadar" in app_text
            and "renderFutureEdgeRadar" not in app_text
            and "type === \"edge\"" not in app_text,
            "ui_renders_radar_claim_card_evidence_contract": bool(app_text)
            and "function renderDossierRadar" in app_text
            and "item.evidence_grade" in app_text
            and "item.uncertainty_reasons" in app_text
            and "item.required_evidence" in app_text
            and "renderEvidenceObjects(item.evidence_objects" in app_text
            and "Claim Card uncertainty" in app_text,
            "topic_lens_public_future_growth_uses_candidate_edges": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                ('"future_growth":', '"candidate_edges": future_growth', '"future_directions": future_directions'),
            )
            and _source_absent(
                repo_root / "echelon/api/graph_visual_backend.py",
                ('"predicted_edges": future_growth',),
            )
            and bool(app_text)
            and "future_growth?.candidate_edges" in app_text
            and "future_growth?.predicted_edges" not in app_text,
            "radar_public_scores_avoid_probability_copy": (
                _source_contains(
                    repo_root / "echelon/api/graph_visual_backend.py",
                    (
                        '"candidate_score": candidate_score',
                        '"score_semantics": "candidate ranking score; not validation confidence or a conclusion probability"',
                        '"candidate_score": conf',
                    ),
                )
                and bool(app_text)
                and "候选分数" in app_text
                and "item.candidate_score" in app_text
                and "technical_probability" not in app_text
                and "技术评分" not in app_text
                and "item.technical_score" not in app_text
                and _source_absent(
                    repo_root / "echelon/api/graph_visual_backend.py",
                    ('"technical_score": d.get("confidence")', "technical_probability"),
                )
            ),
        }
    checks.update(source_checks)
    return {
        "issue": "R&D Radar Promotion Contract",
        "status": _gate_status(all(checks.values())),
        "checks": checks,
        "main_radar_cards": len(claim_cards),
        "candidate_pool_items": len(candidate_pool),
        "incomplete_claim_cards": len(incomplete_cards),
        "candidate_edges": len(candidate_edges),
        "policy": (
            "R&D Radar main view may contain only complete Step13 Claim Cards. "
            "Incomplete cards and GNN/VGAE future edges remain visible only as candidate_pool evidence-gathering targets."
        ),
    }


def audit_main_path_uncertainty_contract(repo_root: Path | None = None) -> dict[str, Any]:
    """Verify low linked-ref coverage demotes main-path/citation claims visibly."""
    try:
        from echelon.api.graph_visual_backend import (
            _apply_history_main_path_contract,
            _build_history_main_path_contract,
        )

        main_path_edges = [
            {
                "edge_id": "main:p1:p2",
                "source_paper_id": "p1",
                "target_paper_id": "p2",
                "weight": 0.8,
                "plain_language": "sample main-path edge",
            }
        ]
        contract = _build_history_main_path_contract(
            main_path_edges=main_path_edges,
            key_turning_papers=[
                {
                    "paper_id": "p1",
                    "claim_scope": "topic_specific_turning_candidate",
                    "evidence_grade": "metadata_turning_candidate",
                    "uncertainty_reasons": ["linked refs below target"],
                }
            ],
            broader_context_papers=[{"paper_id": "p3"}],
            value_model={
                "frontfill_status": {
                    "linked_ref_rate": 0.12,
                    "primary_section_rate": 0.02,
                    "openalex_w_rate": 0.55,
                }
            },
        )
        _apply_history_main_path_contract(main_path_edges, contract)
    except Exception as exc:
        return {
            "issue": "Main Path Uncertainty Contract",
            "status": "fail",
            "error": str(exc),
            "policy": "When linked refs are below 30%, main-path/citation evolution must be visibly demoted.",
        }

    low_ref_reason = any("linked refs below 30%" in str(r) for r in contract.get("uncertainty_reasons") or [])
    checks = {
        "history_main_path_has_claim_scope": bool(contract.get("claim_scope")),
        "history_main_path_has_evidence_grade": bool(contract.get("evidence_grade")),
        "low_linked_refs_add_uncertainty": low_ref_reason,
        "history_main_path_has_required_evidence": bool(contract.get("required_evidence")),
        "history_main_path_has_evidence_objects": bool(contract.get("evidence_objects")),
        "main_path_edges_inherit_uncertainty": all(
            edge.get("claim_scope")
            and edge.get("evidence_grade")
            and any("linked refs below 30%" in str(r) for r in edge.get("uncertainty_reasons") or [])
            for edge in main_path_edges
        ),
    }
    source_checks = {
        "api_returns_history_contract": False,
        "ui_renders_main_path_uncertainty": False,
        "api_visual_story_steps_carry_contract": False,
        "ui_story_mode_renders_contract": False,
        "api_visual_paper_role_carry_contract": False,
        "ui_paper_detail_renders_role_contract": False,
        "api_visual_nodes_carry_role_contract": False,
        "ui_node_hover_renders_role_contract": False,
    }
    if repo_root is not None:
        source_checks = {
            "api_returns_history_contract": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                ("_build_history_main_path_contract", "history_main_path_contract", '"history_main_path": {'),
            ),
            "ui_renders_main_path_uncertainty": _source_contains(
                repo_root / "web/visual-graph/app.js",
                ("Main-path uncertainty", "history.claim_scope", "history.evidence_grade"),
            ),
            "api_visual_story_steps_carry_contract": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _story_step_contract",
                    "get_visual_story_steps",
                    "timeline_context_only",
                    "future_candidate_story_context",
                    "evidence_objects",
                ),
            ),
            "ui_story_mode_renders_contract": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "renderStory",
                    "step.claim_scope",
                    "step.evidence_grade",
                    "step.uncertainty_reasons",
                    "renderEvidenceObjects(step.evidence_objects",
                ),
            ),
            "api_visual_paper_role_carry_contract": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _paper_role_contract",
                    "get_visual_paper_detail",
                    "paper_role",
                    "claim_scope",
                    "evidence_grade",
                    "uncertainty_reasons",
                    "evidence_objects",
                ),
            ),
            "ui_paper_detail_renders_role_contract": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "renderPaper",
                    "paperRole.claim_scope",
                    "paperRole.evidence_grade",
                    "paperRole.uncertainty_reasons",
                    "renderEvidenceObjects(paperRole.evidence_objects",
                ),
            ),
            "api_visual_nodes_carry_role_contract": _source_contains(
                repo_root / "echelon/api/graph_visual_backend.py",
                (
                    "def _visual_node_role_contract",
                    "get_visual_nodes",
                    "visual_node_role",
                    "claim_scope",
                    "evidence_grade",
                    "uncertainty_reasons",
                ),
            ),
            "ui_node_hover_renders_role_contract": _source_contains(
                repo_root / "web/visual-graph/app.js",
                (
                    "els.hover.innerHTML",
                    "node.claim_scope",
                    "node.evidence_grade",
                    "node.uncertainty_reasons",
                ),
            ),
        }
    checks.update(source_checks)
    return {
        "issue": "Main Path Uncertainty Contract",
        "status": _gate_status(all(checks.values())),
        "checks": checks,
        "claim_scope": contract.get("claim_scope"),
        "evidence_grade": contract.get("evidence_grade"),
        "uncertainty_reasons": contract.get("uncertainty_reasons"),
        "policy": "When linked refs are below 30%, citation evolution, main-path claims, Story Mode timeline narratives, selected-paper roles, and visual node hover roles must carry claim_scope, evidence_grade, and uncertainty_reasons.",
    }


def audit_legacy_flow_isolation_contract(repo_root: Path | None = None) -> dict[str, Any]:
    """Verify old enrich/pilot flows are compatibility targets, not acceptance paths."""
    makefile_path = (repo_root or Path(".")) / "Makefile"
    makefile = makefile_path.read_text(encoding="utf-8") if makefile_path.exists() else ""
    if not makefile:
        return {
            "issue": "Legacy Flow Isolation Contract",
            "status": "fail",
            "why": "Makefile is missing or empty",
            "policy": "Current V14B acceptance must run product-chain or post-frontfill-chain; legacy enrich/pilot paths must be labeled compatibility only.",
        }

    current_targets = ("product-chain", "product-chain-fast")
    target_deps = {target: set(_make_target_deps(makefile, target)) for target in current_targets}
    disallowed_current_deps = {
        target: sorted(deps & LEGACY_FLOW_DISALLOWED_CURRENT_DEPS)
        for target, deps in target_deps.items()
        if deps & LEGACY_FLOW_DISALLOWED_CURRENT_DEPS
    }
    legacy_contexts = {
        target: _make_target_context(makefile, target)
        for target in LEGACY_FLOW_TARGETS
    }
    legacy_contexts = {target: context for target, context in legacy_contexts.items() if context}
    unlabeled_legacy_targets = [
        target
        for target, context in legacy_contexts.items()
        if "LEGACY compatibility" not in context or "not current V14B decision workflow" not in context
    ]
    legacy_script_contexts: dict[str, str] = {}
    for rel_path in LEGACY_ARXIV_FLOW_SCRIPTS:
        path = (repo_root or Path(".")) / rel_path
        if path.exists():
            legacy_script_contexts[rel_path] = path.read_text(encoding="utf-8")
    unguarded_legacy_scripts = [
        rel_path
        for rel_path, text in legacy_script_contexts.items()
        if "LEGACY compatibility" not in text
        or "not the current V14B decision workflow" not in text
        or "V14B_RUN_LEGACY_ARXIV_FLOW" not in text
    ]
    step9_path = (repo_root or Path(".")) / "echelon/v14b/step9_report.py"
    step9_text = step9_path.read_text(encoding="utf-8") if step9_path.exists() else ""
    v14_config_path = (repo_root or Path(".")) / "echelon/v14b/config.py"
    v14_init_path = (repo_root or Path(".")) / "echelon/v14b/__init__.py"
    step4_path = (repo_root or Path(".")) / "echelon/v14b/step4_subgraph.py"
    step0_id_repair_path = (repo_root or Path(".")) / "echelon/v14b/step0_id_repair.py"
    step1_enrich_path = (repo_root or Path(".")) / "echelon/v14b/step1_enrich.py"
    step12_path = (repo_root or Path(".")) / "echelon/v14b/step12_goal_alignment_audit.py"
    db_schema_path = (repo_root or Path(".")) / "echelon/v14b/db_schema.py"
    step4_text = step4_path.read_text(encoding="utf-8") if step4_path.exists() else ""
    step0_id_repair_text = step0_id_repair_path.read_text(encoding="utf-8") if step0_id_repair_path.exists() else ""
    step1_enrich_text = step1_enrich_path.read_text(encoding="utf-8") if step1_enrich_path.exists() else ""
    step12_text = step12_path.read_text(encoding="utf-8") if step12_path.exists() else ""
    db_schema_text = db_schema_path.read_text(encoding="utf-8") if db_schema_path.exists() else ""
    step9_avoids_old_pilot_instruction = (
        bool(step9_text)
        and "make pilot 全流程" not in step9_text
        and "make product-chain" in step9_text
        and "make post-frontfill-chain" in step9_text
        and "legacy compatibility" in step9_text
    )
    step9_openalex_language_is_coverage = (
        bool(step9_text)
        and "OpenAlex W 覆盖率" in step9_text
        and "Field/Topic 覆盖率" in step9_text
        and "coverage is not a success claim" in step9_text
        and "OpenAlex enrich 成功率" not in step9_text
        and "OpenAlex 命中率" not in step9_text
        and "OpenAlex 跨库" not in step9_text
    )
    step9_decision_readiness_not_frontend_launch = (
        bool(step9_text)
        and "证据决策放行条件" in step9_text
        and "Topic Dossier multi-topic regression" in step9_text
        and "Radar 主视图只允许完整 Step13 Claim Card" in step9_text
        and "candidate_pool_only" in step9_text
        and "前端启动条件" not in step9_text
        and "启动前端" not in step9_text
        and "可启动 V14-B 前端开发" not in step9_text
        and "VGAE test AUC" not in step9_text
        and "主干道节点 100-200" not in step9_text
        and "突变节点 100-300" not in step9_text
        and "重型算法调优建议" not in step9_text
        and "_go_nogo_recommendation" not in step9_text
    )
    step9_algo_report_filename_is_evidence_decision = (
        _source_contains(v14_config_path, ("REPORT_ALGO_VALIDATION", "V14B_Evidence_Decision_算法验证报告.md"))
        and "V14B_Evidence_Decision_算法验证报告.md" in step9_text
        and "V14B_Evidence_Decision_算法验证报告.md" in makefile
        and "V14B_Pilot_算法验证报告.md" not in step9_text
        and "V14B_Pilot_算法验证报告.md" not in makefile
    )
    package_docstring_avoids_legacy_pilot_flow = (
        _source_contains(
            v14_init_path,
            (
                "Evidence Decision workflow",
                "evidence-constrained research decision pipeline",
                "legacy pilot graph flow",
                "compatibility-only",
            ),
        )
        and _source_absent(
            v14_init_path,
            (
                "Pilot 模块",
                "9-step",
                "Step 1: OpenAlex enrich",
            ),
        )
    )
    step4_and_step9_use_bounded_subgraph_scope = (
        bool(step4_text)
        and bool(step9_text)
        and "bounded_evidence_subgraph" in step4_text
        and "bounded_evidence_subgraph" in step9_text
        and "_normalise_subgraph_scope_row" in step9_text
        and "bounded evidence / extraction support" in step9_text
        and "pilot_evidence_subgraph" not in step4_text
        and "pilot_adequate_for_algorithmic_evidence" not in step4_text
        and "标为 pilot/evidence" not in step9_text
        and "pilot/evidence，完整" not in step9_text
        and "与 V12.5 Pilot 对比" not in step9_text
    )
    step12_and_schema_use_bounded_subgraph_scope = (
        bool(step12_text)
        and bool(db_schema_text)
        and "bounded evidence subgraph for extraction support" in step12_text
        and "bounded evidence subgraph" in step12_text
        and "bounded evidence subgraph" in db_schema_text
        and "pilot/evidence" not in db_schema_text
        and "pilot/evidence subgraph" not in step12_text
        and "as pilot/evidence" not in step12_text
        and "explicitly labeling the 5,000-node subgraph as pilot/evidence" not in step12_text
    )
    first_current = min(
        (idx for idx in (makefile.find("make product-chain"), makefile.find("make post-frontfill-chain")) if idx >= 0),
        default=-1,
    )
    first_legacy = min(
        (idx for idx in (makefile.find("make pilot"), makefile.find("make pilot-full")) if idx >= 0),
        default=-1,
    )
    current_chain_advertised = "make product-chain" in makefile and "make post-frontfill-chain" in makefile
    help_prefers_current = (
        current_chain_advertised
        and "Legacy compatibility (not current acceptance path)" in makefile
        and first_current >= 0
        and (first_legacy < 0 or first_current < first_legacy)
    )
    pilot_full_context = legacy_contexts.get("pilot-full", "")
    product_chain_context = _make_target_context(makefile, "product-chain", before=0, after=14)
    decision_audit_context = _make_target_context(makefile, "decision-audit", before=0, after=12)
    topic_gap_repair_context = _make_target_context(makefile, "topic-gap-repair", before=0, after=14)
    decision_audit_targets = (
        "topic-regression",
        "section-queue-audit",
        "topic-gap-section-audit",
        "topic-gap-no-target-inspect",
        "cited-work-backfill-queue",
        "raw-pdf-store-audit",
        "topic-gap-raw-pdf-inspect",
        "direction-readiness-audit",
        "algorithm-logic-audit",
        "value-delivery-audit",
    )
    topic_gap_repair_targets = (
        "topic-regression",
        "section-queue-audit",
        "topic-gap-section-audit",
        "section-evidence-topic-gaps",
        "topic-regression",
        "section-queue-audit",
        "topic-gap-section-audit",
        "direction-readiness-audit",
        "value-delivery-audit",
    )
    checks = {
        "current_product_chain_present": bool(re.search(r"^product-chain\s*:", makefile, flags=re.M)),
        "post_frontfill_entry_present": bool(re.search(r"^post-frontfill-chain\s*:", makefile, flags=re.M)),
        "decision_audit_target_present": bool(re.search(r"^decision-audit\s*:", makefile, flags=re.M)),
        "topic_gap_repair_target_present": bool(re.search(r"^topic-gap-repair\s*:", makefile, flags=re.M)),
        "product_chain_runs_decision_audit": "decision-audit" in product_chain_context,
        "decision_audit_runs_regression_gap_readiness_value": _context_contains_ordered_targets(
            decision_audit_context,
            decision_audit_targets,
        ),
        "topic_gap_repair_refreshes_queue_ingests_and_reaudits": _context_contains_ordered_targets(
            topic_gap_repair_context,
            topic_gap_repair_targets,
        ),
        "topic_gap_repair_refuses_concurrent_section_ingest": (
            "scripts/guard_topic_gap_repair.py" in topic_gap_repair_context
            and _source_contains(
                (repo_root or Path(".")) / "scripts/guard_topic_gap_repair.py",
                (
                    "active broad section ingest detected",
                    "V14B_ALLOW_CONCURRENT_TOPIC_GAP_REPAIR",
                    "watch_step5s_section_ingest.py",
                    "run_after_frontfill_product_chain.py",
                ),
            )
        ),
        "post_frontfill_uses_topic_gap_repair": _source_contains(
            (repo_root or Path(".")) / "scripts/run_after_frontfill_product_chain.py",
            ("V14B_TOPIC_GAP_FRONTFILL_CMD", "make topic-gap-repair"),
        ),
        "post_frontfill_requires_decision_grade_section_gates": _source_contains(
            (repo_root or Path(".")) / "scripts/run_after_frontfill_product_chain.py",
            (
                "decision_grade_primary_section_papers",
                "topic_gap_decision_grade_section_rate",
                "SECTION_PARSER_CONTRACT_VERSION",
            ),
        ),
        "product_chains_avoid_legacy_targets": not disallowed_current_deps,
        "legacy_targets_labeled": not unlabeled_legacy_targets,
        "legacy_arxiv_scripts_require_explicit_opt_in": not unguarded_legacy_scripts,
        "step9_report_avoids_old_pilot_instruction": step9_avoids_old_pilot_instruction,
        "step9_openalex_language_is_coverage_not_success": step9_openalex_language_is_coverage,
        "step9_uses_decision_readiness_not_frontend_launch": step9_decision_readiness_not_frontend_launch,
        "step9_algo_report_filename_is_evidence_decision": step9_algo_report_filename_is_evidence_decision,
        "package_docstring_avoids_legacy_pilot_flow": package_docstring_avoids_legacy_pilot_flow,
        "step4_and_step9_use_bounded_subgraph_scope": step4_and_step9_use_bounded_subgraph_scope,
        "step12_and_schema_use_bounded_subgraph_scope": step12_and_schema_use_bounded_subgraph_scope,
        "id_repair_uses_unambiguous_exact_reference_relinking": (
            bool(step0_id_repair_text)
            and "apply_exact_relinks" in step0_id_repair_text
            and "exact_reference_status_counts" in step0_id_repair_text
            and "link_paper_reference_internals" not in step0_id_repair_text
        ),
        "legacy_enrich_relinker_delegates_to_exact_relinking": (
            bool(step1_enrich_text)
            and "def link_paper_reference_internals" in step1_enrich_text
            and "apply_exact_relinks" in step1_enrich_text
            and "link_updates_applied" in step1_enrich_text
        ),
        "help_prefers_current_chain": help_prefers_current,
        "pilot_full_is_legacy_compatibility_only": (
            not pilot_full_context
            or (
                "LEGACY compatibility" in pilot_full_context
                and "not current V14B decision workflow" in pilot_full_context
            )
        ),
    }
    return {
        "issue": "Legacy Flow Isolation Contract",
        "status": _gate_status(all(checks.values())),
        "checks": checks,
        "current_target_deps": {target: sorted(deps) for target, deps in target_deps.items()},
        "decision_audit_required_targets": list(decision_audit_targets),
        "topic_gap_repair_required_targets": list(topic_gap_repair_targets),
        "disallowed_current_deps": disallowed_current_deps,
        "legacy_targets_present": sorted(legacy_contexts),
        "unlabeled_legacy_targets": unlabeled_legacy_targets,
        "legacy_arxiv_scripts_present": sorted(legacy_script_contexts),
        "unguarded_legacy_arxiv_scripts": unguarded_legacy_scripts,
        "policy": (
            "Current V14B acceptance must run product-chain or post-frontfill-chain, and product-chain must "
            "finish with the decision-audit loop: multi-topic regression, topic gap queue refresh, topic-gap "
            "section triage, no-target PDF inspection, raw PDF store reuse audit, local raw-PDF parser dry run, direction readiness, "
            "algorithm-logic audit, and value delivery. Benchmark-topic evidence gaps must have a targeted repair loop that refreshes regression "
            "gaps, refreshes the section queue, classifies section blockers, ingests topic-gap papers, and re-audits. "
            "Post-frontfill downstream promotion must require decision-grade current-contract section coverage, "
            "not raw primary-section presence. "
            "Old enrich/pilot/arXiv-gap-era flows may remain only as explicitly labeled legacy compatibility targets."
        ),
    }


def audit_multi_topic_regression(
    report_dir: Path,
    metrics: dict[str, Any] | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    metrics = metrics or {}
    expected = {
        "metalens",
        "metasurface holography",
        "photonic crystal cavity",
        "quantum light source",
    }
    defined = set(BENCHMARK_TOPICS)
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
    benchmark_fixture_contract_ok = bool(live_results) and all(
        (r.get("benchmark_fixture_contract") or {}).get("role")
        == "regression_fixture_not_product_allowlist"
        and (r.get("benchmark_fixture_contract") or {}).get("llm_policy")
        == "no_llm_required_for_topic_preflight"
        for r in live_results
    )
    no_gold_topic_fields = bool(live_results) and all(
        "gold_branch_coverage" not in r for r in live_results
    )
    topic_regression_avoids_gold_topic_aliases = True
    topic_regression_cli_defaults_to_suite = True
    product_baseline_defaults_to_suite = True
    makefile_product_baseline_defaults_to_suite = True
    section_queue_defaults_to_multi_topic = True
    section_queue_tracks_decision_grade_gap_coverage = True
    current_plan_docs_avoid_gold_topic_language = True
    if repo_root is not None:
        topic_regression_source = repo_root / "echelon/v14b/topic_regression.py"
        product_baseline_source = repo_root / "echelon/v14b/product_baseline.py"
        section_queue_source = repo_root / "echelon/v14b/step5s_section_queue_audit.py"
        makefile_source = repo_root / "Makefile"
        topic_regression_avoids_gold_topic_aliases = _source_absent(
            topic_regression_source,
            (
                "GoldTopic",
                "GOLD_TOPICS",
                "METALENS_GOLD",
                "METASURFACE_HOLOGRAPHY_GOLD",
                "PHOTONIC_CRYSTAL_CAVITY_GOLD",
                "QUANTUM_LIGHT_SOURCE_GOLD",
            ),
        )
        topic_regression_cli_defaults_to_suite = _source_contains(
            topic_regression_source,
            ('default="all"', "BENCHMARK_TOPICS"),
        )
        product_baseline_defaults_to_suite = (
            _source_contains(
                product_baseline_source,
                ("PRODUCT_BASELINE_TOPICS", "topic_lens_quality_suite", 'default="all"'),
            )
            and _source_absent(
                product_baseline_source,
                (
                    "Metalens topic quality",
                    'parser.add_argument("--topic", default="metalens")',
                    'default="metalens"',
                ),
            )
        )
        makefile_product_baseline_defaults_to_suite = _source_contains(
            makefile_source,
            ("product-baseline:", "V14B_BASELINE_TOPIC:-all"),
        )
        section_queue_defaults_to_multi_topic = (
            _source_contains(
                section_queue_source,
                (
                    "DEFAULT_SECTION_AUDIT_TOPICS",
                    "PRODUCT_BASELINE_TOPICS",
                    "topic_terms = topic_terms or list(DEFAULT_SECTION_AUDIT_TOPICS)",
                ),
            )
            and _source_absent(makefile_source, ("V14B_SECTION_AUDIT_TOPIC:-metalens",))
        )
        section_queue_tracks_decision_grade_gap_coverage = _source_contains(
            section_queue_source,
            (
                "has_decision_grade_primary_section",
                "decision_grade_primary_section_rate",
                'not r["has_decision_grade_primary_section"]',
            ),
        )
        stale_gold_topic_doc_phrases = (
            "topic gold fixtures",
            "Create gold expectations",
            "Multi-topic Gold Regression",
            "gold fixtures for",
            "gold regression fixtures",
        )
        current_plan_docs = (
            repo_root / "reports/v14b_pilot/100h_value_delivery_plan.md",
            repo_root / "reports/v14b_pilot/end_to_end_audit_goals_20260530.md",
        )
        current_plan_docs_avoid_gold_topic_language = all(
            _source_absent(path, stale_gold_topic_doc_phrases)
            for path in current_plan_docs
            if path.exists()
        )
    contract_fail = bool(live_results) and not (
        benchmark_fixture_contract_ok and no_gold_topic_fields
        and topic_regression_avoids_gold_topic_aliases
        and topic_regression_cli_defaults_to_suite
        and product_baseline_defaults_to_suite
        and makefile_product_baseline_defaults_to_suite
        and section_queue_defaults_to_multi_topic
        and section_queue_tracks_decision_grade_gap_coverage
        and current_plan_docs_avoid_gold_topic_language
    )
    topic_gap_queue_papers = int(metrics.get("topic_gap_queue_papers") or 0)
    topic_gap_primary_rate = float(metrics.get("topic_gap_primary_section_rate") or 0.0)
    topic_gap_decision_grade_rate = float(metrics.get("topic_gap_decision_grade_section_rate") or 0.0)
    topic_gap_blocking = topic_gap_queue_papers > 0 and topic_gap_decision_grade_rate < 0.70
    topic_gap_triage = metrics.get("topic_gap_section_triage_state") or {}
    topic_gap_triage_available = bool(topic_gap_triage.get("available"))
    topic_gap_triage_failure_modes = topic_gap_triage.get("failure_mode_counts") or {}
    topic_gap_no_target = metrics.get("topic_gap_no_target_inspection_state") or {}
    no_target_blocking = int(topic_gap_triage_failure_modes.get("no_target_sections_after_current_parser") or 0) > 0
    no_target_inspection_available = bool(topic_gap_no_target.get("available"))
    return {
        "issue": "Multi-topic Regression",
        "status": (
            "fail"
            if missing or failed_topics or topic_gap_blocking or contract_fail
            else ("pass" if live_results else "warn")
        ),
        "checks": {
            "benchmark_topics_defined": not missing,
            "live_results_have_fixture_contract": benchmark_fixture_contract_ok,
            "live_results_avoid_gold_topic_fields": no_gold_topic_fields,
            "topic_regression_avoids_gold_topic_aliases": topic_regression_avoids_gold_topic_aliases,
            "topic_regression_cli_defaults_to_suite": topic_regression_cli_defaults_to_suite,
            "product_baseline_defaults_to_suite": product_baseline_defaults_to_suite,
            "makefile_product_baseline_defaults_to_suite": makefile_product_baseline_defaults_to_suite,
            "section_queue_defaults_to_multi_topic": section_queue_defaults_to_multi_topic,
            "section_queue_tracks_decision_grade_gap_coverage": section_queue_tracks_decision_grade_gap_coverage,
            "topic_gap_section_triage_available_when_blocking": (
                not topic_gap_blocking or topic_gap_triage_available
            ),
            "topic_gap_no_target_inspection_available_when_needed": (
                not no_target_blocking or no_target_inspection_available
            ),
            "current_plan_docs_avoid_gold_topic_language": current_plan_docs_avoid_gold_topic_language,
        },
        "benchmark_topics": sorted(defined),
        "missing_topics": missing,
        "live_regression_status": live_status,
        "failed_topics": failed_topics,
        "topic_gap_queue_papers": topic_gap_queue_papers,
        "topic_gap_primary_section_papers": int(metrics.get("topic_gap_primary_section_papers") or 0),
        "topic_gap_primary_section_rate": topic_gap_primary_rate,
        "topic_gap_decision_grade_section_papers": int(metrics.get("topic_gap_decision_grade_section_papers") or 0),
        "topic_gap_decision_grade_section_rate": topic_gap_decision_grade_rate,
        "topic_gap_blocking": topic_gap_blocking,
        "topic_gap_section_triage_available": topic_gap_triage_available,
        "topic_gap_section_triage_status": topic_gap_triage.get("status") or "",
        "topic_gap_section_triage_failure_modes": topic_gap_triage_failure_modes,
        "topic_gap_no_target_inspection_available": no_target_inspection_available,
        "topic_gap_no_target_inspection_status": topic_gap_no_target.get("status") or "",
        "topic_gap_no_target_inspection_classifications": topic_gap_no_target.get("classification_counts") or {},
        "topic_gap_no_target_parser_signal_papers": int(
            topic_gap_no_target.get("parser_target_signal_papers") or 0
        ),
        "policy": (
            "Topic value must be tested across multiple optics themes, not tuned only for Metalens. "
            "Benchmark topics are regression fixtures, not product allowlists or LLM cost-control gates; "
            "the active regression and product-baseline entrypoints must default to the full benchmark suite, "
            "and topic-gap repair is blocked until queued papers have decision-grade current-contract section evidence. "
            "When blocked, a topic-gap section triage report must identify whether the next repair is current-contract "
            "reparse, parser/full-text inspection, access recovery, or targeted ingest. Current-parser no-target "
            "papers require a no-target PDF inspection before parser thresholds can be loosened."
        ),
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
    if report_dir is None:
        report_dir = repo_root / "reports/v14b_pilot"
    metrics = collect_metrics(
        db_main,
        db_v14,
        topic_gap_queue=default_topic_gap_queue(repo_root),
    )
    metrics["section_frontfill_state"] = select_section_frontfill_state(repo_root)
    metrics["openalex_frontfill_state"] = select_openalex_frontfill_state(repo_root)
    metrics["reference_relink_state"] = select_reference_relink_state(repo_root, report_dir)
    metrics["cited_work_backfill_queue_state"] = load_cited_work_backfill_state(
        repo_root / "data/v14b/cited_work_backfill_queue.csv"
    )
    metrics["cited_work_backfill_run_state"] = load_cited_work_backfill_run_state(
        report_dir / "cited_work_backfill_run.json"
    )
    metrics["topic_gap_section_triage_state"] = load_topic_gap_section_triage_state(
        report_dir / "topic_gap_section_evidence_audit.json"
    )
    metrics["topic_gap_no_target_inspection_state"] = load_topic_gap_no_target_inspection_state(
        report_dir / "topic_gap_no_target_inspection.json"
    )
    with sqlite3.connect(str(db_v14)) as conn_v14:
        metrics["vgae_calibration_audit"] = (
            int(scalar(conn_v14, "SELECT COUNT(*) FROM vgae_calibration_audit") or 0)
            if table_exists(conn_v14, "vgae_calibration_audit")
            else 0
        )
        gates = [
            audit_evidence_bone(metrics),
            audit_openalex_frontfill_guard(repo_root),
            audit_bottleneck_lineage(conn_v14, repo_root),
            audit_branch_lineage(conn_v14, repo_root),
            audit_future_growth(conn_v14, repo_root, report_dir),
            audit_claim_card_engine(conn_v14, repo_root),
            audit_claim_card_high_confidence_evidence_contract(conn_v14, repo_root),
            audit_llm_evidence_boundary(conn_v14, repo_root),
            audit_topic_dossier(conn_v14, repo_root),
            audit_evolution_evidence_map_contract(repo_root),
            audit_rd_radar_promotion_contract(repo_root),
            audit_main_path_uncertainty_contract(repo_root),
            audit_legacy_flow_isolation_contract(repo_root),
            audit_multi_topic_regression(report_dir, metrics, repo_root),
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
        "## Product Gates",
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
