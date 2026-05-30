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


def test_watchdog_pid_probe_degrades_safely_when_ps_is_blocked(monkeypatch):
    mod = _load_watchdog_module()

    monkeypatch.setattr(mod, "run", lambda _cmd: "__permission_denied__")

    assert mod.find_step5s_pid("step5s_section_ingest") == "unknown"


def test_watchdog_pid_probe_ignores_unrelated_processes_with_pattern_arg(monkeypatch):
    mod = _load_watchdog_module()
    ps_output = "\n".join(
        [
            "41978 /Applications/SkyComputerUseClient --note step5s_section_ingest",
            "42000 python3 scripts/watch_step5s_section_ingest.py --pid-pattern step5s_section_ingest",
            "46618 python3 -m echelon.v14b.step5s_section_ingest --db db/echelon_library.sqlite3 --top-n 12000",
        ]
    )
    monkeypatch.setattr(mod, "run", lambda _cmd: ps_output)

    assert mod.find_step5s_pid("step5s_section_ingest") == "46618"


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
        CREATE TABLE section_ingest_attempts (
            attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id TEXT,
            attempt_ts TEXT,
            outcome TEXT,
            source_url TEXT,
            detail TEXT,
            inserted_sections INTEGER,
            primary_sections INTEGER
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
    assert mod.handoff_reason(8000, 8000) == "frontfill_threshold_met"
    assert mod.handoff_reason(2, 8000) == "frontfill_threshold_not_met_downstream_gate_will_hold"


def test_watchdog_soft_stall_state_tracks_evidence_not_just_progress(tmp_path):
    mod = _load_watchdog_module()
    # A restart should preserve evidence counters separately from ordinary
    # progress counters.  This is the difference between "process is alive" and
    # "the evidence bone is getting stronger".
    state = {
        "rows": 1241,
        "papers": 690,
        "done": 1015,
        "last_evidence_rows": 1241,
        "last_evidence_papers": 690,
        "last_evidence_done": 815,
        "last_evidence_ts": 1000.0,
        "low_yield_intervals": 1,
    }
    path = tmp_path / "state.json"
    mod._write_state(path, state)

    loaded = mod._load_state(path)

    assert loaded["rows"] == 1241
    assert loaded["last_evidence_done"] == 815
    assert loaded["done"] - loaded["last_evidence_done"] == 200
    assert loaded["low_yield_intervals"] == 1


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
        CREATE TABLE section_ingest_attempts (
            attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id TEXT,
            attempt_ts TEXT,
            outcome TEXT,
            source_url TEXT,
            detail TEXT,
            inserted_sections INTEGER,
            primary_sections INTEGER
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
            ("p_gap", "Topic gap turning paper", "metalens field of view evidence gap", "2023-01-01", 2023, "2301.00005", None, None, "W5", 15),
        ],
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES ('p_done', 'discussion', ?)",
        ("section evidence " * 20,),
    )
    conn.executemany(
        """
        INSERT INTO section_ingest_attempts
            (paper_id, attempt_ts, outcome, source_url, detail, inserted_sections, primary_sections)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("p_main", "2026-01-01T00:00:00Z", "parse_timeout", "https://arxiv.org/pdf/2001.00001.pdf", "", 0, 0),
            ("p_branch", "2026-01-01T00:00:01Z", "no_target_sections", "https://arxiv.org/pdf/2201.00003.pdf", "", 0, 0),
        ],
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
        topic_evidence_gap_queue=None,
    )

    assert result["delta_queue"] >= 2
    assert result["retry_class_counts"]["retryable_pdf_failure"] >= 1
    assert result["retry_class_counts"]["no_target_sections"] >= 1
    assert (tmp_path / "data" / "section_delta_queue.csv").exists()
    conn = sqlite3.connect(str(db_v14))
    try:
        rows = conn.execute("SELECT paper_id, reasons_json, retry_class FROM section_priority_papers").fetchall()
    finally:
        conn.close()
    reasons = {pid: json.loads(raw) for pid, raw, _retry in rows}
    retries = {pid: retry for pid, _raw, retry in rows}
    assert "main_path_node" in reasons["p_main"]
    assert "future_endpoint" in reasons["p_future"]
    assert "branch_split_driver" in reasons["p_branch"]
    assert retries["p_main"] == "retryable_pdf_failure"
    assert retries["p_branch"] == "no_target_sections"


def test_section_queue_audit_merges_multi_topic_evidence_gaps(tmp_path):
    db_main = tmp_path / "main.sqlite3"
    db_v14 = tmp_path / "v14.sqlite3"
    _make_main_db(db_main)
    _make_v14_db(db_v14)
    gap_csv = tmp_path / "multi_topic_evidence_gap_queue.csv"
    gap_csv.write_text(
        "\n".join(
            [
                "topic,gap_type,bottleneck,priority,candidate_paper_ids,frontfill_query,required_sections,why",
                "metalens,missing_bottleneck_section_evidence,field of view,100,p_gap,metalens field of view,limitation;discussion,missing field-of-view section evidence",
                "metalens,key_turning_paper_missing_primary_section,,90,p_branch,metalens branch driver,limitation;discussion,key turning paper parsed but no target sections",
                "quantum light source,future_candidates_missing_claim_card,,85,,quantum light source,limitation;discussion,claim card input gap",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_section_queue_audit(
        db_main=db_main,
        db_v14=db_v14,
        top_n=10,
        out_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        topic_terms=["metalens"],
        topic_evidence_gap_queue=gap_csv,
    )

    assert result["topic_evidence_gap_summary"]["gap_rows"] == 3
    assert result["topic_evidence_gap_summary"]["gap_paper_ids"] == 2
    assert result["topic_evidence_gap_summary"]["gap_rows_without_candidate_papers"] == 1
    assert result["topic_gap_delta_queue"] == 2
    topic_gap_queue = tmp_path / "data" / "topic_evidence_gap_delta_queue.csv"
    assert topic_gap_queue.exists()
    assert "p_branch" in topic_gap_queue.read_text(encoding="utf-8")

    conn = sqlite3.connect(str(db_v14))
    try:
        row = conn.execute(
            "SELECT priority_score, reasons_json FROM section_priority_papers WHERE paper_id='p_gap'"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    reasons = json.loads(row[1])
    assert "topic_gap_bottleneck_evidence" in reasons
    assert "topic:metalens" in reasons
    assert row[0] >= 200
