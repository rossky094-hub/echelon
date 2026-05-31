from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from echelon.v14b.evidence_contracts import SECTION_PARSER_CONTRACT_VERSION
from echelon.v14b.topic_gap_section_evidence_audit import (
    load_topic_gap_section_triage_state,
    run_topic_gap_section_evidence_audit,
)


def _make_main(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            publication_year INTEGER,
            arxiv_id TEXT,
            doi TEXT,
            openalex_id TEXT,
            s2_paper_id TEXT
        );
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT,
            parser_name TEXT,
            source_url TEXT,
            section_meta_json TEXT
        );
        CREATE TABLE section_ingest_attempts (
            attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id TEXT,
            attempt_ts TEXT,
            outcome TEXT,
            source_url TEXT,
            detail TEXT,
            inserted_sections INTEGER,
            primary_sections INTEGER,
            candidate_file TEXT,
            parser_name TEXT,
            parser_contract_version TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("p_decision", "Decision grade paper", 2020, "2001.00001", "10/a", "W1", "S1"),
            ("p_weak", "Weak current paper", 2021, "2001.00002", "10/b", "W2", "S2"),
            ("p_stale", "Stale parser paper", 2019, "2001.00003", "10/c", "W3", "S3"),
            ("p_notarget", "No target section paper", 2018, "2001.00004", "10/d", "W4", "S4"),
            ("p_unattempted", "Unattempted PDF paper", 2022, "2001.00005", "10/e", "W5", "S5"),
        ],
    )
    current_explicit = json.dumps(
        {
            "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
            "extraction_strategies": ["explicit_heading"],
        }
    )
    current_weak = json.dumps(
        {
            "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
            "extraction_strategies": ["loose_inline_heading"],
        }
    )
    legacy_explicit = json.dumps({"extraction_strategies": ["explicit_heading"]})
    conn.executemany(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                "p_decision",
                "discussion",
                "decision-grade section evidence " * 10,
                "v14b_section_ingest_v3",
                "https://arxiv.org/pdf/2001.00001.pdf",
                current_explicit,
            ),
            (
                "p_weak",
                "discussion",
                "weak current parser evidence " * 10,
                "v14b_section_ingest_v3",
                "https://arxiv.org/pdf/2001.00002.pdf",
                current_weak,
            ),
            (
                "p_stale",
                "conclusion",
                "legacy parser evidence " * 10,
                "v14b_section_ingest_v2",
                "https://arxiv.org/pdf/2001.00003.pdf",
                legacy_explicit,
            ),
        ],
    )
    conn.executemany(
        """
        INSERT INTO section_ingest_attempts
            (paper_id, attempt_ts, outcome, source_url, detail, inserted_sections,
             primary_sections, candidate_file, parser_name, parser_contract_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "p_notarget",
                "2026-05-31T00:00:00Z",
                "no_target_sections",
                "https://arxiv.org/pdf/2001.00004.pdf",
                "PDF parsed, but no target evidence sections were detected.",
                0,
                0,
                "data/v14b/topic_evidence_gap_delta_queue.csv",
                "v14b_section_ingest_v3",
                SECTION_PARSER_CONTRACT_VERSION,
            )
        ],
    )
    conn.commit()
    conn.close()


def _write_queue(path: Path) -> None:
    fieldnames = [
        "paper_id",
        "priority_score",
        "reasons",
        "eligible_pdf",
        "source_url",
        "title",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for idx, pid in enumerate(
            ["p_decision", "p_weak", "p_stale", "p_notarget", "p_unattempted"],
            start=1,
        ):
            writer.writerow(
                {
                    "paper_id": pid,
                    "priority_score": 100 - idx,
                    "reasons": "topic:metalens|topic_gap:metalens:key_turning_paper_missing_primary_section",
                    "eligible_pdf": "True",
                    "source_url": f"https://arxiv.org/pdf/2001.0000{idx}.pdf",
                    "title": pid,
                }
            )


def test_topic_gap_section_audit_classifies_repair_buckets(tmp_path):
    db = tmp_path / "main.sqlite3"
    queue = tmp_path / "topic_gap.csv"
    out_dir = tmp_path / "reports"
    _make_main(db)
    _write_queue(queue)

    result = run_topic_gap_section_evidence_audit(
        db_main=db,
        topic_gap_queue=queue,
        out_dir=out_dir,
    )

    counts = result["summary"]["failure_mode_counts"]
    assert result["summary"]["status"] == "fail"
    assert counts["decision_grade_current_contract"] == 1
    assert counts["current_contract_weak"] == 1
    assert counts["stale_parser_contract"] == 1
    assert counts["no_target_sections_after_current_parser"] == 1
    assert counts["unattempted_pdf_available"] == 1
    assert result["summary"]["topic_summary"]["metalens"]["papers"] == 5
    assert (out_dir / "topic_gap_section_evidence_audit.md").exists()
    assert (out_dir / "topic_gap_section_evidence_audit.csv").exists()


def test_topic_gap_section_triage_loader_exposes_summary(tmp_path):
    db = tmp_path / "main.sqlite3"
    queue = tmp_path / "topic_gap.csv"
    out_dir = tmp_path / "reports"
    _make_main(db)
    _write_queue(queue)
    run_topic_gap_section_evidence_audit(db_main=db, topic_gap_queue=queue, out_dir=out_dir)

    state = load_topic_gap_section_triage_state(
        out_dir / "topic_gap_section_evidence_audit.json"
    )

    assert state["available"] is True
    assert state["queue_papers"] == 5
    assert state["failure_mode_counts"]["no_target_sections_after_current_parser"] == 1
    assert "before high-confidence promotion" in state["next_action"]
