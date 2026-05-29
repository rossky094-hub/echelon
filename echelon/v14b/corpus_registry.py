"""Corpus registry + quarterly snapshot helpers for V14B.

This module introduces multi-corpus runtime primitives without changing the
core paper schema semantics:

- corpus_registry: corpus metadata and source hints
- paper_corpora: many-to-many paper membership
- corpus_runs: quarterly (or ad-hoc) pipeline run ledger
- corpus_snapshots: comparable per-run snapshots for trend deltas
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def normalize_corpus_id(corpus_id: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", (corpus_id or "").strip().lower())
    value = value.strip("-")
    if not value:
        raise ValueError("corpus_id is required")
    return value


def ensure_corpus_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS corpus_registry (
            corpus_id TEXT PRIMARY KEY,
            corpus_name TEXT NOT NULL,
            description TEXT,
            source_provider TEXT,
            source_set_spec TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS paper_corpora (
            paper_id TEXT NOT NULL,
            corpus_id TEXT NOT NULL,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            assignment_source TEXT DEFAULT 'manual',
            score REAL,
            PRIMARY KEY (paper_id, corpus_id)
        );

        CREATE INDEX IF NOT EXISTS idx_paper_corpora_corpus
            ON paper_corpora(corpus_id, assigned_at DESC);
        CREATE INDEX IF NOT EXISTS idx_paper_corpora_paper
            ON paper_corpora(paper_id);

        CREATE TABLE IF NOT EXISTS corpus_runs (
            run_id TEXT PRIMARY KEY,
            corpus_id TEXT NOT NULL,
            quarter_id TEXT,
            run_type TEXT NOT NULL DEFAULT 'quarterly',
            status TEXT NOT NULL DEFAULT 'running',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP,
            db_v14_path TEXT,
            report_dir TEXT,
            notes_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_corpus_runs_corpus
            ON corpus_runs(corpus_id, started_at DESC);

        CREATE TABLE IF NOT EXISTS corpus_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            corpus_id TEXT NOT NULL,
            quarter_id TEXT,
            run_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            db_v14_path TEXT,
            report_dir TEXT,
            papers INTEGER DEFAULT 0,
            refs INTEGER DEFAULT 0,
            linked_refs INTEGER DEFAULT 0,
            future_directions INTEGER DEFAULT 0,
            visual_nodes INTEGER DEFAULT 0,
            visual_edges INTEGER DEFAULT 0,
            metrics_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_corpus_snapshots_corpus
            ON corpus_snapshots(corpus_id, created_at DESC);
        """
    )
    try:
        conn.execute("ALTER TABLE papers ADD COLUMN corpus_id TEXT")
    except sqlite3.Error:
        pass
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_papers_corpus_id ON papers(corpus_id)"
    )
    conn.commit()


def register_corpus(
    conn: sqlite3.Connection,
    *,
    corpus_id: str,
    corpus_name: str,
    description: str | None = None,
    source_provider: str | None = None,
    source_set_spec: str | None = None,
    status: str = "active",
) -> None:
    ensure_corpus_schema(conn)
    cid = normalize_corpus_id(corpus_id)
    conn.execute(
        """
        INSERT INTO corpus_registry
            (corpus_id, corpus_name, description, source_provider, source_set_spec, status, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(corpus_id) DO UPDATE SET
            corpus_name = excluded.corpus_name,
            description = COALESCE(excluded.description, corpus_registry.description),
            source_provider = COALESCE(excluded.source_provider, corpus_registry.source_provider),
            source_set_spec = COALESCE(excluded.source_set_spec, corpus_registry.source_set_spec),
            status = COALESCE(excluded.status, corpus_registry.status),
            updated_at = CURRENT_TIMESTAMP
        """,
        (cid, corpus_name, description, source_provider, source_set_spec, status),
    )
    conn.commit()


def assign_paper_to_corpus(
    conn: sqlite3.Connection,
    *,
    paper_id: str,
    corpus_id: str,
    assignment_source: str = "ingest",
    score: float | None = None,
) -> None:
    ensure_corpus_schema(conn)
    cid = normalize_corpus_id(corpus_id)
    conn.execute(
        """
        INSERT OR REPLACE INTO paper_corpora
            (paper_id, corpus_id, assigned_at, assignment_source, score)
        VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
        """,
        (paper_id, cid, assignment_source, score),
    )
    conn.execute(
        """
        UPDATE papers
        SET corpus_id = COALESCE(corpus_id, ?)
        WHERE id = ?
        """,
        (cid, paper_id),
    )
    conn.commit()


