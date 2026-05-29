from __future__ import annotations

from echelon.v14b.topic_regression import (
    GOLD_TOPICS,
    METALENS_GOLD,
    render_multi_regression_md,
    render_regression_md,
    run_topic_regression,
)


def _branch(name: str):
    return {
        "name": name,
        "historical_bottleneck": "manufacturing consistency",
        "enabling_condition": "inverse design",
        "driver_papers": [{"paper_id": f"{name}-p", "title": name}],
    }


def test_metalens_regression_passes_on_decision_grade_fixture():
    lens = {
        "ready": True,
        "topic_dossier": {
            "branch_splits": [_branch(name) for name in METALENS_GOLD.expected_branches],
            "bottleneck_dossiers": [
                {"name": name, "evidence_papers": [{"paper_id": "p1"}]}
                for name in METALENS_GOLD.expected_bottlenecks
            ],
        },
        "unresolved_limitations": [
            {"keyword": name, "description": name, "paper_id": "p1"}
            for name in METALENS_GOLD.expected_bottlenecks
        ],
        "history_main_path": {
            "key_turning_papers": [
                {
                    "paper_id": f"p{i}",
                    "access_links": [{"url": "https://example.test"}],
                    "content_availability": {"has_primary_evidence_sections": True},
                }
                for i in range(8)
            ]
        },
        "future_growth": {"predicted_edges": [{"source_paper_id": "p1", "target_paper_id": "p2"}]},
        "rd_radar": {"claim_cards": [{"eligible": True}]},
    }

    result = run_topic_regression(lens)

    assert result["overall_status"] == "pass"
    assert all(row["status"] == "pass" for row in result["branch_results"])
    assert all(row["status"] == "pass" for row in result["bottleneck_results"])


def test_metalens_regression_flags_missing_claim_cards_and_evidence():
    lens = {
        "ready": True,
        "topic_dossier": {"branch_splits": [_branch("Imaging systems")], "bottleneck_dossiers": []},
        "history_main_path": {"key_turning_papers": [{"paper_id": "p1", "access_links": []}]},
        "future_growth": {"predicted_edges": [{"source_paper_id": "p1", "target_paper_id": "p2"}]},
        "rd_radar": {"claim_cards": []},
    }

    result = run_topic_regression(lens)
    md = render_regression_md(result)

    assert result["overall_status"] == "fail"
    assert any(gate["name"] == "Claim Cards for Radar" for gate in result["gates"])
    assert "Quality Gaps" in md


def test_gold_topics_cover_required_regression_suite():
    assert {
        "metalens",
        "metasurface holography",
        "photonic crystal cavity",
        "quantum light source",
    }.issubset(GOLD_TOPICS)


def test_multi_topic_rendering_uses_gold_branch_coverage():
    results = [
        {
            "topic": "metasurface holography",
            "overall_status": "warn",
            "gold_branch_coverage": 0.75,
            "key_turning_papers": {"total": 4},
            "future_candidates": {"complete_claim_cards": 1},
        }
    ]
    md = render_multi_regression_md(results)

    assert "metasurface holography" in md
    assert "0.75" in md
