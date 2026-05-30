"""Deterministic Topic Lens readiness contracts.

This module is the shared product contract for arbitrary-topic Topic Lens
readiness.  Benchmark topics remain regression fixtures; this preflight is the
cheap, LLM-free state that any user-entered topic can receive from existing
evidence.
"""
from __future__ import annotations

from typing import Any


NO_LLM_PREFLIGHT_POLICY = (
    "no_llm_required_for_preflight; LLM may audit/name/explain only after evidence exists"
)


def _status(passed: bool, warn: bool = False) -> str:
    if passed:
        return "pass"
    return "warn" if warn else "fail"


def has_evidence_contract(item: dict[str, Any]) -> bool:
    return bool(
        item.get("claim_scope")
        and item.get("evidence_grade")
        and isinstance(item.get("uncertainty_reasons"), list)
    )


def has_clickable_evidence(item: dict[str, Any]) -> bool:
    return bool(
        item.get("evidence_objects")
        or item.get("driver_papers")
        or item.get("access_links")
    )


def paper_has_primary_section(paper: dict[str, Any]) -> bool:
    availability = paper.get("content_availability") or {}
    return bool(availability.get("has_primary_evidence_sections"))


def paper_has_traced_primary_section(paper: dict[str, Any]) -> bool:
    availability = paper.get("content_availability") or {}
    if "has_strong_or_moderate_primary_evidence_sections" in availability:
        return bool(availability.get("has_strong_or_moderate_primary_evidence_sections"))
    provenance = availability.get("primary_section_provenance")
    if isinstance(provenance, dict):
        return int(provenance.get("strong") or 0) + int(provenance.get("moderate") or 0) > 0
    return bool(availability.get("has_primary_evidence_sections"))


def paper_has_access(paper: dict[str, Any]) -> bool:
    return bool(paper.get("access_links") or [])


