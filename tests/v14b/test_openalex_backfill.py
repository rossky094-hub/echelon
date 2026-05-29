from __future__ import annotations

import sqlite3

from echelon.v14b.step0_openalex_backfill import load_targets


def test_load_targets_includes_missing_openalex_even_when_field_present():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            doi TEXT,
            arxiv_id TEXT,
            openalex_id TEXT,
            primary_field_id TEXT,
            primary_topic_id TEXT,
            publication_date TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO papers
            (id, doi, arxiv_id, openalex_id, primary_field_id, primary_topic_id, publication_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("missing_w_with_field", "10.1/a", None, None, "F1", "T1", "2020-01-01"),
            ("s2_topic_with_w", "10.1/b", None, "W123", "F1", "S2F:physics", "2020-01-02"),
            ("complete", "10.1/c", None, "W456", "F1", "T1", "2020-01-03"),
            ("no_lookup_id", None, None, None, "F1", "T1", "2020-01-04"),
        ],
    )
    targets = [row["id"] for row in load_targets(conn)]
    assert "missing_w_with_field" in targets
    assert "s2_topic_with_w" in targets
    assert "complete" not in targets
    assert "no_lookup_id" not in targets

