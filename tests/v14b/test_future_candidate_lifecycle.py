from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from echelon.v14b.future_candidate_lifecycle import future_edge_calibration_context, run_audit


def _make_main(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, openalex_id TEXT);
        CREATE TABLE paper_references (cited_paper_id_internal TEXT);
        CREATE TABLE paper_sections (paper_id TEXT, section_name TEXT, section_text TEXT);
        """
    )
    conn.executemany("INSERT INTO papers VALUES (?, ?)", [("p1", "W1"), ("p2", "W2"), ("p3", "")])
    conn.executemany("INSERT INTO paper_references VALUES (?)", [("p1",), ("p2",), ("",)])
    conn.execute("INSERT INTO paper_sections VALUES ('p1', 'discussion', ?)", ("section evidence " * 20,))
    conn.commit()
    conn.close()


def _make_v14_unfused(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE predicted_future_edges (
            src_paper_id TEXT,
            dst_paper_id TEXT,
            predicted_prob REAL,
            calibrated_prob REAL,
            prediction_confidence REAL,
            calibration_label TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO predicted_future_edges VALUES ('p1', 'p2', 0.9, 0.8, 0.7, 'calibrated_temporal_holdout')"
    )
    conn.commit()
    conn.close()


def _make_v14_with_cards(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE predicted_future_edges (
            src_paper_id TEXT,
            dst_paper_id TEXT,
            predicted_prob REAL,
            prediction_confidence REAL
        );
        CREATE TABLE future_directions (
            direction_id INTEGER,
            direction_name TEXT,
            confidence REAL,
            paper_ids_json TEXT,
            evidence_tier TEXT,
            claim_scope TEXT,
            evidence_json TEXT
        );
        CREATE TABLE direction_claim_cards (
            claim_card_id TEXT,
            direction_id INTEGER,
            direction_name TEXT,
            evidence_strength_level TEXT,
            claim_scope TEXT,
            five_question_complete INTEGER,
            high_confidence_eligible INTEGER,
            quality_gate_json TEXT
        );
        CREATE TABLE vgae_calibration_audit (method TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO predicted_future_edges VALUES (?, ?, ?, ?)",
        [
            ("p1", "p2", 0.9, 0.7),
            ("p2", "p3", 0.8, 0.6),
        ],
    )
    conn.executemany(
        "INSERT INTO future_directions VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                1,
                "Incomplete",
                0.7,
                json.dumps(["p1", "p2"]),
                "exploratory_weak_limitation",
                "exploratory_incomplete_card",
                json.dumps({"future_edge_pairs": [["p1", "p2"]]}),
            ),
            (
                2,
                "Complete",
                0.8,
                json.dumps(["p2", "p3"]),
                "strong",
                "validated_candidate",
                json.dumps({"future_edge_pairs": [["p2", "p3"]]}),
            ),
        ],
    )
    conn.executemany(
        "INSERT INTO direction_claim_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "cc1",
                1,
                "Incomplete",
                "weak_abstract",
                "exploratory_incomplete_card",
                0,
                0,
                json.dumps({"missing_gates": ["unresolved bottleneck evidence"]}),
            ),
            (
                "cc2",
                2,
                "Complete",
                "strong_section",
                "validated_candidate",
                1,
                1,
                json.dumps({"missing_gates": [], "missing_high_confidence_gates": []}),
            ),
        ],
    )
    conn.execute("INSERT INTO vgae_calibration_audit VALUES ('rolling')")
    conn.commit()
    conn.close()


def test_future_candidate_lifecycle_marks_unfused_candidates_candidate_pool_only(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14_unfused(v14)

    result = run_audit(main, v14, tmp_path / "reports")

    assert result["summary"]["state_counts"]["future_candidate_unfused"] == 1
    assert result["summary"]["radar_eligible"] == 0
    assert result["summary"]["context"]["calibration_audits"] == 0
    assert result["summary"]["context"]["edge_calibrated_candidates"] == 1
    assert result["summary"]["context"]["edge_calibration_rate"] == 1.0
    conn = sqlite3.connect(str(v14))
    row = conn.execute("SELECT lifecycle_state, radar_eligible FROM future_candidate_lifecycle").fetchone()
    conn.close()
    assert row == ("future_candidate_unfused", 0)


def test_future_candidate_lifecycle_promotes_only_high_confidence_cards(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14_with_cards(v14)

    result = run_audit(main, v14, tmp_path / "reports")

    assert result["summary"]["state_counts"]["candidate_pool_incomplete_claim_card"] == 1
    assert result["summary"]["state_counts"]["fused_to_radar_claim_card"] == 1
    assert result["summary"]["radar_eligible"] == 0
    assert result["summary"]["radar_claim_cards"] == 1
    assert result["summary"]["context"]["high_confidence_claim_cards"] == 1
    assert result["summary"]["missing_gate_counts"]["unresolved bottleneck evidence"] == 1
    assert (tmp_path / "reports" / "future_candidate_lifecycle_audit.md").exists()


def test_visual_future_predictions_include_lifecycle_metadata(tmp_path):
    from echelon.v14b.step10_visual_graph_builder import load_future_predictions

    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14_unfused(v14)
    run_audit(main, v14, tmp_path / "reports")

    conn = sqlite3.connect(str(v14))
    conn.row_factory = sqlite3.Row
    rows = load_future_predictions(conn)
    conn.close()

    assert rows[0]["lifecycle_state"] == "future_candidate_unfused"
    assert rows[0]["radar_eligible"] == 0
    assert "Step13 Claim Card" in json.loads(rows[0]["missing_gates_json"])


def test_future_edge_calibration_context_distinguishes_edge_and_run_audit(tmp_path):
    v14 = tmp_path / "v14.sqlite3"
    _make_v14_unfused(v14)

    conn = sqlite3.connect(str(v14))
    context = future_edge_calibration_context(conn)
    conn.close()

    assert context["future_edge_candidates"] == 1
    assert context["edge_calibrated_candidates"] == 1
    assert context["edge_calibration_labels"] == {"calibrated_temporal_holdout": 1}


def test_future_candidate_lifecycle_does_not_promote_edges_by_shared_endpoint(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    conn = sqlite3.connect(str(v14))
    conn.executescript(
        """
        CREATE TABLE predicted_future_edges (
            src_paper_id TEXT,
            dst_paper_id TEXT,
            predicted_prob REAL,
            prediction_confidence REAL
        );
        CREATE TABLE future_directions (
            direction_id INTEGER,
            direction_name TEXT,
            confidence REAL,
            paper_ids_json TEXT,
            evidence_tier TEXT,
            claim_scope TEXT,
            evidence_json TEXT
        );
        CREATE TABLE direction_claim_cards (
            claim_card_id TEXT,
            direction_id INTEGER,
            direction_name TEXT,
            evidence_strength_level TEXT,
            claim_scope TEXT,
            five_question_complete INTEGER,
            high_confidence_eligible INTEGER,
            quality_gate_json TEXT
        );
        CREATE TABLE vgae_calibration_audit (method TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO predicted_future_edges VALUES (?, ?, ?, ?)",
        [
            ("p1", "p2", 0.9, 0.7),
            ("p3", "p2", 0.8, 0.6),
        ],
    )
    conn.execute(
        "INSERT INTO future_directions VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            "Exact fused edge only",
            0.8,
            json.dumps(["p1", "p2", "p3"]),
            "strong",
            "validated_candidate",
            json.dumps({"future_edge_pairs": [["p1", "p2"]]}),
        ),
    )
    conn.execute(
        "INSERT INTO direction_claim_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "cc1",
            1,
            "Exact fused edge only",
            "strong_section",
            "validated_candidate",
            1,
            1,
            json.dumps({"missing_gates": [], "missing_high_confidence_gates": []}),
        ),
    )
    conn.execute("INSERT INTO vgae_calibration_audit VALUES ('rolling')")
    conn.commit()
    conn.close()

    result = run_audit(main, v14, tmp_path / "reports")

    assert result["summary"]["state_counts"]["fused_to_radar_claim_card"] == 1
    assert result["summary"]["state_counts"]["future_candidate_unfused"] == 1
    rows = sqlite3.connect(str(v14)).execute(
        """
        SELECT src_paper_id, dst_paper_id, lifecycle_state, radar_eligible
        FROM future_candidate_lifecycle
        ORDER BY src_paper_id
        """
    ).fetchall()
    assert rows == [
        ("p1", "p2", "fused_to_radar_claim_card", 0),
        ("p3", "p2", "future_candidate_unfused", 0),
    ]
