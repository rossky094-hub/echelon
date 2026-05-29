from __future__ import annotations

import sqlite3
from pathlib import Path

from echelon.v14b.direction_readiness_audit import classify_blockers, collect_metrics, readiness_level, run_audit


def _make_main(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, openalex_id TEXT);
        CREATE TABLE paper_references (cited_paper_id_internal TEXT);
        CREATE TABLE paper_sections (paper_id TEXT, section_name TEXT, section_text TEXT);
        """
    )
    conn.executemany("INSERT INTO papers VALUES (?, ?)", [("p1", "W1"), ("p2", "")])
    conn.executemany("INSERT INTO paper_references VALUES (?)", [("p1",), ("",), ("",)])
    conn.execute("INSERT INTO paper_sections VALUES ('p1', 'discussion', ?)", ("evidence " * 20,))
    conn.commit()
    conn.close()


def _make_v14(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE predicted_future_edges (src_paper_id TEXT, dst_paper_id TEXT);
        CREATE TABLE limitation_atoms (paper_id TEXT);
        CREATE TABLE limitation_resolutions (atom_id INTEGER);
        CREATE TABLE fusion_evidence_audit (run_id TEXT, output_directions INTEGER);
        CREATE TABLE future_directions (direction_id INTEGER);
        CREATE TABLE direction_claim_cards (
            claim_card_id TEXT,
            five_question_complete INTEGER,
            high_confidence_eligible INTEGER
        );
        CREATE TABLE visual_edges (layer TEXT);
        CREATE TABLE branch_lineages (branch_id TEXT);
        """
    )
    conn.execute("INSERT INTO predicted_future_edges VALUES ('p1', 'p2')")
    conn.execute("INSERT INTO limitation_atoms VALUES ('p1')")
    conn.execute("INSERT INTO visual_edges VALUES ('future')")
    conn.execute("INSERT INTO branch_lineages VALUES ('B1')")
    conn.commit()
    conn.close()


def test_direction_readiness_blocks_raw_gnn_promotion(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)

    metrics = collect_metrics(main, v14)
    blockers = classify_blockers(metrics)

    assert metrics["predicted_future_edges"] == 1
    assert readiness_level(metrics, blockers) == "candidate_generator_only"
    assert any(b["gate"] == "fusion_materialization" for b in blockers)


def test_direction_readiness_writes_report(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)

    result = run_audit(main, v14, tmp_path / "reports")

    assert result["readiness_level"] == "candidate_generator_only"
    assert (tmp_path / "reports" / "direction_readiness_audit.md").exists()
