from __future__ import annotations

import json
import sqlite3

from echelon.v14b.access_link_audit import run_access_link_audit


def test_access_link_audit_records_roles_links_and_gaps(tmp_path):
    db_main = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db_main))
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            publication_year INTEGER,
            arxiv_id TEXT,
            doi TEXT,
            s2_paper_id TEXT,
            openalex_id TEXT
        );
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT
        );
        INSERT INTO papers VALUES
            ('p1', 'Main paper', 2020, '2001.00001', NULL, NULL, 'W1'),
            ('p2', 'Future paper', 2024, NULL, NULL, NULL, NULL),
            ('p3', 'DOI paper', 2022, NULL, '10.1000/example', 'abc123', NULL);
        INSERT INTO paper_sections VALUES ('p1', 'discussion', 'section evidence section evidence section evidence section evidence section evidence section evidence section evidence');
        """
    )
    conn.commit()
    conn.close()

    db_v14 = tmp_path / "v14.sqlite3"
    conn = sqlite3.connect(str(db_v14))
    conn.executescript(
        """
        CREATE TABLE main_path_edges (
            source_paper_id TEXT,
            target_paper_id TEXT,
            main_path_weight REAL,
            is_main_path INTEGER
        );
        CREATE TABLE predicted_future_edges (
            src_paper_id TEXT,
            dst_paper_id TEXT,
            prediction_confidence REAL
        );
        CREATE TABLE subgraph_nodes (
            paper_id TEXT,
            keystone_score_v14 REAL,
            node_size REAL
        );
        CREATE TABLE limitation_atoms (
            paper_id TEXT
        );
        INSERT INTO main_path_edges VALUES ('p1', 'p2', 10, 1);
        INSERT INTO predicted_future_edges VALUES ('p1', 'p3', 0.9);
        INSERT INTO subgraph_nodes VALUES ('p3', 0.8, 5);
        INSERT INTO limitation_atoms VALUES ('p1');
        """
    )
    conn.commit()
    conn.close()

    summary = run_access_link_audit(
        db_main=db_main,
        db_v14=db_v14,
        out_dir=tmp_path / "reports",
        limit=10,
    )

    assert summary["decision_papers"] == 3
    assert summary["access_gaps"] == 1
    assert summary["with_primary_local_evidence"] == 1
    assert summary["gap_by_role"]["main_path_turning_target"] == 1
    conn = sqlite3.connect(str(db_v14))
    rows = conn.execute(
        "SELECT paper_id, roles_json, synthesized_links_json, access_gap FROM access_link_audit_items"
    ).fetchall()
    conn.close()
    by_id = {row[0]: row for row in rows}
    assert "arxiv_abs" in json.dumps(json.loads(by_id["p1"][2]))
    assert "top_keystone" in json.loads(by_id["p3"][1])
    assert by_id["p2"][3] == 1
