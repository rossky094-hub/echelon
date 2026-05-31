"""First-principles algorithm logic audit for the V14B decision workflow.

This audit asks a different question from "did the pipeline run".  For each
major step it records whether the algorithm's role, input, output, and
promotion guard help the product become an evidence-constrained research
decision system.  Live evidence gaps are reported separately from algorithm-fit
problems so we do not "fix" missing data by weakening scientific semantics.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, DB_V14, REPORT_DIR
from echelon.v14b.direction_readiness_audit import (
    collect_metrics,
    default_topic_gap_queue,
    select_openalex_frontfill_state,
    select_reference_relink_state,
    select_section_frontfill_state,
    table_exists,
)
from echelon.v14b.evidence_contracts import SECTION_PARSER_CONTRACT_VERSION
from echelon.v14b.topic_gap_no_target_inspection import load_topic_gap_no_target_inspection_state
from echelon.v14b.topic_gap_section_evidence_audit import load_topic_gap_section_triage_state


@dataclass(frozen=True)
class StepAudit:
    step: str
    algorithm_role: str
    input_contract: str
    output_contract: str
    promotion_guard: str
    algorithm_fit: str
    readiness: str
    challenge: str
    next_tuning: str


def _count(conn: sqlite3.Connection, table: str, where: str = "1=1") -> int:
    if not table_exists(conn, table):
        return 0
    row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()
    return int(row[0] or 0) if row else 0


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _count_when_columns(
    conn: sqlite3.Connection,
    table: str,
    required_columns: set[str],
    where: str,
) -> int:
    if not required_columns <= _columns(conn, table):
        return 0
    return _count(conn, table, where)


def _lineage_completeness_counts(conn: sqlite3.Connection) -> dict[str, int]:
    if "metadata_json" not in _columns(conn, "bottleneck_lineage_triples"):
        return {
            "complete_typed_lineage_triples": 0,
            "partial_typed_lineage_triples": 0,
            "unknown_typed_lineage_triples": _count(conn, "bottleneck_lineage_triples"),
            "lineage_completeness_counts": {},
        }
    complete = 0
    partial = 0
    unknown = 0
    by_completeness: dict[str, int] = {}
    for row in conn.execute("SELECT metadata_json FROM bottleneck_lineage_triples").fetchall():
        raw = row[0] if not isinstance(row, sqlite3.Row) else row["metadata_json"]
        try:
            meta = json.loads(raw or "{}")
        except Exception:
            meta = {}
        completeness = str(meta.get("typed_chain_completeness") or "").strip()
        if completeness:
            by_completeness[completeness] = by_completeness.get(completeness, 0) + 1
        if meta.get("typed_chain_complete") or completeness == "full":
            complete += 1
        elif completeness:
            partial += 1
        else:
            unknown += 1
    return {
        "complete_typed_lineage_triples": complete,
        "partial_typed_lineage_triples": partial,
        "unknown_typed_lineage_triples": unknown,
        "lineage_completeness_counts": by_completeness,
    }


def _claim_card_chain_support_counts(conn: sqlite3.Connection) -> dict[str, int]:
    if "quality_gate_json" not in _columns(conn, "direction_claim_cards"):
        return {
            "claim_cards_with_section_atom_chain_support": 0,
            "complete_claim_cards_with_section_atom_chain_support": 0,
            "high_confidence_claim_cards_with_section_atom_chain_support": 0,
            "claim_cards_with_full_decision_grade_chain": 0,
        }
    out = {
        "claim_cards_with_section_atom_chain_support": 0,
        "complete_claim_cards_with_section_atom_chain_support": 0,
        "high_confidence_claim_cards_with_section_atom_chain_support": 0,
        "claim_cards_with_full_decision_grade_chain": 0,
    }
    rows = conn.execute(
        """
        SELECT five_question_complete, high_confidence_eligible, quality_gate_json
        FROM direction_claim_cards
        """
    ).fetchall()
    for row in rows:
        raw = row["quality_gate_json"] if isinstance(row, sqlite3.Row) else row[2]
        try:
            gate = json.loads(raw or "{}")
        except Exception:
            gate = {}
        support = gate.get("section_atom_chain_support") if isinstance(gate, dict) else {}
        if not isinstance(support, dict) or int(support.get("total") or 0) <= 0:
            continue
        out["claim_cards_with_section_atom_chain_support"] += 1
        complete = int(row["five_question_complete"] if isinstance(row, sqlite3.Row) else row[0] or 0)
        high_confidence = int(row["high_confidence_eligible"] if isinstance(row, sqlite3.Row) else row[1] or 0)
        if complete:
            out["complete_claim_cards_with_section_atom_chain_support"] += 1
        if high_confidence:
            out["high_confidence_claim_cards_with_section_atom_chain_support"] += 1
        if int(support.get("full_decision_grade") or 0) > 0:
            out["claim_cards_with_full_decision_grade_chain"] += 1
    return out


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _metric_snapshot(db_main: Path, db_v14: Path, report_dir: Path, repo_root: Path) -> dict[str, Any]:
    metrics = collect_metrics(db_main, db_v14, topic_gap_queue=default_topic_gap_queue(repo_root))
    metrics["section_frontfill_state"] = select_section_frontfill_state(repo_root)
    metrics["openalex_frontfill_state"] = select_openalex_frontfill_state(repo_root)
    metrics["reference_relink_state"] = select_reference_relink_state(repo_root, report_dir)
    metrics["topic_gap_section_triage_state"] = load_topic_gap_section_triage_state(
        report_dir / "topic_gap_section_evidence_audit.json"
    )
    metrics["topic_gap_no_target_inspection_state"] = load_topic_gap_no_target_inspection_state(
        report_dir / "topic_gap_no_target_inspection.json"
    )
    metrics["multi_topic_regression"] = _load_json(report_dir / "multi_topic_regression.json", [])
    value_delivery = _load_json(report_dir / "value_delivery_audit.json", {})
    evidence_map_gate: dict[str, Any] = {}
    for gate in value_delivery.get("gates", []) if isinstance(value_delivery, dict) else []:
        if isinstance(gate, dict) and gate.get("issue") == "Evolution Evidence Map Contract":
            evidence_map_gate = gate
            break
    evidence_map_checks = evidence_map_gate.get("checks") if isinstance(evidence_map_gate, dict) else {}
    metrics["evidence_map_uncertainty_overlay_count"] = int(
        evidence_map_gate.get("uncertainty_overlay_count") or 0
    )
    metrics["evidence_map_uncertainty_overlay_gates"] = list(
        evidence_map_gate.get("uncertainty_overlay_gates") or []
    )
    metrics["evidence_map_uncertainty_overlay_contract_pass"] = bool(
        isinstance(evidence_map_checks, dict)
        and evidence_map_checks.get("uncertainty_overlays_contract_present")
        and evidence_map_checks.get("required_uncertainty_overlay_gates_present")
        and evidence_map_checks.get("api_evidence_map_uncertainty_overlays")
        and evidence_map_checks.get("ui_renders_uncertainty_overlays")
    )
    with sqlite3.connect(str(db_main)) as main:
        metrics["embeddings"] = _count(main, "paper_embeddings")
        metrics["section_atoms"] = _count(main, "section_atoms")
        metrics["section_atom_decision_grade"] = _count_when_columns(
            main,
            "section_atoms",
            {"evidence_grade"},
            "evidence_grade = 'section_atom_decision_grade'",
        )
        metrics["section_atoms_fts"] = 1 if table_exists(main, "section_atoms_fts") else 0
        metrics["section_atom_embeddings"] = _count(main, "section_atom_embeddings")
        metrics["section_atom_embeddings_retrieval_only"] = _count_when_columns(
            main,
            "section_atom_embeddings",
            {"claim_scope", "search_semantics"},
            "claim_scope = 'retrieval_context_only' AND search_semantics LIKE '%candidate recall only%'",
        )
        metrics["section_atom_chains"] = _count(main, "section_atom_chains")
        metrics["section_atom_chain_full"] = _count_when_columns(
            main,
            "section_atom_chains",
            {"typed_chain_complete"},
            "typed_chain_complete = 1",
        )
        metrics["section_atom_chain_decision_grade"] = _count_when_columns(
            main,
            "section_atom_chains",
            {"evidence_grade"},
            "evidence_grade IN ('typed_section_lineage', 'typed_section_lineage_traced')",
        )
    with sqlite3.connect(str(db_v14)) as v14:
        metrics["main_path_edges"] = _count(v14, "main_path_edges")
        metrics["main_path_core_edges"] = _count(v14, "main_path_edges", "is_main_path=1")
        metrics["subgraph_nodes"] = _count(v14, "subgraph_nodes")
        metrics["subgraph_edges"] = _count(v14, "subgraph_edges")
        metrics["citation_function_edges"] = _count(v14, "subgraph_edges", "citation_function IS NOT NULL")
        metrics["limitation_atoms"] = _count(v14, "limitation_atoms")
        metrics["limitation_exact_section_atoms"] = _count_when_columns(
            v14,
            "limitation_atoms",
            {"source_section_name"},
            "COALESCE(source_section_name, '') != '' AND source_section_name NOT LIKE '%,%'",
        )
        metrics["limitation_aggregate_section_atoms"] = _count_when_columns(
            v14,
            "limitation_atoms",
            {"source_section_name"},
            "COALESCE(source_section_name, '') LIKE '%,%'",
        )
        metrics["limitation_section_atom_bridge_atoms"] = _count_when_columns(
            v14,
            "limitation_atoms",
            {"source_section_atom_id"},
            "COALESCE(source_section_atom_id, '') != ''",
        )
        metrics["limitation_current_contract_atoms"] = _count_when_columns(
            v14,
            "limitation_atoms",
            {"source_parser_contract_version"},
            f"source_parser_contract_version = '{SECTION_PARSER_CONTRACT_VERSION}'",
        )
        metrics["limitation_typed_chain_atoms"] = _count_when_columns(
            v14,
            "limitation_atoms",
            {"source_section_atom_chain_id"},
            "COALESCE(source_section_atom_chain_id, '') != ''",
        )
        metrics["limitation_current_contract_typed_chain_atoms"] = _count_when_columns(
            v14,
            "limitation_atoms",
            {
                "source_section_atom_chain_id",
                "source_parser_contract_version",
            },
            "COALESCE(source_section_atom_chain_id, '') != '' "
            f"AND source_parser_contract_version = '{SECTION_PARSER_CONTRACT_VERSION}'",
        )
        metrics["limitation_abstract_atoms"] = _count_when_columns(
            v14,
            "limitation_atoms",
            {"evidence_quality"},
            "COALESCE(evidence_quality, '') = 'weak_abstract'",
        )
        metrics["bottleneck_triples"] = _count(v14, "bottleneck_lineage_triples")
        metrics.update(_lineage_completeness_counts(v14))
        metrics.update(_claim_card_chain_support_counts(v14))
        metrics["vgae_calibration_audit"] = _count(v14, "vgae_calibration_audit")
        metrics["mutation_hypotheses"] = _count(v14, "mutation_hypotheses")
        metrics["mutation_hypotheses_with_falsification"] = _count_when_columns(
            v14,
            "mutation_hypotheses",
            {"falsification_conditions_json"},
            "COALESCE(falsification_conditions_json, '[]') NOT IN ('[]', '', 'null')",
        )
        metrics["mutation_hypotheses_with_evidence_contract"] = _count_when_columns(
            v14,
            "mutation_hypotheses",
            {"evidence_grade", "claim_scope", "uncertainty_reasons_json"},
            "COALESCE(evidence_grade, '') != '' "
            "AND COALESCE(claim_scope, '') != '' "
            "AND COALESCE(uncertainty_reasons_json, '[]') NOT IN ('', 'null')",
        )
        metrics["branch_lineages"] = _count(v14, "branch_lineages")
        metrics["visual_nodes"] = _count(v14, "visual_nodes")
        metrics["visual_edges"] = _count(v14, "visual_edges")
        metrics["corpus_registry"] = _count(main, "corpus_registry")
        metrics["corpus_snapshots"] = _count(main, "corpus_snapshots")
    return metrics


def build_algorithm_logic_audit(
    *,
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    report_dir: Path = REPORT_DIR,
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    m = _metric_snapshot(db_main, db_v14, report_dir, repo_root)
    linked_ref_rate = float(m.get("linked_ref_rate") or 0.0)
    openalex_w_rate = float(m.get("openalex_w_rate") or 0.0)
    primary_sections = int(m.get("primary_section_papers") or 0)
    section_atoms = int(m.get("section_atoms") or 0)
    section_atom_decision_grade = int(m.get("section_atom_decision_grade") or 0)
    section_atoms_fts = int(m.get("section_atoms_fts") or 0)
    section_atom_embeddings = int(m.get("section_atom_embeddings") or 0)
    section_atom_embeddings_retrieval_only = int(m.get("section_atom_embeddings_retrieval_only") or 0)
    section_atom_chains = int(m.get("section_atom_chains") or 0)
    section_atom_chain_full = int(m.get("section_atom_chain_full") or 0)
    section_atom_chain_decision_grade = int(m.get("section_atom_chain_decision_grade") or 0)
    limitation_atoms = int(m.get("limitation_atoms") or 0)
    limitation_exact_section_atoms = int(m.get("limitation_exact_section_atoms") or 0)
    limitation_aggregate_section_atoms = int(m.get("limitation_aggregate_section_atoms") or 0)
    limitation_section_atom_bridge_atoms = int(m.get("limitation_section_atom_bridge_atoms") or 0)
    limitation_current_contract_atoms = int(m.get("limitation_current_contract_atoms") or 0)
    limitation_typed_chain_atoms = int(m.get("limitation_typed_chain_atoms") or 0)
    limitation_current_contract_typed_chain_atoms = int(
        m.get("limitation_current_contract_typed_chain_atoms") or 0
    )
    limitation_abstract_atoms = int(m.get("limitation_abstract_atoms") or 0)
    limitation_chain_contract_ready = (
        limitation_atoms > 0
        and limitation_aggregate_section_atoms == 0
        and limitation_current_contract_typed_chain_atoms > 0
        and limitation_abstract_atoms == 0
    )
    complete_typed_lineage_triples = int(m.get("complete_typed_lineage_triples") or 0)
    partial_typed_lineage_triples = int(m.get("partial_typed_lineage_triples") or 0)
    lineage_completeness_counts = dict(m.get("lineage_completeness_counts") or {})
    claim_cards_with_chain_support = int(m.get("claim_cards_with_section_atom_chain_support") or 0)
    complete_claim_cards_with_chain_support = int(
        m.get("complete_claim_cards_with_section_atom_chain_support") or 0
    )
    high_confidence_claim_cards_with_chain_support = int(
        m.get("high_confidence_claim_cards_with_section_atom_chain_support") or 0
    )
    claim_cards_with_full_decision_grade_chain = int(m.get("claim_cards_with_full_decision_grade_chain") or 0)
    mutation_hypotheses = int(m.get("mutation_hypotheses") or 0)
    mutation_hypotheses_with_falsification = int(m.get("mutation_hypotheses_with_falsification") or 0)
    mutation_hypotheses_with_evidence_contract = int(m.get("mutation_hypotheses_with_evidence_contract") or 0)
    mutation_contract_ready = (
        mutation_hypotheses > 0
        and mutation_hypotheses_with_falsification == mutation_hypotheses
        and mutation_hypotheses_with_evidence_contract == mutation_hypotheses
    )
    topic_gap_dg_rate = float(m.get("topic_gap_decision_grade_section_rate") or 0.0)
    no_target = m.get("topic_gap_no_target_inspection_state") or {}
    frontfill = m.get("section_frontfill_state") or {}
    openalex_frontfill = m.get("openalex_frontfill_state") or {}
    regression = m.get("multi_topic_regression") or []
    failed_topics = [
        str(row.get("topic"))
        for row in regression
        if isinstance(row, dict) and row.get("overall_status") == "fail"
    ]
    uncertainty_overlay_count = int(m.get("evidence_map_uncertainty_overlay_count") or 0)
    uncertainty_overlay_gates = list(m.get("evidence_map_uncertainty_overlay_gates") or [])
    uncertainty_overlay_contract_pass = bool(m.get("evidence_map_uncertainty_overlay_contract_pass"))

    steps = [
        StepAudit(
            "id-repair / relinking",
            "Build an exact provider-ID citation spine; never use fuzzy links as citation truth.",
            "DOI/OpenAlex/S2/arXiv identifiers and raw paper_references.",
            "Exact linked internal references plus explicit no-local-match taxonomy.",
            "If linked refs <30%, main-path/citation-evolution claims must expose uncertainty.",
            "aligned",
            "fail" if linked_ref_rate < 0.30 else "pass",
            f"linked refs are {linked_ref_rate:.1%}; the algorithm is conservative but corpus coverage is still thin.",
            "Continue exact cited-work backfill; do not reintroduce fuzzy relinking to inflate coverage.",
        ),
        StepAudit(
            "OpenAlex / local field-topic backfill",
            "Provide field/topic context as an uncertainty-aware enrichment layer, not a product blocker.",
            "OpenAlex IDs plus local metadata fallback.",
            "Field/topic labels and coverage health.",
            "Cross-field and cross-corpus claims need uncertainty while OpenAlex W coverage is incomplete.",
            "aligned",
            "warn" if openalex_w_rate < 0.70 or openalex_frontfill.get("status") in {"stalled_after_cooldown", "stale_without_completion"} else "pass",
            f"OpenAlex W coverage is {openalex_w_rate:.1%}; frontfill status={openalex_frontfill.get('status') or 'unknown'}.",
            "Resume conservative OpenAlex repair or strengthen local field-topic fallback before cross-field claims are promoted.",
        ),
        StepAudit(
            "graph-features",
            "Compute interpretable structural signals for keystone, branch, and fusion weighting.",
            "Exact citation graph and paper metadata.",
            "Centrality, bridge, burst, and corpus-scoped feature columns.",
            "Features are signals, not conclusions; downstream must keep evidence_grade.",
            "aligned",
            "pass",
            "Feature semantics are useful only if linked citation coverage remains honest.",
            "Add feature freshness checks per corpus and expose feature-default rates in audits.",
        ),
        StepAudit(
            "embeddings",
            "Support semantic retrieval and neighborhood expansion without replacing citation evidence.",
            "Paper title/abstract/full-text summaries.",
            "Vector embeddings for semantic/co-cite/future candidate support.",
            "Semantic proximity cannot imply lineage or causality.",
            "aligned",
            "pass" if int(m.get("embeddings") or 0) >= int(m.get("papers") or 0) * 0.95 else "warn",
            f"embeddings={int(m.get('embeddings') or 0):,}; papers={int(m.get('papers') or 0):,}.",
            "Keep semantic layer labeled as retrieval/expansion; require citation/section evidence for claims.",
        ),
        StepAudit(
            "quality audit",
            "Stop poor coverage from becoming confident product output.",
            "Coverage metrics, identifiers, references, embeddings, and corpus scope.",
            "Gate labels and uncertainty reasons.",
            "Quality audit must fail loudly rather than lowering thresholds.",
            "aligned",
            "warn",
            (
                "Quality-audit gaps are exposed as user-visible Evidence Map overlays "
                f"({uncertainty_overlay_count} gates: {', '.join(uncertainty_overlay_gates) or 'none'}); "
                "live readiness still depends on citation and section gaps."
                if uncertainty_overlay_contract_pass
                else "The audit layer exists, but user-visible uncertainty overlays are not yet fully enforced."
            ),
            (
                "Keep overlays tied to Value/Direction readiness gates while continuing citation and section frontfill."
                if uncertainty_overlay_contract_pass
                else "Promote quality-audit failures into user-visible uncertainty overlays."
            ),
        ),
        StepAudit(
            "Step2 main path",
            "Extract historical trunk from citation-flow DAG, with SCC cycles audited instead of deleted.",
            "Exact linked citation graph.",
            "Main path edges plus cycle audit.",
            "Main path below 30% linked refs is historical-hypothesis, not field truth.",
            "aligned",
            "warn" if linked_ref_rate < 0.30 else "pass",
            f"main_path_core_edges={int(m.get('main_path_core_edges') or 0):,}; linked_ref_rate={linked_ref_rate:.1%}.",
            "Keep uncertainty labels on main path and continue exact citation corpus expansion.",
        ),
        StepAudit(
            "Step3 keystone",
            "Rank papers as branch/turning-point candidates using structural and temporal signals.",
            "Graph features, citations, recency, and field context.",
            "Keystone scores for prioritization and dossier reading paths.",
            "Keystone is an importance prior; branch causality needs lineage evidence.",
            "aligned",
            "pass",
            "Useful for queue prioritization, risky if interpreted as causal driver by itself.",
            "Add per-feature contribution traces to Topic Dossier driver-paper explanations.",
        ),
        StepAudit(
            "Step4 graph/subgraph evidence",
            "Create a bounded expensive-model evidence set while preserving full-graph product scope.",
            "Keystone/main/future/branch candidate paper IDs.",
            "Subgraph nodes/edges and bounded scope audit.",
            "Subgraph-only conclusions must be scoped as bounded evidence.",
            "aligned",
            "pass" if int(m.get("subgraph_nodes") or 0) else "fail",
            f"subgraph_nodes={int(m.get('subgraph_nodes') or 0):,}; subgraph_edges={int(m.get('subgraph_edges') or 0):,}.",
            "Keep Step10 full-graph/LOD path separate from Step4 bounded extraction support.",
        ),
        StepAudit(
            "Step5a citation function",
            "Label citation roles as weak/moderate evidence for fusion, not ground truth.",
            "Citation edge endpoints plus metadata/context when available.",
            "Citation-function labels, confidence, and evidence level.",
            "No-context labels must remain low weight.",
            "aligned",
            "warn" if int(m.get("citation_function_edges") or 0) else "fail",
            f"citation_function_edges={int(m.get('citation_function_edges') or 0):,}; evidence remains weak without citation sentences.",
            "Prefer deterministic weak labels now; add citation-context extraction before increasing weights.",
        ),
        StepAudit(
            "Step5b calibrated future candidate generator",
            "Generate future candidates from temporal evidence; never produce conclusions directly.",
            "Time-forward evolution edges, graph features, embeddings, and calibration split.",
            "Candidate edges with raw/calibrated scores and lifecycle state.",
            "Uncalibrated or unfused edges stay candidate pool only.",
            "aligned",
            "pass" if int(m.get("vgae_calibration_audit") or 0) else "fail",
            f"future_candidate_edges={int(m.get('future_candidate_edges') or 0):,}; calibration_audits={int(m.get('vgae_calibration_audit') or 0):,}.",
            "Continue rolling held-out-year calibration and stratified external audit; do not expose VGAE as Radar claims.",
        ),
        StepAudit(
            "Step5s section evidence",
            "Materialize section-level evidence for limitation, bottleneck, and Claim Card reasoning.",
            "OA PDFs and prioritized topic/claim/branch queues.",
            "Current-contract decision-grade primary section rows plus failure taxonomy.",
            "No section coverage for key papers means no high-confidence bottleneck/Claim Card.",
            "aligned",
            "fail" if primary_sections < 8000 or topic_gap_dg_rate < 0.70 else "pass",
            (
                f"primary_section_papers={primary_sections:,}; topic_gap_decision_grade={topic_gap_dg_rate:.1%}; "
                f"no-target parser signal={int(no_target.get('parser_target_signal_papers') or 0):,}."
            ),
            "Do not loosen parser for current no-target bucket; reparse stale-contract rows and process unattempted PDF rows when the active ingest is safe.",
        ),
        StepAudit(
            "Step5s-a section atom search",
            "Split trusted sections into span-bound retrieval atoms with exact hard-evidence search and fuzzy candidate recall; keep GNN/VGAE as ranking or expansion only.",
            "paper_sections with parser contract, extraction provenance, pages, and raw-PDF storage URI when available.",
            "section_atoms plus FTS/BM25 hard-evidence hits and atom embeddings labeled retrieval_context_only.",
            "Exact atom hits can seed evidence work; fuzzy hits are candidate recall only and cannot become scientific conclusions without typed chains and promotion gates.",
            "aligned",
            "fail"
            if not section_atoms
            else ("warn" if not section_atoms_fts or not section_atom_embeddings_retrieval_only else "pass"),
            (
                f"section_atoms={section_atoms:,}; decision_grade_atoms={section_atom_decision_grade:,}; "
                f"exact_atom_fts={'yes' if section_atoms_fts else 'no'}; "
                f"fuzzy_atom_embeddings={section_atom_embeddings:,}; "
                f"retrieval_only_embeddings={section_atom_embeddings_retrieval_only:,}; "
                "GNN/VGAE must not atomize sections."
            ),
            "Feed exact hits and fuzzy candidate recall into Step5c/Step13 through evidence contracts instead of re-parsing ad hoc text.",
        ),
        StepAudit(
            "Step5s-b section atom typed chains",
            "Assemble co-located section atoms into typed bottleneck-chain evidence candidates before Step13 claim reasoning.",
            "section_atoms with atom_type, section order, parser contract, pages, and source URI.",
            "section_atom_chains carrying typed_chain_completeness, evidence objects, claim_scope, and uncertainty reasons.",
            "Partial chains are exploratory context only; full chains still require Step13 Claim Card promotion.",
            "aligned",
            "fail" if not section_atom_chains else ("warn" if not section_atom_chain_full else "pass"),
            (
                f"section_atom_chains={section_atom_chains:,}; full_chains={section_atom_chain_full:,}; "
                f"decision_grade_chains={section_atom_chain_decision_grade:,}; these chains are evidence substrate, not conclusions."
            ),
            "Wire full/partial section_atom_chains into Step13 so bottleneck_lineage_triples stop relying on placeholder stages.",
        ),
        StepAudit(
            "Step5c limitation / resolution extraction",
            "Extract unresolved constraints and resolution attempts from trusted sections.",
            "Current-contract section atoms and typed chains first, weak abstract metadata only as scoped fallback.",
            "Typed limitations/resolutions with section atom, typed-chain, parser-contract, and weight provenance.",
            "Abstract-only bottlenecks cannot support high-confidence Claim Cards.",
            "aligned" if limitation_chain_contract_ready else "needs_tuning",
            "fail" if not limitation_atoms else ("fail" if limitation_aggregate_section_atoms else "warn"),
            (
                f"limitation_atoms={limitation_atoms:,}; exact_section_atoms={limitation_exact_section_atoms:,}; "
                f"aggregate_section_atoms={limitation_aggregate_section_atoms:,}; "
                f"section_atom_bridge_atoms={limitation_section_atom_bridge_atoms:,}; "
                f"current_contract_atoms={limitation_current_contract_atoms:,}; "
                f"typed_chain_atoms={limitation_typed_chain_atoms:,}; "
                f"current_contract_typed_chain_atoms={limitation_current_contract_typed_chain_atoms:,}; "
                f"abstract_atoms={limitation_abstract_atoms:,}; section coverage is still the limiting input."
            ),
            (
                "Re-run Step5c after section-source traceability repair; then retune toward typed chains from "
                "current-contract sections and keep abstract fallback low scope."
                if limitation_aggregate_section_atoms else
                "Run Step5c after section atom chains so limitation atoms inherit current-contract typed-chain provenance."
                if not limitation_chain_contract_ready else
                "Use Step5c limitation atoms as section-atom/typed-chain evidence; keep abstract fallback disabled for claims."
            ),
        ),
        StepAudit(
            "Step6 fusion",
            "Fuse independent evidence paths into direction candidates with explicit adequacy.",
            "Main path terminals, calibrated future candidates, limitations, field/topic context.",
            "Future directions with evidence tier, claim scope, and adequacy label.",
            "Sparse fusion should output few/zero directions instead of placeholders.",
            "aligned",
            "warn" if int(m.get("future_directions") or 0) else "fail",
            f"future_directions={int(m.get('future_directions') or 0):,}; high_confidence_claim_cards={int(m.get('high_confidence_claim_cards') or 0):,}.",
            "Raise evidence by improving inputs, not by lowering fusion thresholds.",
        ),
        StepAudit(
            "Step13 first-principles + Claim Card engine",
            "Turn candidate directions into falsifiable, evidence-scoped research claims.",
            "Fused directions, bottleneck lineage, section evidence, calibration, and history.",
            "Five-question Claim Cards with evidence objects and uncertainty reasons.",
            "Incomplete cards stay candidate pool; Radar main view requires complete cards.",
            "aligned",
            "warn" if int(m.get("complete_claim_cards") or 0) else "fail",
            (
                f"Claim Cards={int(m.get('direction_claim_cards') or 0):,}; "
                f"complete={int(m.get('complete_claim_cards') or 0):,}; "
                f"high_confidence={int(m.get('high_confidence_claim_cards') or 0):,}; "
                f"chain_supported_cards={claim_cards_with_chain_support:,}; "
                f"complete_chain_supported_cards={complete_claim_cards_with_chain_support:,}; "
                f"full_decision_grade_chain_cards={claim_cards_with_full_decision_grade_chain:,}; "
                f"complete_typed_lineage_triples={complete_typed_lineage_triples:,}; "
                f"partial_typed_lineage_triples={partial_typed_lineage_triples:,}; "
                f"lineage_completeness={lineage_completeness_counts}."
            ),
            (
                "Increase full decision-grade typed chains and Step6 fusion tier so chain-supported complete cards "
                "can progress beyond exploratory status without weakening gates."
            ),
        ),
        StepAudit(
            "Step7 mutation",
            "Explore evidence-backed variation paths without inventing scientific conclusions.",
            "Claim-card candidates and graph/section constraints.",
            "Mutation hypotheses scoped to candidate pool with inherited evidence contracts.",
            "Mutation outputs must inherit evidence grade and falsification conditions.",
            "aligned" if mutation_contract_ready else "needs_tuning",
            "warn" if mutation_contract_ready else "warn",
            (
                f"mutation_hypotheses={mutation_hypotheses:,}; "
                f"with_falsification={mutation_hypotheses_with_falsification:,}; "
                f"with_evidence_contract={mutation_hypotheses_with_evidence_contract:,}. "
                "Legacy red/orange/purple node flags remain graph-inspection signals only."
            ),
            (
                "Use mutation_hypotheses as falsifiable follow-up actions; do not promote visual flags into claims."
                if mutation_contract_ready else
                "Run Step7 after Step13 so mutation_hypotheses inherit Claim Card evidence grade, scope, and falsification."
            ),
        ),
        StepAudit(
            "Step8 layout",
            "Lay out graph evidence for inspection, not for discovering lineage by clustering alone.",
            "Visual nodes/edges with layer contracts.",
            "Coordinates and clusters with lineage_status separation.",
            "Layout cluster alone cannot imply branch lineage.",
            "aligned",
            "pass" if int(m.get("visual_nodes") or 0) else "warn",
            f"visual_nodes={int(m.get('visual_nodes') or 0):,}; branch_lineages={int(m.get('branch_lineages') or 0):,}.",
            "Keep layout_cluster_only separate from weak/evidence-backed splits in UI/API.",
        ),
        StepAudit(
            "Step9 report",
            "Report evidence boundaries and remaining risk rather than a success narrative.",
            "Audits, graph outputs, Claim Cards, and regression results.",
            "Evidence-decision report with uncertainty and next actions.",
            "Reports must not describe low-coverage paths as complete.",
            "aligned",
            "warn",
            "Current reports expose insufficiency; live product remains below high-confidence threshold.",
            "Make algorithm_logic_audit a required report section before product release.",
        ),
        StepAudit(
            "Step10 visual graph / Topic Dossier / Radar",
            "Present Topic Dossier first, graph as explain/verify layers, Radar as gated Claim Cards.",
            "Evidence layers, lineage, candidates, and Claim Cards.",
            "Dossier, Evidence Map, and Radar views with layer limits.",
            "No naked GNN edges in Radar main view.",
            "aligned",
            "warn" if failed_topics else "pass",
            f"failed regression topics={', '.join(failed_topics) or 'none'}.",
            "Prioritize multi-topic dossier failures over single-topic polish.",
        ),
        StepAudit(
            "Step12 / value delivery audit",
            "Enforce acceptance gates and keep weak evidence from becoming product claims.",
            "All reports, live tables, source contracts, and regression outputs.",
            "Gate summary and evidence_policy.",
            "Goal completion requires every explicit gate to be proven by current evidence.",
            "aligned",
            "fail" if failed_topics or topic_gap_dg_rate < 0.70 or linked_ref_rate < 0.30 else "pass",
            f"evidence_policy depends on linked refs, topic-gap sections, calibration, Claim Cards, and multi-corpus gates.",
            "Use this audit as the release stop/go gate; do not redefine success around passing subsets.",
        ),
        StepAudit(
            "quarterly / multi-corpus",
            "Preserve corpus-specific builds before cross-corpus bridge graph.",
            "Corpus registry, paper_corpora, snapshots, and corpus-scoped runs.",
            "Independent optics/CS/materials snapshots plus later bridge graph.",
            "No optics-only hardwiring in algorithms.",
            "aligned",
            "pass" if int(m.get("corpus_registry") or 0) else "warn",
            f"corpus_registry={int(m.get('corpus_registry') or 0):,}; corpus_snapshots={int(m.get('corpus_snapshots') or 0):,}.",
            "Add per-corpus algorithm-logic audit before building cross-corpus bridge claims.",
        ),
    ]

    status_counts = {
        "algorithm_fit": dict(sorted(_count_values(s.algorithm_fit for s in steps).items())),
        "readiness": dict(sorted(_count_values(s.readiness for s in steps).items())),
    }
    return {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "metrics": {
            "linked_ref_rate": linked_ref_rate,
            "openalex_w_rate": openalex_w_rate,
            "primary_section_papers": primary_sections,
            "section_atoms": section_atoms,
            "section_atom_decision_grade": section_atom_decision_grade,
            "section_atoms_fts": section_atoms_fts,
            "section_atom_embeddings": section_atom_embeddings,
            "section_atom_embeddings_retrieval_only": section_atom_embeddings_retrieval_only,
            "section_atom_chains": section_atom_chains,
            "section_atom_chain_full": section_atom_chain_full,
            "section_atom_chain_decision_grade": section_atom_chain_decision_grade,
            "limitation_atoms": limitation_atoms,
            "limitation_exact_section_atoms": limitation_exact_section_atoms,
            "limitation_aggregate_section_atoms": limitation_aggregate_section_atoms,
            "limitation_section_atom_bridge_atoms": limitation_section_atom_bridge_atoms,
            "limitation_current_contract_atoms": limitation_current_contract_atoms,
            "limitation_typed_chain_atoms": limitation_typed_chain_atoms,
            "limitation_current_contract_typed_chain_atoms": limitation_current_contract_typed_chain_atoms,
            "limitation_abstract_atoms": limitation_abstract_atoms,
            "complete_typed_lineage_triples": complete_typed_lineage_triples,
            "partial_typed_lineage_triples": partial_typed_lineage_triples,
            "lineage_completeness_counts": lineage_completeness_counts,
            "claim_cards_with_section_atom_chain_support": claim_cards_with_chain_support,
            "complete_claim_cards_with_section_atom_chain_support": complete_claim_cards_with_chain_support,
            "high_confidence_claim_cards_with_section_atom_chain_support": high_confidence_claim_cards_with_chain_support,
            "claim_cards_with_full_decision_grade_chain": claim_cards_with_full_decision_grade_chain,
            "mutation_hypotheses": mutation_hypotheses,
            "mutation_hypotheses_with_falsification": mutation_hypotheses_with_falsification,
            "mutation_hypotheses_with_evidence_contract": mutation_hypotheses_with_evidence_contract,
            "topic_gap_decision_grade_section_rate": topic_gap_dg_rate,
            "failed_topics": failed_topics,
            "evidence_map_uncertainty_overlay_count": uncertainty_overlay_count,
            "evidence_map_uncertainty_overlay_gates": uncertainty_overlay_gates,
            "evidence_map_uncertainty_overlay_contract_pass": uncertainty_overlay_contract_pass,
        },
        "status_counts": status_counts,
        "steps": [s.__dict__ for s in steps],
        "policy": (
            "Algorithm fit must be judged before path execution. A step can be algorithmically aligned while "
            "live readiness is failing; the correct action is then to improve inputs/evidence, not weaken the algorithm."
        ),
    }


def _count_values(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = str(value)
        out[key] = out.get(key, 0) + 1
    return out


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# V14B Algorithm Logic Audit",
        "",
        f"- generated_at: `{result['generated_at']}`",
        f"- linked_ref_rate: `{float(result['metrics']['linked_ref_rate']):.1%}`",
        f"- openalex_w_rate: `{float(result['metrics']['openalex_w_rate']):.1%}`",
        f"- primary_section_papers: `{int(result['metrics']['primary_section_papers']):,}`",
        f"- section_atoms: `{int(result['metrics']['section_atoms']):,}`",
        f"- section_atom_decision_grade: `{int(result['metrics']['section_atom_decision_grade']):,}`",
        f"- section_atoms_fts: `{'yes' if int(result['metrics']['section_atoms_fts']) else 'no'}`",
        f"- section_atom_embeddings: `{int(result['metrics']['section_atom_embeddings']):,}`",
        f"- section_atom_embeddings_retrieval_only: `{int(result['metrics']['section_atom_embeddings_retrieval_only']):,}`",
        f"- section_atom_chains: `{int(result['metrics']['section_atom_chains']):,}`",
        f"- section_atom_chain_full: `{int(result['metrics']['section_atom_chain_full']):,}`",
        f"- section_atom_chain_decision_grade: `{int(result['metrics']['section_atom_chain_decision_grade']):,}`",
        f"- limitation_exact_section_atoms: `{int(result['metrics']['limitation_exact_section_atoms']):,}`",
        f"- limitation_aggregate_section_atoms: `{int(result['metrics']['limitation_aggregate_section_atoms']):,}`",
        f"- limitation_section_atom_bridge_atoms: `{int(result['metrics']['limitation_section_atom_bridge_atoms']):,}`",
        f"- limitation_current_contract_atoms: `{int(result['metrics']['limitation_current_contract_atoms']):,}`",
        f"- limitation_typed_chain_atoms: `{int(result['metrics']['limitation_typed_chain_atoms']):,}`",
        f"- limitation_current_contract_typed_chain_atoms: `{int(result['metrics']['limitation_current_contract_typed_chain_atoms']):,}`",
        f"- limitation_abstract_atoms: `{int(result['metrics']['limitation_abstract_atoms']):,}`",
        f"- complete_typed_lineage_triples: `{int(result['metrics']['complete_typed_lineage_triples']):,}`",
        f"- partial_typed_lineage_triples: `{int(result['metrics']['partial_typed_lineage_triples']):,}`",
        f"- lineage_completeness_counts: `{json.dumps(result['metrics'].get('lineage_completeness_counts') or {}, ensure_ascii=False, sort_keys=True)}`",
        f"- claim_cards_with_section_atom_chain_support: `{int(result['metrics']['claim_cards_with_section_atom_chain_support']):,}`",
        f"- complete_claim_cards_with_section_atom_chain_support: `{int(result['metrics']['complete_claim_cards_with_section_atom_chain_support']):,}`",
        f"- claim_cards_with_full_decision_grade_chain: `{int(result['metrics']['claim_cards_with_full_decision_grade_chain']):,}`",
        f"- mutation_hypotheses: `{int(result['metrics']['mutation_hypotheses']):,}`",
        f"- mutation_hypotheses_with_falsification: `{int(result['metrics']['mutation_hypotheses_with_falsification']):,}`",
        f"- mutation_hypotheses_with_evidence_contract: `{int(result['metrics']['mutation_hypotheses_with_evidence_contract']):,}`",
        f"- topic_gap_decision_grade_section_rate: `{float(result['metrics']['topic_gap_decision_grade_section_rate']):.1%}`",
        f"- failed regression topics: `{', '.join(result['metrics']['failed_topics']) or 'none'}`",
        f"- evidence_map_uncertainty_overlays: `{int(result['metrics']['evidence_map_uncertainty_overlay_count']):,}`",
        "",
        "## Policy",
        "",
        result["policy"],
        "",
        "## Step Audits",
        "",
        "| step | algorithm_fit | readiness | algorithm role | challenge | next tuning |",
        "|---|---|---|---|---|---|",
    ]
    for step in result["steps"]:
        lines.append(
            f"| {_md(step['step'])} | `{step['algorithm_fit']}` | `{step['readiness']}` | "
            f"{_md(step['algorithm_role'])} | {_md(step['challenge'])} | {_md(step['next_tuning'])} |"
        )
    lines.extend(
        [
            "",
            "## Input / Output Contracts",
            "",
            "| step | input contract | output contract | promotion guard |",
            "|---|---|---|---|",
        ]
    )
    for step in result["steps"]:
        lines.append(
            f"| {_md(step['step'])} | {_md(step['input_contract'])} | "
            f"{_md(step['output_contract'])} | {_md(step['promotion_guard'])} |"
        )
    return "\n".join(lines) + "\n"


def _md(raw: Any) -> str:
    return " ".join(str(raw or "").replace("|", ";").split())


def run_algorithm_logic_audit(
    *,
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    report_dir: Path = REPORT_DIR,
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    report_dir.mkdir(parents=True, exist_ok=True)
    result = build_algorithm_logic_audit(
        db_main=db_main,
        db_v14=db_v14,
        report_dir=report_dir,
        repo_root=repo_root,
    )
    md_path = report_dir / "algorithm_logic_audit.md"
    json_path = report_dir / "algorithm_logic_audit.json"
    md_path.write_text(render_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"report": str(md_path), "json": str(json_path), "status_counts": result["status_counts"]}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Audit V14B step-by-step algorithm logic.")
    parser.add_argument("--db", default=str(DB_MAIN))
    parser.add_argument("--db-v14", default=str(DB_V14))
    parser.add_argument("--out-dir", default=str(REPORT_DIR))
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    result = run_algorithm_logic_audit(
        db_main=Path(args.db),
        db_v14=Path(args.db_v14),
        report_dir=Path(args.out_dir),
        repo_root=Path(args.repo_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
