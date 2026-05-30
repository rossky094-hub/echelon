"""Topic-level product regression and readiness audits.

Benchmark topics are not an allowlist for product behavior or a way to save LLM
spend.  They are deterministic regression fixtures with known expected
branches/bottlenecks, used to catch cases where the Topic Dossier works for
Metalens but fails on other optics subdomains.  Arbitrary topics can still run
the cheaper evidence-readiness preflight without invoking LLM judgment.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.product_baseline import (
    METALENS_EXPECTED_BRANCHES,
    evaluate_topic_lens,
)
from echelon.v14b.topic_readiness import build_topic_readiness_preflight


@dataclass(frozen=True)
class BenchmarkTopic:
    topic: str
    expected_branches: tuple[str, ...]
    expected_bottlenecks: tuple[str, ...]
    minimum_key_turning_papers: int = 5
    minimum_branches_with_driver_papers: int = 4
    minimum_turning_papers_with_access: int = 5
    minimum_turning_papers_with_primary_section: int = 3


METALENS_BENCHMARK = BenchmarkTopic(
    topic="metalens",
    expected_branches=METALENS_EXPECTED_BRANCHES,
    expected_bottlenecks=(
        "efficiency",
        "chromatic aberration",
        "field of view",
        "manufacturing consistency",
        "system integration",
        "cost",
    ),
)

METASURFACE_HOLOGRAPHY_BENCHMARK = BenchmarkTopic(
    topic="metasurface holography",
    expected_branches=(
        "High-efficiency visible holography",
        "Large field-of-view holography",
        "Multiplexed and dynamic holography",
        "Fabrication-tolerant metasurface design",
    ),
    expected_bottlenecks=(
        "efficiency",
        "speckle",
        "field of view",
        "crosstalk",
        "fabrication tolerance",
    ),
    minimum_key_turning_papers=4,
    minimum_branches_with_driver_papers=3,
    minimum_turning_papers_with_access=3,
    minimum_turning_papers_with_primary_section=2,
)

PHOTONIC_CRYSTAL_CAVITY_BENCHMARK = BenchmarkTopic(
    topic="photonic crystal cavity",
    expected_branches=(
        "High-Q nanocavities",
        "Cavity quantum electrodynamics",
        "On-chip coupling and integration",
        "Tunable and nonlinear cavity devices",
    ),
    expected_bottlenecks=(
        "quality factor",
        "mode volume",
        "coupling loss",
        "fabrication disorder",
        "thermal stability",
    ),
    minimum_key_turning_papers=4,
    minimum_branches_with_driver_papers=3,
    minimum_turning_papers_with_access=3,
    minimum_turning_papers_with_primary_section=2,
)

QUANTUM_LIGHT_SOURCE_BENCHMARK = BenchmarkTopic(
    topic="quantum light source",
    expected_branches=(
        "Single-photon emitters",
        "Entangled photon-pair sources",
        "Integrated quantum photonics",
        "Deterministic coupling and collection",
    ),
    expected_bottlenecks=(
        "brightness",
        "indistinguishability",
        "collection efficiency",
        "scalability",
        "integration",
    ),
    minimum_key_turning_papers=4,
    minimum_branches_with_driver_papers=3,
    minimum_turning_papers_with_access=3,
    minimum_turning_papers_with_primary_section=2,
)

BENCHMARK_TOPICS: dict[str, BenchmarkTopic] = {
    g.topic: g
    for g in (
        METALENS_BENCHMARK,
        METASURFACE_HOLOGRAPHY_BENCHMARK,
        PHOTONIC_CRYSTAL_CAVITY_BENCHMARK,
        QUANTUM_LIGHT_SOURCE_BENCHMARK,
    )
}

BOTTLENECK_SYNONYMS: dict[str, tuple[str, ...]] = {
    "brightness": (
        "brightness",
        "source brightness",
        "emission rate",
        "photon flux",
        "pair rate",
    ),
    "chromatic aberration": (
        "chromatic aberration",
        "chromatic",
        "dispersion",
        "achromatic",
        "broadband",
    ),
    "collection efficiency": (
        "collection efficiency",
        "extraction efficiency",
        "collection",
        "outcoupling",
        "out-coupling",
    ),
    "cost": (
        "cost",
        "low-cost",
        "cost-effective",
        "commercial",
        "mass production",
    ),
    "coupling loss": (
        "coupling loss",
        "coupling losses",
        "interface loss",
        "extraction loss",
        "fiber-chip",
    ),
    "crosstalk": (
        "crosstalk",
        "cross-talk",
        "channel leakage",
        "polarization leakage",
        "multiplex leakage",
    ),
    "efficiency": (
        "efficiency",
        "low efficiency",
        "diffraction efficiency",
        "throughput",
        "loss",
    ),
    "fabrication disorder": (
        "fabrication disorder",
        "disorder",
        "sidewall roughness",
        "process variation",
        "fabrication error",
    ),
    "fabrication tolerance": (
        "fabrication tolerance",
        "fabrication-tolerant",
        "process tolerance",
        "process repeatability",
        "manufacturing consistency",
        "fabrication consistency",
        "process variation",
    ),
    "field of view": (
        "field of view",
        "field-of-view",
        "fov",
        "wide-angle",
        "wide angle",
        "off-axis",
        "off axis",
        "angular aberration",
        "angular bandwidth",
    ),
    "indistinguishability": (
        "indistinguishability",
        "indistinguishable",
        "hong-ou-mandel",
        "hom visibility",
        "two-photon interference",
    ),
    "integration": (
        "integration",
        "integrated",
        "on-chip",
        "packaging",
        "heterogeneous integration",
    ),
    "manufacturing consistency": (
        "manufacturing consistency",
        "large-area uniformity",
        "uniformity",
        "yield",
        "repeatability",
        "wafer-scale",
        "scalable fabrication",
    ),
    "mode volume": (
        "mode volume",
        "modal volume",
        "small mode",
        "v mode",
    ),
    "quality factor": (
        "quality factor",
        "q-factor",
        "q factor",
        "high-q",
        "high q",
    ),
    "scalability": (
        "scalability",
        "scalable",
        "scale-up",
        "large-scale",
        "wafer-scale",
    ),
    "speckle": (
        "speckle",
        "speckle noise",
        "holographic noise",
        "coherence noise",
    ),
    "system integration": (
        "system integration",
        "integration",
        "integrated",
        "packaging",
        "alignment",
        "on-chip",
    ),
    "thermal stability": (
        "thermal stability",
        "thermal drift",
        "temperature stability",
        "thermal tuning",
        "heating",
    ),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _lower_text(value: Any) -> str:
    if isinstance(value, str):
        return value.lower()
    return json.dumps(value, ensure_ascii=False).lower()


def _terms_for(label: str) -> tuple[str, ...]:
    key = label.lower().strip()
    return BOTTLENECK_SYNONYMS.get(key, (key,))


def _matched_terms(label: str, text: str) -> list[str]:
    lower = text.lower()
    return [term for term in _terms_for(label) if term in lower]


def _branch_by_name(lens: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dossier = lens.get("topic_dossier") or {}
    branches = dossier.get("branch_splits") or []
    return {
        str(branch.get("name") or ""): branch
        for branch in branches
        if isinstance(branch, dict)
    }


def _bottleneck_text(lens: dict[str, Any]) -> str:
    dossier = lens.get("topic_dossier") or {}
    pieces = [
        dossier.get("hard_bottlenecks") or dossier.get("bottleneck_dossiers") or [],
        lens.get("unresolved_limitations") or [],
        lens.get("bottleneck_lineage") or [],
    ]
    return " ".join(_lower_text(piece) for piece in pieces)


def _branch_hypothesis_text(lens: dict[str, Any]) -> str:
    dossier = lens.get("topic_dossier") or {}
    pieces = []
    for branch in dossier.get("branch_splits") or []:
        if not isinstance(branch, dict):
            continue
        pieces.append(
            {
                "name": branch.get("name"),
                "historical_bottleneck": branch.get("historical_bottleneck"),
                "why_appeared": branch.get("why_appeared"),
                "enabling_condition": branch.get("enabling_condition"),
            }
        )
    return _lower_text(pieces)


def _turning_papers(lens: dict[str, Any]) -> list[dict[str, Any]]:
    history = lens.get("history_main_path") or {}
    return [
        p for p in (history.get("key_turning_papers") or [])
        if isinstance(p, dict)
    ]


def _future_edges(lens: dict[str, Any]) -> list[dict[str, Any]]:
    future_growth = lens.get("future_growth") or {}
    edges = future_growth.get("candidate_edges") or []
    return [
        e for e in (edges or [])
        if isinstance(e, dict)
    ]


def _future_candidate_endpoint_ids(edges: list[dict[str, Any]], *, limit: int = 12) -> list[str]:
    """Return concrete paper targets whose sections can unblock future Claim Cards."""
    out: list[str] = []
    seen: set[str] = set()
    for edge in edges:
        for key in ("source_paper_id", "target_paper_id", "src_paper_id", "dst_paper_id"):
            pid = str(edge.get(key) or "").strip()
            if pid and pid not in seen:
                seen.add(pid)
                out.append(pid)
        for paper_key in ("source_paper", "target_paper"):
            paper = edge.get(paper_key) or {}
            if not isinstance(paper, dict):
                continue
            pid = str(paper.get("paper_id") or "").strip()
            if pid and pid not in seen:
                seen.add(pid)
                out.append(pid)
        if len(out) >= limit:
            break
    return out[:limit]


def _claim_cards(lens: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        c for c in ((lens.get("rd_radar") or {}).get("claim_cards") or [])
        if isinstance(c, dict)
    ]


def _has_evidence_contract(item: dict[str, Any]) -> bool:
    return bool(
        item.get("claim_scope")
        and item.get("evidence_grade")
        and isinstance(item.get("uncertainty_reasons"), list)
    )


def _has_clickable_evidence(item: dict[str, Any]) -> bool:
    return bool(item.get("evidence_objects") or item.get("driver_papers") or item.get("access_links"))


def _five_question_contract_summary(lens: dict[str, Any]) -> dict[str, int]:
    questions = [
        q
        for q in ((lens.get("first_principles") or {}).get("five_questions") or [])
        if isinstance(q, dict)
    ]
    contracted = [q for q in questions if _has_evidence_contract(q)]
    clickable = [q for q in contracted if _has_clickable_evidence(q)]
    return {
        "total": len(questions),
        "with_contract": len(contracted),
        "with_clickable_evidence": len(clickable),
    }


def _bottleneck_lineage_contract_summary(lens: dict[str, Any]) -> dict[str, int]:
    constraints = [
        c
        for c in ((lens.get("bottleneck_lineage") or {}).get("constraints") or [])
        if isinstance(c, dict)
    ]
    contracted = [c for c in constraints if _has_evidence_contract(c)]
    typed = [c for c in contracted if c.get("typed_chain")]
    clickable = [c for c in contracted if _has_clickable_evidence(c)]
    return {
        "total": len(constraints),
        "with_contract": len(contracted),
        "with_typed_chain": len(typed),
        "with_clickable_evidence": len(clickable),
    }


def _reading_path_contract_summary(lens: dict[str, Any]) -> dict[str, Any]:
    steps = [
        s
        for s in ((lens.get("topic_dossier") or {}).get("reading_path") or [])
        if isinstance(s, dict)
    ]
    contracted = [s for s in steps if _has_evidence_contract(s)]
    clickable = [s for s in contracted if _has_clickable_evidence(s)]
    modes = sorted({str(s.get("mode") or "unknown") for s in clickable})
    return {
        "total": len(steps),
        "with_contract": len(contracted),
        "with_clickable_evidence": len(clickable),
        "modes": modes,
    }


def _paper_has_primary_section(paper: dict[str, Any]) -> bool:
    availability = paper.get("content_availability") or {}
    return bool(availability.get("has_primary_evidence_sections"))


def _paper_has_traced_primary_section(paper: dict[str, Any]) -> bool:
    availability = paper.get("content_availability") or {}
    if "has_strong_or_moderate_primary_evidence_sections" in availability:
        return bool(availability.get("has_strong_or_moderate_primary_evidence_sections"))
    provenance = availability.get("primary_section_provenance")
    if isinstance(provenance, dict):
        return int(provenance.get("strong") or 0) + int(provenance.get("moderate") or 0) > 0
    return bool(availability.get("has_primary_evidence_sections"))


def _paper_has_access(paper: dict[str, Any]) -> bool:
    return bool(paper.get("access_links") or [])


def _status(passed: bool, warn: bool = False) -> str:
    if passed:
        return "pass"
    return "warn" if warn else "fail"


def _branch_driver_ids_for_bottleneck(lens: dict[str, Any], label: str, *, limit: int = 12) -> list[str]:
    dossier = lens.get("topic_dossier") or {}
    out: list[str] = []
    seen: set[str] = set()
    for branch in dossier.get("branch_splits") or []:
        if not isinstance(branch, dict):
            continue
        branch_text = _lower_text(
            {
                "historical_bottleneck": branch.get("historical_bottleneck"),
                "why_appeared": branch.get("why_appeared"),
                "enabling_condition": branch.get("enabling_condition"),
            }
        )
        if not _matched_terms(label, branch_text):
            continue
        for paper in branch.get("driver_papers") or []:
            pid = str((paper or {}).get("paper_id") or "").strip()
            if not pid or pid in seen:
                continue
            seen.add(pid)
            out.append(pid)
            if len(out) >= limit:
                return out
    return out


def _turning_primary_section_gaps(turning: list[dict[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    rows = []
    for paper in turning:
        if _paper_has_traced_primary_section(paper):
            continue
        has_primary = _paper_has_primary_section(paper)
        rows.append(
            {
                "paper_id": paper.get("paper_id"),
                "title": paper.get("title"),
                "year": paper.get("year"),
                "gap_type": (
                    "key_turning_paper_weak_section_provenance"
                    if has_primary
                    else "key_turning_paper_missing_primary_section"
                ),
                "reason": (
                    "key turning paper has only weak section parser provenance"
                    if has_primary
                    else "key turning paper lacks local primary section evidence"
                ),
                "primary_section_provenance": (
                    paper.get("content_availability") or {}
                ).get("primary_section_provenance"),
                "access_links": paper.get("access_links") or [],
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _result_gap_candidate_ids(result: dict[str, Any], *, limit: int = 20) -> list[str]:
    """Collect concrete papers that can unblock generic topic evidence gaps."""
    out: list[str] = []
    seen: set[str] = set()

    def add(pid: Any) -> None:
        value = str(pid or "").strip()
        if not value or value in seen:
            return
        seen.add(value)
        out.append(value)

    for row in result.get("bottleneck_results") or []:
        for pid in row.get("candidate_paper_ids") or []:
            add(pid)
            if len(out) >= limit:
                return out
    for paper in result.get("turning_primary_section_gaps") or []:
        add(paper.get("paper_id"))
        if len(out) >= limit:
            return out
    for pid in result.get("future_candidate_gap_paper_ids") or []:
        add(pid)
        if len(out) >= limit:
            return out
    return out


def build_evidence_gap_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a regression result into an actionable evidence-frontfill queue.

    These rows are deliberately not proof that a bottleneck exists. They are the
    next audit targets needed before the Topic Dossier can make stronger claims.
    """
    topic = str(result.get("topic") or "")
    rows: list[dict[str, Any]] = []
    for row in result.get("bottleneck_results") or []:
        if row.get("present_in_evidence"):
            continue
        candidate_ids = row.get("candidate_paper_ids") or []
        priority = 100 if row.get("present_in_branch_hypothesis") else 80
        rows.append(
            {
                "topic": topic,
                "gap_type": "missing_bottleneck_section_evidence",
                "bottleneck": row.get("name"),
                "priority": priority,
                "candidate_paper_ids": ";".join(str(x) for x in candidate_ids),
                "frontfill_query": f"{topic} {row.get('name')}",
                "required_sections": "limitation;discussion;conclusion;future work;results;error_analysis;ablation;method;experiments",
                "why": (
                    "Expected bottleneck appears in branch hypothesis but lacks limitation/section evidence"
                    if row.get("present_in_branch_hypothesis")
                    else "Expected bottleneck is missing from evidence and needs targeted paper/section retrieval"
                ),
            }
        )
    for paper in result.get("turning_primary_section_gaps") or []:
        rows.append(
            {
                "topic": topic,
                "gap_type": paper.get("gap_type") or "key_turning_paper_missing_primary_section",
                "bottleneck": "",
                "priority": 90,
                "candidate_paper_ids": str(paper.get("paper_id") or ""),
                "frontfill_query": f"{topic} {paper.get('title') or paper.get('paper_id')}",
                "required_sections": "limitation;discussion;conclusion;future work;results;method;experiments",
                "why": paper.get("reason") or "key turning paper needs local section evidence",
            }
        )
    if (result.get("future_candidates") or {}).get("total") and not (result.get("future_candidates") or {}).get("complete_claim_cards"):
        candidate_ids = result.get("future_candidate_gap_paper_ids") or []
        rows.append(
            {
                "topic": topic,
                "gap_type": "future_candidates_missing_claim_card",
                "bottleneck": "",
                "priority": 85,
                "candidate_paper_ids": ";".join(str(x) for x in candidate_ids),
                "frontfill_query": topic,
                "required_sections": "limitation;discussion;conclusion;future work;results;error_analysis;ablation",
                "why": (
                    "Future candidates exist but Step6/Step13 has not produced a complete Claim Card; "
                    "frontfill these candidate endpoints so Step5c/Step13 can test bottleneck and history evidence"
                ),
            }
        )
    if not (result.get("future_candidates") or {}).get("total") and not (result.get("future_candidates") or {}).get("complete_claim_cards"):
        candidate_ids = _result_gap_candidate_ids(result)
        rows.append(
            {
                "topic": topic,
                "gap_type": "future_candidate_generation_missing",
                "bottleneck": "",
                "priority": 87,
                "candidate_paper_ids": ";".join(str(x) for x in candidate_ids),
                "frontfill_query": topic,
                "required_sections": "limitation;discussion;conclusion;future work;results;error_analysis;ablation;method;experiments",
                "why": (
                    "No Step5b future candidates matched this topic, so Radar must stay empty. "
                    "Frontfill branch-driver, bottleneck, and turning-paper sections so the next Step5b/Step6/Step13 run can test whether this is a true absence or an evidence gap."
                ),
            }
        )
    five_q = result.get("first_principles_contracts") or {}
    if int(five_q.get("with_clickable_evidence") or 0) < 5:
        candidate_ids = _result_gap_candidate_ids(result)
        rows.append(
            {
                "topic": topic,
                "gap_type": "first_principles_five_questions_missing_evidence_contract",
                "bottleneck": "",
                "priority": 95,
                "candidate_paper_ids": ";".join(str(x) for x in candidate_ids),
                "frontfill_query": topic,
                "required_sections": "limitation;discussion;conclusion;future work;results;method;experiments",
                "why": "Topic Dossier five-question brief lacks complete claim_scope/evidence_grade/uncertainty/clickable evidence contracts",
            }
        )
    reading = result.get("reading_path_contracts") or {}
    if int(reading.get("with_clickable_evidence") or 0) < 4:
        candidate_ids = _result_gap_candidate_ids(result)
        rows.append(
            {
                "topic": topic,
                "gap_type": "topic_reading_path_missing_evidence_contract",
                "bottleneck": "",
                "priority": 88,
                "candidate_paper_ids": ";".join(str(x) for x in candidate_ids),
                "frontfill_query": topic,
                "required_sections": "limitation;discussion;conclusion;future work;results;method;experiments",
                "why": (
                    "Topic Dossier reading path is missing enough audited steps; "
                    "researchers need starter, turning, branch/bottleneck, and future/Claim Card reading routes with clickable evidence"
                ),
            }
        )
    lineage = result.get("bottleneck_lineage_contracts") or {}
    if int(lineage.get("with_clickable_evidence") or 0) < 1:
        rows.append(
            {
                "topic": topic,
                "gap_type": "bottleneck_lineage_missing_typed_evidence_contract",
                "bottleneck": "",
                "priority": 95,
                "candidate_paper_ids": "",
                "frontfill_query": topic,
                "required_sections": "limitation;discussion;conclusion;future work;results;error_analysis;ablation;method;experiments",
                "why": "Bottleneck Lineage Graph lacks an auditable typed chain with clickable section evidence",
            }
        )
    return rows


