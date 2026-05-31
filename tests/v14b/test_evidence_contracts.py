from __future__ import annotations

from echelon.v14b.evidence_contracts import (
    SECTION_PARSER_CONTRACT_VERSION,
    evidence_availability_flags,
    paper_has_decision_grade_primary_section,
    paper_has_traced_primary_section,
    summarize_primary_section_provenance,
)


def test_primary_section_decision_grade_requires_current_contract_and_traceable_strategy():
    sections = [
        {
            "section_name": "discussion",
            "extraction_strategies": ["explicit_heading"],
            "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
        },
        {
            "section_name": "conclusion",
            "extraction_strategies": ["explicit_heading"],
            "parser_contract_version": "legacy_contract",
        },
        {
            "section_name": "limitations",
            "extraction_strategies": ["loose_inline_heading"],
            "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
        },
    ]

    provenance = summarize_primary_section_provenance(sections)
    flags = evidence_availability_flags(provenance)

    assert provenance["strong"] == 2
    assert provenance["weak"] == 1
    assert provenance["current_contract"] == 2
    assert provenance["decision_grade"] == 1
    assert flags["has_strong_or_moderate_primary_evidence_sections"] is True
    assert flags["has_current_contract_primary_evidence_sections"] is True
    assert flags["has_decision_grade_primary_evidence_sections"] is True
    assert flags["primary_section_evidence_grade"] == "decision_grade"


def test_traced_primary_is_not_decision_grade_without_current_contract():
    paper = {
        "content_availability": {
            "has_primary_evidence_sections": True,
            "has_strong_or_moderate_primary_evidence_sections": True,
            "has_current_contract_primary_evidence_sections": False,
            "primary_section_provenance": {
                "strong": 1,
                "moderate": 0,
                "weak": 0,
                "current_contract": 0,
                "decision_grade": 0,
            },
        }
    }

    assert paper_has_traced_primary_section(paper)
    assert not paper_has_decision_grade_primary_section(paper)


def test_terminal_summary_cue_is_weak_context_not_decision_grade():
    provenance = summarize_primary_section_provenance(
        [
            {
                "section_name": "conclusion",
                "extraction_strategies": ["terminal_cue_summary"],
                "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
            }
        ]
    )
    flags = evidence_availability_flags(provenance)

    assert provenance["weak"] == 1
    assert provenance["current_contract"] == 1
    assert provenance["decision_grade"] == 0
    assert flags["has_primary_evidence_sections"] is True
    assert flags["has_decision_grade_primary_evidence_sections"] is False
    assert flags["primary_section_evidence_grade"] == "weak"
