"""Shared evidence qualification contracts for V14B.

This module keeps user-visible evidence gates from drifting apart.  A section
being present is not the same as a section being decision-grade: high-confidence
Topic Dossier, bottleneck, and Claim Card paths need both traceable extraction
provenance and the current parser contract.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

SECTION_PARSER_NAME = "v14b_section_ingest_v3"
SECTION_PARSER_CONTRACT_VERSION = "v14b_section_parser_contract_v3_toc_guard"
SECTION_PARSER_CONTRACT_GUARDS = (
    "toc_dot_leader",
    "toc_numbered_entry",
    "ambiguous_lowercase_fragment_heading",
)

PRIMARY_SECTION_NAMES = (
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

DECISION_SECTION_NAMES = frozenset(
    {
        "limitation",
        "limitations",
        "discussion",
        "conclusion",
        "conclusions",
        "future_work",
        "future_directions",
        "results",
        "error_analysis",
        "ablation",
        "method",
        "methods",
        "experiments",
    }
)

STRONG_SECTION_STRATEGIES = frozenset(
    {
        "explicit_heading",
        "heading_continuation",
        "embedded_heading",
    }
)

MODERATE_SECTION_STRATEGIES = frozenset({"inline_heading"})

WEAK_SECTION_STRATEGIES = frozenset(
    {
        "loose_inline_heading",
        "parser_hint",
        "terminal_cue_summary",
        "legacy_unknown_strategy",
    }
)


def normalize_section_key(raw: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(raw or "").strip().lower())


def is_decision_section(raw: Any) -> bool:
    return normalize_section_key(raw) in DECISION_SECTION_NAMES


def _strategy_set(raw: Any) -> set[str]:
    if isinstance(raw, str):
        return {raw.strip()} if raw.strip() else set()
    return {str(v).strip() for v in (raw or []) if str(v or "").strip()}


def section_strategy_quality(strategies: set[str]) -> str:
    if strategies & STRONG_SECTION_STRATEGIES:
        return "strong"
    if strategies & MODERATE_SECTION_STRATEGIES:
        return "moderate"
    return "weak"


def section_provenance_strength(section: dict[str, Any]) -> str:
    strategies = _strategy_set(section.get("extraction_strategies"))
    if strategies:
        return section_strategy_quality(strategies)
    grade = str(section.get("evidence_grade") or "")
    if grade in {"section_explicit_heading", "section_embedded_heading"}:
        return "strong"
    if grade == "section_inline_heading":
        return "moderate"
    return "weak"


def section_contract_version(section: dict[str, Any]) -> str:
    meta = section.get("meta") if isinstance(section.get("meta"), dict) else {}
    return str(
        section.get("parser_contract_version")
        or meta.get("parser_contract_version")
        or "legacy_unknown_contract"
    )


def summarize_primary_section_provenance(sections: list[dict[str, Any]]) -> dict[str, Any]:
    decision_sections = [
        s
        for s in sections
        if is_decision_section(s.get("section_name") or s.get("section_type"))
    ]
    quality_counts = Counter(section_provenance_strength(s) for s in decision_sections)
    current_contract = [
        s for s in decision_sections
        if section_contract_version(s) == SECTION_PARSER_CONTRACT_VERSION
    ]
    current_quality_counts = Counter(section_provenance_strength(s) for s in current_contract)
    decision_grade = int(current_quality_counts.get("strong", 0)) + int(current_quality_counts.get("moderate", 0))
    return {
        "strong": int(quality_counts.get("strong", 0)),
        "moderate": int(quality_counts.get("moderate", 0)),
        "weak": int(quality_counts.get("weak", 0)),
        "total": len(decision_sections),
        "current_contract": len(current_contract),
        "decision_grade": decision_grade,
        "legacy_or_stale_contract": len(decision_sections) - len(current_contract),
        "section_names": sorted(
            {
                normalize_section_key(s.get("section_name") or s.get("section_type"))
                for s in decision_sections
            }
        ),
    }


def primary_section_evidence_grade(provenance: dict[str, Any]) -> str:
    if int(provenance.get("decision_grade") or 0) > 0:
        return "decision_grade"
    if int(provenance.get("strong") or 0) + int(provenance.get("moderate") or 0) > 0:
        return "strong_or_moderate_stale_or_unknown_contract"
    if int(provenance.get("total") or 0) > 0:
        return "weak"
    return "none"


def evidence_availability_flags(provenance: dict[str, Any]) -> dict[str, Any]:
    strong_or_moderate = int(provenance.get("strong") or 0) + int(provenance.get("moderate") or 0)
    return {
        "has_primary_evidence_sections": int(provenance.get("total") or 0) > 0,
        "has_strong_or_moderate_primary_evidence_sections": strong_or_moderate > 0,
        "has_current_contract_primary_evidence_sections": int(provenance.get("current_contract") or 0) > 0,
        "has_decision_grade_primary_evidence_sections": int(provenance.get("decision_grade") or 0) > 0,
        "primary_section_evidence_grade": primary_section_evidence_grade(provenance),
        "primary_section_provenance": provenance,
    }


def _availability(paper_or_availability: dict[str, Any]) -> dict[str, Any]:
    if "content_availability" in paper_or_availability:
        value = paper_or_availability.get("content_availability")
        return value if isinstance(value, dict) else {}
    return paper_or_availability if isinstance(paper_or_availability, dict) else {}


def paper_has_primary_section(paper: dict[str, Any]) -> bool:
    return bool(_availability(paper).get("has_primary_evidence_sections"))


def paper_has_traced_primary_section(paper: dict[str, Any]) -> bool:
    availability = _availability(paper)
    if "has_strong_or_moderate_primary_evidence_sections" in availability:
        return bool(availability.get("has_strong_or_moderate_primary_evidence_sections"))
    provenance = availability.get("primary_section_provenance")
    if isinstance(provenance, dict):
        return int(provenance.get("strong") or 0) + int(provenance.get("moderate") or 0) > 0
    return False


def paper_has_current_contract_primary_section(paper: dict[str, Any]) -> bool:
    availability = _availability(paper)
    if "has_current_contract_primary_evidence_sections" in availability:
        return bool(availability.get("has_current_contract_primary_evidence_sections"))
    provenance = availability.get("primary_section_provenance")
    if isinstance(provenance, dict):
        return int(provenance.get("current_contract") or 0) > 0
    return False


def paper_has_decision_grade_primary_section(paper: dict[str, Any]) -> bool:
    availability = _availability(paper)
    if "has_decision_grade_primary_evidence_sections" in availability:
        return bool(availability.get("has_decision_grade_primary_evidence_sections"))
    provenance = availability.get("primary_section_provenance")
    if isinstance(provenance, dict):
        return int(provenance.get("decision_grade") or 0) > 0
    return paper_has_traced_primary_section(paper) and paper_has_current_contract_primary_section(paper)
