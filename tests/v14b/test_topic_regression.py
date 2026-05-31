from __future__ import annotations

import echelon.v14b.topic_regression as topic_regression

from echelon.v14b.topic_regression import (
    BENCHMARK_TOPICS,
    METALENS_BENCHMARK,
    build_evidence_gap_rows,
    render_multi_regression_md,
    render_readiness_md,
    render_regression_md,
    run_topic_readiness_preflight,
    run_topic_regression,
)


def _branch(name: str):
    return {
        "name": name,
        "historical_bottleneck": "manufacturing consistency",
        "enabling_condition": "inverse design",
        "driver_papers": [{"paper_id": f"{name}-p", "title": name}],
    }


def _decision_grade_primary_availability() -> dict:
    return {
        "has_primary_evidence_sections": True,
        "has_strong_or_moderate_primary_evidence_sections": True,
        "has_current_contract_primary_evidence_sections": True,
        "has_decision_grade_primary_evidence_sections": True,
        "primary_section_provenance": {
            "strong": 1,
            "moderate": 0,
            "weak": 0,
            "current_contract": 1,
            "decision_grade": 1,
            "total": 1,
        },
    }


def _evidence_contract_fragments():
    reading_steps = [
        "starter",
        "turning",
        "branch_driver",
        "bottleneck",
        "future_candidate",
    ]
    return {
        "first_principles": {
            "five_questions": [
                {
                    "question": f"Q{i}",
                    "answer": f"A{i}",
                    "claim_scope": "candidate_pool_only",
                    "evidence_grade": "section_backed",
                    "uncertainty_reasons": ["audit fixture"],
                    "evidence_objects": [
                        {
                            "type": "paper",
                            "paper_id": f"p{i}",
                            "click_target": {"kind": "paper", "id": f"p{i}"},
                        }
                    ],
                }
                for i in range(1, 6)
            ]
        },
        "topic_dossier": {
            "reading_path": [
                {
                    "mode": mode,
                    "title": mode,
                    "why": f"read {mode}",
                    "claim_scope": "candidate_pool_only",
                    "evidence_grade": "section_backed_reading_path",
                    "uncertainty_reasons": ["audit fixture"],
                    "required_evidence": ["clickable paper"],
                    "papers": [{"paper_id": f"{mode}-p", "title": mode}],
                    "evidence_objects": [
                        {
                            "type": "paper",
                            "paper_id": f"{mode}-p",
                            "click_target": {"kind": "paper", "id": f"{mode}-p"},
                        }
                    ],
                }
                for mode in reading_steps
            ]
        },
        "bottleneck_lineage": {
            "constraints": [
                {
                    "principle_id": "FP1",
                    "claim_scope": "bottleneck_lineage_evidence",
                    "evidence_grade": "typed_section_lineage",
                    "uncertainty_reasons": ["audit fixture"],
                    "typed_chain_completeness": "full",
                    "typed_chain": [{"source_stage": "constraint", "target_stage": "failure"}],
                    "evidence_objects": [
                        {
                            "type": "bottleneck_lineage_triple",
                            "paper_id": "p1",
                            "click_target": {"kind": "paper", "id": "p1"},
                        }
                    ],
                }
            ]
        },
    }


