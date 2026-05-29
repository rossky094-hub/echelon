from __future__ import annotations

import sqlite3

from echelon.v14b.corpus_registry import (
    create_temp_corpus_table,
    ensure_corpus_schema,
    register_corpus,
    write_corpus_snapshot,
)


def test_corpus_schema_and_scope(tmp_path):
    db = tmp_path / "library.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            corpus_id TEXT
        )
        """
    )
    conn.execute("INSERT INTO papers(id, title) VALUES ('p1', 'a')")
    conn.execute("INSERT INTO papers(id, title) VALUES ('p2', 'b')")
    conn.commit()

    ensure_corpus_schema(conn)
    register_corpus(conn, corpus_id="optics", corpus_name="Optics")
    conn.execute(
        "INSERT INTO paper_corpora(paper_id, corpus_id) VALUES ('p1', 'optics')"
    )
    conn.commit()

    scoped = create_temp_corpus_table(conn, "optics")
    assert scoped == 1
    row = conn.execute("SELECT COUNT(*) FROM temp.v14b_corpus_papers").fetchone()
    assert row[0] == 1

    write_corpus_snapshot(
        conn,
        snapshot_id="s1",
        corpus_id="optics",
        quarter_id="2026Q2",
        run_id="r1",
        db_v14_path="db/v14_optics.sqlite3",
        report_dir="reports/v14b_pilot",
        metrics={"papers": 1, "refs": 0},
    )
    snap = conn.execute(
        "SELECT corpus_id, quarter_id, papers FROM corpus_snapshots WHERE snapshot_id='s1'"
    ).fetchone()
    assert snap[0] == "optics"
    assert snap[1] == "2026Q2"
    assert snap[2] == 1
    conn.close()
