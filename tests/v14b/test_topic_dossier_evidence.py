from __future__ import annotations

from echelon.api.graph_visual_backend import _build_rd_radar, _build_topic_dossier, _lineage_status


def test_topic_dossier_returns_clickable_evidence_objects():
    hit = {
        "paper_id": "p1",
        "title": "Broadband achromatic metalens imaging",
        "abstract": "achromatic metalens imaging with manufacturing limits",
        "year": 2022,
        "cluster_id": "C1",
        "branch_id": "B1",
        "cluster_label": "metalens imaging",
        "score": 0.9,
        "access_links": [{"label": "arXiv", "url": "https://arxiv.org/abs/2201.1"}],
        "content_availability": {"has_primary_evidence_sections": True},
        "limitations": [{"keyword": "efficiency", "description": "limited efficiency"}],
    }
    limitation = {
        "paper_id": "p1",
        "title": "Broadband achromatic metalens imaging",
        "keyword": "efficiency",
        "description": "efficiency remains limited",
        "evidence_quality": "section_level",
    }

    dossier = _build_topic_dossier(
        topic="metalens",
        hits=[hit],
        turning_hits=[{**hit, "reason": {"why": "main path"}}],
        branch_dossiers=[],
        bottleneck_lineage={"top_unresolved_keywords": [{"keyword": "efficiency"}]},
        unresolved_limitations=[limitation],
        rd_radar={"claim_cards_ready": False, "claim_cards": []},
        main_path_edges=[
            {"edge_id": "main:p1:p2", "source_paper_id": "p1", "target_paper_id": "p2", "weight": 0.8}
        ],
        future_growth=[
            {
                "edge_id": "future:p1:p2",
                "source_paper_id": "p1",
                "target_paper_id": "p2",
                "confidence": 0.7,
                "evidence": {"relationship_scope": "direct_paper_match"},
                "source_paper": hit,
                "target_paper": {"paper_id": "p2", "title": "Future metalens"},
            }
        ],
        value_model={"fusion_status": "partial"},
    )

    assert dossier["evidence_objects"]
    assert dossier["branch_splits"][0]["evidence_objects"][0]["paper_id"] == "p1"
    assert dossier["hard_bottlenecks"][0]["evidence_objects"]
    assert dossier["validation_directions"][0]["evidence_objects"]
    assert dossier["insufficient_evidence"][0]["claim"] == "investable future direction"


def test_rd_radar_promotes_only_complete_claim_cards():
    radar = _build_rd_radar(
        future_directions=[
            {
                "direction_id": 1,
                "direction_name": "Incomplete direction",
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
                "direction_name": "Complete but exploratory direction",
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
            },
        ],
    )

    assert len(radar["claim_cards"]) == 1
    assert radar["claim_cards"][0]["title"] == "Complete but exploratory direction"
    assert radar["claim_cards"][0]["eligible"] is False
    assert len(radar["incomplete_claim_cards"]) == 1
    assert any(item["kind"] == "incomplete_claim_card" for item in radar["candidate_pool"])
    edge_items = [item for item in radar["candidate_pool"] if item["kind"] == "candidate_edge"]
    assert edge_items[0]["model_evidence"]["calibrated_prob"] == 0.75


def test_branch_lineage_status_distinguishes_layout_from_evidence():
    assert _lineage_status({"parent_citation_support": 2}, 0.2) == "layout_cluster_only"
    assert _lineage_status({"parent_citation_support": 5}, 0.2) == "weak_split_candidate"
    assert _lineage_status({"parent_citation_support": 12}, 0.35) == "evidence_backed_split"
