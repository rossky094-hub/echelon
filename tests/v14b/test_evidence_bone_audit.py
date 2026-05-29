from __future__ import annotations

import sqlite3
from pathlib import Path

from echelon.v14b.evidence_bone_audit import collect_audit, run_audit, watchdog_history


def _make_main(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE paper_references (
            citing_paper_id TEXT,
            cited_paper_id_external TEXT,
            cited_paper_id_internal TEXT,
            cited_paper_id_provider TEXT,
            cited_paper_id_norm TEXT
        );
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO paper_references VALUES (?, ?, ?, ?, ?)",
        [
            ("p1", "10.1/a", "", "doi", "10.1/a"),
            ("p1", "https://openalex.org/W123", "", "openalex", "W123"),
            ("p2", "2301.00001", "", "arxiv", "2301.00001"),
            ("p2", "short", "", "", ""),
            ("p3", "10.2/b", "p4", "doi", "10.2/b"),
        ],
    )
    conn.executemany(
        "INSERT INTO paper_sections VALUES (?, ?, ?)",
        [
            ("p1", "discussion", "evidence " * 20),
            ("p2", "abstract", "not primary " * 20),
        ],
    )
    conn.commit()
    conn.close()


def _make_v14(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE section_priority_summary (
            audit_ts TEXT,
            category TEXT,
            total INTEGER,
            in_top_n INTEGER,
            any_section INTEGER,
            primary_section INTEGER,
            eligible_pdf INTEGER,
            coverage_json TEXT
        );
        CREATE TABLE section_priority_papers (
            paper_id TEXT,
            has_primary_section INTEGER,
            eligible_pdf INTEGER,
            in_top_n INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO section_priority_summary VALUES ('t1', 'main_path_node', 10, 8, 2, 1, 9, '{}')"
    )
    conn.executemany(
        "INSERT INTO section_priority_papers VALUES (?, ?, ?, ?)",
        [("p1", 1, 1, 1), ("p2", 0, 1, 1), ("p3", 0, 1, 0)],
    )
    conn.commit()
    conn.close()


def test_evidence_bone_audit_classifies_refs_sections_and_logs(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)
    section_log = tmp_path / "section.log"
    section_log.write_text(
        "Cannot set gray non-stroke color because /'P1' is an invalid float value\n"
        "\rStep5s sections: 10/12000 [00:10<10:00, parsed=1]\n",
        encoding="utf-8",
    )
    watchdog_log = tmp_path / "watchdog.log"
    watchdog_log.write_text(
        "LOW_YIELD_SCAN progress_delta=200 rows_delta=0\n"
        "SECTION_EVIDENCE_SOFT_STALL progress_delta=220 low_yield_intervals=2\n",
        encoding="utf-8",
    )
    watchdog_state = tmp_path / "watchdog_state.json"
    watchdog_state.write_text(
        """
        {
          "rows": 2,
          "papers": 2,
          "primary_section_papers": 1,
          "done": 220,
          "total": 12000,
          "no_evidence_done_delta": 210,
          "no_evidence_elapsed_s": 7200,
          "low_yield_intervals": 2
        }
        """,
        encoding="utf-8",
    )
    openalex_log = tmp_path / "openalex.log"
    openalex_log.write_text("Server disconnected without sending a response.\n", encoding="utf-8")

    result = collect_audit(
        db_main=main,
        db_v14=v14,
        section_log=section_log,
        watchdog_log=watchdog_log,
        watchdog_state=watchdog_state,
        openalex_log=openalex_log,
    )

    taxonomy = {row["kind"]: row["n"] for row in result["reference_taxonomy"]["taxonomy"]}
    assert taxonomy["doi_unlinked"] == 1
    assert taxonomy["openalex_unlinked"] == 1
    assert taxonomy["arxiv_unlinked"] == 1
    assert result["section_coverage"]["primary_section_papers"] == 1
    assert result["frontfill_log_taxonomy"]["event_counts"]["low_yield_scan"] == 1
    assert result["frontfill_health"]["status"] == "soft_stall"
    assert result["frontfill_health"]["no_evidence_done_delta"] == 210


def test_watchdog_history_detects_elapsed_no_evidence_growth(tmp_path):
    log = tmp_path / "watchdog.log"
    log.write_text(
        "[2026-05-29T06:56:02Z] pid=1 status=running rows=1241 papers=690 progress=na\n"
        "[2026-05-29T13:43:54Z] pid=1 status=running rows=1241 papers=690 "
        "primary_section_papers=690 delta_rows=0 delta_papers=0 done=944/12000 elapsed_s=23160\n",
        encoding="utf-8",
    )

    history = watchdog_history(log)

    assert history["available"] is True
    assert history["latest"]["done"] == 944
    assert history["no_evidence_elapsed_s"] > 6 * 3600


def test_evidence_bone_audit_writes_report(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)
    out = run_audit(
        db_main=main,
        db_v14=v14,
        out_dir=tmp_path / "reports",
        section_log=tmp_path / "missing-section.log",
        watchdog_log=tmp_path / "missing-watch.log",
        openalex_log=tmp_path / "missing-openalex.log",
    )

    assert (tmp_path / "reports" / "evidence_bone_audit.md").exists()
    assert "evidence_bone_audit.json" in out["json"]
