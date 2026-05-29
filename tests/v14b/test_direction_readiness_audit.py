from __future__ import annotations

import sqlite3
from pathlib import Path

from echelon.v14b.direction_readiness_audit import (
    classify_blockers,
    collect_metrics,
    load_section_frontfill_state,
    readiness_level,
    run_audit,
    select_section_frontfill_state,
)


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


def test_direction_readiness_flags_section_frontfill_soft_stall(tmp_path):
    state = tmp_path / "watchdog_state.json"
    state.write_text(
        """
        {
          "done": 1200,
          "total": 12000,
          "rows": 1241,
          "papers": 690,
          "primary_section_papers": 690,
          "no_evidence_done_delta": 240,
          "no_evidence_elapsed_s": 7200,
          "low_yield_intervals": 2
        }
        """,
        encoding="utf-8",
    )

    metrics = {
        "linked_ref_rate": 0.31,
        "primary_section_papers": 9000,
        "predicted_future_edges": 0,
        "future_directions": 0,
        "direction_claim_cards": 0,
        "complete_claim_cards": 0,
        "openalex_w_rate": 0.72,
        "section_frontfill_state": load_section_frontfill_state(state),
    }
    blockers = classify_blockers(metrics)

    assert metrics["section_frontfill_state"]["status"] == "soft_stall"
    assert any(b["gate"] == "section_frontfill_efficiency" for b in blockers)


def test_direction_readiness_infers_soft_stall_from_watchdog_log(tmp_path):
    state = tmp_path / "section_top12000_watchdog_state.json"
    state.write_text(
        '{"done": 1015, "total": 12000, "rows": 1241, "papers": 690, "low_yield_intervals": 0}',
        encoding="utf-8",
    )
    state.with_name("section_top12000_watchdog.log").write_text(
        "[2026-05-29T06:56:02Z] pid=1 status=running rows=1241 papers=690 progress=na\n"
        "[2026-05-29T16:43:54Z] pid=1 status=running rows=1241 papers=690 "
        "done=1015/12000 elapsed_s=33961\n",
        encoding="utf-8",
    )

    loaded = load_section_frontfill_state(state)

    assert loaded["status"] == "soft_stall"
    assert loaded["no_evidence_elapsed_s"] > 9 * 3600


def test_direction_readiness_prefers_active_delta_watchdog_state(tmp_path):
    log_dir = tmp_path / "logs" / "v14b"
    log_dir.mkdir(parents=True)
    (log_dir / "section_top12000_watchdog_state.json").write_text(
        '{"done": 1000, "total": 12000, "rows": 100, "papers": 90}',
        encoding="utf-8",
    )
    (log_dir / "section_delta_watchdog_state.json").write_text(
        '{"done": 20, "total": 12227, "rows": 200, "papers": 190}',
        encoding="utf-8",
    )

    loaded = select_section_frontfill_state(tmp_path)

    assert loaded["source"] == "section_delta"
    assert loaded["done"] == 20


def test_direction_readiness_writes_report(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)

    result = run_audit(main, v14, tmp_path / "reports")

    assert result["readiness_level"] == "candidate_generator_only"
    assert (tmp_path / "reports" / "direction_readiness_audit.md").exists()