def test_metalens_regression_passes_on_decision_grade_fixture():
    lens = {
        "ready": True,
        **_evidence_contract_fragments(),
        "topic_dossier": {
            **_evidence_contract_fragments()["topic_dossier"],
            "branch_splits": [_branch(name) for name in METALENS_BENCHMARK.expected_branches],
            "bottleneck_dossiers": [
                {"name": name, "evidence_papers": [{"paper_id": "p1"}]}
                for name in METALENS_BENCHMARK.expected_bottlenecks
            ],
        },
        "unresolved_limitations": [
            {"keyword": name, "description": name, "paper_id": "p1"}
            for name in METALENS_BENCHMARK.expected_bottlenecks
        ],
        "history_main_path": {
            "key_turning_papers": [
                {
                    "paper_id": f"p{i}",
                    "access_links": [{"url": "https://example.test"}],
                    "content_availability": _decision_grade_primary_availability(),
                }
                for i in range(8)
            ]
        },
        "future_growth": {"candidate_edges": [{"source_paper_id": "p1", "target_paper_id": "p2"}]},
        "rd_radar": {"claim_cards": [{"eligible": True}]},
    }

    result = run_topic_regression(lens)

    assert result["overall_status"] == "pass"
    assert result["benchmark_fixture_contract"]["role"] == "regression_fixture_not_product_allowlist"
    assert result["benchmark_fixture_contract"]["llm_policy"] == "no_llm_required_for_topic_preflight"
    assert "benchmark_branch_coverage" in result
    assert "gold_branch_coverage" not in result
    assert all(row["status"] == "pass" for row in result["branch_results"])
    assert all(row["status"] == "pass" for row in result["bottleneck_results"])


def test_topic_regression_exports_no_gold_topic_aliases():
    assert not hasattr(topic_regression, "GoldTopic")
    assert not hasattr(topic_regression, "GOLD_TOPICS")
    assert not hasattr(topic_regression, "METALENS_GOLD")


def test_metalens_regression_flags_missing_claim_cards_and_evidence():
    lens = {
        "ready": True,
        "topic_dossier": {"branch_splits": [_branch("Imaging systems")], "bottleneck_dossiers": []},
        "history_main_path": {"key_turning_papers": [{"paper_id": "p1", "access_links": []}]},
        "future_growth": {"candidate_edges": [{"source_paper_id": "p1", "target_paper_id": "p2"}]},
        "rd_radar": {"claim_cards": []},
    }

    result = run_topic_regression(lens)
    md = render_regression_md(result)

    assert result["overall_status"] == "fail"
    assert any(gate["name"] == "Claim Cards for Radar" for gate in result["gates"])
    assert "Quality Gaps" in md
    assert result["evidence_gap_rows"]
    future_gap = [
        row for row in result["evidence_gap_rows"]
        if row["gap_type"] == "future_candidates_missing_claim_card"
    ][0]
    assert future_gap["candidate_paper_ids"] == "p1;p2"


def test_topic_regression_does_not_count_weak_full_lineage_as_promotable():
    fragments = _evidence_contract_fragments()
    fragments["bottleneck_lineage"]["constraints"][0].update(
        {
            "claim_scope": "exploratory_bottleneck_lineage",
            "evidence_grade": "weak_typed_section_lineage",
            "typed_chain_completeness": "full",
        }
    )
    lens = {
        "ready": True,
        **fragments,
        "topic_dossier": {
            **fragments["topic_dossier"],
            "branch_splits": [_branch(name) for name in METALENS_BENCHMARK.expected_branches],
            "bottleneck_dossiers": [
                {"name": name, "evidence_papers": [{"paper_id": "p1"}]}
                for name in METALENS_BENCHMARK.expected_bottlenecks
            ],
        },
        "history_main_path": {
            "key_turning_papers": [
                {
                    "paper_id": f"p{i}",
                    "access_links": [{"url": "https://example.test"}],
                    "content_availability": _decision_grade_primary_availability(),
                }
                for i in range(8)
            ]
        },
        "rd_radar": {"claim_cards": [{"eligible": True}]},
    }

    result = run_topic_regression(lens)

    assert result["bottleneck_lineage_contracts"]["with_partial_typed_chain"] == 1
    assert result["bottleneck_lineage_contracts"]["with_typed_chain"] == 0
    lineage_gate = next(g for g in result["gates"] if g["name"] == "bottleneck lineage typed contracts")
    assert lineage_gate["status"] == "fail"


