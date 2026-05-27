"""
High-Water Mark (HWM) persistence — AUDIT-051 fix.

V11.1 bug: Weekly ingestion always re-fetched from a hardcoded start date,
causing:
1. Duplicate paper ingestion (same papers fetched and re-processed every week)
2. Data black holes on cron failure (no state to resume from)
3. Exponentially growing API call volume as the corpus grows

V11.2 fix:
- ingestion_hwm table (SQLite for Pilot) persists the last processed date
- weekly_incremental_ingestion() reads MAX(publication_date) from DB
- Falls back to DEFAULT_START_DATE if table empty (fresh install)
- Updates HWM atomically after ingestion completes
- On cron failure/restart: resumes from last successful HWM

Schema:
    CREATE TABLE ingestion_hwm (
        table_name  TEXT PRIMARY KEY,
        hwm_date    TEXT NOT NULL,   -- ISO 8601 date: YYYY-MM-DD
        updated_at  TEXT NOT NULL,   -- ISO 8601 timestamp
        run_count   INTEGER NOT NULL DEFAULT 0
    );
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Generator, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# [AUDIT-051] Default start date for fresh installs (no prior HWM)
DEFAULT_START_DATE: str = "2020-01-01"

# SQLite DB path (Pilot).  In production, replace with PostgreSQL or similar.
DEFAULT_DB_PATH: str = "/tmp/echelon_pilot.db"

# HWM table name
HWM_TABLE: str = "ingestion_hwm"


# ---------------------------------------------------------------------------
# DB connection helpers
# ---------------------------------------------------------------------------

@contextmanager
def _db_connection(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite connection with WAL mode for Pilot."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# HWM table DDL
# ---------------------------------------------------------------------------

def ensure_hwm_table(db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Create the ingestion_hwm table if it does not exist.

    [AUDIT-051] Called on every startup to guarantee the table is present
    before any HWM read/write operations.
    """
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {HWM_TABLE} (
        table_name  TEXT PRIMARY KEY,
        hwm_date    TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        run_count   INTEGER NOT NULL DEFAULT 0
    )
    """
    with _db_connection(db_path) as conn:
        conn.execute(ddl)
    logger.debug(f"[AUDIT-051] Ensured {HWM_TABLE} table in {db_path}")


# ---------------------------------------------------------------------------
# HWM read / write
# ---------------------------------------------------------------------------

def get_hwm(
    table_name: str,
    db_path: str = DEFAULT_DB_PATH,
) -> str:
    """
    Read the current High-Water Mark date for a given table.

    [AUDIT-051] Returns the last successfully ingested publication_date.
    Falls back to DEFAULT_START_DATE if no HWM exists yet.

    Args:
        table_name: Logical table name (e.g. "paper", "citation").
        db_path:    SQLite database path.

    Returns:
        ISO 8601 date string ("YYYY-MM-DD").
    """
    ensure_hwm_table(db_path)
    with _db_connection(db_path) as conn:
        row = conn.execute(
            f"SELECT hwm_date FROM {HWM_TABLE} WHERE table_name = ?",
            (table_name,),
        ).fetchone()

    if row is None:
        logger.info(
            f"[AUDIT-051] No HWM for table '{table_name}'; "
            f"defaulting to {DEFAULT_START_DATE}"
        )
        return DEFAULT_START_DATE

    logger.info(f"[AUDIT-051] HWM for '{table_name}': {row['hwm_date']}")
    return row["hwm_date"]


def set_hwm(
    table_name: str,
    hwm_date: str,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """
    Persist the High-Water Mark date for a given table.

    [AUDIT-051] Called AFTER successful ingestion to record the new HWM.
    Uses UPSERT (INSERT OR REPLACE) for idempotency.

    Args:
        table_name: Logical table name.
        hwm_date:   New HWM in ISO 8601 format ("YYYY-MM-DD").
        db_path:    SQLite database path.
    """
    ensure_hwm_table(db_path)
    now = datetime.now(timezone.utc).isoformat()

    with _db_connection(db_path) as conn:
        conn.execute(
            f"""
            INSERT INTO {HWM_TABLE} (table_name, hwm_date, updated_at, run_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(table_name) DO UPDATE SET
                hwm_date   = excluded.hwm_date,
                updated_at = excluded.updated_at,
                run_count  = {HWM_TABLE}.run_count + 1
            """,
            (table_name, hwm_date, now),
        )

    logger.info(f"[AUDIT-051] HWM updated: table='{table_name}' hwm_date={hwm_date}")


def get_max_publication_date(
    table: str,
    db_path: str = DEFAULT_DB_PATH,
) -> Optional[str]:
    """
    Query MAX(publication_date) from the specified table.

    [AUDIT-051] Used by weekly_incremental_ingestion() to find the most
    recent paper already in the DB, so we only fetch newer papers.

    Args:
        table:   Table name (e.g. "paper").
        db_path: SQLite database path.

    Returns:
        ISO date string or None if table is empty / does not exist.
    """
    try:
        with _db_connection(db_path) as conn:
            row = conn.execute(
                f"SELECT MAX(publication_date) AS max_date FROM {table}"
            ).fetchone()
        if row and row["max_date"]:
            return row["max_date"]
        return None
    except sqlite3.OperationalError as exc:
        # Table may not exist yet (first run)
        logger.warning(f"[AUDIT-051] Cannot query MAX(publication_date) from '{table}': {exc}")
        return None


# ---------------------------------------------------------------------------
# Weekly incremental ingestion  [AUDIT-051]
# ---------------------------------------------------------------------------

def weekly_incremental_ingestion(
    table: str = "paper",
    db_path: str = DEFAULT_DB_PATH,
    fetcher_fn=None,   # callable(since_date: str, until_date: str) -> list[dict]
) -> dict:
    """
    Incremental ingestion that resumes from the last High-Water Mark.

    [AUDIT-051] Algorithm:
    1. Read current HWM from ingestion_hwm table
    2. Also query MAX(publication_date) from the paper table
    3. Use the LATER of the two as the actual start date
       (guards against DB inconsistency)
    4. Fetch papers published since start_date
    5. Insert new papers
    6. Update HWM to today's date

    This prevents:
    - Duplicate ingestion (papers before HWM are skipped)
    - Data black holes on cron failure (HWM is only updated on success)
    - Budget overruns (only N new papers per week, not all papers)

    Args:
        table:      Target table name (e.g. "paper").
        db_path:    SQLite database path.
        fetcher_fn: callable(since_date: str, until_date: str) -> list[dict]
                    If None, a no-op stub is used (for testing).

    Returns:
        Summary dict with keys:
            since_date:      Actual start date used.
            until_date:      End date (today).
            fetched_count:   Number of papers fetched from API.
            inserted_count:  Number of new papers inserted.
            hwm_updated_to:  New HWM date set.
            skipped_count:   Papers already in DB (skipped).
    """
    ensure_hwm_table(db_path)

    # ── Step 1: Determine start date ────────────────────────────────────────
    hwm_date = get_hwm(table, db_path)
    db_max_date = get_max_publication_date(table, db_path)

    if db_max_date and db_max_date > hwm_date:
        since_date = db_max_date
        logger.info(
            f"[AUDIT-051] DB MAX({table}.publication_date)={db_max_date} > "
            f"HWM={hwm_date}; using DB max as start date"
        )
    else:
        since_date = hwm_date
        logger.info(f"[AUDIT-051] Resuming from HWM: {since_date}")

    until_date = date.today().isoformat()

    if since_date >= until_date:
        logger.info(f"[AUDIT-051] No new data to ingest (since={since_date} >= until={until_date})")
        return {
            "since_date": since_date,
            "until_date": until_date,
            "fetched_count": 0,
            "inserted_count": 0,
            "hwm_updated_to": since_date,
            "skipped_count": 0,
        }

    # ── Step 2: Fetch new papers ─────────────────────────────────────────────
    if fetcher_fn is None:
        logger.warning("[AUDIT-051] No fetcher_fn provided; using no-op stub")
        fetcher_fn = lambda since, until: []  # noqa: E731

    try:
        new_papers = fetcher_fn(since_date, until_date)
    except Exception as exc:
        logger.error(
            f"[AUDIT-051] Fetch failed for {since_date} → {until_date}: {exc}. "
            "HWM NOT updated (safe resume on next run)."
        )
        raise

    fetched_count = len(new_papers)
    logger.info(f"[AUDIT-051] Fetched {fetched_count} papers since {since_date}")

    # ── Step 3: Insert (upsert) into DB ─────────────────────────────────────
    inserted_count = 0
    skipped_count = 0

    try:
        with _db_connection(db_path) as conn:
            # Ensure paper table exists (minimal schema for Pilot)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper (
                    paper_id         TEXT PRIMARY KEY,
                    title            TEXT,
                    abstract         TEXT,
                    publication_date TEXT,
                    topic_id         TEXT,
                    created_at       TEXT
                )
            """)

            for paper in new_papers:
                pid = paper.get("paper_id") or paper.get("id", "")
                pub_date = paper.get("publication_date", "")
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO paper
                            (paper_id, title, abstract, publication_date, topic_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            pid,
                            paper.get("title", ""),
                            paper.get("abstract", ""),
                            pub_date,
                            paper.get("topic_id", ""),
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
                    if conn.execute("SELECT changes()").fetchone()[0] > 0:
                        inserted_count += 1
                    else:
                        skipped_count += 1
                except sqlite3.Error as exc:
                    logger.warning(f"[AUDIT-051] Insert failed for paper {pid!r}: {exc}")

    except Exception as exc:
        logger.error(
            f"[AUDIT-051] DB insert failed: {exc}. HWM NOT updated."
        )
        raise

    # ── Step 4: Update HWM (only on success) ────────────────────────────────
    set_hwm(table, until_date, db_path)

    summary = {
        "since_date":    since_date,
        "until_date":    until_date,
        "fetched_count": fetched_count,
        "inserted_count": inserted_count,
        "hwm_updated_to": until_date,
        "skipped_count": skipped_count,
    }
    logger.info(f"[AUDIT-051] Ingestion complete: {summary}")
    return summary


# ---------------------------------------------------------------------------
# HWM inspection utility
# ---------------------------------------------------------------------------

def list_all_hwm(db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """
    List all HWM records in the database.

    Returns:
        List of dicts with keys: table_name, hwm_date, updated_at, run_count.
    """
    ensure_hwm_table(db_path)
    with _db_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT table_name, hwm_date, updated_at, run_count FROM {HWM_TABLE} ORDER BY table_name"
        ).fetchall()
    return [dict(r) for r in rows]
