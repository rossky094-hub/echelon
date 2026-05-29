from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

from echelon.v14b.step5s_section_queue_audit import run_section_queue_audit


def _load_watchdog_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "watch_step5s_section_ingest.py"
    spec = importlib.util.spec_from_file_location("watch_step5s_section_ingest", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_watchdog_parses_top12000_progress(tmp_path):
    mod = _load_watchdog_module()
    log = tmp_path / "step5s.log"
    log.write_text(
        "\rStep5s sections:   8%|8         | 920/12000 [5:35:00<67:10:00, 20.00s/it]",
        encoding="utf-8",
    )

    parsed = mod.parse_progress(log)

    assert parsed["done"] == 920
    assert parsed["total"] == 12000
    assert parsed["elapsed_s"] == 5 * 3600 + 35 * 60
    assert "done=920/12000" in mod.get_progress(log)


def test_watchdog_done_and_primary_section_gate(tmp_path):
    mod = _load_watchdog_module()
    db_main = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db_main))
    conn.executescript(
        """
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO paper_sections VALUES (?, ?, ?)",
        [
            ("p1", "discussion", "rich section evidence " * 8),
            ("p1", "abstract", "not a primary evidence section " * 8),
            ("p2", "limitations", "short"),
            ("p3", "future_work", "future experiment evidence " * 8),
        ],
    )
    conn.commit()
    conn.close()

    assert mod.is_step5s_done("running", {"done": 12000, "total": 12000})
    assert mod.is_step5s_done("done", {"done": None, "total": None})
    assert mod.get_primary_section_papers(db_main) == 2


def _make_main_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            abstract TEXT,
            publication_date TEXT,
            publication_year INTEGER,
            arxiv_id TEXT,
            doi TEXT,
            s2_paper_id TEXT,
            openalex_id TEXT,
            cited_by_count INTEGER
        );
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("p_main", "Metalens main path", "metalens trunk", "2020-01-01", 2020, "2001.00001", None, None, "W1", 100),
            ("p_future", "Future metalens", "metalens future", "2024-01-01", 2024, "2401.00002", None, None, "W2", 50),
            ("p_branch", "Branch driver", "split evidence", "2022-01-01", 2022, "2201.00003", None, None, "W3", 20),
            ("p_done", "Already sectioned", "metalens limitation", "2021-01-01", 2021, "2101.00004", None, None, "W4", 10),
        ],
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES ('p_done', 'discussion', ?)",
        ("section evidence " * 20,),
    )
    conn.commit()
    conn.close()


def _make_v14_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE main_path_edges (
            source_paper_id TEXT,
            target_paper_id TEXT,
            is_main_path INTEGER,
            main_path_weight REAL,
            spc REAL
        );
        CREATE TABLE predicted_future_edges (
            src_paper_id TEXT,
            dst_paper_id TEXT,
            predicted_prob REAL,
            prediction_confidence REAL
        );
        CREATE TABLE limitation_atoms (
            paper_id TEXT,
            severity TEXT,
            evidence_weight REAL
        );
        CREATE TABLE limitation_resolutions (
            atom_id INTEGER,
            resolver_paper_id TEXT,
            confidence REAL
        );
        CREATE TABLE branch_lineages (
            split_evidence_json TEXT,
            split_confidence REAL
        );
        CREATE TABLE subgraph_nodes (
            paper_id TEXT,
            keystone_score_v14 REAL,
            is_keystone INTEGER,
            node_size REAL
        );
        CREATE TABLE visual_nodes (
            paper_id TEXT,
            cluster_id TEXT,
            node_size REAL,
            uncertainty_score REAL
        );
        CREATE TABLE visual_clusters (
            cluster_id TEXT
        );
        """
    )
    conn.execute("INSERT INTO main_path_edges VALUES ('p_main', 'p_done', 1, 10, 10)")
    conn.execute("INSERT INTO predicted_future_edges VALUES ('p_main', 'p_future', 0.9, 0.8)")
    conn.execute("INSERT INTO limitation_atoms VALUES ('p_done', 'high', 0.9)")
    conn.execute("INSERT INTO limitation_resolutions VALUES (1, 'p_future', 0.8)")
    conn.execute(
        "INSERT INTO branch_lineages VALUES (?, 0.9)",
        (json.dumps({"driver_papers": ["p_branch"]}),),
    )
    conn.execute("INSERT INTO subgraph_nodes VALUES ('p_main', 0.9, 1, 10)")
    conn.executemany(
        "INSERT INTO visual_nodes VALUES (?, ?, ?, ?)",
        [("p_main", "C1", 10, 0.1), ("p_branch", "C2", 9, 0.8)],
    )
    conn.execute("INSERT INTO visual_clusters VALUES ('C1')")
    conn.execute("INSERT INTO visual_clusters VALUES ('C2')")
    conn.commit()
    conn.close()


def test_section_queue_audit_writes_delta_queue(tmp_path):
    db_main = tmp_path / "main.sqlite3"
    db_v14 = tmp_path / "v14.sqlite3"
    _make_main_db(db_main)
    _make_v14_db(db_v14)

    result = run_section_queue_audit(
        db_main=db_main,
        db_v14=db_v14,
        top_n=10,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        topic_terms=["metalens"],
    )

    assert result["delta_queue"] >= 3
    assert (tmp_path / "data" / "section_delta_queue.csv").exists()
    conn = sqlite3.connect(str(db_v14))
    try:
        rows = conn.execute("SELECT paper_id, reasons_json FROM section_priority_papers").fetchall()
    finally:
        conn.close()
    reasons = {pid: json.loads(raw) for pid, raw in rows}
    assert "main_path_node" in reasons["p_main"]
    assert "future_endpoint" in reasons["p_future"]
    assert "branch_split_driver" in reasons["p_branch"]