def _contracts(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    contracted = [item for item in items if has_evidence_contract(item)]
    clickable = [item for item in contracted if has_clickable_evidence(item)]
    return contracted, clickable


def build_topic_readiness_preflight(
    *,
    topic: str,
    topic_dossier: dict[str, Any],
    turning_hits: list[dict[str, Any]],
    future_growth: list[dict[str, Any]],
    rd_radar: dict[str, Any],
    first_principles_questions: list[dict[str, Any]],
    bottleneck_lineage: dict[str, Any],
) -> dict[str, Any]:
    """Build the LLM-free readiness state for an arbitrary Topic Lens query."""
    branch_splits = [
        b for b in (topic_dossier.get("branch_splits") or [])
        if isinstance(b, dict)
    ]
    bottlenecks = [
        b for b in (
            topic_dossier.get("hard_bottlenecks")
            or topic_dossier.get("bottleneck_dossiers")
            or []
        )
        if isinstance(b, dict)
    ]
    constraints = [
        c for c in ((bottleneck_lineage or {}).get("constraints") or [])
        if isinstance(c, dict)
    ]
    claim_cards = [
        c for c in ((rd_radar or {}).get("claim_cards") or [])
        if isinstance(c, dict)
    ]
    reading_path = [
        item for item in (topic_dossier.get("reading_path") or [])
        if isinstance(item, dict)
    ]

    first_principles_contracts, five_q_clickable = _contracts(first_principles_questions)
    lineage_contracts, lineage_clickable_base = _contracts(constraints)
    lineage_clickable = [c for c in lineage_clickable_base if c.get("typed_chain")]
    reading_contracts, reading_clickable = _contracts(reading_path)

    turning_with_access = sum(1 for p in turning_hits if paper_has_access(p))
    turning_with_primary = sum(1 for p in turning_hits if paper_has_primary_section(p))
    turning_with_traced = sum(1 for p in turning_hits if paper_has_traced_primary_section(p))
    complete_claim_cards = sum(
        1
        for c in claim_cards
        if c.get("eligible")
        or c.get("five_question_complete")
        or ((c.get("claim_card") or {}).get("five_question_complete"))
    )
    high_confidence_cards = sum(1 for c in claim_cards if c.get("eligible"))
    dossier_has_contract = has_evidence_contract(topic_dossier)
    turning_required = min(3, max(1, len(turning_hits)))

    gates = [
        {
            "name": "topic dossier evidence contract",
            "status": _status(dossier_has_contract),
            "actual": int(dossier_has_contract),
            "required": 1,
        },
        {
            "name": "branch split candidates",
            "status": _status(bool(branch_splits), warn=True),
            "actual": len(branch_splits),
            "required": 1,
        },
        {
            "name": "bottleneck evidence candidates",
            "status": _status(bool(bottlenecks), warn=True),
            "actual": len(bottlenecks),
            "required": 1,
        },
        {
            "name": "turning papers with access",
            "status": _status(turning_with_access >= turning_required, warn=bool(turning_hits)),
            "actual": turning_with_access,
            "required": turning_required,
        },
        {
            "name": "turning papers with strong/moderate section provenance",
            "status": _status(turning_with_traced >= turning_required, warn=turning_with_primary > 0),
            "actual": turning_with_traced,
            "required": turning_required,
        },
        {
            "name": "five-question evidence contracts",
            "status": _status(
                len(first_principles_contracts) >= 5 and len(five_q_clickable) >= 5,
                warn=bool(first_principles_questions),
            ),
            "actual": len(five_q_clickable),
            "required": 5,
        },
        {
            "name": "bottleneck lineage typed contracts",
            "status": _status(bool(lineage_clickable), warn=bool(lineage_contracts or constraints)),
            "actual": len(lineage_clickable),
            "required": 1,
        },
        {
            "name": "auditable reading path",
            "status": _status(len(reading_clickable) >= 4, warn=bool(reading_contracts or reading_path)),
            "actual": len(reading_clickable),
            "required": 4,
        },
        {
            "name": "complete Claim Cards",
            "status": _status(complete_claim_cards > 0, warn=bool(future_growth)),
            "actual": complete_claim_cards,
            "required": 1,
        },
    ]
    hard_fail = [g for g in gates if g["status"] == "fail"]
    warn = [g for g in gates if g["status"] == "warn"]
    if high_confidence_cards and not hard_fail and not warn:
        readiness_level = "decision_grade_available"
    elif complete_claim_cards and not hard_fail and not warn:
        readiness_level = "claim_card_ready"
    elif complete_claim_cards:
        readiness_level = "claim_card_available_with_gaps"
    elif branch_splits or bottlenecks or turning_hits:
        readiness_level = "evidence_dossier_available" if not hard_fail else "evidence_dossier_with_gaps"
    else:
        readiness_level = "search_context_only"

    return {
        "topic": topic,
        "audit_type": "deterministic_topic_readiness_preflight",
        "llm_policy": NO_LLM_PREFLIGHT_POLICY,
        "readiness_level": readiness_level,
        "overall_status": "fail" if hard_fail else ("warn" if warn else "pass"),
        "gates": gates,
        "metrics": {
            "branch_splits": len(branch_splits),
            "bottleneck_candidates": len(bottlenecks),
            "turning_papers": len(turning_hits),
            "turning_with_access_links": turning_with_access,
            "turning_with_primary_sections": turning_with_primary,
            "turning_with_strong_or_moderate_section_provenance": turning_with_traced,
            "future_candidates": len(future_growth),
            "claim_cards": len(claim_cards),
            "complete_claim_cards": complete_claim_cards,
            "high_confidence_claim_cards": high_confidence_cards,
            "five_question_clickable_contracts": len(five_q_clickable),
            "lineage_clickable_contracts": len(lineage_clickable),
            "reading_path_clickable_contracts": len(reading_clickable),
        },
        "policy": (
            "This readiness state is not a benchmark-topic regression and does not call an LLM. "
            "It tells the UI how far an arbitrary topic can be trusted before stronger evidence arrives."
        ),
    }
