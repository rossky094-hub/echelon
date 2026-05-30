from __future__ import annotations

import sqlite3

import echelon.api.graph_visual_backend as graph_backend
from echelon.api.graph_visual_backend import (
    _build_rd_radar,
    _build_bottleneck_lineage,
    _build_branch_dossiers,
    _build_evidence_map,
    _build_history_main_path_contract,
    _build_topic_branch_splits,
    _build_topic_dossier,
    _build_topic_readiness_preflight,
    _content_access_payload,
    _evidence_contract_for_five_questions,
    _lineage_status,
    _section_evidence_contract,
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
    assert dossier["claim_scope"] == "candidate_pool_only"
    assert dossier["evidence_grade"] in {"metadata_only", "moderate_section"}
    assert dossier["uncertainty_reasons"]
    assert dossier["branch_splits"][0]["evidence_objects"][0]["paper_id"] == "p1"
    assert dossier["hard_bottlenecks"][0]["evidence_objects"]
    assert dossier["hard_bottlenecks"][0]["claim_scope"]
    assert dossier["hard_bottlenecks"][0]["evidence_grade"]
    assert dossier["hard_bottlenecks"][0]["uncertainty_reasons"]
    assert dossier["validation_directions"][0]["evidence_objects"]
    assert dossier["validation_directions"][0]["claim_scope"]
    assert dossier["validation_directions"][0]["evidence_grade"]
    assert dossier["validation_directions"][0]["uncertainty_reasons"]
    assert dossier["reading_path"]
    for item in dossier["reading_path"]:
        assert item["claim_scope"]
        assert item["evidence_grade"]
        assert item["uncertainty_reasons"]
        assert item["required_evidence"]
        assert item["evidence_objects"]
    assert dossier["insufficient_evidence"][0]["claim"] == "investable future direction"


def test_section_evidence_contract_exposes_extraction_provenance():
    explicit = _section_evidence_contract(
        "discussion",
        {"extraction_strategies": ["explicit_heading", "heading_continuation"]},
        [3, 4],
    )
    inline = _section_evidence_contract(
        "future_work",
        {"extraction_strategies": ["inline_heading"]},
        [7],
    )
    embedded = _section_evidence_contract(
        "conclusion",
        {"extraction_strategies": ["embedded_heading"]},
        [11],
    )
    loose = _section_evidence_contract(
        "conclusion",
        {"extraction_strategies": ["loose_inline_heading"]},
        [12],
    )
    legacy = _section_evidence_contract("abstract", {}, [])

    assert explicit["evidence_grade"] == "section_explicit_heading"
    assert explicit["claim_scope"] == "section_level_evidence"
    assert not explicit["uncertainty_reasons"]
    assert embedded["evidence_grade"] == "section_embedded_heading"
    assert embedded["claim_scope"] == "section_level_evidence_with_block_boundary_uncertainty"
    assert loose["evidence_grade"] == "section_loose_inline_heading"
    assert loose["claim_scope"] == "supporting_section_evidence_with_heading_uncertainty"
    assert inline["evidence_grade"] == "section_inline_heading"
    assert inline["claim_scope"] == "section_level_evidence_with_layout_uncertainty"
    assert "section boundary may be less reliable" in " ".join(inline["uncertainty_reasons"])
    assert legacy["evidence_grade"] == "section_legacy_unknown_strategy"
    assert legacy["claim_scope"] == "supporting_context_only"
    assert "strategy unavailable" in " ".join(legacy["uncertainty_reasons"])


def test_content_availability_summarizes_primary_section_provenance():
    sections = [
        {
            "section_name": "limitations",
            "extraction_strategies": ["explicit_heading"],
            "evidence_grade": "section_explicit_heading",
        },
        {
            "section_name": "discussion",
            "extraction_strategies": ["loose_inline_heading"],
            "evidence_grade": "section_loose_inline_heading",
        },
        {
            "section_name": "abstract",
            "extraction_strategies": ["parser_hint"],
            "evidence_grade": "section_parser_hint",
        },
    ]

    local_content, availability, _links, _policy = _content_access_payload(
        ids={},
        access={},
        sections=sections,
        limitations=[],
        claim_cards=[],
    )

    provenance = availability["primary_section_provenance"]
    assert availability["has_primary_evidence_sections"] is True
    assert availability["has_strong_or_moderate_primary_evidence_sections"] is True
    assert availability["primary_section_evidence_grade"] == "strong_or_moderate"
    assert provenance["strong"] == 1
    assert provenance["weak"] == 1
    assert provenance["total"] == 2
    assert local_content["primary_section_provenance"] == provenance


def test_topic_dossier_demotes_topline_when_evidence_is_missing():
    dossier = _build_topic_dossier(
        topic="unknown topic",
        hits=[],
        turning_hits=[],
        branch_dossiers=[],
        bottleneck_lineage={"top_unresolved_keywords": []},
        unresolved_limitations=[],
        rd_radar={"claim_cards_ready": False, "claim_cards": []},
        main_path_edges=[],
        future_growth=[],
        value_model={
            "fusion_status": "not_materialized",
            "frontfill_status": {
                "linked_ref_rate": 0.1,
                "primary_section_rate": 0.01,
                "openalex_w_rate": 0.5,
            },
        },
    )

    assert dossier["claim_scope"] == "insufficient_evidence"
    assert dossier["evidence_grade"] == "insufficient"
    assert "not yet have enough evidence-backed" in dossier["headline"]
    assert dossier["insufficient_evidence"]
    assert "linked refs below 30%" in " ".join(dossier["uncertainty_reasons"])


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
                    "calibration_status": "calibrated_with_run_audit",
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
    assert edge_items[0]["evidence_grade"] == "calibrated_candidate_generator"


def test_branch_lineage_status_distinguishes_layout_from_evidence():
    assert _lineage_status({"parent_citation_support": 2}, 0.2) == "layout_cluster_only"
    assert _lineage_status({"parent_citation_support": 5}, 0.2) == "weak_split_candidate"
    assert _lineage_status({"parent_citation_support": 12}, 0.35) == "evidence_backed_split"


def test_branch_dossiers_carry_evidence_contracts_for_lineage_status():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE visual_clusters (
            cluster_id TEXT PRIMARY KEY,
            branch_id TEXT,
            label TEXT,
            n_nodes INTEGER,
            year_start INTEGER,
            year_end INTEGER,
            top_terms_json TEXT,
            representative_papers_json TEXT,
            evidence_json TEXT
        );
        CREATE TABLE branch_lineages (
            branch_id TEXT PRIMARY KEY,
            parent_branch_id TEXT,
            split_year INTEGER,
            strength REAL,
            split_confidence REAL,
            split_evidence_json TEXT,
            why_json TEXT,
            future_json TEXT
        );
        CREATE TABLE visual_nodes (
            paper_id TEXT PRIMARY KEY,
            cluster_id TEXT,
            branch_id TEXT,
            x REAL,
            y REAL,
            z REAL,
            publication_year INTEGER,
            node_size REAL,
            color_hex TEXT,
            visual_role TEXT,
            uncertainty_score REAL,
            flags_json TEXT
        );
        CREATE TABLE visual_paper_details (
            paper_id TEXT PRIMARY KEY,
            ids_json TEXT,
            metadata_json TEXT,
            abstract TEXT,
            sections_json TEXT,
            limitations_json TEXT,
            recommendation_json TEXT,
            access_json TEXT,
            claim_cards_json TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO visual_clusters VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "C1",
            "B1",
            "metalens manufacturing",
            10,
            2018,
            2025,
            '["manufacturing","yield"]',
            '[{"paper_id":"p1"}]',
            "{}",
        ),
    )
    conn.execute(
        "INSERT INTO branch_lineages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "B1",
            "B0",
            2021,
            0.5,
            0.42,
            '{"parent_citation_support":12,"parent_support_ratio":0.42,"driver_papers":["p1"],"constraint_shift":{"status":"fabrication constraint shift","note":"wafer scale"}}',
            "{}",
            "{}",
        ),
    )
    conn.execute(
        "INSERT INTO visual_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("p1", "C1", "B1", 0, 0, 0, 2024, 1, "#fff", "driver", 0.1, "{}"),
    )
    conn.execute(
        "INSERT INTO visual_paper_details VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "p1",
            '{"doi":"10.1/example"}',
            '{"title":"Wafer scale metalens manufacturing","year":2024}',
            "abstract",
            '[{"section_name":"discussion","text":"manufacturing yield remains constrained","extraction_strategies":["explicit_heading"]}]',
            "[]",
            "{}",
            "{}",
            "[]",
        ),
    )

    dossiers = _build_branch_dossiers(conn, [{"cluster_id": "C1", "branch_id": "B1", "n": 10}])

    assert dossiers[0]["lineage_status"] == "evidence_backed_split"
    assert dossiers[0]["claim_scope"] == "evidence_backed_branch_split_candidate"
    assert dossiers[0]["evidence_grade"] == "section_backed_branch_split"
    assert dossiers[0]["required_evidence"]
    assert "uncertainty_reasons" in dossiers[0]
    assert dossiers[0]["evidence_objects"][0]["type"] == "branch_lineage"
    assert any(obj.get("type") == "paper" for obj in dossiers[0]["evidence_objects"])


