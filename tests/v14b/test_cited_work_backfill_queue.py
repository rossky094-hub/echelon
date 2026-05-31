from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from echelon.v14b.cited_work_backfill_queue import (
    load_cited_work_backfill_state,
    run_queue,
)


def _make_main(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            publication_year INTEGER,
            openalex_id TEXT,
            doi TEXT,
            arxiv_id TEXT,
            s2_paper_id TEXT
        );
        CREATE TABLE paper_references (
            citing_paper_id TEXT,
            cited_paper_id_external TEXT,
            cited_paper_id_internal TEXT,
            cited_paper_id_provider TEXT,
            cited_paper_id_norm TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("seed_high", "High value seed", 2024, "W1", "10.1/seed", "", ""),
            ("seed_low", "Low value seed", 2023, "W2", "10.2/seed", "", ""),
            ("local_doi", "Existing DOI work", 2020, "W3", "10.1000/existing", "", ""),
            ("local_arxiv", "Existing arXiv work", 2021, "W4", "", "2301.00001", ""),
            ("non_seed", "Non seed", 2022, "W5", "10.5/nonseed", "", ""),
        ],
    )
    conn.executemany(
        "INSERT INTO paper_references VALUES (?, ?, ?, ?, ?)",
        [
            ("seed_high", "10.555/high", "", "doi", "10.555/high"),
            ("seed_high", "https://openalex.org/W999", "", "openalex", "W999"),
            ("seed_high", "2302.00002", "", "arxiv", "2302.00002"),
            ("seed_high", "10.1000/existing", "", "doi", "10.1000/existing"),
            ("seed_high", "10.48550/arxiv.2301.00001", "", "doi", "10.48550/arxiv.2301.00001"),
            ("seed_high", "10.222/linked", "already_local", "doi", "10.222/linked"),
            ("seed_low", "S2:abcdef1234567890abcdef1234567890abcdef12", "", "s2", "abcdef1234567890abcdef1234567890abcdef12"),
            ("non_seed", "10.999/nonseed", "", "doi", "10.999/nonseed"),
        ],
    )
    conn.commit()
    conn.close()


def _make_v14(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE section_priority_papers (
            paper_id TEXT,
            priority_score REAL,
            reasons_json TEXT,
            title TEXT,
            audit_ts TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO section_priority_papers VALUES (?, ?, ?, ?, ?)",
        [
            (
                "seed_high",
                100.0,
                json.dumps(["topic_gap_bottleneck_evidence", "main_path_node"]),
                "High value seed",
                "t2",
            ),
            (
                "seed_low",
                20.0,
                json.dumps(["cluster_representative"]),
                "Low value seed",
                "t2",
            ),
            (
                "stale_seed",
                999.0,
                json.dumps(["topic_gap_claim_card_inputs"]),
                "Stale seed",
                "t1",
            ),
        ],
    )
    conn.commit()
    conn.close()


def test_cited_work_backfill_queue_uses_only_missing_exact_provider_ids(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    _make_main(main)
    _make_v14(v14)

    result = run_queue(
        db_main=main,
        db_v14=v14,
        out_dir=tmp_path / "reports",
        queue_path=tmp_path / "data" / "cited_work_backfill_queue.csv",
        topic_gap_queue=None,
        limit=10,
    )

    rows = result["top_targets"]
    queued = {(row["provider"], row["normalized_id"]) for row in rows}
    assert ("doi", "10.555/high") in queued
    assert ("openalex", "W999") in queued
    assert ("arxiv", "2302.00002") in queued
    assert ("s2", "abcdef1234567890abcdef1234567890abcdef12") in queued

    assert ("doi", "10.1000/existing") not in queued
    assert ("doi", "10.48550/arxiv.2301.00001") not in queued
    assert ("doi", "10.999/nonseed") not in queued
    assert result["summary"]["excluded_status_counts"]["exact_linkable"] == 2


def test_cited_work_backfill_queue_prioritizes_decision_gap_context_and_writes_contract(tmp_path):
    main = tmp_path / "main.sqlite3"
    v14 = tmp_path / "v14.sqlite3"
    queue = tmp_path / "data" / "cited_work_backfill_queue.csv"
    _make_main(main)
    _make_v14(v14)

    result = run_queue(
        db_main=main,
        db_v14=v14,
        out_dir=tmp_path / "reports",
        queue_path=queue,
        topic_gap_queue=None,
        limit=10,
    )

    top = result["top_targets"][0]
    assert top["provider"] == "doi"
    assert top["normalized_id"] == "10.555/high"
    assert top["claim_scope"] == "evidence_frontfill_task"
    assert top["evidence_grade"] == "missing_local_cited_work"
    uncertainty = json.loads(top["uncertainty_reasons_json"])
    assert any("not a scientific conclusion" in reason for reason in uncertainty)
    assert "topic_gap" in top["high_value_categories"]

    state = load_cited_work_backfill_state(queue)
    assert state["available"] is True
    assert state["status"] == "ready"
    assert state["queue_rows"] == 4
    assert state["provider_counts"]["doi"] == 1
