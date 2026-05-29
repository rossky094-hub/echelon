"""Shared evidence grading rules for V14B product claims.

The product must never present a graph edge, branch, bottleneck, or future
direction as stronger than the evidence behind it.  These helpers keep that
policy consistent across audits and downstream builders.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


SECTION_LEVEL_QUALITIES = {
    "section_level",
    "structured_sections",
    "primary_section",
    "full_text_section",
}

WEAK_TEXT_QUALITIES = {
    "weak_abstract",
    "abstract",
}

MODEL_ONLY_QUALITIES = {
    "model_only",
    "calibrated_graph",
    "edge_candidate",
}


def normalize_quality(value: Any) -> str:
    return str(value or "unknown").strip().lower()


def grade_from_qualities(qualities: Iterable[Any]) -> str:
    """Return a stable claim-grade from row-level evidence quality labels."""
    q = [normalize_quality(v) for v in qualities if normalize_quality(v)]
    if not q:
        return "insufficient"
    counts = Counter(q)
    section = sum(counts.get(v, 0) for v in SECTION_LEVEL_QUALITIES)
    weak_text = sum(counts.get(v, 0) for v in WEAK_TEXT_QUALITIES)
    model_only = sum(counts.get(v, 0) for v in MODEL_ONLY_QUALITIES)
    section_ratio = section / max(1, len(q))
    if section >= 3 and section_ratio >= 0.70:
        return "strong_section"
    if section >= 1 and section_ratio >= 0.35:
        return "moderate_section"
    if weak_text and not section:
        return "weak_abstract"
    if model_only and not section and not weak_text:
        return "model_only"
    return "metadata_only"


def coverage_grade(*, linked_ref_rate: float, primary_section_rate: float, openalex_rate: float) -> str:
    """Grade the graph's current evidence bone, independent of a specific claim."""
    if linked_ref_rate >= 0.30 and primary_section_rate >= 0.12 and openalex_rate >= 0.70:
        return "usable_evidence_bone"
    if linked_ref_rate >= 0.15 and primary_section_rate >= 0.03:
        return "thin_evidence_bone"
    return "very_thin_evidence_bone"


def claim_scope_policy(
    *,
    evidence_grade: str,
    has_complete_claim_card: bool = False,
    has_calibration: bool = False,
    linked_ref_rate: float = 0.0,
) -> str:
    """Maximum user-facing scope allowed by evidence quality."""
    if (
        evidence_grade == "strong_section"
        and has_complete_claim_card
        and has_calibration
        and linked_ref_rate >= 0.30
    ):
        return "validated_candidate"
    if evidence_grade in {"strong_section", "moderate_section"} and has_complete_claim_card:
        return "exploratory_with_claim_card"
    if evidence_grade in {"weak_abstract", "metadata_only", "model_only"}:
        return "candidate_pool_only"
    return "insufficient_evidence"


def uncertainty_reasons(
    *,
    linked_ref_rate: float,
    primary_section_rate: float,
    openalex_rate: float,
    has_calibration: bool,
) -> list[str]:
    reasons: list[str] = []
    if linked_ref_rate < 0.30:
        reasons.append("linked refs below 30%; citation backbone is incomplete")
    if primary_section_rate < 0.12:
        reasons.append("section-level evidence below decision-grade target")
    if openalex_rate < 0.70:
        reasons.append("OpenAlex topic/field coverage below cross-field target")
    if not has_calibration:
        reasons.append("future-growth calibration audit missing")
    return reasons
