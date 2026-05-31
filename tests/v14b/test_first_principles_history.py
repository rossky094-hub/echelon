import json
import sqlite3

from echelon.v14b.evidence_contracts import SECTION_PARSER_CONTRACT_VERSION


def test_classify_principle_detects_physical_constraint():
    from echelon.v14b.step13_first_principles_history import classify_principle

    text = "fabrication tolerance and thermal loss limit optical coupling efficiency"
    p = classify_principle(text)
    assert p.principle_id == "FP_PHYSICAL_CONSTRAINT"


def test_step13_load_atoms_rejects_aggregate_section_provenance(tmp_path):
    from echelon.v14b.db_schema import init_v14b_db
    from echelon.v14b.step13_first_principles_history import load_atoms

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
            section_meta_json TEXT
        );
        INSERT INTO papers VALUES ('p1', 'Paper', 'Abstract', 2024, 'F1');
        """
    )
    conn_main.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?)",
        (
            "p1",
            "discussion",
            "current contract limitation evidence " * 12,
            json.dumps(
                {
                    "extraction_strategies": ["explicit_heading"],
                    "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
                }
            ),
        ),
    )
    conn_main.commit()

    db_v14 = tmp_path / "v14.sqlite3"
    conn_v14 = init_v14b_db(db_v14)
    conn_v14.execute(
        """
        INSERT INTO limitation_atoms
            (paper_id, description, keyword, severity, evidence_source,
             evidence_quality, evidence_weight, source_section_name, extractor_method)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "p1",
            "Fabrication remains limited.",
            "fabrication",
            "high",
            "structured_sections",
            "section_level",
            0.9,
            "discussion,method",
            "heuristic",
        ),
    )
    conn_v14.commit()

    atoms = load_atoms(conn_main, conn_v14)
    conn_main.close()
    conn_v14.close()

    assert atoms
    assert atoms[0]["section_parser_contract_version"] == "legacy_unknown_contract"
    assert atoms[0]["section_decision_grade"] is False


def test_step13_load_atoms_accepts_section_atom_bridge_provenance(tmp_path):
    from echelon.v14b.db_schema import init_v14b_db
    from echelon.v14b.step13_first_principles_history import load_atoms

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
        INSERT INTO papers VALUES ('p1', 'Paper', 'Abstract', 2024, 'F1');
        """
    )
    conn_main.commit()

    db_v14 = tmp_path / "v14.sqlite3"
    conn_v14 = init_v14b_db(db_v14)
    conn_v14.execute(
        """
        INSERT INTO limitation_atoms
            (paper_id, description, keyword, severity, evidence_source,
             evidence_quality, evidence_weight, source_section_name, extractor_method,
             source_section_atom_id, source_section_atom_type,
             source_section_atom_evidence_grade, source_storage_uri,
             source_page_start, source_page_end, source_parser_contract_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "p1",
            "Fabrication remains limited.",
            "fabrication",
            "high",
            "section_atoms",
            "section_level",
            0.9,
            "discussion",
            "section_atom_bridge",
            "sa1",
            "constraint",
            "section_atom_decision_grade",
            "/Volumes/LaCie/Echelon_Paper_Raw_Data/pdfs/p1.pdf",
            4,
            5,
            SECTION_PARSER_CONTRACT_VERSION,
        ),
    )
    conn_v14.commit()

    atoms = load_atoms(conn_main, conn_v14)
    conn_main.close()
    conn_v14.close()

    assert atoms
    assert atoms[0]["section_provenance_strength"] == "strong"
    assert atoms[0]["section_parser_contract_version"] == SECTION_PARSER_CONTRACT_VERSION
    assert atoms[0]["section_decision_grade"] is True
    assert "section_atom_bridge" in atoms[0]["section_extraction_strategies"]
    assert atoms[0]["source_section_atom_id"] == "sa1"


