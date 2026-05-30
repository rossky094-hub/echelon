import json
import sqlite3

from echelon.v14b.evidence_contracts import SECTION_PARSER_CONTRACT_VERSION


def test_classify_principle_detects_physical_constraint():
    from echelon.v14b.step13_first_principles_history import classify_principle

    text = "fabrication tolerance and thermal loss limit optical coupling efficiency"
    p = classify_principle(text)
    assert p.principle_id == "FP_PHYSICAL_CONSTRAINT"


def test_step13_builds_first_principles_outputs(tmp_path):
    from echelon.v14b.db_schema import init_v14b_db
    from echelon.v14b.step13_first_principles_history import run_first_principles_history

    db_main = tmp_path / "main.sqlite3"
    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    conn_main.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            abstract TEXT,
            publication_year INTEGER,
            primary_field_id TEXT
        );
        CREATE TABLE paper_sections (
            paper_id TEXT NOT NULL,
            section_name TEXT NOT NULL,
            section_text TEXT NOT NULL,
            source_type TEXT,
            parser_name TEXT,
            source_url TEXT,
            section_pages_json TEXT,
            section_meta_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (paper_id, section_name)
        );
        INSERT INTO papers VALUES
            ('p1', 'Fabrication-limited metasurface', 'thermal loss and fabrication tolerance remain key bottlenecks', 2020, 'F1'),
            ('p2', 'Sim2real policy transfer', 'domain shift remains a major generalization challenge', 2021, 'F2'),
            ('p3', 'Non-convex inverse design', 'gradient instability under non-convex optimization', 2022, 'F1'),
            ('p4', 'Scalable photonic integration', 'integration and latency constraints in deployment', 2024, 'F1');
        INSERT INTO paper_sections
            (paper_id, section_name, section_text, section_pages_json, section_meta_json)
        VALUES
            ('p1', 'limitations', 'fabrication tolerance and thermal loss remain unresolved', '[4,5]', '{"n_pages":2,"extraction_strategies":["explicit_heading"]}'),
            ('p2', 'discussion', 'domain shift failures remain under distribution shift', '[6]', '{"n_pages":1,"extraction_strategies":["embedded_heading"]}');
        """
    )
    conn_main.close()

    db_v14 = tmp_path / "v14.sqlite3"
    conn_v14 = init_v14b_db(db_v14)
    conn_v14.executescript(
        """
        INSERT INTO limitation_atoms
            (paper_id, description, keyword, severity, evidence_source, evidence_quality, evidence_weight, source_section_name, extractor_method)
        VALUES
            ('p1', 'Fabrication tolerance and thermal loss reduce efficiency.', 'fabrication', 'high', 'structured_sections', 'section_level', 0.80, 'limitations', 'heuristic'),
            ('p2', 'Domain shift causes sim-to-real failures.', 'domain shift', 'high', 'structured_sections', 'section_level', 0.75, 'discussion', 'heuristic'),
            ('p3', 'Non-convex optimization leads to unstable gradients.', 'non-convex', 'medium', 'abstract', 'weak_abstract', 0.35, '', 'heuristic');

        INSERT INTO limitation_resolutions
            (atom_id, resolver_paper_id, resolution_year, confidence, evidence_text)
        VALUES
            (2, 'p4', 2024, 0.92, 'Mitigates domain shift with adaptation.');

        INSERT INTO predicted_future_edges
            (src_paper_id, dst_paper_id, predicted_prob, raw_predicted_prob, calibrated_prob, prediction_confidence, calibration_label, src_year, dst_year, is_cross_field)
        VALUES
            ('p1', 'p4', 0.82, 0.87, 0.79, 0.78, 'calibrated_temporal_holdout', 2020, 2024, 0),
            ('p3', 'p4', 0.76, 0.80, 0.74, 0.72, 'calibrated_temporal_holdout', 2022, 2024, 1);

        INSERT INTO future_directions
            (direction_name, confidence, expected_period, main_path_evidence, vgae_evidence, limitation_evidence, paper_ids_json, evidence_paths, evidence_tier, claim_scope, calibration_label, evidence_json)
        VALUES
            ('Sim2Real Robust Transfer', 0.62, '2026-2029', 'main path', 'vgae', 'domain shift unresolved', '["p2","p4"]', 2, 'exploratory_weak_limitation', 'exploratory_hypothesis', 'calibrated_temporal_holdout', '{}');
        """
    )
    conn_v14.commit()
    conn_v14.close()

    out_dir = tmp_path / "reports"
    result = run_first_principles_history(db_main=db_main, db_v14=db_v14, out_dir=out_dir)

    assert result["principles"] >= 2
    assert (out_dir / "第一性原理_卡点历史脉络报告.md").exists()
    assert (out_dir / "first_principles_bottleneck_history.json").exists()

    conn_v14 = sqlite3.connect(str(db_v14))
    rows = conn_v14.execute(
        "SELECT principle_id, unresolved_atoms, resolved_atoms FROM first_principles_principles"
    ).fetchall()
    lineage_n = conn_v14.execute(
        "SELECT COUNT(*) FROM bottleneck_lineage_triples"
    ).fetchone()[0]
    claim_rows = conn_v14.execute(
        "SELECT COUNT(*), SUM(five_question_complete), SUM(high_confidence_eligible) FROM direction_claim_cards"
    ).fetchone()
    future_gate = conn_v14.execute(
        "SELECT claim_card_complete, high_confidence_eligible, claim_scope, quality_gate_json FROM future_directions LIMIT 1"
    ).fetchone()
    conn_v14.close()
    assert rows
    assert any((r[1] or 0) > 0 for r in rows)
    assert lineage_n > 0
    assert claim_rows[0] >= 1
    assert future_gate is not None
    gate = json.loads(future_gate[3])
    assert future_gate[0] == 0
    assert future_gate[1] == 0
    assert future_gate[2] == "exploratory_incomplete_card"
    assert "unresolved bottleneck evidence" in gate["missing_gates"]
    assert "future-growth calibration available" in gate["missing_high_confidence_gates"]


def test_step13_complete_exploratory_card_is_not_high_confidence():
    from echelon.v14b.step13_first_principles_history import build_direction_claim_cards

    atoms = [
        {
            "paper_id": "p1",
            "paper_title": "Wafer-scale metalens manufacturing",
            "publication_year": 2024,
            "description": "Fabrication tolerance still limits broadband imaging quality.",
            "keyword": "fabrication",
            "severity": "high",
            "evidence_quality": "section_level",
            "evidence_weight": 0.9,
            "is_resolved": 0,
        }
    ]
    future_directions = [
        {
            "direction_id": 1,
            "direction_name": "Wafer-scale broadband metalens manufacturing",
            "paper_ids_json": '["p1"]',
            "confidence": 0.82,
            "evidence_tier": "exploratory",
            "calibration_label": "calibrated_temporal_holdout",
        }
    ]
    principles = [
        {
            "principle_id": "FP_PHYSICAL_CONSTRAINT",
            "principle_name": "物理实现与制造约束",
            "root_cause": "fabrication tolerance and material loss",
        }
    ]
    calibration = {"method": "temporal_platt_logistic", "avg_calibrated_auc": 0.84}

    cards, updates = build_direction_claim_cards(
        atoms=atoms,
        future_directions=future_directions,
        principle_rows=principles,
        calibration_audit=calibration,
    )

    assert len(cards) == 1
    gate = json.loads(cards[0]["quality_gate_json"])
    enablers = json.loads(cards[0]["enabling_conditions_json"])
    assert cards[0]["five_question_complete"] == 1
    assert cards[0]["high_confidence_eligible"] == 0
    assert cards[0]["claim_scope"] == "exploratory_with_claim_card"
    experiment = json.loads(cards[0]["minimal_validation_experiment_json"])
    assert experiment["success_criteria"]
    assert experiment["falsification_conditions"]
    assert gate["candidate_score"] == 0.82
    assert "direction_confidence" not in gate
    assert gate["high_confidence_gates"]["candidate_score_ready"] is True
    assert "direction_confidence_ready" not in gate["high_confidence_gates"]
    assert enablers["candidate_score"] == 0.82
    assert "prediction_confidence" not in enablers
    assert any("future candidate score" in s for s in enablers["new_enablers"])
    assert "triangulated Step6 fusion evidence" in gate["missing_high_confidence_gates"]
    assert updates[0]["high_confidence_eligible"] == 0


def test_step13_weak_section_provenance_blocks_high_confidence():
    from echelon.v14b.step13_first_principles_history import build_direction_claim_cards

    atoms = [
        {
            "paper_id": "p1",
            "paper_title": "Weakly parsed metalens bottleneck",
            "publication_year": 2024,
            "description": "Fabrication tolerance still limits broadband imaging quality.",
            "keyword": "fabrication",
            "severity": "high",
            "evidence_quality": "section_level",
            "section_provenance_strength": "weak",
            "section_extraction_strategies": ["loose_inline_heading"],
            "evidence_weight": 0.9,
            "is_resolved": 0,
        }
    ]
    future_directions = [
        {
            "direction_id": 1,
            "direction_name": "Wafer-scale broadband metalens manufacturing",
            "paper_ids_json": '["p1"]',
            "confidence": 0.86,
            "evidence_tier": "triangulated_strong",
            "calibration_label": "calibrated_temporal_holdout",
        }
    ]
    principles = [
        {
            "principle_id": "FP_PHYSICAL_CONSTRAINT",
            "principle_name": "物理实现与制造约束",
            "root_cause": "fabrication tolerance and material loss",
        }
    ]
    calibration = {"method": "temporal_platt_logistic", "avg_calibrated_auc": 0.84}

    cards, updates = build_direction_claim_cards(
        atoms=atoms,
        future_directions=future_directions,
        principle_rows=principles,
        calibration_audit=calibration,
    )

    gate = json.loads(cards[0]["quality_gate_json"])
    unresolved = json.loads(cards[0]["unresolved_bottleneck_json"])
    assert cards[0]["five_question_complete"] == 1
    assert cards[0]["high_confidence_eligible"] == 0
    assert cards[0]["evidence_strength_level"] == "weak"
    assert gate["section_provenance"]["weak"] == 1
    assert gate["candidate_score"] == 0.86
    assert gate["high_confidence_gates"]["candidate_score_ready"] is True
    assert "direction_confidence_ready" not in gate["high_confidence_gates"]
    assert gate["high_confidence_gates"]["section_provenance_ready"] is False
    assert gate["high_confidence_gates"]["section_decision_grade_ready"] is False
    assert "strong section-level evidence" in gate["missing_high_confidence_gates"]
    assert "strong or moderate section parser provenance" in gate["missing_high_confidence_gates"]
    assert "current parser-contract decision-grade section evidence" in gate["missing_high_confidence_gates"]
    assert unresolved["section_provenance"]["strategies"]["loose_inline_heading"] == 1
    assert updates[0]["high_confidence_eligible"] == 0


def test_step13_stale_strong_sections_block_high_confidence():
    from echelon.v14b.step13_first_principles_history import build_direction_claim_cards

    atoms = [
        {
            "paper_id": f"p{i}",
            "paper_title": f"Legacy parsed bottleneck {i}",
            "publication_year": 2024,
            "description": "Fabrication tolerance still limits broadband imaging quality.",
            "keyword": "fabrication",
            "severity": "high",
            "evidence_quality": "section_level",
            "section_provenance_strength": "strong",
            "section_extraction_strategies": ["explicit_heading"],
            "section_parser_contract_version": "legacy_unknown_contract",
            "evidence_weight": 0.9,
            "is_resolved": 0,
        }
        for i in range(1, 4)
    ]
    future_directions = [
        {
            "direction_id": 1,
            "direction_name": "Wafer-scale broadband metalens manufacturing",
            "paper_ids_json": '["p1","p2","p3"]',
            "confidence": 0.86,
            "evidence_tier": "triangulated_strong",
            "calibration_label": "calibrated_temporal_holdout",
        }
    ]
    principles = [
        {
            "principle_id": "FP_PHYSICAL_CONSTRAINT",
            "principle_name": "物理实现与制造约束",
            "root_cause": "fabrication tolerance and material loss",
        }
    ]

    cards, updates = build_direction_claim_cards(
        atoms=atoms,
        future_directions=future_directions,
        principle_rows=principles,
        calibration_audit={"method": "temporal_platt_logistic", "avg_calibrated_auc": 0.84},
    )

    gate = json.loads(cards[0]["quality_gate_json"])
    enablers = json.loads(cards[0]["enabling_conditions_json"])
    assert cards[0]["five_question_complete"] == 1
    assert cards[0]["evidence_strength_level"] == "strong"
    assert cards[0]["high_confidence_eligible"] == 0
    assert gate["high_confidence_gates"]["section_evidence_strong"] is True
    assert gate["high_confidence_gates"]["section_provenance_ready"] is True
    assert gate["high_confidence_gates"]["section_decision_grade_ready"] is False
    assert gate["section_provenance"]["decision_grade"] == 0
    assert gate["section_provenance"]["contract_versions"]["legacy_unknown_contract"] == 3
    assert "current parser-contract decision-grade section evidence" in gate["missing_high_confidence_gates"]
    assert any("current parser-contract decision-grade" in s for s in enablers["missing_enablers"])
    assert updates[0]["high_confidence_eligible"] == 0


def test_step13_current_contract_decision_grade_sections_can_be_high_confidence():
    from echelon.v14b.step13_first_principles_history import build_direction_claim_cards

    atoms = [
        {
            "paper_id": f"p{i}",
            "paper_title": f"Current parsed bottleneck {i}",
            "publication_year": 2024,
            "description": "Fabrication tolerance still limits broadband imaging quality.",
            "keyword": "fabrication",
            "severity": "high",
            "evidence_quality": "section_level",
            "section_provenance_strength": "strong",
            "section_extraction_strategies": ["explicit_heading"],
            "section_parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
            "section_decision_grade": True,
            "evidence_weight": 0.9,
            "is_resolved": 0,
        }
        for i in range(1, 4)
    ]
    future_directions = [
        {
            "direction_id": 1,
            "direction_name": "Wafer-scale broadband metalens manufacturing",
            "paper_ids_json": '["p1","p2","p3"]',
            "confidence": 0.86,
            "evidence_tier": "triangulated_strong",
            "calibration_label": "calibrated_temporal_holdout",
        }
    ]
    principles = [
        {
            "principle_id": "FP_PHYSICAL_CONSTRAINT",
            "principle_name": "物理实现与制造约束",
            "root_cause": "fabrication tolerance and material loss",
        }
    ]

    cards, updates = build_direction_claim_cards(
        atoms=atoms,
        future_directions=future_directions,
        principle_rows=principles,
        calibration_audit={"method": "temporal_platt_logistic", "avg_calibrated_auc": 0.84},
    )

    gate = json.loads(cards[0]["quality_gate_json"])
    unresolved = json.loads(cards[0]["unresolved_bottleneck_json"])
    assert cards[0]["five_question_complete"] == 1
    assert cards[0]["high_confidence_eligible"] == 1
    assert cards[0]["claim_scope"] == "validated_candidate"
    assert gate["high_confidence_gates"]["section_decision_grade_ready"] is True
    assert gate["section_provenance"]["decision_grade"] == 3
    assert unresolved["section_provenance"]["current_contract"] == 3
    assert updates[0]["high_confidence_eligible"] == 1
