from __future__ import annotations

from echelon.api.graph_visual_backend import (
    _build_rd_radar,
    _build_topic_branch_splits,
    _build_topic_dossier,
    _lineage_status,
    _split_topic_turning_papers,
    _topic_branch_facets,
)


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


def test_gold_topic_facets_are_not_metalens_template_reuse():
    holography = [f["name"] for f in _topic_branch_facets("metasurface holography")]
    cavity = [f["name"] for f in _topic_branch_facets("photonic crystal cavity")]
    quantum_source = [f["name"] for f in _topic_branch_facets("quantum light source")]

    assert "High-efficiency visible holography" in holography
    assert "Imaging systems" not in holography
    assert "High-Q nanocavities" in cavity
    assert "Single-photon emitters" in quantum_source


def test_topic_branch_splits_label_facet_matches_as_weak_not_layout():
    hit = {
        "paper_id": "p1",
        "title": "Dynamic high efficiency 3D meta-holography in visible range",
        "abstract": "multiplexed visible holography with metasurface fabrication tolerance",
        "year": 2024,
        "cluster_id": "C13",
        "branch_id": "B13",
        "cluster_label": "design, metasurfaces, metasurface",
        "content_availability": {"has_primary_evidence_sections": True},
    }

    splits = _build_topic_branch_splits(
        "metasurface holography",
        hits=[hit],
        turning_hits=[hit],
    )

    names = {row["name"]: row for row in splits}
    assert "High-efficiency visible holography" in names
    assert names["High-efficiency visible holography"]["lineage_status"] == "weak_split_candidate"
    assert names["High-efficiency visible holography"]["evidence_grade"] == "section_backed_topic_branch_candidate"
    assert names["High-efficiency visible holography"]["uncertainty_reasons"]


def test_topic_turning_papers_demote_broader_field_context():
    papers = [
        {
            "paper_id": "metalens-1",
            "title": "Large-area achromatic metalens for imaging",
            "abstract": "Metalens imaging with broad field of view.",
            "score": 2.0,
        },
        {
            "paper_id": "broad-1",
            "title": "Microwave photonics with superconducting quantum circuits",
            "abstract": "A broad photonics main-path paper about quantum circuits.",
            "score": 10.0,
        },
    ]

    topic_specific, broader = _split_topic_turning_papers("metalens", papers)

    assert [p["paper_id"] for p in topic_specific] == ["metalens-1"]
    assert [p["paper_id"] for p in broader] == ["broad-1"]
    assert topic_specific[0]["reason"]["topic_relevance_scope"] == "topic_specific"
    assert broader[0]["reason"]["topic_relevance_scope"] == "broader_field_context"