def test_bottleneck_synonyms_do_not_hide_evidence():
    lens = {
        "ready": True,
        **_evidence_contract_fragments(),
        "topic_dossier": {
            **_evidence_contract_fragments()["topic_dossier"],
            "branch_splits": [_branch(name) for name in METALENS_BENCHMARK.expected_branches],
            "bottleneck_dossiers": [
                {"name": "field of view and angular aberration", "evidence_papers": [{"paper_id": "p1"}]},
                {"name": "manufacturing consistency", "evidence_papers": [{"paper_id": "p2"}]},
                {"name": "cost and reliability", "evidence_papers": [{"paper_id": "p3"}]},
                {"name": "efficiency", "evidence_papers": [{"paper_id": "p4"}]},
                {"name": "chromatic aberration", "evidence_papers": [{"paper_id": "p5"}]},
                {"name": "system integration", "evidence_papers": [{"paper_id": "p6"}]},
            ],
        },
        "history_main_path": {
            "key_turning_papers": [
                {
                    "paper_id": f"p{i}",
                    "access_links": [{"url": "https://example.test"}],
                    "content_availability": _decision_grade_primary_availability(),
                }
                for i in range(8)
            ]
        },
        "rd_radar": {"claim_cards": [{"eligible": True}]},
    }

    result = run_topic_regression(lens)

    by_name = {row["name"]: row for row in result["bottleneck_results"]}
    assert by_name["field of view"]["present_in_evidence"]
    assert "field of view" in by_name["field of view"]["matched_evidence_terms"]
    assert by_name["cost"]["present_in_evidence"]


def test_topic_regression_flags_weak_turning_section_provenance():
    weak_availability = {
        "has_primary_evidence_sections": True,
        "has_strong_or_moderate_primary_evidence_sections": False,
        "primary_section_provenance": {
            "strong": 0,
            "moderate": 0,
            "weak": 1,
            "current_contract": 1,
            "decision_grade": 0,
            "total": 1,
        },
    }
    lens = {
        "ready": True,
        **_evidence_contract_fragments(),
        "topic_dossier": {
            **_evidence_contract_fragments()["topic_dossier"],
            "branch_splits": [_branch(name) for name in METALENS_BENCHMARK.expected_branches],
            "bottleneck_dossiers": [
                {"name": name, "evidence_papers": [{"paper_id": "p1"}]}
                for name in METALENS_BENCHMARK.expected_bottlenecks
            ],
        },
        "unresolved_limitations": [
            {"keyword": name, "description": name, "paper_id": "p1"}
            for name in METALENS_BENCHMARK.expected_bottlenecks
        ],
        "history_main_path": {
            "key_turning_papers": [
                {
                    "paper_id": f"p{i}",
                    "access_links": [{"url": "https://example.test"}],
                    "content_availability": weak_availability,
                }
                for i in range(8)
            ]
        },
        "future_growth": {"candidate_edges": [{"source_paper_id": "p1", "target_paper_id": "p2"}]},
        "rd_radar": {"claim_cards": [{"eligible": True}]},
    }

    result = run_topic_regression(lens)
    gates = {gate["name"]: gate for gate in result["gates"]}

    assert result["overall_status"] == "fail"
    assert gates["turning papers with primary sections"]["status"] == "pass"
    assert gates["turning papers with strong/moderate section provenance"]["status"] == "fail"
    assert result["key_turning_papers"]["with_strong_or_moderate_primary_section"] == 0
    assert any(
        row["gap_type"] == "key_turning_paper_weak_section_provenance"
        for row in result["evidence_gap_rows"]
    )


def test_missing_bottleneck_becomes_frontfill_gap_not_silent_failure():
    lens = {
        "ready": True,
        "topic_dossier": {
            "branch_splits": [
                {
                    **_branch("Broadband achromatic correction"),
                    "historical_bottleneck": "field-of-view and angular bandwidth remain unresolved",
                    "driver_papers": [{"paper_id": "driver-1", "title": "Wide angle metalens"}],
                }
            ],
            "bottleneck_dossiers": [],
        },
        "history_main_path": {
            "key_turning_papers": [
                {"paper_id": "turning-1", "title": "Turning", "access_links": [{"url": "https://example.test"}]}
            ]
        },
        "future_growth": {"candidate_edges": [{"source_paper_id": "p1", "target_paper_id": "p2"}]},
        "rd_radar": {"claim_cards": []},
    }

    result = run_topic_regression(lens)
    rows = build_evidence_gap_rows(result)

    fov = [row for row in result["bottleneck_results"] if row["name"] == "field of view"][0]
    assert fov["present_in_branch_hypothesis"]
    assert "driver-1" in fov["candidate_paper_ids"]
    assert any(row["gap_type"] == "missing_bottleneck_section_evidence" for row in rows)
    assert any(row["gap_type"] == "key_turning_paper_missing_primary_section" for row in rows)


