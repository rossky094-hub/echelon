from dataclasses import dataclass
import sqlite3

from echelon.v14b.step5s_section_ingest import (
    _arxiv_pdf_url,
    _select_candidate_ids,
    ensure_sections_table,
    extract_sections_from_blocks,
    extract_sections_with_metadata,
    record_ingest_attempt,
    read_candidate_file,
)


@dataclass
class _Block:
    text: str
    section_hint: str = "body"
    page_no: int = 1


def test_arxiv_pdf_url_from_arxiv_id_and_doi():
    assert _arxiv_pdf_url("2401.12345v2", None) == "https://arxiv.org/pdf/2401.12345.pdf"
    assert _arxiv_pdf_url(None, "10.48550/arXiv.2301.00001v3") == "https://arxiv.org/pdf/2301.00001.pdf"
    assert _arxiv_pdf_url(None, "10.1000/journal.paper") is None


def test_extract_sections_from_blocks_captures_primary_and_secondary_sections():
    long_tail = " This paragraph describes concrete technical constraints and evidence." * 8
    blocks = [
        _Block("1 Discussion\nWe analyze unresolved constraints." + long_tail),
        _Block("2 Future Work\nFuture work requires better noise suppression." + long_tail),
        _Block("3 Error Analysis\nFailure cases remain in low-SNR regime." + long_tail),
        _Block("4 Ablation Study\nAblation indicates coupling instability." + long_tail),
        _Block("5 Conclusion\nThe remaining bottleneck is fabrication tolerance." + long_tail),
    ]
    sections = extract_sections_from_blocks(blocks)
    assert "discussion" in sections
    assert "future_work" in sections
    assert "conclusion" in sections
    assert "error_analysis" in sections
    assert "ablation" in sections
    for text in sections.values():
        assert len(text) >= 160


def test_extract_sections_with_metadata_includes_page_numbers():
    long_tail = " Evidence sentence for parser coverage." * 10
    blocks = [
        _Block("1 Limitations\nConstraint persists." + long_tail, page_no=4),
        _Block("2 Discussion\nWe compare failures." + long_tail, page_no=5),
    ]
    sections = extract_sections_with_metadata(blocks)
    assert "limitations" in sections
    assert "discussion" in sections
    assert sections["limitations"]["pages"] == [4]
    assert sections["discussion"]["pages"] == [5]
    assert len(sections["limitations"]["text"]) >= 160


def test_select_candidate_ids_fills_beyond_keystone_rows():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE subgraph_nodes (
            paper_id TEXT PRIMARY KEY,
            keystone_score_v14 REAL,
            is_keystone BOOLEAN,
            node_size REAL
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO subgraph_nodes
            (paper_id, keystone_score_v14, is_keystone, node_size)
        VALUES (?, ?, ?, ?)
        """,
        [
            ("k1", 0.9, 1, 10.0),
            ("k2", 0.8, 1, 9.0),
            ("n1", 0.7, 0, 8.0),
            ("n2", 0.6, 0, 7.0),
            ("n3", 0.5, 0, 6.0),
        ],
    )
    ids = _select_candidate_ids(conn, 5)
    assert ids == ["k1", "k2", "n1", "n2", "n3"]


def test_select_candidate_ids_prioritizes_prediction_and_branch_evidence():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE subgraph_nodes (
            paper_id TEXT PRIMARY KEY,
            keystone_score_v14 REAL,
            is_keystone BOOLEAN,
            node_size REAL
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
        CREATE TABLE main_path_edges (
            source_paper_id TEXT,
            target_paper_id TEXT,
            is_main_path INTEGER,
            main_path_weight REAL,
            spc REAL
        );
        CREATE TABLE branch_lineages (
            split_evidence_json TEXT,
            split_confidence REAL
        );
        CREATE TABLE visual_nodes (
            paper_id TEXT,
            cluster_id TEXT,
            node_size REAL
        );
        """
    )
    conn.executemany(
        "INSERT INTO subgraph_nodes VALUES (?, ?, ?, ?)",
        [
            ("k1", 0.9, 1, 10.0),
            ("k2", 0.8, 1, 9.0),
            ("n1", 0.7, 0, 8.0),
        ],
    )
    conn.executemany(
        "INSERT INTO predicted_future_edges VALUES (?, ?, ?, ?)",
        [
            ("future_src_1", "future_dst_1", 0.9, 0.8),
            ("future_src_2", "future_dst_2", 0.8, 0.7),
        ],
    )
    conn.execute("INSERT INTO limitation_atoms VALUES ('limitation_paper', 'high', 0.9)")
    conn.execute("INSERT INTO main_path_edges VALUES ('main_old', 'main_new', 1, 0.8, 5.0)")
    conn.execute(
        "INSERT INTO branch_lineages VALUES (?, ?)",
        ('{"driver_papers":["branch_driver"]}', 0.9),
    )
    conn.executemany(
        "INSERT INTO visual_nodes VALUES (?, ?, ?)",
        [
            ("cluster_rep_a", "C1", 10.0),
            ("cluster_rep_b", "C2", 9.0),
        ],
    )

    ids = _select_candidate_ids(conn, 12)

    assert ids[:10] == [
        "future_src_1",
        "future_src_2",
        "future_dst_1",
        "future_dst_2",
        "limitation_paper",
        "main_old",
        "main_new",
        "k1",
        "k2",
        "branch_driver",
    ]
    assert "cluster_rep_a" in ids
    assert "cluster_rep_b" in ids


def test_read_candidate_file_accepts_delta_queue_csv(tmp_path):
    queue = tmp_path / "section_delta_queue.csv"
    queue.write_text(
        "paper_id,priority_score,reasons\np1,10,main_path\np2,9,future\np1,8,duplicate\n",
        encoding="utf-8",
    )

    assert read_candidate_file(queue) == ["p1", "p2"]
    assert read_candidate_file(queue, limit=1) == ["p1"]


def test_section_ingest_records_attempt_outcomes(tmp_path):
    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    ensure_sections_table(conn)

    record_ingest_attempt(
        conn,
        paper_id="p1",
        outcome="no_target_sections",
        run_id="run1",
        source_url="https://arxiv.org/pdf/2401.00001.pdf",
        detail="parsed but no target section",
        inserted_sections=0,
        primary_sections=0,
    )
    conn.commit()

    row = conn.execute(
        "SELECT paper_id, outcome, source_url, detail FROM section_ingest_attempts"
    ).fetchone()
    conn.close()
    assert row == (
        "p1",
        "no_target_sections",
        "https://arxiv.org/pdf/2401.00001.pdf",
        "parsed but no target section",
    )
