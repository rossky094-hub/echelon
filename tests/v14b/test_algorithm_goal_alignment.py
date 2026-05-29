import sqlite3


def test_step5a_heuristic_classifier_is_bounded_and_deterministic():
    from echelon.v14b.step5a_scibert import heuristic_classify_edge

    edge = {"citing_id": "new", "cited_id": "old"}
    metadata = {
        "new": {
            "title": "Scalable integrated photonic resonator based on prior microcomb design",
            "abstract": "We improve the platform using a robust low-loss architecture.",
        },
        "old": {
            "title": "Microcomb design in optical resonators",
            "abstract": "An optical resonator platform for frequency combs.",
        },
    }

    func, conf = heuristic_classify_edge(edge, metadata)
    assert func in {"extension", "usage", "similarity", "background", "motivation", "future_work"}
    assert 0.0 <= conf <= 0.65


def test_step5a_no_context_labels_are_weak_evidence():
    from echelon.v14b.step5a_scibert import (
        citation_function_evidence_level,
        citation_function_evidence_weight,
    )

    assert citation_function_evidence_level(False) == "weak_paper_metadata"
    assert citation_function_evidence_weight(0.95, False) <= 0.25
    assert citation_function_evidence_weight(0.95, True) > citation_function_evidence_weight(0.95, False)


def test_step5b_builds_time_forward_evolution_edges(tmp_path):
    from echelon.v14b.step5b_vgae import build_evolution_edge_records

    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            publication_year INTEGER,
            primary_field_id TEXT
        );
        INSERT INTO papers VALUES ('old', 2020, 'F1');
        INSERT INTO papers VALUES ('new', 2024, 'F1');
        INSERT INTO papers VALUES ('same_a', 2023, 'F1');
        INSERT INTO papers VALUES ('same_b', 2023, 'F1');
        INSERT INTO papers VALUES ('future', 2026, 'F1');
        """
    )
    raw_edges = [
        ("new", "old"),       # real citation, evolution old -> new
        ("same_a", "same_b"), # ambiguous same-year
        ("old", "future"),    # clear time-inverted reference
    ]
    node_id_map = {"old": 0, "new": 1, "same_a": 2, "same_b": 3, "future": 4}

    records, stats = build_evolution_edge_records(conn, raw_edges, node_id_map)
    conn.close()

    assert [(r.src_id, r.dst_id) for r in records] == [("old", "new")]
    assert stats["skipped_same_year"] == 1
    assert stats["skipped_time_inverted"] == 1


def test_step5b_temporal_split_uses_later_edges_for_holdout():
    from echelon.v14b.step5b_vgae import EvolutionEdge, split_edges_temporally

    records = [
        EvolutionEdge(i, i + 1, f"p{i}", f"p{i+1}", 2000 + i, 2001 + i)
        for i in range(20)
    ]
    train, val, test = split_edges_temporally(records, val_ratio=0.1, test_ratio=0.1)

    assert train
    assert val
    assert test
    assert max(e.dst_year for e in train) <= min(e.dst_year for e in val)
    assert max(e.dst_year for e in val) <= min(e.dst_year for e in test)


def test_step5b_calibration_separates_raw_score_from_product_confidence():
    import numpy as np
    from echelon.v14b.step5b_vgae import (
        apply_probability_calibration,
        fit_probability_calibrator,
    )

    calibrator = fit_probability_calibrator(
        positive_scores=np.array([0.65, 0.72, 0.82, 0.91]),
        negative_scores=np.array([0.40, 0.55, 0.70, 0.88]),
        bins=4,
    )
    calibrated, support, label = apply_probability_calibration(0.99, calibrator)

    assert label == "calibrated_temporal_holdout"
    assert support > 0
    assert 0.0 <= calibrated <= 0.995
    assert calibrated < 0.99


def test_step5b_resume_requires_calibration_audit(tmp_path):
    from echelon.v14b.db_schema import init_v14b_db
    from echelon.v14b.step5b_vgae import (
        _vgae_resume_state_valid,
        ensure_calibration_audit_schema,
        write_calibration_audit,
    )

    db_v14 = tmp_path / "v14.sqlite3"
    conn = init_v14b_db(db_v14)
    conn.execute(
        """
        INSERT INTO predicted_future_edges
            (src_paper_id, dst_paper_id, predicted_prob, src_year, dst_year, is_cross_field)
        VALUES ('old', 'new', 0.8, 2020, 2024, 0)
        """
    )
    conn.commit()

    valid, reason = _vgae_resume_state_valid(conn, {"records_n": 1})
    assert not valid
    assert "vgae_calibration_audit" in reason

    ensure_calibration_audit_schema(conn)
    write_calibration_audit(
        conn,
        calibrator={"method": "uncalibrated_no_holdout", "label": "uncalibrated"},
        cal_summary={},
        rolling_backtest={},
    )
    valid, reason = _vgae_resume_state_valid(conn, {"records_n": 1})
    conn.close()
    assert valid, reason


def test_step6_empty_fusion_writes_no_placeholder(tmp_path):
    from echelon.v14b.db_schema import init_v14b_db
    from echelon.v14b.step6_fusion import run_fusion

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
        """
    )
    conn_main.close()

    db_v14 = tmp_path / "v14.sqlite3"
    conn_v14 = init_v14b_db(db_v14)
    conn_v14.close()

    stats = run_fusion(db_main=db_main, db_v14=db_v14, resume=False)

    conn_v14 = sqlite3.connect(str(db_v14))
    count = conn_v14.execute("SELECT COUNT(*) FROM future_directions").fetchone()[0]
    conn_v14.close()
    assert stats["records_n"] == 0
    assert count == 0


def test_step6_resume_rejects_stale_fusion_audit(tmp_path):
    from echelon.v14b.db_schema import init_v14b_db
    from echelon.v14b.step6_fusion import _fusion_resume_state_valid

    db_v14 = tmp_path / "v14.sqlite3"
    conn = init_v14b_db(db_v14)
    conn.execute("DELETE FROM future_directions")
    conn.execute(
        """
        INSERT INTO fusion_evidence_audit
            (run_id, n_terminals, n_vgae_preds_top, n_vgae_preds_total,
             n_cross_field_total, n_unresolved, n_candidates, n_directions,
             limitation_quality_json, evidence_path_json, adequacy_label, remaining_risk)
        VALUES ('r1', 1, 1, 1, 0, 1, 20, 20, '{}', '{}', 'adequate_candidate_set', '')
        """
    )
    conn.commit()

    valid, reason = _fusion_resume_state_valid(conn, {"records_n": 0})
    conn.close()
    assert not valid
    assert "fusion_evidence_audit" in reason