def test_missing_future_candidates_becomes_actionable_frontfill_gap():
    lens = {
        "ready": True,
        **_evidence_contract_fragments(),
        "topic_dossier": {
            **_evidence_contract_fragments()["topic_dossier"],
            "branch_splits": [
                {
                    **_branch("High-efficiency visible holography"),
                    "historical_bottleneck": "efficiency and speckle remain unresolved",
                    "driver_papers": [{"paper_id": "driver-1", "title": "Holography driver"}],
                }
            ],
            "bottleneck_dossiers": [],
        },
        "history_main_path": {
            "key_turning_papers": [
                {"paper_id": "turning-1", "title": "Turning", "access_links": [{"url": "https://example.test"}]}
            ]
        },
        "future_growth": {"candidate_edges": []},
        "rd_radar": {"claim_cards": []},
    }

    result = run_topic_regression(lens, BENCHMARK_TOPICS["metasurface holography"])
    rows = build_evidence_gap_rows(result)
    future_gap = [
        row for row in rows
        if row["gap_type"] == "future_candidate_generation_missing"
    ][0]

    assert "driver-1" in future_gap["candidate_paper_ids"]
    assert future_gap["priority"] >= 87
    assert "Radar must stay empty" in future_gap["why"]


def test_benchmark_topics_cover_required_regression_suite():
    assert {
        "metalens",
        "metasurface holography",
        "photonic crystal cavity",
        "quantum light source",
    }.issubset(BENCHMARK_TOPICS)


def test_multi_topic_rendering_uses_benchmark_branch_coverage():
    results = [
        {
            "topic": "metasurface holography",
            "overall_status": "warn",
            "benchmark_branch_coverage": 0.75,
            "key_turning_papers": {"total": 4},
            "future_candidates": {"complete_claim_cards": 1},
            "evidence_gap_rows": [
                {
                    "gap_type": "missing_bottleneck_section_evidence",
                    "topic": "metasurface holography",
                }
            ],
        }
    ]
    md = render_multi_regression_md(results)

    assert "metasurface holography" in md
    assert "0.75" in md
    assert "Evidence Gap Summary" in md


def test_arbitrary_topic_preflight_is_llm_free_and_not_benchmark_gated():
    lens = {
        "ready": True,
        **_evidence_contract_fragments(),
        "topic_dossier": {
            **_evidence_contract_fragments()["topic_dossier"],
            "claim_scope": "candidate_pool_only",
            "evidence_grade": "metadata_only",
            "uncertainty_reasons": ["fixture"],
            "branch_splits": [_branch("Custom branch")],
            "hard_bottlenecks": [{"name": "integration", "evidence_papers": [{"paper_id": "p1"}]}],
        },
        "history_main_path": {
            "key_turning_papers": [
                {
                    "paper_id": "p1",
                    "access_links": [{"url": "https://example.test"}],
                    "content_availability": {
                        **_decision_grade_primary_availability(),
                    },
                }
            ]
        },
        "future_growth": {"candidate_edges": []},
        "rd_radar": {"claim_cards": []},
    }

    result = run_topic_readiness_preflight(lens, "custom photonics topic")
    md = render_readiness_md(result)

    assert result["audit_type"] == "deterministic_topic_readiness_preflight"
    assert "no_llm_required" in result["llm_policy"]
    assert result["metrics"]["branch_splits"] == 1
    assert "Benchmark regressions remain stricter" in md
