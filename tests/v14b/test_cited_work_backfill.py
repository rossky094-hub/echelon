from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from echelon.v14b.cited_work_backfill import FetchResult, load_cited_work_backfill_run_state, run_backfill
from echelon.v14b.cited_work_backfill_queue import QUEUE_FIELDNAMES


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            openalex_id TEXT,
            doi TEXT,
            arxiv_id TEXT,
            title TEXT NOT NULL,
            abstract TEXT,
            publication_date TEXT NOT NULL,
            publication_year INTEGER,
            n_authors INTEGER,
            cited_by_count INTEGER,
            primary_topic_id TEXT,
            primary_subfield_id TEXT,
            primary_field_id TEXT,
            primary_domain_id TEXT,
            venue_id TEXT,
            is_retracted INTEGER,
            is_paratext INTEGER,
            language TEXT,
            open_access TEXT,
            raw_jsonb TEXT,
            first_ingested_at TEXT,
            last_refreshed_at TEXT,
            source_provider TEXT,
            ingestion_job_id TEXT,
            openalex_enriched INTEGER,
            corpus_id TEXT,
            s2_paper_id TEXT
        );
        CREATE TABLE paper_references (
            citing_paper_id TEXT NOT NULL,
            cited_paper_id_external TEXT NOT NULL,
            cited_paper_id_internal TEXT,
            cited_paper_id_provider TEXT,
            cited_paper_id_norm TEXT,
            PRIMARY KEY (citing_paper_id, cited_paper_id_external)
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO papers
            (id, openalex_id, doi, title, publication_date, publication_year, corpus_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("seed", "WSEED", "10.seed/a", "Seed", "2024-01-01", 2024, "optics"),
            ("existing", "WEXIST", "10.existing/a", "Existing", "2020-01-01", 2020, "optics"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO paper_references
            (citing_paper_id, cited_paper_id_external, cited_paper_id_internal,
             cited_paper_id_provider, cited_paper_id_norm)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("seed", "W999", "", "openalex", "W999"),
            ("seed", "WEXIST", "", "openalex", "WEXIST"),
        ],
    )
    conn.commit()
    conn.close()


def _write_queue(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"rank": 1, "priority_score": 100.0, "provider": "openalex", "normalized_id": "W999", "citing_paper_count": 5},
        {"rank": 2, "priority_score": 90.0, "provider": "doi", "normalized_id": "10.555/new", "citing_paper_count": 4},
        {"rank": 3, "priority_score": 80.0, "provider": "openalex", "normalized_id": "WEXIST", "citing_paper_count": 3},
        {"rank": 4, "priority_score": 70.0, "provider": "s2", "normalized_id": "abcdef", "citing_paper_count": 2},
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=QUEUE_FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            payload = {name: "" for name in QUEUE_FIELDNAMES}
            payload.update(row)
            payload["claim_scope"] = "evidence_frontfill_task"
            payload["evidence_grade"] = "missing_local_cited_work"
            writer.writerow(payload)


def _work(openalex_id: str, doi: str, title: str) -> dict:
    return {
        "id": f"https://openalex.org/{openalex_id}",
        "doi": f"https://doi.org/{doi}",
        "title": title,
        "publication_year": 2021,
        "publication_date": "2021-05-10",
        "cited_by_count": 42,
        "primary_topic": {
            "id": "https://openalex.org/T1",
            "subfield": {"id": "https://openalex.org/S1"},
            "field": {"id": "https://openalex.org/F1"},
            "domain": {"id": "https://openalex.org/D1"},
        },
        "topics": [],
        "authorships": [{"author": {"display_name": "A"}}],
        "referenced_works": ["https://openalex.org/W1001", "https://openalex.org/W1002"],
        "locations": [],
        "ids": {"openalex": f"https://openalex.org/{openalex_id}", "doi": f"https://doi.org/{doi}"},
        "open_access": {"is_oa": True},
        "language": "en",
        "is_retracted": False,
        "type": "article",
        "abstract_inverted_index": {"hello": [0], "world": [1]},
    }


def test_cited_work_backfill_inserts_exact_work_and_relinks(tmp_path):
    db = tmp_path / "main.sqlite3"
    queue = tmp_path / "queue.csv"
    out_dir = tmp_path / "reports"
    _make_db(db)
    _write_queue(queue)

    def fetcher(target):
        if target.provider == "openalex":
            return FetchResult(_work("W999", "10.999/new", "OpenAlex target"), http_status=200)
        if target.provider == "doi":
            return FetchResult(_work("W555", "10.555/new", "DOI target"), http_status=200)
        raise AssertionError(target.provider)

    result = run_backfill(
        db_main=db,
        queue_path=queue,
        out_dir=out_dir,
        limit=10,
        providers=("openalex", "doi"),
        corpus_id="optics",
        dry_run=False,
        apply_relinks=True,
        fetcher=fetcher,
    )

    assert result["summary"]["status_counts"]["inserted"] == 2
    assert result["summary"]["status_counts"]["skip_existing_local_work"] == 1
    assert result["summary"]["relink_apply_result"]["apply_result"]["link_updates_applied"] >= 1

    conn = sqlite3.connect(str(db))
    linked = conn.execute(
        """
        SELECT cited_paper_id_internal
        FROM paper_references
        WHERE citing_paper_id='seed' AND cited_paper_id_external='W999'
        """
    ).fetchone()[0]
    assert linked
    assert conn.execute("SELECT COUNT(*) FROM paper_references WHERE citing_paper_id=?", (linked,)).fetchone()[0] == 2
    assert conn.execute("SELECT corpus_id FROM papers WHERE id=?", (linked,)).fetchone()[0] == "optics"
    assert conn.execute("SELECT COUNT(*) FROM paper_corpora WHERE paper_id=? AND corpus_id='optics'", (linked,)).fetchone()[0] == 1
    conn.close()

    state = load_cited_work_backfill_run_state(out_dir / "cited_work_backfill_run.json")
    assert state["available"] is True
    assert state["inserted_or_updated"] == 2


def test_cited_work_backfill_rejects_identity_mismatch(tmp_path):
    db = tmp_path / "main.sqlite3"
    queue = tmp_path / "queue.csv"
    _make_db(db)
    _write_queue(queue)

    def fetcher(_target):
        return FetchResult(_work("WOTHER", "10.other/value", "Wrong target"), http_status=200)

    result = run_backfill(
        db_main=db,
        queue_path=queue,
        out_dir=tmp_path / "reports",
        limit=1,
        providers=("openalex",),
        corpus_id="optics",
        fetcher=fetcher,
    )

    assert result["summary"]["status_counts"] == {"identity_mismatch": 1}
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM papers WHERE openalex_id='WOTHER'").fetchone()[0] == 0
    conn.close()
