from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3

from echelon.v14b.step5s_section_ingest import (
    SECTION_PARSER_CONTRACT_VERSION,
    SECTION_PARSER_NAME,
    _arxiv_pdf_url,
    _checkpoint_step_name,
    _local_raw_pdf_path,
    _raw_pdf_storage_relpath_for_arxiv,
    _has_current_primary_sections,
    _has_primary_sections,
    _parser_contract_digest,
    _select_candidate_ids,
    ensure_sections_table,
    extract_sections_from_blocks,
    extract_sections_with_metadata,
    load_candidates,
    record_ingest_attempt,
    read_local_raw_pdf,
    read_candidate_file,
    run_section_ingest,
    upsert_sections,
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


def test_raw_pdf_storage_path_matches_downloader_layout():
    assert _raw_pdf_storage_relpath_for_arxiv("2401.12345") == Path("pdfs/arxiv/2401/2401.12345.pdf")
    assert _raw_pdf_storage_relpath_for_arxiv("cond-mat/9704085") == Path(
        "pdfs/arxiv/cond-mat/9704085.pdf"
    )


def test_read_local_raw_pdf_prefers_manifest_success(tmp_path):
    store = tmp_path / "raw_store"
    pdf_path = store / "pdfs" / "arxiv" / "2401" / "2401.12345.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\nlocal cache pdf bytes")
    manifest = store / "manifests" / "raw_pdf_downloads.sqlite3"
    manifest.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(manifest))
    conn.execute(
        """
        CREATE TABLE raw_pdf_downloads (
            paper_id TEXT PRIMARY KEY,
            arxiv_id TEXT,
            status TEXT,
            storage_path TEXT,
            downloaded_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO raw_pdf_downloads VALUES (?, ?, ?, ?, ?, ?)",
        ("p1", "2401.12345", "success", str(pdf_path), "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    blob, path = read_local_raw_pdf(
        {"id": "p1", "arxiv_id": "2401.12345"},
        store_root=store,
        manifest_path=manifest,
    )

    assert blob == b"%PDF-1.4\nlocal cache pdf bytes"
    assert path == pdf_path


def test_read_local_raw_pdf_can_be_disabled_for_network_control(tmp_path):
    store = tmp_path / "raw_store"
    pdf_path = store / "pdfs" / "arxiv" / "2401" / "2401.12345.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\nlocal cache pdf bytes")

    blob, path = read_local_raw_pdf(
        {"id": "p1", "arxiv_id": "2401.12345"},
        store_root=store,
        manifest_path=None,
        prefer_local_raw_pdf=False,
    )

    assert blob is None
    assert path is None


def test_read_local_raw_pdf_matches_manifest_by_doi_when_paper_id_differs(tmp_path):
    store = tmp_path / "raw_store"
    pdf_path = store / "pdfs" / "other" / "doi-paper.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\nlocal cache pdf bytes")
    manifest = store / "manifests" / "raw_pdf_downloads.sqlite3"
    manifest.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(manifest))
    conn.execute(
        """
        CREATE TABLE raw_pdf_downloads (
            paper_id TEXT PRIMARY KEY,
            arxiv_id TEXT,
            doi TEXT,
            s2_paper_id TEXT,
            status TEXT,
            storage_path TEXT,
            downloaded_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO raw_pdf_downloads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "manifest-paper-id",
            "",
            "10.1234/example.paper",
            "",
            "success",
            str(pdf_path),
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    blob, path = read_local_raw_pdf(
        {"id": "candidate-paper-id", "doi": "10.1234/EXAMPLE.PAPER"},
        store_root=store,
        manifest_path=manifest,
    )

    assert blob == b"%PDF-1.4\nlocal cache pdf bytes"
    assert path == pdf_path


def test_read_local_raw_pdf_matches_manifest_by_s2_when_no_arxiv(tmp_path):
    store = tmp_path / "raw_store"
    pdf_path = store / "pdfs" / "other" / "s2-paper.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\nlocal cache pdf bytes")
    manifest = store / "manifests" / "raw_pdf_downloads.sqlite3"
    manifest.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(manifest))
    conn.execute(
        """
        CREATE TABLE raw_pdf_downloads (
            paper_id TEXT PRIMARY KEY,
            arxiv_id TEXT,
            doi TEXT,
            s2_paper_id TEXT,
            status TEXT,
            storage_path TEXT,
            downloaded_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO raw_pdf_downloads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "manifest-paper-id",
            "",
            "",
            "abcdef1234567890abcdef1234567890abcdef12",
            "success",
            str(pdf_path),
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    blob, path = read_local_raw_pdf(
        {"id": "candidate-paper-id", "s2_paper_id": "S2:abcdef1234567890abcdef1234567890abcdef12"},
        store_root=store,
        manifest_path=manifest,
    )

    assert blob == b"%PDF-1.4\nlocal cache pdf bytes"
    assert path == pdf_path


def test_local_raw_pdf_rejects_non_pdf_manifest_hit(tmp_path):
    store = tmp_path / "raw_store"
    bad_path = store / "pdfs" / "arxiv" / "2401" / "2401.12345.pdf"
    bad_path.parent.mkdir(parents=True)
    bad_path.write_bytes(b"not a pdf")
    manifest = store / "manifests" / "raw_pdf_downloads.sqlite3"
    manifest.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(manifest))
    conn.execute(
        """
        CREATE TABLE raw_pdf_downloads (
            paper_id TEXT PRIMARY KEY,
            arxiv_id TEXT,
            status TEXT,
            storage_path TEXT,
            downloaded_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO raw_pdf_downloads VALUES (?, ?, ?, ?, ?, ?)",
        ("p1", "2401.12345", "success", str(bad_path), "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    assert _local_raw_pdf_path(
        {"id": "p1", "arxiv_id": "2401.12345"},
        store_root=store,
        manifest_path=manifest,
    ) is None


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


def test_extract_sections_handles_inline_headings_from_pdf_blocks():
    long_tail = " This paragraph carries concrete claim evidence." * 10
    blocks = [
        _Block("1. Results and Discussion. We compare the failed baseline." + long_tail, page_no=6),
        _Block("Summary and Outlook: The next validation should test scale-up." + long_tail, page_no=7),
        _Block("Methods and experiments - Devices were fabricated and tested." + long_tail, page_no=8),
    ]

    sections = extract_sections_with_metadata(blocks)

    assert "discussion" in sections or "results" in sections
    assert "future_work" in sections
    assert "method" in sections
    assert "inline_heading" in sections["future_work"]["extraction_strategies"]
    assert sections["future_work"]["pages"] == [7]


def test_extract_sections_handles_numbered_headings_embedded_in_flat_pdf_blocks():
    long_tail = " This paragraph carries concrete evidence about the remaining constraint." * 10
    flat_page = (
        "The introduction text is flattened on this page. "
        "4. Results and Discussion The prototype improves throughput but still fails under scale-up."
        f"{long_tail} "
        "5. Conclusions The remaining bottleneck is manufacturing repeatability and validation cost."
        f"{long_tail} "
        "6. References [1] bibliography text should be excluded."
    )

    sections = extract_sections_with_metadata([_Block(flat_page, page_no=11)])

    assert "discussion" in sections or "results" in sections
    assert "conclusion" in sections
    assert "embedded_heading" in sections["conclusion"]["extraction_strategies"]
    assert "References" not in sections["conclusion"]["text"]
    assert sections["conclusion"]["pages"] == [11]


def test_extract_sections_handles_loose_single_word_heading_without_promoting_result_sentences():
    long_tail = " This paragraph carries concrete evidence about the remaining constraint." * 10
    blocks = [
        _Block("Conclusions We find that manufacturing repeatability remains unresolved." + long_tail, page_no=12),
        _Block("Results show that this ordinary sentence is not a section heading." + long_tail, page_no=13),
    ]

    sections = extract_sections_with_metadata(blocks)

    assert "conclusion" in sections
    assert "loose_inline_heading" in sections["conclusion"]["extraction_strategies"]
    assert "results" not in sections
    assert sections["conclusion"]["pages"] == [12]


def test_extract_sections_rejects_table_of_contents_entries():
    blocks = [
        _Block("5.1 Experiments. . . . . . . . . . . . . . . . . . . . 38", page_no=2),
        _Block("11 Summary and perspectives 100", page_no=3),
        _Block(
            "1. Introduction\n"
            + "This review text is an introduction, not section evidence. " * 12,
            page_no=4,
        ),
    ]

    sections = extract_sections_with_metadata(blocks)

    assert "experiments" not in sections
    assert "conclusion" not in sections
    assert "future_work" not in sections


def test_extract_sections_rejects_lowercase_perspectives_fragment():
    blocks = [
        _Block("perspectives.", page_no=6),
        _Block(
            "This sentence follows a wrapped paragraph fragment and should not be "
            "promoted into future-work evidence. " * 10,
            page_no=6,
        ),
    ]

    sections = extract_sections_with_metadata(blocks)

    assert "future_work" not in sections


def test_extract_sections_uses_terminal_summary_as_weak_conclusion_only_on_final_pages():
    long_tail = " This terminal paragraph reports constraints, failed attempts, and measured tradeoffs." * 8
    blocks = [
        _Block(
            "Abstract\nIn summary, this abstract sentence should not become section evidence."
            + long_tail,
            page_no=1,
        ),
        _Block(
            "The middle body has no target headings and remains ordinary narrative." + long_tail,
            page_no=2,
        ),
        _Block(
            "In summary, the device improves quality factor but still suffers from fabrication "
            "drift and packaging sensitivity."
            + long_tail
            + " References [1] bibliography text",
            page_no=3,
        ),
    ]

    sections = extract_sections_with_metadata(blocks)

    assert list(sections) == ["conclusion"]
    assert sections["conclusion"]["pages"] == [3]
    assert sections["conclusion"]["extraction_strategies"] == ["terminal_cue_summary"]
    assert "References" not in sections["conclusion"]["text"]


def test_extract_sections_does_not_use_terminal_summary_when_heading_evidence_exists():
    long_tail = " This paragraph carries concrete claim evidence." * 10
    blocks = [
        _Block("1 Discussion\nThe discussion heading is explicit." + long_tail, page_no=2),
        _Block("In summary, terminal prose exists but should not create a duplicate." + long_tail, page_no=3),
    ]

    sections = extract_sections_with_metadata(blocks)

    assert "discussion" in sections
    assert "conclusion" not in sections


def test_extract_sections_stops_at_references_heading():
    long_tail = " This paragraph carries concrete claim evidence." * 10
    reference_tail = " [1] unrelated bibliography text should not become evidence." * 20
    blocks = [
        _Block("Conclusion\nThe device still has a scale-up bottleneck." + long_tail, page_no=9),
        _Block("References", page_no=10),
        _Block(reference_tail, page_no=10),
    ]

    sections = extract_sections_with_metadata(blocks)

    assert "conclusion" in sections
    assert "bibliography" not in sections["conclusion"]["text"].lower()
    assert "[1]" not in sections["conclusion"]["text"]


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


def test_read_candidate_file_expands_multi_topic_gap_queue_by_priority(tmp_path):
    queue = tmp_path / "multi_topic_evidence_gap_queue.csv"
    queue.write_text(
        "\n".join(
            [
                "topic,gap_type,bottleneck,priority,candidate_paper_ids,frontfill_query,required_sections,why",
                "metalens,future_candidates_missing_claim_card,,85,p_low;p_shared,metalens,limitation,claim",
                "metalens,bottleneck_lineage_missing_topic_specific_typed_chain,efficiency,97,p_high;p_shared,metalens efficiency,limitation,chain",
                "metalens,missing_bottleneck_section_evidence,cost,100,p_top,metalens cost,limitation,bottleneck",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert read_candidate_file(queue) == ["p_top", "p_high", "p_shared", "p_low"]
    assert read_candidate_file(queue, limit=2) == ["p_top", "p_high"]


def test_load_candidates_preserves_evidence_budget_order():
    conn_main = sqlite3.connect(":memory:")
    conn_main.row_factory = sqlite3.Row
    conn_main.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            arxiv_id TEXT,
            doi TEXT,
            s2_paper_id TEXT,
            publication_date TEXT
        );
        """
    )
    conn_main.executemany(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("high_value_gap", "High value topic gap", "2401.00001", "", "", "2001-01-01"),
            ("newer_low_value", "Newer but lower value", "2401.00002", "", "", "2025-01-01"),
            ("branch_driver", "Branch driver", "2401.00003", "", "", "2010-01-01"),
        ],
    )
    conn_v14 = sqlite3.connect(":memory:")

    papers = load_candidates(
        conn_main,
        conn_v14,
        top_n=3,
        candidate_ids=["high_value_gap", "branch_driver", "newer_low_value"],
    )

    assert [p["id"] for p in papers] == [
        "high_value_gap",
        "branch_driver",
        "newer_low_value",
    ]


def test_method_results_sections_count_as_claim_supporting_primary_evidence():
    conn = sqlite3.connect(":memory:")
    ensure_sections_table(conn)
    conn.execute(
        """
        INSERT INTO paper_sections
            (paper_id, section_name, section_text, source_type, parser_name, source_url)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "p_method",
            "method",
            "This method section contains enough experimental mechanism evidence. " * 4,
            "pdf",
            "test",
            "https://arxiv.org/pdf/2401.00001.pdf",
        ),
    )
    conn.commit()

    assert _has_primary_sections(conn, "p_method")


def test_upsert_sections_records_parser_contract_version():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_sections_table(conn)

    upsert_sections(
        conn,
        "p1",
        {
            "discussion": {
                "text": "This discussion section carries decision evidence. " * 5,
                "pages": [2],
                "n_blocks": 1,
                "extraction_strategies": ["explicit_heading"],
            }
        },
        "https://arxiv.org/pdf/2401.00001.pdf",
    )

    row = conn.execute(
        "SELECT parser_name, section_meta_json FROM paper_sections WHERE paper_id='p1'"
    ).fetchone()
    assert row["parser_name"] == SECTION_PARSER_NAME
    assert SECTION_PARSER_CONTRACT_VERSION in row["section_meta_json"]
    assert "toc_dot_leader" in row["section_meta_json"]


def test_upsert_sections_records_local_raw_pdf_delivery():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_sections_table(conn)

    upsert_sections(
        conn,
        "p1",
        {
            "discussion": {
                "text": "This discussion section carries decision evidence. " * 5,
                "pages": [2],
                "n_blocks": 1,
                "extraction_strategies": ["explicit_heading"],
            }
        },
        "https://arxiv.org/pdf/2401.00001.pdf",
        source_storage_uri="/Volumes/LaCie/Echelon_Paper_Raw_Data/pdfs/arxiv/2401/2401.00001.pdf",
    )

    row = conn.execute(
        "SELECT section_meta_json FROM paper_sections WHERE paper_id='p1'"
    ).fetchone()
    meta = json.loads(row["section_meta_json"])
    assert meta["source_delivery"] == "local_raw_pdf_cache"
    assert meta["source_storage_uri"].endswith("2401.00001.pdf")


def test_legacy_primary_sections_do_not_block_current_parser_contract():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_sections_table(conn)
    conn.execute(
        """
        INSERT INTO paper_sections
            (paper_id, section_name, section_text, source_type, parser_name, source_url,
             section_pages_json, section_meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "p1",
            "discussion",
            "Legacy discussion text should be re-parsed under the current contract. " * 3,
            "arxiv_pdf",
            "v14b_section_ingest_v2",
            "https://arxiv.org/pdf/2401.00001.pdf",
            "[]",
            "{}",
        ),
    )

    assert _has_primary_sections(conn, "p1")
    assert not _has_current_primary_sections(conn, "p1")


def test_upsert_replaces_legacy_contract_even_when_new_text_is_shorter():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_sections_table(conn)
    conn.execute(
        """
        INSERT INTO paper_sections
            (paper_id, section_name, section_text, source_type, parser_name, source_url,
             section_pages_json, section_meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "p1",
            "discussion",
            "Legacy noisy table-of-contents and introduction text. " * 12,
            "arxiv_pdf",
            "v14b_section_ingest_v2",
            "https://arxiv.org/pdf/2401.00001.pdf",
            "[]",
            "{}",
        ),
    )

    upsert_sections(
        conn,
        "p1",
        {
            "discussion": {
                "text": "Current guarded discussion evidence. " * 6,
                "pages": [4],
                "n_blocks": 1,
                "extraction_strategies": ["explicit_heading"],
            }
        },
        "https://arxiv.org/pdf/2401.00001.pdf",
    )

    row = conn.execute(
        "SELECT section_text, parser_name, section_meta_json FROM paper_sections WHERE paper_id='p1'"
    ).fetchone()
    assert row["section_text"].startswith("Current guarded discussion evidence.")
    assert row["parser_name"] == SECTION_PARSER_NAME
    assert SECTION_PARSER_CONTRACT_VERSION in row["section_meta_json"]
    assert _has_current_primary_sections(conn, "p1")


def test_upsert_keeps_longer_current_contract_text():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_sections_table(conn)
    upsert_sections(
        conn,
        "p1",
        {
            "discussion": {
                "text": "Long current discussion evidence. " * 12,
                "pages": [4],
                "n_blocks": 1,
                "extraction_strategies": ["explicit_heading"],
            }
        },
        "https://arxiv.org/pdf/2401.00001.pdf",
    )
    upsert_sections(
        conn,
        "p1",
        {
            "discussion": {
                "text": "Short current evidence.",
                "pages": [5],
                "n_blocks": 1,
                "extraction_strategies": ["explicit_heading"],
            }
        },
        "https://arxiv.org/pdf/2401.00001.pdf",
    )

    row = conn.execute(
        "SELECT section_text, section_pages_json FROM paper_sections WHERE paper_id='p1'"
    ).fetchone()
    assert row["section_text"].startswith("Long current discussion evidence.")
    assert row["section_pages_json"] == "[4]"


def test_delta_queue_uses_content_addressed_checkpoint(tmp_path):
    queue = tmp_path / "section_delta_queue.csv"
    queue.write_text("paper_id\np1\np2\n", encoding="utf-8")

    normal_name, normal_digest = _checkpoint_step_name(None)
    delta_name, delta_digest = _checkpoint_step_name(queue)

    contract_digest = _parser_contract_digest()
    assert normal_name == f"step5s_section_ingest_{contract_digest}"
    assert normal_digest == ""
    assert delta_name.startswith("step5s_section_ingest_delta_")
    assert delta_digest
    assert delta_digest in delta_name
    assert contract_digest in delta_name


def test_checkpoint_name_changes_with_parser_contract_version(tmp_path):
    queue = tmp_path / "section_delta_queue.csv"
    queue.write_text("paper_id\np1\n", encoding="utf-8")

    step_name, candidate_digest = _checkpoint_step_name(queue)

    assert SECTION_PARSER_CONTRACT_VERSION
    assert candidate_digest in step_name
    assert _parser_contract_digest() in step_name


def test_checkpoint_name_separates_local_raw_pdf_refresh_mode(tmp_path):
    queue = tmp_path / "section_delta_queue.csv"
    queue.write_text("paper_id\np1\n", encoding="utf-8")

    normal_name, digest = _checkpoint_step_name(queue)
    local_name, local_digest = _checkpoint_step_name(queue, "local_raw_pdf_only_refresh")

    assert digest == local_digest
    assert normal_name != local_name
    assert local_name.endswith("_local_raw_pdf_only_refresh")


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
        """
        SELECT paper_id, outcome, source_url, detail, parser_contract_version
        FROM section_ingest_attempts
        """
    ).fetchone()
    conn.close()
    assert row == (
        "p1",
        "no_target_sections",
        "https://arxiv.org/pdf/2401.00001.pdf",
        "parsed but no target section",
        SECTION_PARSER_CONTRACT_VERSION,
    )


def test_run_section_ingest_refreshes_current_sections_from_local_raw_pdf(tmp_path, monkeypatch):
    import echelon.v14b.config as config
    import echelon.v14b.step5s_section_ingest as mod

    monkeypatch.setattr(config, "CHECKPOINT_DIR", tmp_path / "checkpoints")
    monkeypatch.setattr(
        mod,
        "parse_pdf_pages_with_timeout",
        lambda _path: [
            _Block(
                "1 Results\n"
                + "Local raw cache evidence gives traceable result-section provenance. " * 8,
                page_no=3,
            )
        ],
    )

    db_main = tmp_path / "main.sqlite3"
    db_v14 = tmp_path / "v14.sqlite3"
    store = tmp_path / "raw_store"
    pdf_path = store / "pdfs" / "arxiv" / "2401" / "2401.12345.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\nlocal cache pdf bytes")
    manifest = store / "manifests" / "raw_pdf_downloads.sqlite3"
    manifest.parent.mkdir(parents=True)

    conn_manifest = sqlite3.connect(str(manifest))
    conn_manifest.execute(
        """
        CREATE TABLE raw_pdf_downloads (
            paper_id TEXT PRIMARY KEY,
            arxiv_id TEXT,
            status TEXT,
            storage_path TEXT,
            downloaded_at TEXT
        )
        """
    )
    conn_manifest.execute(
        "INSERT INTO raw_pdf_downloads VALUES (?, ?, ?, ?, ?)",
        ("p1", "2401.12345", "success", str(pdf_path), "2026-01-01T00:00:00Z"),
    )
    conn_manifest.commit()
    conn_manifest.close()

    conn = sqlite3.connect(str(db_main))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            arxiv_id TEXT,
            doi TEXT,
            s2_paper_id TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?)",
        ("p1", "Local cache paper", "2401.12345", "", ""),
    )
    ensure_sections_table(conn)
    conn.execute(
        """
        INSERT INTO paper_sections
            (paper_id, section_name, section_text, source_type, parser_name, source_url,
             section_pages_json, section_meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "p1",
            "results",
            "Short current result evidence. " * 6,
            "arxiv_pdf",
            SECTION_PARSER_NAME,
            "https://arxiv.org/pdf/2401.12345.pdf",
            "[2]",
            json.dumps(
                {
                    "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
                    "extraction_strategies": ["explicit_heading"],
                    "source_delivery": "network_pdf_fetch",
                }
            ),
        ),
    )
    conn.commit()
    conn.close()

    queue = tmp_path / "queue.csv"
    queue.write_text("paper_id\np1\n", encoding="utf-8")

    stats = run_section_ingest(
        db_main=db_main,
        db_v14=db_v14,
        top_n=1,
        limit=1,
        resume=False,
        candidate_file=queue,
        raw_pdf_store_root=store,
        raw_pdf_manifest=manifest,
        local_raw_pdf_only=True,
        refresh_local_raw_pdf=True,
    )

    conn = sqlite3.connect(str(db_main))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT section_text, section_pages_json, section_meta_json FROM paper_sections WHERE paper_id='p1'"
    ).fetchone()
    attempt = conn.execute(
        """
        SELECT outcome, detail
        FROM section_ingest_attempts
        WHERE paper_id='p1'
        ORDER BY attempt_id DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()

    meta = json.loads(row["section_meta_json"])
    assert stats["local_raw_pdf_cache_hits"] == 1
    assert stats["network_pdf_fetches"] == 0
    assert stats["refresh_local_raw_pdf"] is True
    assert row["section_text"].startswith("Local raw cache evidence")
    assert row["section_pages_json"] == "[3]"
    assert meta["source_delivery"] == "local_raw_pdf_cache"
    assert meta["source_storage_uri"] == str(pdf_path)
    assert attempt["outcome"] == "success_primary"
    assert "PDF bytes loaded from raw cache" in attempt["detail"]