def run_topic_readiness_preflight(lens: dict[str, Any], topic: str) -> dict[str, Any]:
    """Cheap, deterministic evidence-readiness check for any topic.

    This is intentionally benchmark-free and LLM-free.  It lets arbitrary topics
    produce an honest Topic Dossier state while benchmark topics remain the
    stricter regression suite with hand-authored expected branches/bottlenecks.
    """
    dossier = lens.get("topic_dossier") or {}
    turning = _turning_papers(lens)
    future_edges = _future_edges(lens)
    return build_topic_readiness_preflight(
        topic=topic,
        topic_dossier=dossier,
        turning_hits=turning,
        future_growth=future_edges,
        rd_radar=lens.get("rd_radar") or {},
        first_principles_questions=[
            q
            for q in ((lens.get("first_principles") or {}).get("five_questions") or [])
            if isinstance(q, dict)
        ],
        bottleneck_lineage=lens.get("bottleneck_lineage") or {},
    )


def run_topic_regression(lens: dict[str, Any], benchmark: BenchmarkTopic = METALENS_BENCHMARK) -> dict[str, Any]:
    baseline = evaluate_topic_lens(benchmark.topic, lens)
    branches = _branch_by_name(lens)
    bottleneck_text = _bottleneck_text(lens)
    branch_hypothesis_text = _branch_hypothesis_text(lens)
    turning = _turning_papers(lens)
    future_edges = _future_edges(lens)
    claim_cards = _claim_cards(lens)
    five_question_contracts = _five_question_contract_summary(lens)
    lineage_contracts = _bottleneck_lineage_contract_summary(lens)
    reading_path_contracts = _reading_path_contract_summary(lens)

    branch_results = []
    branches_with_drivers = 0
    for name in benchmark.expected_branches:
        branch = branches.get(name)
        driver_papers = (branch or {}).get("driver_papers") or []
        has_driver = bool(driver_papers)
        branches_with_drivers += int(has_driver)
        branch_results.append(
            {
                "name": name,
                "present": bool(branch),
                "driver_papers": len(driver_papers),
                "has_bottleneck": bool((branch or {}).get("historical_bottleneck")),
                "has_enabler": bool((branch or {}).get("enabling_condition")),
                "status": _status(bool(branch) and has_driver),
            }
        )
    branch_coverage = sum(1 for row in branch_results if row["present"]) / max(1, len(benchmark.expected_branches))

    bottleneck_results = []
    for label in benchmark.expected_bottlenecks:
        evidence_terms = _matched_terms(label, bottleneck_text)
        hypothesis_terms = _matched_terms(label, branch_hypothesis_text)
        matched = bool(evidence_terms)
        bottleneck_results.append(
            {
                "name": label,
                "present_in_evidence": matched,
                "present_in_branch_hypothesis": bool(hypothesis_terms),
                "matched_evidence_terms": evidence_terms,
                "matched_branch_terms": hypothesis_terms,
                "candidate_paper_ids": _branch_driver_ids_for_bottleneck(lens, label),
                "status": _status(matched),
            }
        )

    turning_with_access = sum(1 for p in turning if _paper_has_access(p))
    turning_with_primary_section = sum(1 for p in turning if _paper_has_primary_section(p))
    turning_with_traced_primary_section = sum(1 for p in turning if _paper_has_traced_primary_section(p))
    complete_claim_cards = sum(
        1
        for c in claim_cards
        if c.get("eligible")
        or c.get("five_question_complete")
        or ((c.get("claim_card") or {}).get("five_question_complete"))
    )
    turning_primary_gaps = _turning_primary_section_gaps(turning)

    gates = [
        {
            "name": "expected branches found",
            "actual": branch_coverage,
            "required": 1.0,
            "status": _status(branch_coverage >= 1.0),
        },
        {
            "name": "branches with driver papers",
            "actual": branches_with_drivers,
            "required": benchmark.minimum_branches_with_driver_papers,
            "status": _status(branches_with_drivers >= benchmark.minimum_branches_with_driver_papers),
        },
        {
            "name": "expected bottlenecks evidenced",
            "actual": sum(1 for b in bottleneck_results if b["present_in_evidence"]),
            "required": len(benchmark.expected_bottlenecks),
            "status": _status(all(b["present_in_evidence"] for b in bottleneck_results)),
        },
        {
            "name": "key turning papers",
            "actual": len(turning),
            "required": benchmark.minimum_key_turning_papers,
            "status": _status(len(turning) >= benchmark.minimum_key_turning_papers),
        },
        {
            "name": "turning papers with access links",
            "actual": turning_with_access,
            "required": benchmark.minimum_turning_papers_with_access,
            "status": _status(turning_with_access >= benchmark.minimum_turning_papers_with_access),
        },
        {
            "name": "turning papers with primary sections",
            "actual": turning_with_primary_section,
            "required": benchmark.minimum_turning_papers_with_primary_section,
            "status": _status(turning_with_primary_section >= benchmark.minimum_turning_papers_with_primary_section),
        },
        {
            "name": "turning papers with strong/moderate section provenance",
            "actual": turning_with_traced_primary_section,
            "required": benchmark.minimum_turning_papers_with_primary_section,
            "status": _status(turning_with_traced_primary_section >= benchmark.minimum_turning_papers_with_primary_section),
        },
        {
            "name": "five-question evidence contracts",
            "actual": five_question_contracts["with_clickable_evidence"],
            "required": 5,
            "status": _status(
                five_question_contracts["total"] >= 5
                and five_question_contracts["with_contract"] >= 5
                and five_question_contracts["with_clickable_evidence"] >= 5
            ),
        },
        {
            "name": "bottleneck lineage typed contracts",
            "actual": lineage_contracts["with_clickable_evidence"],
            "required": 1,
            "status": _status(
                lineage_contracts["with_contract"] >= 1
                and lineage_contracts["with_typed_chain"] >= 1
                and lineage_contracts["with_clickable_evidence"] >= 1
            ),
        },
        {
            "name": "auditable reading path",
            "actual": reading_path_contracts["with_clickable_evidence"],
            "required": 4,
            "status": _status(
                reading_path_contracts["with_contract"] >= 4
                and reading_path_contracts["with_clickable_evidence"] >= 4
            ),
        },
        {
            "name": "Claim Cards for Radar",
            "actual": complete_claim_cards,
            "required": 1,
            "status": _status(complete_claim_cards >= 1, warn=bool(future_edges)),
        },
    ]
    fail = [gate for gate in gates if gate["status"] == "fail"]
    warn = [gate for gate in gates if gate["status"] == "warn"]
    overall = "fail" if fail else "warn" if warn else "pass"

    result = {
        "audit_ts": utc_now(),
        "topic": benchmark.topic,
        "benchmark_topic": True,
        "benchmark_fixture_contract": {
            "role": "regression_fixture_not_product_allowlist",
            "product_scope": "arbitrary_topics_use_deterministic_readiness_preflight",
            "llm_policy": "no_llm_required_for_topic_preflight",
        },
        "overall_status": overall,
        "benchmark_branch_coverage": branch_coverage,
        "deterministic_readiness": run_topic_readiness_preflight(lens, benchmark.topic),
        "gates": gates,
        "branch_results": branch_results,
        "bottleneck_results": bottleneck_results,
        "key_turning_papers": {
            "total": len(turning),
            "with_access_links": turning_with_access,
            "with_primary_section": turning_with_primary_section,
            "with_strong_or_moderate_primary_section": turning_with_traced_primary_section,
        },
        "future_candidates": {
            "total": len(future_edges),
            "claim_cards": len(claim_cards),
            "complete_claim_cards": complete_claim_cards,
        },
        "first_principles_contracts": five_question_contracts,
        "bottleneck_lineage_contracts": lineage_contracts,
        "reading_path_contracts": reading_path_contracts,
        "future_candidate_gap_paper_ids": _future_candidate_endpoint_ids(future_edges),
        "turning_primary_section_gaps": turning_primary_gaps,
        "baseline_quality": baseline,
    }
    result["evidence_gap_rows"] = build_evidence_gap_rows(result)
    return result


