from __future__ import annotations

import sqlite3

from echelon.v14b.corpus_registry import ensure_corpus_schema, register_corpus
from echelon.v14b.quarterly_run import _bootstrap_corpus_membership


def test_bootstrap_corpus_membership_assigns_from_keyword(tmp_path):
    db = tmp_path / "library.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            abstract TEXT,
            raw_jsonb TEXT,
            primary_topic_id TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO papers(id, title, abstract, raw_jsonb, primary_topic_id)
        VALUES
            ('p1', 'Optics paper A', 'laser optics', '{"topic":"optics"}', 'physics.optics'),
            ('p2', 'Optics paper B', 'photonics', '{"topic":"optics"}', 'physics.optics'),
            ('p3', 'Other paper', 'math', '{"topic":"math"}', 'math')
        """
    )
    conn.commit()

    ensure_corpus_schema(conn)
    register_corpus(conn, corpus_id="optics", corpus_name="Optics")

    scoped = _bootstrap_corpus_membership(
        conn,
        corpus_id="optics",
        set_spec="physics:physics:optics",
    )
    assert scoped >= 2
    mapped = conn.execute(
        "SELECT COUNT(*) FROM paper_corpora WHERE corpus_id='optics'"
    ).fetchone()[0]
    assert mapped >= 2
    conn.close()

