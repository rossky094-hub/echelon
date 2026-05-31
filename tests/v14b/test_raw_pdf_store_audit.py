from __future__ import annotations

import json
import sqlite3

from echelon.v14b.raw_pdf_store_audit import (
    load_manifest_summary,
    load_queue_raw_pdf_coverage,
    load_section_reuse_summary,
    run_raw_pdf_store_audit,
)


def _create_manifest(path, rows):
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE raw_pdf_downloads (
            paper_id TEXT PRIMARY KEY,
            arxiv_id TEXT,
            doi TEXT,
            s2_paper_id TEXT,
            storage_path TEXT,
            status TEXT,
            size_bytes INTEGER,
            first_seen_at TEXT,
            updated_at TEXT,
            downloaded_at TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO raw_pdf_downloads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_raw_pdf_store_audit_reports_manifest_reuse_and_queue_coverage(tmp_path):
    store = tmp_path / "raw_store"
    p1_pdf = store / "pdfs" / "arxiv" / "2401" / "2401.00001.pdf"
    p2_pdf = store / "pdfs" / "other" / "doi-paper.pdf"
    p1_pdf.parent.mkdir(parents=True)
    p2_pdf.parent.mkdir(parents=True)
    p1_pdf.write_bytes(b"%PDF-1.4\np1")
    p2_pdf.write_bytes(b"%PDF-1.4\np2")
    manifest = store / "manifests" / "raw_pdf_downloads.sqlite3"
    now = "2026-01-01T00:00:00Z"
    _create_manifest(
        manifest,
        [
            ("p1", "2401.00001", "", "", str(p1_pdf), "success", p1_pdf.stat().st_size, now, now, now),
            ("manifest-p2", "", "10.1234/example.paper", "", str(p2_pdf), "success", p2_pdf.stat().st_size, now, now, now),
            ("p3", "", "", "", "", "queued", 0, now, now, ""),
        ],
    )

    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            arxiv_id TEXT,
            doi TEXT,
            s2_paper_id TEXT,
            title TEXT
        );
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_meta_json TEXT
        );
        CREATE TABLE section_ingest_attempts (
            paper_id TEXT,
            detail TEXT,
            source_url TEXT
        );
        """
    )
    conn.execute("INSERT INTO papers VALUES ('p1', '2401.00001', '', '', 'Arxiv paper')")
    conn.execute("INSERT INTO papers VALUES ('p2', '', '10.1234/EXAMPLE.PAPER', '', 'DOI paper')")
    conn.execute("INSERT INTO papers VALUES ('p3', '', '', '', 'Missing paper')")
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?)",
        ("p1", "discussion", json.dumps({"source_delivery": "local_raw_pdf_cache"})),
    )
    conn.execute(
        "INSERT INTO section_ingest_attempts VALUES (?, ?, ?)",
        ("p1", "PDF bytes loaded from raw cache: /tmp/p1.pdf", "file:///tmp/p1.pdf"),
    )
    conn.commit()
    conn.close()

    queue = tmp_path / "queue.csv"
    queue.write_text("paper_id\np1\np2\np3\n", encoding="utf-8")
    out_dir = tmp_path / "reports"

    summary = run_raw_pdf_store_audit(
        db_main=db,
        store_root=store,
        manifest_path=manifest,
        candidate_file=queue,
        out_dir=out_dir,
    )

    assert summary["manifest"]["success_papers"] == 2
    assert summary["manifest"]["success_probable_pdfs"] == 2
    assert summary["section_reuse"]["local_raw_pdf_section_papers"] == 1
    assert summary["section_reuse"]["local_raw_pdf_success_attempts"] == 1
    assert summary["candidate_queue_coverage"]["queue_papers"] == 3
    assert summary["candidate_queue_coverage"]["raw_pdf_available_papers"] == 2
    assert summary["status"] == "pass"
    assert (out_dir / "raw_pdf_store_audit.md").exists()


def test_raw_pdf_store_audit_warns_when_cache_is_not_consumed(tmp_path):
    store = tmp_path / "raw_store"
    p1_pdf = store / "pdfs" / "arxiv" / "2401" / "2401.00001.pdf"
    p1_pdf.parent.mkdir(parents=True)
    p1_pdf.write_bytes(b"%PDF-1.4\np1")
    manifest = store / "manifests" / "raw_pdf_downloads.sqlite3"
    now = "2026-01-01T00:00:00Z"
    _create_manifest(
        manifest,
        [("p1", "2401.00001", "", "", str(p1_pdf), "success", p1_pdf.stat().st_size, now, now, now)],
    )

    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE papers (id TEXT PRIMARY KEY, arxiv_id TEXT, doi TEXT, s2_paper_id TEXT, title TEXT)")
    conn.execute("INSERT INTO papers VALUES ('p1', '2401.00001', '', '', 'Arxiv paper')")
    conn.commit()
    conn.close()

    summary = run_raw_pdf_store_audit(
        db_main=db,
        store_root=store,
        manifest_path=manifest,
        candidate_file=None,
        out_dir=tmp_path / "reports",
    )

    assert summary["status"] == "warn"
    assert any("has not consumed" in item for item in summary["warnings"])


def test_raw_pdf_store_audit_small_loaders_handle_missing_inputs(tmp_path):
    assert load_manifest_summary(None, None)["status"] == "not_configured"

    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE papers (id TEXT PRIMARY KEY, arxiv_id TEXT, doi TEXT, s2_paper_id TEXT, title TEXT)")
    conn.commit()
    conn.close()

    assert load_section_reuse_summary(db)["local_raw_pdf_section_papers"] == 0
    coverage = load_queue_raw_pdf_coverage(
        db,
        store_root=None,
        manifest_path=None,
        candidate_file=tmp_path / "missing.csv",
    )
    assert coverage["queue_papers"] == 0
