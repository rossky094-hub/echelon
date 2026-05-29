from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from echelon.v14b.value_delivery_audit import collect_value_gates, run_audit


def _make_main(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, openalex_id TEXT);
        CREATE TABLE paper_references (cited_paper_id_internal TEXT);
        CREATE TABLE paper_sections (paper_id TEXT, section_name TEXT, section_text TEXT);
        CREATE TABLE corpus_registry (corpus_id TEXT PRIMARY KEY);
        CREATE TABLE paper_corpora (paper_id TEXT, corpus_id TEXT);
        CREATE TABLE corpus_runs (run_id TEXT PRIMARY KEY, corpus_id TEXT);
        CREATE TABLE corpus_snapshots (snapshot_id TEXT PRIMARY KEY, corpus_id TEXT);
        """
    )
    conn.executemany("INSERT INTO papers VALUES (?, ?)", [("p1", "W1"), ("p2", "W2")])
    conn.executemany("INSERT INTO paper_references VALUES (?)", [("p1",), ("p2",), ("",)])
    conn.execute("INSERT INTO paper_sections VALUES ('p1', 'discussion', ?)", ("section evidence " * 20,))
    conn.commit()
    conn.close()


def _make_v14(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE predicted_future_edges (src_paper_id TEXT, dst_paper_id TEXT);
        CREATE TABLE vgae_calibration_audit (method TEXT);
        CREATE TABLE limitation_atoms (paper_id TEXT);
        CREATE TABLE limitation_resolutions (atom_id INTEGER);
        CREATE TABLE fusion_evidence_audit (run_id TEXT, output_directions INTEGER);
        CREATE TABLE future_directions (direction_id INTEGER);
        CREATE TABLE direction_claim_cards (
            claim_card_id TEXT,
            direction_id INTEGER,
            direction_name TEXT,
            root_constraint_json TEXT,
            attempts_last_10y_json TEXT,
            enabling_conditions_json TEXT,
            unresolved_bottleneck_json TEXT,
            minimal_validation_experiment_json TEXT,
            evidence_strength_level TEXT,
            claim_scope TEXT,
            five_question_complete INTEGER,
            high_confidence_eligible INTEGER,
            quality_gate_json TEXT
        );
        CREATE TABLE visual_nodes (paper_id TEXT);
        CREATE TABLE visual_edges (layer TEXT);
        CREATE VIRTUAL TABLE visual_search_fts USING fts5(title);
        CREATE TABLE branch_lineages (
            branch_id TEXT,
            parent_branch_id TEXT,
            split_confidence REAL,
            split_evidence_json TEXT
        );
        CREATE TABLE bottleneck_lineage_triples (
            source_stage TEXT,
            target_stage TEXT,
            evidence_quality TEXT,
            evidence_page INTEGER
        );
        """
    )
    conn.execute("INSERT INTO predicted_future_edges VALUES ('p1', 'p2')")
    conn.execute("INSERT INTO vgae_calibration_audit VALUES ('rolling')")
    conn.execute("INSERT INTO direction_claim_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 ("cc1", 1, "d", "{}", "[]", "{}", "{}", "{}", "moderate", "exploratory", 1, 0, "{}"))
    conn.execute("INSERT INTO visual_nodes VALUES ('p1')")
    conn.execute("INSERT INTO visual_edges VALUES ('future')")
    conn.execute(
        "INSERT INTO branch_lineages VALUES ('B1', 'B0', 0.3, ?)",
        (json.dumps({"lineage_status": "evidence_backed_split", "parent_citation_support": 8}),),
    )
    for src, dst in (
        ("constraint", "failure_mechanism"),
        ("failure_mechanism", "attempt_path"),
        ("attempt_path", "local_fix"),
        ("local_fix", "new_constraint"),
    ):
        conn.execute("INSERT INTO bottleneck_lineage_triples VALUES (?, ?, 'section_level', 4)", (src, dst))
    conn.commit()
    conn.close()


def _make_v14_edge_calibrated_without_run_audit(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE predicted_future_edges (
            src_paper_id TEXT,
            dst_paper_id TEXT,
            predicted_prob REAL,
            calibrated_prob REAL,
            calibration_method TEXT,
            calibration_label TEXT
        );
        CREATE TABLE future_candidate_lifecycle (
            lifecycle_state TEXT,
            radar_eligible INTEGER
        );
        CREATE TABLE direction_claim_cards (
            five_question_complete INTEGER,
            high_confidence_eligible INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO predicted_future_edges VALUES ('p1', 'p2', 0.9, 0.8, 'temporal_platt_logistic', 'calibrated_temporal_holdout')"
    )
    conn.execute("INSERT INTO future_candidate_lifecycle VALUES ('future_candidate_unfused', 0)")
    conn.commit()
    conn.close()


def test_value_delivery_audit_maps_eight_gates(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "quarterly-run:\nquarterly-run-optics:\nquarterly-run-cs:\nquarterly-run-materials:\n",
        encoding="utf-8",
    )
    q = tmp_path / "echelon/v14b"
    q.mkdir(parents=True)
    (q / "quarterly_run.py").write_text("parser.add_argument('--corpus-id')", encoding="utf-8")

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "multi_topic_regression.json").write_text(
        json.dumps([{"topic": "metalens", "overall_status": "pass"}]),
        encoding="utf-8",
    )

    result = collect_value_gates(main, v14, tmp_path, report_dir)

    assert len(result["gates"]) == 8
    assert any(g["issue"] == "Future Growth Calibration" for g in result["gates"])
    assert any(g["issue"] == "Multi-topic Regression" and g["status"] == "pass" for g in result["gates"])


def test_value_delivery_audit_reports_edge_calibration_without_run_audit(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14_edge_calibrated_without_run_audit(v14)

    result = collect_value_gates(main, v14, Path("."))
    future_gate = next(g for g in result["gates"] if g["issue"] == "Future Growth Calibration")

    assert future_gate["status"] == "warn"
    assert future_gate["edge_calibrated_candidates"] == 1
    assert future_gate["calibration_audits"] == 0
    assert "run-level rolling held-out-year audit" in future_gate["calibration_gap"]


def test_value_delivery_audit_fails_when_live_topic_regression_fails(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)
    (tmp_path / "Makefile").write_text(
        "quarterly-run:\nquarterly-run-optics:\nquarterly-run-cs:\nquarterly-run-materials:\n",
        encoding="utf-8",
    )
    q = tmp_path / "echelon/v14b"
    q.mkdir(parents=True)
    (q / "quarterly_run.py").write_text("--corpus-id", encoding="utf-8")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "multi_topic_regression.json").write_text(
        json.dumps([{"topic": "quantum light source", "overall_status": "fail"}]),
        encoding="utf-8",
    )

    result = collect_value_gates(main, v14, tmp_path, report_dir)
    multi = next(g for g in result["gates"] if g["issue"] == "Multi-topic Regression")

    assert multi["status"] == "fail"
    assert multi["failed_topics"] == ["quantum light source"]


def test_value_delivery_audit_writes_report(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)
    (tmp_path / "Makefile").write_text(
        "quarterly-run:\nquarterly-run-optics:\nquarterly-run-cs:\nquarterly-run-materials:\n",
        encoding="utf-8",
    )
    q = tmp_path / "echelon/v14b"
    q.mkdir(parents=True)
    (q / "quarterly_run.py").write_text("--corpus-id", encoding="utf-8")

    out = run_audit(main, v14, tmp_path / "reports", tmp_path)

    assert (tmp_path / "reports" / "value_delivery_audit.md").exists()
    assert "evidence_policy" in out