def test_benchmark_topic_facets_are_not_metalens_template_reuse():
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
    assert topic_specific[0]["claim_scope"] == "topic_specific_turning_candidate"
    assert topic_specific[0]["evidence_grade"] == "metadata_turning_candidate"
    assert topic_specific[0]["uncertainty_reasons"]
    assert broader[0]["reason"]["topic_relevance_scope"] == "broader_field_context"
    assert broader[0]["claim_scope"] == "broader_context_not_topic_turning_paper"
    assert broader[0]["evidence_grade"] == "metadata_broader_context"


def test_evidence_map_layer_combinations_have_decision_contract(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE visual_edges (edge_type TEXT, layer TEXT, is_main_path INTEGER);
        CREATE TABLE future_directions (direction_id INTEGER);
        CREATE TABLE direction_claim_cards (claim_card_id TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO visual_edges VALUES (?, ?, ?)",
        [
            ("main_path", "citation", 1),
            ("citation", "citation", 0),
            ("future_growth", "future", 0),
        ],
    )
    monkeypatch.setattr(
        graph_backend,
        "_frontfill_status",
        lambda _conn=None: {
            "available": True,
            "linked_ref_rate": 0.12,
            "primary_section_rate": 0.02,
            "openalex_w_rate": 0.55,
        },
    )

    model = graph_backend._visual_value_model(conn)

    assert model["layer_combinations"]
    assert "fusion_value" in model["layers"]
    assert any("fusion_value" in combo["layers"] for combo in model["layer_combinations"])
    for combo in model["layer_combinations"]:
        assert combo["can_explain"]
        assert combo["cannot_explain"]
        assert combo["required_evidence"]
        assert combo["claim_scope"]
        assert combo["evidence_grade"]
        assert combo["uncertainty_reasons"]


def test_evidence_map_preserves_layer_combination_contract():
    value_model = {
        "layers": {
            "main_path": {"relationship": "main meaning"},
            "future": {"relationship": "future meaning"},
        },
        "layer_combinations": [
            {
                "layers": ["future", "bottleneck"],
                "label": "Bottleneck-driven future candidates",
                "question": "which future candidates are bottleneck-driven?",
                "decision_use": "candidate pool only",
                "relationship": "future plus bottleneck",
                "display": "purple plus red",
                "can_explain": ["candidate overlap with bottlenecks"],
                "cannot_explain": ["investment-ready direction"],
                "required_evidence": ["calibrated future", "section bottleneck"],
                "claim_scope": "candidate_pool_only",
                "evidence_grade": "calibrated_graph_plus_bottleneck_candidate",
                "uncertainty_reasons": ["no complete Claim Card"],
            }
        ],
    }

    evidence_map = _build_evidence_map(
        main_path_edges=[],
        turning_hits=[],
        future_growth=[],
        branch_dossiers=[],
        value_model=value_model,
    )
    combo = evidence_map["recommended_layer_combinations"][0]

    assert combo["claim_scope"] == "candidate_pool_only"
    assert combo["can_explain"] == ["candidate overlap with bottlenecks"]
    assert combo["cannot_explain"] == ["investment-ready direction"]
    assert combo["required_evidence"] == ["calibrated future", "section bottleneck"]


def test_history_main_path_contract_demotes_low_linked_refs():
    contract = _build_history_main_path_contract(
        main_path_edges=[
            {
                "edge_id": "main:p1:p2",
                "source_paper_id": "p1",
                "target_paper_id": "p2",
                "plain_language": "main path context",
            }
        ],
        key_turning_papers=[{"paper_id": "p1"}],
        broader_context_papers=[{"paper_id": "p3"}],
        value_model={
            "frontfill_status": {
                "linked_ref_rate": 0.12,
                "primary_section_rate": 0.02,
                "openalex_w_rate": 0.55,
            }
        },
    )

    assert contract["claim_scope"] == "main_path_context_low_linked_refs"
    assert contract["evidence_grade"] == "citation_backbone_partial_low_linked_refs"
    assert any("linked refs below 30%" in r for r in contract["uncertainty_reasons"])
    assert contract["required_evidence"]
    assert contract["evidence_objects"][0]["claim_scope"] == "main_path_context_low_linked_refs"


def test_first_principles_five_questions_carry_evidence_contracts():
    paper = {
        "paper_id": "p1",
        "title": "Metalens validation paper",
        "year": 2024,
        "content_availability": {"has_primary_evidence_sections": True},
        "reason": {"why": "main path turning paper"},
    }
    edge = {
        "edge_id": "future:p1:p2",
        "source_paper_id": "p1",
        "target_paper_id": "p2",
        "confidence": 0.8,
        "evidence": {
            "calibration_label": "calibrated_temporal_holdout",
            "calibrated_prob": 0.75,
            "calibration_status": "calibrated_with_run_audit",
        },
    }
    questions = [{"question": f"Q{i}", "answer": f"A{i}"} for i in range(1, 6)]

    wrapped = _evidence_contract_for_five_questions(
        questions,
        topic_dossier={
            "claim_scope": "candidate_pool_only",
            "evidence_grade": "metadata_only",
            "uncertainty_reasons": ["linked refs below target"],
            "branch_splits": [
                {
                    "evidence_objects": [
                        {
                            "type": "paper",
                            "paper_id": "p1",
                            "label": "driver",
                            "click_target": {"kind": "paper", "id": "p1"},
                        }
                    ]
                }
            ],
            "hard_bottlenecks": [
                {
                    "evidence_objects": [
                        {
                            "type": "limitation_atom",
                            "paper_id": "p1",
                            "label": "efficiency",
                        }
                    ]
                }
            ],
        },
        turning_hits=[paper],
        unresolved_limitations=[
            {
                "paper_id": "p1",
                "keyword": "efficiency",
                "description": "efficiency remains limited",
                "evidence_quality": "section_level",
            }
        ],
        future_growth=[edge],
        top_claim_card=None,
    )

    assert len(wrapped) == 5
    for item in wrapped:
        assert item["claim_scope"]
        assert item["evidence_grade"]
        assert item["uncertainty_reasons"]
        assert item["required_evidence"]
        assert item["evidence_objects"]
    assert wrapped[-1]["claim_scope"] == "candidate_pool_only"
    assert wrapped[-1]["evidence_grade"] == "calibrated_candidate_generator"


def test_first_principles_q5_uses_gap_evidence_when_future_candidates_are_absent():
    questions = [{"question": f"Q{i}", "answer": f"A{i}"} for i in range(1, 6)]
    wrapped = _evidence_contract_for_five_questions(
        questions,
        topic_dossier={
            "claim_scope": "candidate_pool_only",
            "evidence_grade": "metadata_only",
            "uncertainty_reasons": ["linked refs below target"],
            "branch_splits": [
                {
                    "evidence_objects": [
                        {
                            "type": "paper",
                            "paper_id": "driver-1",
                            "label": "driver",
                            "click_target": {"kind": "paper", "id": "driver-1"},
                        }
                    ]
                }
            ],
            "hard_bottlenecks": [
                {
                    "evidence_objects": [
                        {
                            "type": "limitation_atom",
                            "paper_id": "bottleneck-1",
                            "label": "efficiency",
                            "click_target": {"kind": "paper", "id": "bottleneck-1"},
                        }
                    ]
                }
            ],
        },
        turning_hits=[],
        unresolved_limitations=[],
        future_growth=[],
        top_claim_card=None,
    )

    assert wrapped[-1]["evidence_grade"] == "future_candidate_generation_gap"
    assert wrapped[-1]["evidence_objects"]
    assert "no calibrated future candidate matched" in " ".join(wrapped[-1]["uncertainty_reasons"])


def test_bottleneck_lineage_constraints_are_auditable_typed_chains():
    lineage = _build_bottleneck_lineage(
        principles=[
            {
                "principle_id": "FP_MANUFACTURING",
                "principle_name": "Manufacturing scalability",
                "root_cause": "Large-area metalens fabrication loses uniformity.",
                "risk_label": "high",
                "bottleneck_score": 0.9,
                "unresolved_atoms": 3,
                "resolved_atoms": 1,
                "current_backlog": 2.0,
                "peak_backlog_year": 2024,
                "top_keywords_json": '[{"key":"scalability"},{"key":"uniformity"}]',
            }
        ],
        history_events=[
            {
                "principle_id": "FP_MANUFACTURING",
                "event_year": 2024,
                "opened_atoms": 2,
                "resolved_atoms": 1,
            }
        ],
        unresolved_limitations=[
            {
                "paper_id": "p1",
                "keyword": "scalability",
                "description": "scalability remains limited",
                "evidence_quality": "section_level",
                "source_section_name": "discussion",
            }
        ],
        lineage_triples=[
            {
                "triple_id": "t1",
                "principle_id": "FP_MANUFACTURING",
                "edge_order": 1,
                "source_stage": "constraint",
                "target_stage": "failure_mechanism",
                "source_text": "large area",
                "target_text": "uniformity drops",
                "relation_type": "constraint_causes_failure",
                "paper_id": "p1",
                "event_year": 2024,
                "evidence_section": "discussion",
                "evidence_quality": "section_level",
                "evidence_weight": 0.75,
            }
        ],
    )

    constraint = lineage["constraints"][0]
    assert constraint["claim_scope"] == "bottleneck_lineage_evidence"
    assert constraint["evidence_grade"] == "typed_section_lineage"
    assert constraint["typed_chain"][0]["source_stage"] == "constraint"
    assert constraint["required_evidence"]
    assert constraint["evidence_objects"][0]["type"] == "bottleneck_lineage_triple"
    assert constraint["evidence_objects"][0]["click_target"] == {"kind": "paper", "id": "p1"}


def test_topic_lens_readiness_preflight_is_arbitrary_topic_contract():
    readiness = _build_topic_readiness_preflight(
        topic="custom photonics topic",
        topic_dossier={
            "claim_scope": "candidate_pool_only",
            "evidence_grade": "metadata_only",
            "uncertainty_reasons": ["fixture"],
            "branch_splits": [{"name": "Custom branch"}],
            "hard_bottlenecks": [{"name": "integration"}],
            "reading_path": [
                {
                    "claim_scope": "candidate_pool_only",
                    "evidence_grade": "section_backed",
                    "evidence_objects": [{"type": "paper", "paper_id": f"r{i}"}],
                }
                for i in range(4)
            ],
        },
        turning_hits=[
            {
                "paper_id": "p1",
                "access_links": [{"url": "https://example.test"}],
                "content_availability": {
                    "has_primary_evidence_sections": True,
                    "has_strong_or_moderate_primary_evidence_sections": False,
                },
            }
        ],
        future_growth=[{"edge_id": "future:p1:p2"}],
        rd_radar={
            "claim_cards": [
                {
                    "eligible": False,
                    "claim_card": {
                        "five_question_complete": True,
                    },
                }
            ]
        },
        first_principles_questions=[
            {
                "claim_scope": "candidate_pool_only",
                "evidence_grade": "section_backed",
                "uncertainty_reasons": ["fixture"],
                "evidence_objects": [{"type": "paper", "paper_id": f"q{i}"}],
            }
            for i in range(5)
        ],
        bottleneck_lineage={
            "constraints": [
                {
                    "claim_scope": "bottleneck_lineage_evidence",
                    "evidence_grade": "typed_section_lineage",
                    "typed_chain": [{"source_stage": "constraint", "target_stage": "failure"}],
                    "evidence_objects": [{"type": "bottleneck_lineage_triple"}],
                }
            ]
        },
    )

    assert readiness["audit_type"] == "deterministic_topic_readiness_preflight"
    assert "no_llm_required" in readiness["llm_policy"]
    assert readiness["readiness_level"] == "claim_card_available_with_gaps"
    assert readiness["overall_status"] == "warn"
    gate_by_name = {gate["name"]: gate for gate in readiness["gates"]}
    assert gate_by_name["turning papers with strong/moderate section provenance"]["status"] == "warn"
    assert readiness["metrics"]["complete_claim_cards"] == 1
