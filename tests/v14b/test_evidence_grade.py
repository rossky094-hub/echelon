from __future__ import annotations

from echelon.v14b.evidence_grade import (
    claim_scope_policy,
    coverage_grade,
    grade_from_qualities,
    uncertainty_reasons,
)


def test_grade_from_qualities_prefers_section_evidence():
    assert grade_from_qualities(["section_level", "section_level", "section_level", "weak_abstract"]) == "strong_section"
    assert grade_from_qualities(["section_level", "weak_abstract"]) == "moderate_section"
    assert grade_from_qualities(["weak_abstract"]) == "weak_abstract"
    assert grade_from_qualities(["calibrated_graph"]) == "model_only"


def test_claim_scope_policy_blocks_model_only_radar_promotion():
    assert (
        claim_scope_policy(
            evidence_grade="model_only",
            has_complete_claim_card=True,
            has_calibration=True,
            linked_ref_rate=0.40,
        )
        == "candidate_pool_only"
    )
    assert (
        claim_scope_policy(
            evidence_grade="strong_section",
            has_complete_claim_card=True,
            has_calibration=True,
            linked_ref_rate=0.35,
        )
        == "validated_candidate"
    )


def test_coverage_grade_and_uncertainty_reasons():
    assert coverage_grade(linked_ref_rate=0.31, primary_section_rate=0.13, openalex_rate=0.75) == "usable_evidence_bone"
    reasons = uncertainty_reasons(
        linked_ref_rate=0.13,
        primary_section_rate=0.01,
        openalex_rate=0.55,
        has_calibration=False,
    )
    assert len(reasons) == 4