def bulk_assign_by_topic_keyword(
    conn: sqlite3.Connection,
    *,
    corpus_id: str,
    topic_keyword: str,
    assignment_source: str = "topic_keyword",
) -> int:
    """Assign papers whose topic/raw_json contains keyword."""
    ensure_corpus_schema(conn)
    cid = normalize_corpus_id(corpus_id)
    keyword = (topic_keyword or "").strip().lower()
    if not keyword:
        return 0
    rows = conn.execute(
        """
        SELECT id
        FROM papers
        WHERE lower(COALESCE(primary_topic_id, '')) LIKE ?
           OR lower(COALESCE(raw_jsonb, '')) LIKE ?
        """,
        (f"%{keyword}%", f"%{keyword}%"),
    ).fetchall()
    if not rows:
        return 0
    payload = [(str(r[0]), cid, assignment_source) for r in rows]
    conn.executemany(
        """
        INSERT OR REPLACE INTO paper_corpora
            (paper_id, corpus_id, assigned_at, assignment_source, score)
        VALUES (?, ?, CURRENT_TIMESTAMP, ?, NULL)
        """,
        payload,
    )
    conn.execute(
        """
        UPDATE papers
        SET corpus_id = COALESCE(corpus_id, ?)
        WHERE id IN (SELECT paper_id FROM paper_corpora WHERE corpus_id = ?)
        """,
        (cid, cid),
    )
    conn.commit()
    return len(payload)


def create_temp_corpus_table(
    conn: sqlite3.Connection,
    corpus_id: str | None,
    *,
    table_name: str = "v14b_corpus_papers",
) -> int:
    """Create TEMP table for corpus paper IDs; returns row count."""
    conn.execute(f"DROP TABLE IF EXISTS temp.{table_name}")
    if not corpus_id:
        return 0
    ensure_corpus_schema(conn)
    cid = normalize_corpus_id(corpus_id)
    conn.execute(
        f"CREATE TEMP TABLE {table_name} (paper_id TEXT PRIMARY KEY)"
    )
    conn.execute(
        f"""
        INSERT OR IGNORE INTO {table_name}(paper_id)
        SELECT paper_id FROM paper_corpora WHERE corpus_id = ?
        """,
        (cid,),
    )
    conn.execute(
        f"""
        INSERT OR IGNORE INTO {table_name}(paper_id)
        SELECT id FROM papers WHERE corpus_id = ?
        """,
        (cid,),
    )
    cnt = int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
    return cnt


def begin_corpus_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    corpus_id: str,
    quarter_id: str | None,
    run_type: str = "quarterly",
    db_v14_path: str | None = None,
    report_dir: str | None = None,
    notes: dict[str, Any] | None = None,
) -> None:
    ensure_corpus_schema(conn)
    cid = normalize_corpus_id(corpus_id)
    conn.execute(
        """
        INSERT OR REPLACE INTO corpus_runs
            (run_id, corpus_id, quarter_id, run_type, status, started_at,
             finished_at, db_v14_path, report_dir, notes_json)
        VALUES (?, ?, ?, ?, 'running', CURRENT_TIMESTAMP, NULL, ?, ?, ?)
        """,
        (
            run_id,
            cid,
            quarter_id,
            run_type,
            db_v14_path,
            report_dir,
            json.dumps(notes or {}, ensure_ascii=False),
        ),
    )
    conn.commit()


def finish_corpus_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    status: str,
    notes: dict[str, Any] | None = None,
) -> None:
    ensure_corpus_schema(conn)
    conn.execute(
        """
        UPDATE corpus_runs
        SET status = ?,
            finished_at = CURRENT_TIMESTAMP,
            notes_json = COALESCE(?, notes_json)
        WHERE run_id = ?
        """,
        (
            status,
            json.dumps(notes, ensure_ascii=False) if notes is not None else None,
            run_id,
        ),
    )
    conn.commit()


def write_corpus_snapshot(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    corpus_id: str,
    quarter_id: str | None,
    run_id: str | None,
    db_v14_path: str | None,
    report_dir: str | None,
    metrics: dict[str, Any],
) -> None:
    ensure_corpus_schema(conn)
    cid = normalize_corpus_id(corpus_id)
    conn.execute(
        """
        INSERT OR REPLACE INTO corpus_snapshots
            (snapshot_id, corpus_id, quarter_id, run_id, created_at,
             db_v14_path, report_dir, papers, refs, linked_refs,
             future_directions, visual_nodes, visual_edges, metrics_json)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            cid,
            quarter_id,
            run_id,
            db_v14_path,
            report_dir,
            int(metrics.get("papers", 0)),
            int(metrics.get("refs", 0)),
            int(metrics.get("linked_refs", 0)),
            int(metrics.get("future_directions", 0)),
            int(metrics.get("visual_nodes", 0)),
            int(metrics.get("visual_edges", 0)),
            json.dumps(metrics, ensure_ascii=False),
        ),
    )
    conn.commit()


def load_previous_snapshot(
    conn: sqlite3.Connection,
    *,
    corpus_id: str,
    quarter_id: str | None = None,
) -> Optional[dict]:
    ensure_corpus_schema(conn)
    cid = normalize_corpus_id(corpus_id)
    if quarter_id:
        row = conn.execute(
            """
            SELECT *
            FROM corpus_snapshots
            WHERE corpus_id = ? AND quarter_id <> ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (cid, quarter_id),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT *
            FROM corpus_snapshots
            WHERE corpus_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (cid,),
        ).fetchone()
    return dict(row) if row else None


def now_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"