def test_bottleneck_lineage_triples_mark_missing_stages():
    from echelon.v14b.step13_first_principles_history import (
        HEURISTIC_RESOLUTION_EVIDENCE_TEXT,
        build_bottleneck_lineage_triples,
    )

    triples = build_bottleneck_lineage_triples(
        atoms=[
            {
                "atom_id": 1,
                "paper_id": "p1",
                "paper_title": "Paper",
                "publication_year": 2024,
                "description": "Fabrication tolerance still limits broadband imaging quality.",
                "keyword": "fabrication",
                "severity": "high",
                "evidence_quality": "section_level",
                "evidence_weight": 0.9,
                "source_section_name": "discussion",
            }
        ],
        resolution_rows=[
            {
                "atom_id": 1,
                "resolver_paper_id": "p2",
                "resolution_year": 2025,
                "confidence": 0.65,
                "evidence_text": HEURISTIC_RESOLUTION_EVIDENCE_TEXT,
            }
        ],
        section_pages={},
        future_directions=[],
    )

    assert len(triples) == 4
    metadata = json.loads(triples[1]["metadata_json"])
    assert metadata["typed_chain_complete"] is False
    assert metadata["typed_chain_completeness"] == "resolution_candidate_partial"
    assert metadata["n_resolutions"] == 1
    assert metadata["n_validated_resolutions"] == 0
    assert "attempt_path" not in metadata["placeholder_stages"]
    assert "local_fix" in metadata["placeholder_stages"]
    assert triples[1]["target_text"].startswith("candidate_resolver:")
    assert triples[2]["target_text"].startswith("missing evidence:")


def test_bottleneck_lineage_triples_can_be_full_with_validated_fix_and_follow_on_constraint():
    from echelon.v14b.step13_first_principles_history import build_bottleneck_lineage_triples

    triples = build_bottleneck_lineage_triples(
        atoms=[
            {
                "atom_id": 1,
                "paper_id": "p1",
                "paper_title": "Paper",
                "publication_year": 2021,
                "description": "Fabrication tolerance still limits broadband imaging quality.",
                "keyword": "fabrication",
                "severity": "high",
                "evidence_quality": "section_level",
                "evidence_weight": 0.9,
                "source_section_name": "discussion",
            },
            {
                "atom_id": 2,
                "paper_id": "p3",
                "paper_title": "Follow-on paper",
                "publication_year": 2024,
                "description": "Packaging drift becomes the new fabrication constraint.",
                "keyword": "fabrication",
                "severity": "medium",
                "evidence_quality": "section_level",
                "evidence_weight": 0.8,
                "source_section_name": "discussion",
            },
        ],
        resolution_rows=[
            {
                "atom_id": 1,
                "resolver_paper_id": "p2",
                "resolution_year": 2023,
                "confidence": 0.9,
                "evidence_text": "Measured mitigation improves fabrication tolerance and reduces imaging loss.",
            }
        ],
        section_pages={},
        future_directions=[],
    )

    first_atom_triples = [t for t in triples if t["atom_id"] == 1]
    assert len(first_atom_triples) == 4
    metadata = json.loads(first_atom_triples[0]["metadata_json"])
    assert metadata["typed_chain_complete"] is True
    assert metadata["typed_chain_completeness"] == "full"
    assert metadata["placeholder_stages"] == []
    assert first_atom_triples[2]["target_text"].startswith("Measured mitigation")


def test_bottleneck_lineage_triples_consume_section_atom_chains_as_full_evidence():
    from echelon.v14b.step13_first_principles_history import build_bottleneck_lineage_triples

    chain = {
        "chain_id": "sac1",
        "paper_id": "p1",
        "paper_title": "Wafer-scale fabrication paper",
        "publication_year": 2024,
        "section_name": "discussion",
        "section_key": "discussion",
        "constraint_atom_id": "sa1",
        "failure_mechanism_atom_id": "sa2",
        "attempted_path_atom_id": "sa3",
        "local_fix_atom_id": "sa4",
        "new_constraint_atom_id": "sa5",
        "constraint_text": "Fabrication tolerance is the root physical constraint.",
        "failure_mechanism_text": "Overlay mismatch creates phase loss.",
        "attempted_path_text": "The authors attempted calibration and inverse design.",
        "local_fix_text": "Calibration mitigates mismatch in the prototype.",
        "new_constraint_text": "Packaging drift remains as a new constraint.",
        "typed_chain_complete": 1,
        "typed_chain_completeness": "full",
        "missing_stages": [],
        "evidence_grade": "typed_section_lineage",
        "claim_scope": "bottleneck_lineage_evidence",
        "uncertainty_reasons": ["chain is evidence context only until Step13 Claim Card promotion"],
        "evidence_objects": [
            {
                "type": "section_atom",
                "role": "constraint",
                "atom_id": "sa1",
                "paper_id": "p1",
                "page_start": 4,
                "page_end": 5,
            }
        ],
    }

    triples = build_bottleneck_lineage_triples(
        atoms=[],
        resolution_rows=[],
        section_pages={},
        future_directions=[{"direction_id": 7, "direction_name": "wafer scale fabrication", "paper_ids_json": '["p1"]'}],
        section_atom_chains=[chain],
    )

    assert len(triples) == 4
    assert [t["source_stage"] for t in triples] == ["constraint", "failure_mechanism", "attempt_path", "local_fix"]
    assert triples[1]["target_stage"] == "attempt_path"
    assert triples[0]["direction_id"] == 7
    assert triples[0]["evidence_page"] == 4
    metadata = json.loads(triples[0]["metadata_json"])
    assert metadata["source"] == "section_atom_chain"
    assert metadata["section_atom_chain_id"] == "sac1"
    assert metadata["typed_chain_complete"] is True
    assert metadata["typed_chain_completeness"] == "full"
    assert metadata["evidence_grade"] == "typed_section_lineage"
    assert metadata["placeholder_stages"] == []
    assert metadata["section_atom_ids"]["attempt_path"] == "sa3"
    assert metadata["evidence_objects"][0]["atom_id"] == "sa1"


