from __future__ import annotations

from echelon.api.graph_visual_backend import _build_topic_dossier


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