def render_regression_md(result: dict[str, Any]) -> str:
    title = str(result.get("topic") or "topic").title()
    lines = [
        f"# {title} Topic Regression",
        "",
        f"- Audit: `{result['audit_ts']}`",
        f"- Topic: `{result['topic']}`",
        f"- Overall status: **{result['overall_status']}**",
        "",
        "## Gates",
        "",
        "| Gate | Actual | Required | Status |",
        "| --- | ---: | ---: | --- |",
    ]
    for gate in result["gates"]:
        actual = gate["actual"]
        if isinstance(actual, float):
            actual = f"{actual:.2f}"
        lines.append(f"| {gate['name']} | {actual} | {gate['required']} | {gate['status']} |")
    lines.extend(["", "## Expected Branches", "", "| Branch | Drivers | Bottleneck | Enabler | Status |", "| --- | ---: | --- | --- | --- |"])
    for row in result["branch_results"]:
        lines.append(
            f"| {row['name']} | {row['driver_papers']} | {row['has_bottleneck']} | {row['has_enabler']} | {row['status']} |"
        )
    lines.extend(["", "## Expected Bottlenecks", "", "| Bottleneck | Evidence | Branch Hypothesis | Candidate Papers | Status |", "| --- | --- | --- | ---: | --- |"])
    for row in result["bottleneck_results"]:
        lines.append(
            f"| {row['name']} | {row['present_in_evidence']} | {row.get('present_in_branch_hypothesis')} | "
            f"{len(row.get('candidate_paper_ids') or [])} | {row['status']} |"
        )
    k = result["key_turning_papers"]
    f = result["future_candidates"]
    q = result.get("first_principles_contracts") or {}
    lineage = result.get("bottleneck_lineage_contracts") or {}
    reading = result.get("reading_path_contracts") or {}
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"- Key turning papers: {k['total']} total, {k['with_access_links']} with access links, "
            f"{k['with_primary_section']} with primary local sections, "
            f"{k.get('with_strong_or_moderate_primary_section', 0)} with strong/moderate parser provenance.",
            f"- Future candidates: {f['total']} graph candidates, {f['claim_cards']} Radar cards, {f['complete_claim_cards']} complete cards.",
            f"- Five-question evidence contracts: {q.get('with_clickable_evidence', 0)}/{q.get('total', 0)} have claim scope, evidence grade, uncertainty, and clickable evidence.",
            f"- Bottleneck lineage contracts: {lineage.get('with_clickable_evidence', 0)}/{lineage.get('total', 0)} constraints have typed/clickable evidence contracts.",
            f"- Reading path contracts: {reading.get('with_clickable_evidence', 0)}/{reading.get('total', 0)} steps are auditable; modes={', '.join(reading.get('modes') or []) or 'N/A'}.",
            "- Benchmark topics are regression fixtures, not a product allowlist or an LLM cost-control boundary.",
            "- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.",
        ]
    )
    gaps = (result.get("baseline_quality") or {}).get("quality_gaps") or []
    if gaps:
        lines.extend(["", "## Quality Gaps", ""])
        for gap in gaps:
            lines.append(f"- {gap}")
    evidence_rows = result.get("evidence_gap_rows") or []
    if evidence_rows:
        lines.extend(
            [
                "",
                "## Evidence Gap Queue",
                "",
                "| Gap | Bottleneck | Priority | Candidate Papers | Why |",
                "| --- | --- | ---: | ---: | --- |",
            ]
        )
        for row in evidence_rows[:30]:
            candidate_count = len([x for x in str(row.get("candidate_paper_ids") or "").split(";") if x])
            lines.append(
                f"| {row.get('gap_type')} | {row.get('bottleneck') or ''} | "
                f"{row.get('priority')} | {candidate_count} | {row.get('why')} |"
            )
    return "\n".join(lines) + "\n"


