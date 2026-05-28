import sqlite3

from echelon.v14b.step0_id_repair import backfill_field_topic_local, infer_field_from_topic


def test_infer_field_from_topic_rules():
    assert infer_field_from_topic("S2F:physics") == "31"
    assert infer_field_from_topic("physics.optics") == "31"
    assert infer_field_from_topic("cs.LG") == "17"
    assert infer_field_from_topic("cond-mat.mtrl-sci") == "25"
    assert infer_field_from_topic("unknown.topic") is None


def test_backfill_field_topic_local_uses_topic_table_and_rules(tmp_path):
    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            primary_topic_id TEXT,
            primary_field_id TEXT,
            primary_subfield_id TEXT,
            primary_domain_id TEXT
        );
        CREATE TABLE topics_hierarchy (
            topic_id TEXT PRIMARY KEY,
            field_id TEXT,
            subfield_id TEXT,
            domain_id TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO papers(id, primary_topic_id, primary_field_id, primary_subfield_id, primary_domain_id) VALUES (?, ?, ?, ?, ?)",
        [
            ("p1", "T100", None, None, None),          # from topics_hierarchy
            ("p2", "S2F:physics", None, None, None),   # from local rule
            ("p3", "physics.optics", None, None, None),# from local rule
            ("p4", "unknown", None, None, None),       # stays null
        ],
    )
    conn.execute(
        "INSERT INTO topics_hierarchy(topic_id, field_id, subfield_id, domain_id) VALUES (?, ?, ?, ?)",
        ("T100", "22", "S3107", "D3"),
    )
    conn.commit()

    stats = backfill_field_topic_local(conn)
    assert stats["field_backfill_from_topics_hierarchy"] == 1
    assert stats["field_backfill_from_local_rules"] >= 2

    rows = {
        r[0]: (r[1], r[2], r[3])
        for r in conn.execute(
            "SELECT id, primary_field_id, primary_subfield_id, primary_domain_id FROM papers"
        ).fetchall()
    }
    conn.close()

    assert rows["p1"] == ("22", "S3107", "D3")
    assert rows["p2"][0] == "31"
    assert rows["p3"][0] == "31"
    assert rows["p4"][0] is None
