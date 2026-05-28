import sqlite3


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
        INSERT INTO papers VALUES
            ('p1', 'Fabrication-limited metasurface', 'thermal loss and fabrication tolerance remain key bottlenecks', 2020, 'F1'),
            ('p2', 'Sim2real policy transfer', 'domain shift remains a major generalization challenge', 2021, 'F2'),
            ('p3', 'Non-convex inverse design', 'gradient instability under non-convex optimization', 2022, 'F1'),
            ('p4', 'Scalable photonic integration', 'integration and latency constraints in deployment', 2024, 'F1');
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
    conn_v14.close()
    assert rows
    assert any((r[1] or 0) > 0 for r in rows)