def test_bottleneck_lineage_triples_keep_partial_section_atom_chains_exploratory():
    from echelon.v14b.step13_first_principles_history import build_bottleneck_lineage_triples

    triples = build_bottleneck_lineage_triples(
        atoms=[],
        resolution_rows=[],
        section_pages={},
        future_directions=[],
        section_atom_chains=[
            {
                "chain_id": "sac_partial",
                "paper_id": "p2",
                "publication_year": 2025,
                "section_name": "results",
                "constraint_atom_id": "sa10",
                "failure_mechanism_atom_id": "sa11",
                "attempted_path_atom_id": "sa12",
                "constraint_text": "Efficiency remains limited.",
                "failure_mechanism_text": "Coupling loss dominates.",
                "attempted_path_text": "A grating coupler was attempted.",
                "typed_chain_complete": 0,
                "typed_chain_completeness": "attempted_path_partial",
                "missing_stages": ["local_fix", "new_constraint"],
                "evidence_grade": "partial_typed_section_lineage",
                "claim_scope": "exploratory_bottleneck_lineage",
                "uncertainty_reasons": ["typed lineage is partial"],
                "evidence_objects": [],
            }
        ],
    )

    assert len(triples) == 4
    assert triples[2]["target_text"].startswith("missing evidence: no local_fix")
    metadata = json.loads(triples[2]["metadata_json"])
    assert metadata["source"] == "section_atom_chain"
    assert metadata["typed_chain_complete"] is False
    assert metadata["typed_chain_completeness"] == "attempted_path_partial"
    assert metadata["target_stage_is_placeholder"] is True
    assert "local_fix" in metadata["placeholder_stages"]
    assert metadata["claim_scope"] == "exploratory_bottleneck_lineage"


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
        CREATE TABLE section_atom_chains (
            chain_id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            section_name TEXT NOT NULL,
            section_key TEXT NOT NULL,
            chain_index INTEGER NOT NULL,
            constraint_atom_id TEXT,
            failure_mechanism_atom_id TEXT,
            attempted_path_atom_id TEXT,
            local_fix_atom_id TEXT,
            new_constraint_atom_id TEXT,
            constraint_text TEXT,
            failure_mechanism_text TEXT,
            attempted_path_text TEXT,
            local_fix_text TEXT,
            new_constraint_text TEXT,
            relation_edges_json TEXT NOT NULL,
            typed_chain_complete INTEGER NOT NULL,
            typed_chain_completeness TEXT NOT NULL,
            missing_stages_json TEXT NOT NULL,
            evidence_grade TEXT NOT NULL,
            claim_scope TEXT NOT NULL,
            uncertainty_reasons_json TEXT NOT NULL,
            evidence_objects_json TEXT NOT NULL,
            created_at TEXT NOT NULL
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
    conn_main.execute(
        """
        INSERT INTO section_atom_chains VALUES (
            'sac1', 'p1', 'limitations', 'limitations', 0,
            'sa1', 'sa2', 'sa3', 'sa4', 'sa5',
            'fabrication tolerance is the physical constraint',
            'thermal loss reduces efficiency',
            'inverse design was attempted',
            'calibration mitigates part of the loss',
            'packaging drift remains unresolved',
            '[]', 1, 'full', '[]', 'typed_section_lineage',
            'bottleneck_lineage_evidence',
            '["chain is evidence context only"]',
            '[{"type":"section_atom","role":"constraint","atom_id":"sa1","paper_id":"p1","page_start":4,"page_end":5}]',
            '2026-05-31T00:00:00Z'
        )
        """
    )
    conn_main.commit()
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
    chain_lineage = conn_v14.execute(
        "SELECT metadata_json FROM bottleneck_lineage_triples WHERE triple_id LIKE 'chain:%' LIMIT 1"
    ).fetchone()
    claim_contract = conn_v14.execute(
        """
        SELECT evidence_grade, claim_scope, uncertainty_reasons_json, evidence_objects_json
        FROM direction_claim_cards
        LIMIT 1
        """
    ).fetchone()
    future_gate = conn_v14.execute(
        "SELECT claim_card_complete, high_confidence_eligible, claim_scope, quality_gate_json FROM future_directions LIMIT 1"
    ).fetchone()
    conn_v14.close()
    assert rows
    assert any((r[1] or 0) > 0 for r in rows)
    assert lineage_n > 0
    assert chain_lineage is not None
    assert json.loads(chain_lineage[0])["source"] == "section_atom_chain"
    assert claim_rows[0] >= 1
    assert claim_contract is not None
    assert claim_contract[0]
    assert claim_contract[1]
    assert isinstance(json.loads(claim_contract[2]), list)
    assert json.loads(claim_contract[3])
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
    assert cards[0]["evidence_grade"] == "complete_claim_card_pending_high_confidence_evidence"
    assert any(
        "high-confidence" in reason
        for reason in json.loads(cards[0]["uncertainty_reasons_json"])
    )
    assert any(
        obj["type"] == "minimal_validation_experiment"
        for obj in json.loads(cards[0]["evidence_objects_json"])
    )
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
    assert cards[0]["evidence_grade"] == "complete_claim_card_pending_high_confidence_evidence"
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
    assert cards[0]["evidence_grade"] == "complete_claim_card_pending_high_confidence_evidence"
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
    assert cards[0]["evidence_grade"] == "decision_grade_claim_card"
    assert json.loads(cards[0]["uncertainty_reasons_json"]) == []
    assert any(
        obj["type"] == "claim_card_unresolved_bottleneck"
        for obj in json.loads(cards[0]["evidence_objects_json"])
    )
    assert gate["high_confidence_gates"]["section_decision_grade_ready"] is True
    assert gate["section_provenance"]["decision_grade"] == 3
    assert unresolved["section_provenance"]["current_contract"] == 3
    assert updates[0]["high_confidence_eligible"] == 1


def test_step13_claim_cards_consume_full_section_atom_chains_as_five_question_evidence():
    from echelon.v14b.step13_first_principles_history import build_direction_claim_cards

    chain = {
        "chain_id": "sac_full",
        "paper_id": "p1",
        "paper_title": "Wafer-scale metalens manufacturing",
        "publication_year": 2025,
        "section_name": "discussion",
        "section_key": "discussion",
        "constraint_text": "Fabrication tolerance is the root physical constraint.",
        "failure_mechanism_text": "Overlay mismatch creates phase loss.",
        "attempted_path_text": "The authors attempted calibration and inverse design.",
        "local_fix_text": "Calibration mitigates mismatch in the prototype.",
        "new_constraint_text": "Packaging drift remains as a new constraint.",
        "typed_chain_complete": 1,
        "typed_chain_completeness": "full",
        "evidence_grade": "typed_section_lineage",
        "claim_scope": "bottleneck_lineage_evidence",
    }

    cards, updates = build_direction_claim_cards(
        atoms=[],
        section_atom_chains=[chain],
        future_directions=[
            {
                "direction_id": 42,
                "direction_name": "Wafer-scale fabrication packaging drift",
                "paper_ids_json": '["p1"]',
                "confidence": 0.84,
                "evidence_tier": "triangulated_strong",
                "calibration_label": "calibrated_temporal_holdout",
            }
        ],
        principle_rows=[
            {
                "principle_id": "FP_PHYSICAL_CONSTRAINT",
                "principle_name": "物理实现与制造约束",
                "root_cause": "fabrication tolerance and material loss",
            }
        ],
        calibration_audit={"method": "temporal_platt_logistic", "avg_calibrated_auc": 0.84},
    )

    attempts = json.loads(cards[0]["attempts_last_10y_json"])
    unresolved = json.loads(cards[0]["unresolved_bottleneck_json"])
    gate = json.loads(cards[0]["quality_gate_json"])
    objects = json.loads(cards[0]["evidence_objects_json"])
    assert cards[0]["five_question_complete"] == 1
    assert cards[0]["high_confidence_eligible"] == 1
    assert cards[0]["claim_scope"] == "validated_candidate"
    assert cards[0]["evidence_grade"] == "decision_grade_claim_card"
    assert attempts[0]["source"] == "section_atom_chain"
    assert attempts[0]["attempt_path"].startswith("The authors attempted")
    assert unresolved["items"][0]["source"] == "section_atom_chain"
    assert unresolved["items"][0]["description"].startswith("Packaging drift")
    assert gate["section_atom_chain_support"]["full_decision_grade"] == 1
    assert gate["high_confidence_gates"]["section_decision_grade_ready"] is True
    assert any(obj["type"] == "claim_card_typed_chain_attempt" for obj in objects)
    assert any(obj["type"] == "claim_card_typed_chain_bottleneck" for obj in objects)
    assert updates[0]["high_confidence_eligible"] == 1


def test_step13_prefers_step6_fused_section_atom_chain_ids():
    from echelon.v14b.step13_first_principles_history import build_direction_claim_cards

    chain = {
        "chain_id": "sac_fused",
        "paper_id": "p_chain",
        "paper_title": "Fused chain source",
        "publication_year": 2025,
        "section_name": "discussion",
        "section_key": "discussion",
        "constraint_text": "Thermal packaging drift is the root physical constraint.",
        "failure_mechanism_text": "Heat accumulation creates optical phase loss.",
        "attempted_path_text": "The authors attempted active cooling.",
        "local_fix_text": "Active cooling stabilizes the prototype.",
        "new_constraint_text": "Power overhead remains unresolved.",
        "typed_chain_complete": 1,
        "typed_chain_completeness": "full",
        "evidence_grade": "typed_section_lineage",
        "claim_scope": "bottleneck_lineage_evidence",
    }

    cards, _ = build_direction_claim_cards(
        atoms=[],
        section_atom_chains=[chain],
        future_directions=[
            {
                "direction_id": 44,
                "direction_name": "Device reliability direction",
                "paper_ids_json": '["p_other"]',
                "evidence_json": json.dumps({"section_atom_chain_ids": ["sac_fused"]}),
                "confidence": 0.84,
                "evidence_tier": "triangulated_strong",
                "calibration_label": "calibrated_temporal_holdout",
            }
        ],
        principle_rows=[],
        calibration_audit={"method": "temporal_platt_logistic", "avg_calibrated_auc": 0.84},
    )

    attempts = json.loads(cards[0]["attempts_last_10y_json"])
    gate = json.loads(cards[0]["quality_gate_json"])
    assert cards[0]["five_question_complete"] == 1
    assert attempts[0]["section_atom_chain_id"] == "sac_fused"
    assert attempts[0]["source"] == "section_atom_chain"
    assert gate["section_atom_chain_support"]["full_decision_grade"] == 1


def test_step13_partial_section_atom_chains_complete_card_but_block_high_confidence():
    from echelon.v14b.step13_first_principles_history import build_direction_claim_cards

    chain = {
        "chain_id": "sac_partial",
        "paper_id": "p1",
        "paper_title": "Metalens coupling loss",
        "publication_year": 2025,
        "section_name": "results",
        "section_key": "results",
        "constraint_text": "Efficiency remains limited by coupling loss.",
        "failure_mechanism_text": "Coupling loss dominates the measured failure mode.",
        "attempted_path_text": "A grating coupler was attempted.",
        "typed_chain_complete": 0,
        "typed_chain_completeness": "attempted_path_partial",
        "evidence_grade": "partial_typed_section_lineage",
        "claim_scope": "exploratory_bottleneck_lineage",
    }

    cards, updates = build_direction_claim_cards(
        atoms=[],
        section_atom_chains=[chain],
        future_directions=[
            {
                "direction_id": 43,
                "direction_name": "Metalens coupling loss mitigation",
                "paper_ids_json": '["p1"]',
                "confidence": 0.85,
                "evidence_tier": "triangulated_strong",
                "calibration_label": "calibrated_temporal_holdout",
            }
        ],
        principle_rows=[
            {
                "principle_id": "FP_PHYSICAL_CONSTRAINT",
                "principle_name": "物理实现与制造约束",
                "root_cause": "coupling loss and fabrication tolerance",
            }
        ],
        calibration_audit={"method": "temporal_platt_logistic", "avg_calibrated_auc": 0.84},
    )

    gate = json.loads(cards[0]["quality_gate_json"])
    reasons = json.loads(cards[0]["uncertainty_reasons_json"])
    assert cards[0]["five_question_complete"] == 1
    assert cards[0]["high_confidence_eligible"] == 0
    assert cards[0]["claim_scope"] == "exploratory_with_claim_card"
    assert cards[0]["evidence_grade"] == "complete_claim_card_pending_high_confidence_evidence"
    assert gate["section_atom_chain_support"]["partial"] == 1
    assert gate["high_confidence_gates"]["section_evidence_strong"] is False
    assert gate["high_confidence_gates"]["section_decision_grade_ready"] is False
    assert "strong section-level evidence" in gate["missing_high_confidence_gates"]
    assert any("current parser-contract decision-grade" in reason for reason in reasons)
    assert updates[0]["high_confidence_eligible"] == 0