def render_readiness_md(result: dict[str, Any]) -> str:
    title = str(result.get("topic") or "topic").title()
    metrics = result.get("metrics") or {}
    lines = [
        f"# {title} Topic Readiness Preflight",
        "",
        f"- Audit type: `{result.get('audit_type')}`",
        f"- Topic: `{result.get('topic')}`",
        f"- Readiness level: **{result.get('readiness_level')}**",
        f"- Overall status: **{result.get('overall_status')}**",
        f"- LLM policy: {result.get('llm_policy')}",
        "",
        "## Gates",
        "",
        "| Gate | Actual | Required | Status |",
        "| --- | ---: | ---: | --- |",
    ]
    for gate in result.get("gates") or []:
        lines.append(f"| {gate.get('name')} | {gate.get('actual')} | {gate.get('required')} | {gate.get('status')} |")
    lines.extend(
        [
            "",
            "## Evidence Counts",
            "",
            f"- branch splits: {metrics.get('branch_splits', 0)}",
            f"- bottleneck candidates: {metrics.get('bottleneck_candidates', 0)}",
            f"- turning papers: {metrics.get('turning_papers', 0)}",
            f"- turning papers with strong/moderate section provenance: {metrics.get('turning_with_strong_or_moderate_section_provenance', 0)}",
            f"- future candidates: {metrics.get('future_candidates', 0)}",
            f"- complete Claim Cards: {metrics.get('complete_claim_cards', 0)}",
            "",
            "This preflight is cheap and deterministic. Benchmark regressions remain stricter because they compare against hand-authored expected branch and bottleneck structure.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_multi_regression_md(results: list[dict[str, Any]]) -> str:
    lines = [
        "# Multi-topic Topic Lens Regression",
        "",
        f"- Audit: `{utc_now()}`",
        "",
        "| Topic | Overall | Branch Coverage | Turning Papers | 5Q Evidence | Lineage Evidence | Reading Path | Complete Claim Cards |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        baseline = result.get("baseline_quality") or {}
        turning = result.get("key_turning_papers") or {}
        future = result.get("future_candidates") or {}
        q = result.get("first_principles_contracts") or {}
        lineage = result.get("bottleneck_lineage_contracts") or {}
        reading = result.get("reading_path_contracts") or {}
        lines.append(
            "| {topic} | {status} | {coverage:.2f} | {turning} | {fiveq} | {lineage} | {reading} | {cards} |".format(
                topic=result.get("topic"),
                status=result.get("overall_status"),
                coverage=float(
                    result.get("benchmark_branch_coverage")
                    or baseline.get("expected_branch_coverage")
                    or 0.0
                ),
                turning=int(turning.get("total") or 0),
                fiveq=int(q.get("with_clickable_evidence") or 0),
                lineage=int(lineage.get("with_clickable_evidence") or 0),
                reading=int(reading.get("with_clickable_evidence") or 0),
                cards=int(future.get("complete_claim_cards") or 0),
            )
        )
    lines.extend(
        [
            "",
            "## Product Gate",
            "",
            "This suite prevents the Topic Dossier from being tuned only for Metalens. "
            "A topic may fail because evidence is genuinely thin; the required behavior is explicit gaps, not confident generic prose.",
        ]
    )
    gap_rows = [row for result in results for row in (result.get("evidence_gap_rows") or [])]
    if gap_rows:
        by_type: dict[str, int] = {}
        for row in gap_rows:
            by_type[str(row.get("gap_type") or "unknown")] = by_type.get(str(row.get("gap_type") or "unknown"), 0) + 1
        lines.extend(["", "## Evidence Gap Summary", ""])
        for key, count in sorted(by_type.items()):
            lines.append(f"- {key}: {count}")
        lines.append("")
        lines.append("See `multi_topic_evidence_gap_queue.csv` for section/OpenAlex/frontfill targets.")
    return "\n".join(lines) + "\n"


def _slug_topic(topic: str) -> str:
    return "_".join(
        part for part in re.split(r"[^a-zA-Z0-9]+", topic.lower().strip())
        if part
    ) or "topic"


def write_evidence_gap_outputs(results: list[dict[str, Any]], out_dir: Path) -> None:
    rows = [row for result in results for row in (result.get("evidence_gap_rows") or [])]
    json_path = out_dir / "multi_topic_evidence_gap_queue.json"
    csv_path = out_dir / "multi_topic_evidence_gap_queue.csv"
    md_path = out_dir / "multi_topic_evidence_gap_queue.md"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fieldnames = [
        "topic",
        "gap_type",
        "bottleneck",
        "priority",
        "candidate_paper_ids",
        "frontfill_query",
        "required_sections",
        "why",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    lines = [
        "# Multi-topic Evidence Gap Queue",
        "",
        f"- Audit: `{utc_now()}`",
        f"- Rows: {len(rows)}",
        "",
        "These rows are not conclusions. They are targeted evidence-frontfill tasks generated by the multi-topic regression gate.",
        "",
        "| Topic | Gap | Bottleneck | Priority | Candidate Papers |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for row in rows[:80]:
        candidate_count = len([x for x in str(row.get("candidate_paper_ids") or "").split(";") if x])
        lines.append(
            f"| {row.get('topic')} | {row.get('gap_type')} | {row.get('bottleneck') or ''} | "
            f"{row.get('priority')} | {candidate_count} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_topic_lens(topic: str, top_k: int) -> dict[str, Any]:
    from echelon.api.graph_visual_backend import get_topic_lens

    return get_topic_lens(topic=topic, top_k=top_k)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Topic Lens product regression.")
    parser.add_argument(
        "--topic",
        default="all",
        help=(
            "benchmark topic name, 'all' for the benchmark suite, or any topic "
            "for deterministic readiness preflight"
        ),
    )
    parser.add_argument("--top-k", type=int, default=80)
    parser.add_argument("--out-dir", default="reports/v14b_pilot")
    args = parser.parse_args(argv)
    topic_arg = args.topic.lower().strip()
    if topic_arg == "all":
        benchmark_topics = list(BENCHMARK_TOPICS.values())
    else:
        benchmark_topics = [BENCHMARK_TOPICS[topic_arg]] if topic_arg in BENCHMARK_TOPICS else []

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    outputs = []
    for benchmark in benchmark_topics:
        lens = load_topic_lens(benchmark.topic, args.top_k)
        result = run_topic_regression(lens, benchmark)
        results.append(result)
        slug = _slug_topic(benchmark.topic)
        md = out_dir / f"{slug}_topic_regression.md"
        json_path = out_dir / f"{slug}_topic_regression.json"
        md.write_text(render_regression_md(result), encoding="utf-8")
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outputs.append({"topic": benchmark.topic, "report": str(md), "json": str(json_path), "overall_status": result["overall_status"], "audit_type": "benchmark_regression"})

    if len(results) > 1:
        suite_md = out_dir / "multi_topic_regression.md"
        suite_json = out_dir / "multi_topic_regression.json"
        suite_md.write_text(render_multi_regression_md(results), encoding="utf-8")
        suite_json.write_text(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        write_evidence_gap_outputs(results, out_dir)
        outputs.append({"topic": "all", "report": str(suite_md), "json": str(suite_json), "audit_type": "benchmark_regression_suite"})
    elif not benchmark_topics:
        lens = load_topic_lens(topic_arg, args.top_k)
        result = run_topic_readiness_preflight(lens, topic_arg)
        slug = _slug_topic(topic_arg)
        md = out_dir / f"{slug}_topic_readiness.md"
        json_path = out_dir / f"{slug}_topic_readiness.json"
        md.write_text(render_readiness_md(result), encoding="utf-8")
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outputs.append({"topic": topic_arg, "report": str(md), "json": str(json_path), "overall_status": result["overall_status"], "audit_type": result["audit_type"]})
    print(json.dumps({"outputs": outputs}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
