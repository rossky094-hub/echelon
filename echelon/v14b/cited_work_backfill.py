"""Execute exact-ID cited-work backfill targets.

The queue builder turns citation uncertainty into an evidence acquisition
worklist.  This module takes the next conservative step: fetch only exact
provider-ID targets that can be verified through OpenAlex, insert the missing
works locally, and leave scientific claims gated until exact relinking and
downstream audits are rerun.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlencode

import httpx

from echelon.core.ulid_utils import ulid_new
from echelon.v14b.config import DB_MAIN, OPENALEX_EMAIL
from echelon.v14b.corpus_registry import ensure_corpus_schema, normalize_corpus_id
from echelon.v14b.id_normalization import (
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_work_id,
)
from echelon.v14b.reference_relink_audit import apply_exact_relinks, table_columns, table_exists
from echelon.v14b.utils import setup_logging

logger = logging.getLogger("echelon.v14b.cited_work_backfill")

OPENALEX_FIELDS = (
    "id,doi,title,display_name,publication_year,publication_date,cited_by_count,"
    "primary_topic,topics,referenced_works,authorships,locations,ids,open_access,"
    "language,is_retracted,type,abstract_inverted_index,primary_location"
)
SUPPORTED_PROVIDERS = ("openalex", "doi", "arxiv")


@dataclass(frozen=True)
class QueueTarget:
    rank: int
    provider: str
    norm: str
    priority_score: float
    citing_paper_count: int
    claim_scope: str
    evidence_grade: str


@dataclass(frozen=True)
class FetchResult:
    work: dict[str, Any] | None
    http_status: int | None = None
    error: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def jdumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(str(value))
    except Exception:
        return default


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def load_queue_targets(
    queue_path: Path,
    *,
    limit: int | None = None,
    providers: tuple[str, ...] = SUPPORTED_PROVIDERS,
) -> list[QueueTarget]:
    allowed = {p.strip().lower() for p in providers if p.strip()}
    rows: list[QueueTarget] = []
    with queue_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            provider = str(raw.get("provider") or "").strip().lower()
            norm = str(raw.get("normalized_id") or "").strip()
            if provider not in allowed or not norm:
                continue
            try:
                rank = int(raw.get("rank") or 0)
            except Exception:
                rank = 0
            try:
                priority = float(raw.get("priority_score") or 0.0)
            except Exception:
                priority = 0.0
            try:
                citing_count = int(raw.get("citing_paper_count") or 0)
            except Exception:
                citing_count = 0
            rows.append(
                QueueTarget(
                    rank=rank,
                    provider=provider,
                    norm=norm,
                    priority_score=priority,
                    citing_paper_count=citing_count,
                    claim_scope=str(raw.get("claim_scope") or ""),
                    evidence_grade=str(raw.get("evidence_grade") or ""),
                )
            )
            if limit and len(rows) >= limit:
                break
    return rows


def ensure_attempt_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cited_work_backfill_attempts (
            target_provider TEXT NOT NULL,
            target_norm TEXT NOT NULL,
            queue_rank INTEGER,
            priority_score REAL,
            citing_paper_count INTEGER,
            status TEXT NOT NULL,
            local_paper_id TEXT,
            openalex_id TEXT,
            doi TEXT,
            title TEXT,
            http_status INTEGER,
            referenced_work_count INTEGER DEFAULT 0,
            error TEXT,
            attempted_at TEXT NOT NULL,
            source_queue TEXT,
            PRIMARY KEY (target_provider, target_norm)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_cited_work_backfill_attempts_status
            ON cited_work_backfill_attempts(status, attempted_at DESC)
        """
    )


def openalex_url(target: QueueTarget) -> str | None:
    mailto = OPENALEX_EMAIL
    select = OPENALEX_FIELDS
    if target.provider == "openalex":
        wid = normalize_openalex_work_id(target.norm)
        if not wid:
            return None
        return f"https://api.openalex.org/works/{wid}?select={select}&mailto={quote(mailto, safe='@')}"
    if target.provider == "doi":
        doi = normalize_doi(target.norm)
        if not doi:
            return None
        return (
            "https://api.openalex.org/works/doi:"
            f"{quote(doi, safe='')}?select={select}&mailto={quote(mailto, safe='@')}"
        )
    if target.provider == "arxiv":
        arxiv_id = normalize_arxiv_id(target.norm)
        if not arxiv_id:
            return None
        return (
            "https://api.openalex.org/works?"
            + urlencode(
                {
                    "filter": f"locations.landing_page_url:https://arxiv.org/abs/{arxiv_id}",
                    "per_page": "1",
                    "select": select,
                    "mailto": mailto,
                }
            )
        )
    return None


def default_fetcher(client: httpx.Client, target: QueueTarget, *, delay: float) -> FetchResult:
    url = openalex_url(target)
    if not url:
        return FetchResult(None, error="unsupported_or_invalid_provider_id")
    for attempt in range(6):
        try:
            resp = client.get(url, timeout=45.0)
        except Exception as exc:
            return FetchResult(None, error=str(exc))
        if resp.status_code == 200:
            time.sleep(delay)
            data = resp.json()
            if isinstance(data, dict) and "results" in data:
                results = data.get("results") or []
                work = results[0] if results and isinstance(results[0], dict) else None
                return FetchResult(work, http_status=resp.status_code)
            return FetchResult(data if isinstance(data, dict) else None, http_status=resp.status_code)
        if resp.status_code == 404:
            return FetchResult(None, http_status=404, error="not_found")
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            try:
                wait = float(retry_after) if retry_after else 0.0
            except ValueError:
                wait = 0.0
            wait = max(wait, delay, min(300.0, 60.0 * (attempt + 1)))
            logger.warning("OpenAlex 429 while cited-work backfill target=%s:%s; cooldown %.1fs", target.provider, target.norm, wait)
            time.sleep(wait)
            continue
        return FetchResult(None, http_status=resp.status_code, error=resp.text[:240])
    return FetchResult(None, http_status=429, error="rate_limited_after_retries")


def abstract_from_inverted_index(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    positions: list[tuple[int, str]] = []
    for token, indexes in value.items():
        if not isinstance(indexes, list):
            continue
        for idx in indexes:
            try:
                positions.append((int(idx), str(token)))
            except Exception:
                continue
    if not positions:
        return None
    return " ".join(token for _idx, token in sorted(positions))


def _oa_tail(value: Any) -> str | None:
    if not value:
        return None
    tail = str(value).split("/")[-1].strip()
    return tail or None


def _extract_arxiv_id(work: dict[str, Any]) -> str | None:
    ids = work.get("ids") or {}
    if isinstance(ids, dict):
        for key in ("arxiv", "arxiv_id"):
            found = normalize_arxiv_id(ids.get(key))
            if found:
                return found
    payload = json.dumps(work.get("locations") or [], ensure_ascii=False)
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^\"?#\s]+)", payload, flags=re.I)
    return normalize_arxiv_id(match.group(1)) if match else None


def _extract_venue_id(work: dict[str, Any]) -> str | None:
    location = work.get("primary_location") or {}
    if not isinstance(location, dict):
        return None
    source = location.get("source") or {}
    if not isinstance(source, dict):
        return None
    return _oa_tail(source.get("id"))


def validate_work_identity(target: QueueTarget, work: dict[str, Any]) -> tuple[bool, str]:
    work_openalex = normalize_openalex_work_id(work.get("id"))
    work_doi = normalize_doi(work.get("doi"))
    work_arxiv = _extract_arxiv_id(work)
    if target.provider == "openalex":
        return (work_openalex == normalize_openalex_work_id(target.norm), "openalex_id_mismatch")
    if target.provider == "doi":
        return (work_doi == normalize_doi(target.norm), "doi_mismatch")
    if target.provider == "arxiv":
        return (work_arxiv == normalize_arxiv_id(target.norm), "arxiv_id_mismatch")
    return False, "unsupported_provider"


def paper_payload_from_work(
    work: dict[str, Any],
    *,
    corpus_id: str | None,
    ingestion_job_id: str,
) -> dict[str, Any]:
    primary_topic = work.get("primary_topic") or {}
    subfield = primary_topic.get("subfield") or {}
    field = primary_topic.get("field") or {}
    domain = primary_topic.get("domain") or {}
    year = work.get("publication_year")
    pub_date = work.get("publication_date")
    if not pub_date and year:
        pub_date = f"{int(year):04d}-01-01"
    pub_date = pub_date or "1900-01-01"
    title = clean_text(work.get("title") or work.get("display_name") or "")
    return {
        "id": ulid_new(),
        "openalex_id": normalize_openalex_work_id(work.get("id")),
        "doi": normalize_doi(work.get("doi")),
        "arxiv_id": _extract_arxiv_id(work),
        "pmid": None,
        "title": title or "[missing OpenAlex title]",
        "abstract": abstract_from_inverted_index(work.get("abstract_inverted_index")),
        "publication_date": pub_date,
        "publication_year": int(year) if str(year or "").isdigit() else int(str(pub_date)[:4]),
        "n_authors": len(work.get("authorships") or []),
        "cited_by_count": int(work.get("cited_by_count") or 0),
        "primary_topic_id": _oa_tail(primary_topic.get("id")) if primary_topic else None,
        "primary_subfield_id": _oa_tail(subfield.get("id")) if subfield else None,
        "primary_field_id": _oa_tail(field.get("id")) if field else None,
        "primary_domain_id": _oa_tail(domain.get("id")) if domain else None,
        "venue_id": _extract_venue_id(work),
        "is_retracted": int(bool(work.get("is_retracted"))),
        "is_paratext": int(str(work.get("type") or "").lower() == "paratext"),
        "language": work.get("language"),
        "open_access": json.dumps(work.get("open_access"), ensure_ascii=False) if work.get("open_access") is not None else None,
        "raw_jsonb": json.dumps(work, ensure_ascii=False),
        "first_ingested_at": utc_now(),
        "last_refreshed_at": utc_now(),
        "source_provider": "openalex_cited_work_backfill",
        "ingestion_job_id": ingestion_job_id,
        "openalex_enriched": 1,
        "corpus_id": normalize_corpus_id(corpus_id) if corpus_id else None,
    }


def lookup_existing_paper_id(conn: sqlite3.Connection, payload: dict[str, Any]) -> str | None:
    cols = table_columns(conn, "papers")
    checks = (
        ("openalex_id", payload.get("openalex_id")),
        ("doi", payload.get("doi")),
        ("arxiv_id", payload.get("arxiv_id")),
        ("s2_paper_id", payload.get("s2_paper_id")),
    )
    for col, value in checks:
        if col in cols and value:
            if col == "doi":
                row = conn.execute("SELECT id FROM papers WHERE lower(doi)=lower(?) LIMIT 1", (value,)).fetchone()
            else:
                row = conn.execute(f"SELECT id FROM papers WHERE {col}=? LIMIT 1", (value,)).fetchone()
            if row:
                return str(row[0])
    return None


def upsert_paper_from_work(conn: sqlite3.Connection, payload: dict[str, Any]) -> tuple[str, bool]:
    cols = table_columns(conn, "papers")
    existing_id = lookup_existing_paper_id(conn, payload)
    now = utc_now()
    if existing_id:
        update_pairs = []
        params: list[Any] = []
        for col in (
            "openalex_id",
            "doi",
            "arxiv_id",
            "abstract",
            "publication_date",
            "publication_year",
            "n_authors",
            "cited_by_count",
            "primary_topic_id",
            "primary_subfield_id",
            "primary_field_id",
            "primary_domain_id",
            "venue_id",
            "language",
            "open_access",
            "raw_jsonb",
            "source_provider",
            "ingestion_job_id",
            "openalex_enriched",
            "corpus_id",
        ):
            if col not in cols:
                continue
            if col in {"raw_jsonb", "cited_by_count", "source_provider", "ingestion_job_id", "openalex_enriched"}:
                update_pairs.append(f"{col} = ?")
            else:
                update_pairs.append(f"{col} = COALESCE({col}, ?)")
            params.append(payload.get(col))
        if "last_refreshed_at" in cols:
            update_pairs.append("last_refreshed_at = ?")
            params.append(now)
        if update_pairs:
            params.append(existing_id)
            conn.execute(f"UPDATE papers SET {', '.join(update_pairs)} WHERE id = ?", params)
        return existing_id, False

    insert_payload = {key: value for key, value in payload.items() if key in cols}
    if "title" in cols and not insert_payload.get("title"):
        insert_payload["title"] = "[missing OpenAlex title]"
    if "publication_date" in cols and not insert_payload.get("publication_date"):
        insert_payload["publication_date"] = "1900-01-01"
    names = list(insert_payload)
    placeholders = ", ".join("?" for _ in names)
    conn.execute(
        f"INSERT INTO papers ({', '.join(names)}) VALUES ({placeholders})",
        [insert_payload[name] for name in names],
    )
    return str(insert_payload["id"]), True


def assign_backfilled_paper_to_corpus(conn: sqlite3.Connection, paper_id: str, corpus_id: str | None) -> None:
    if not corpus_id:
        return
    ensure_corpus_schema(conn)
    cid = normalize_corpus_id(corpus_id)
    conn.execute(
        """
        INSERT OR REPLACE INTO paper_corpora
            (paper_id, corpus_id, assigned_at, assignment_source, score)
        VALUES (?, ?, CURRENT_TIMESTAMP, 'cited_work_backfill', 1.0)
        """,
        (paper_id, cid),
    )
    if "corpus_id" in table_columns(conn, "papers"):
        conn.execute("UPDATE papers SET corpus_id = COALESCE(corpus_id, ?) WHERE id = ?", (cid, paper_id))


def insert_openalex_references(conn: sqlite3.Connection, paper_id: str, work: dict[str, Any]) -> int:
    if not table_exists(conn, "paper_references"):
        return 0
    cols = table_columns(conn, "paper_references")
    if not {"citing_paper_id", "cited_paper_id_external"}.issubset(cols):
        return 0
    rows = []
    for ref in work.get("referenced_works") or []:
        norm = normalize_openalex_work_id(ref)
        if not norm:
            continue
        row = {
            "citing_paper_id": paper_id,
            "cited_paper_id_external": norm,
            "cited_paper_id_provider": "openalex",
            "cited_paper_id_norm": norm,
        }
        rows.append(row)
    if not rows:
        return 0
    if {"cited_paper_id_provider", "cited_paper_id_norm"}.issubset(cols):
        conn.executemany(
            """
            INSERT OR IGNORE INTO paper_references
                (citing_paper_id, cited_paper_id_external, cited_paper_id_provider, cited_paper_id_norm)
            VALUES (:citing_paper_id, :cited_paper_id_external, :cited_paper_id_provider, :cited_paper_id_norm)
            """,
            rows,
        )
    else:
        conn.executemany(
            """
            INSERT OR IGNORE INTO paper_references
                (citing_paper_id, cited_paper_id_external)
            VALUES (:citing_paper_id, :cited_paper_id_external)
            """,
            rows,
        )
    return len(rows)


def record_attempt(
    conn: sqlite3.Connection,
    target: QueueTarget,
    *,
    status: str,
    local_paper_id: str | None = None,
    payload: dict[str, Any] | None = None,
    http_status: int | None = None,
    referenced_work_count: int = 0,
    error: str = "",
    source_queue: Path | None = None,
) -> None:
    ensure_attempt_table(conn)
    conn.execute(
        """
        INSERT INTO cited_work_backfill_attempts
            (target_provider, target_norm, queue_rank, priority_score, citing_paper_count,
             status, local_paper_id, openalex_id, doi, title, http_status,
             referenced_work_count, error, attempted_at, source_queue)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(target_provider, target_norm) DO UPDATE SET
            queue_rank = excluded.queue_rank,
            priority_score = excluded.priority_score,
            citing_paper_count = excluded.citing_paper_count,
            status = excluded.status,
            local_paper_id = excluded.local_paper_id,
            openalex_id = excluded.openalex_id,
            doi = excluded.doi,
            title = excluded.title,
            http_status = excluded.http_status,
            referenced_work_count = excluded.referenced_work_count,
            error = excluded.error,
            attempted_at = excluded.attempted_at,
            source_queue = excluded.source_queue
        """,
        (
            target.provider,
            target.norm,
            target.rank,
            target.priority_score,
            target.citing_paper_count,
            status,
            local_paper_id,
            (payload or {}).get("openalex_id"),
            (payload or {}).get("doi"),
            (payload or {}).get("title"),
            http_status,
            referenced_work_count,
            error[:500],
            utc_now(),
            str(source_queue) if source_queue else None,
        ),
    )


FetchCallable = Callable[[QueueTarget], FetchResult]


def process_target(
    conn: sqlite3.Connection,
    target: QueueTarget,
    *,
    fetcher: FetchCallable,
    corpus_id: str | None,
    ingestion_job_id: str,
    dry_run: bool,
    source_queue: Path,
) -> dict[str, Any]:
    placeholder_payload = {
        "openalex_id": target.norm if target.provider == "openalex" else None,
        "doi": target.norm if target.provider == "doi" else None,
        "arxiv_id": target.norm if target.provider == "arxiv" else None,
    }
    existing_id = lookup_existing_paper_id(conn, placeholder_payload)
    if existing_id:
        record_attempt(
            conn,
            target,
            status="skip_existing_local_work",
            local_paper_id=existing_id,
            payload=placeholder_payload,
            source_queue=source_queue,
        )
        return {"status": "skip_existing_local_work", "local_paper_id": existing_id, "provider": target.provider}
    if dry_run:
        record_attempt(conn, target, status="dry_run_pending_fetch", source_queue=source_queue)
        return {"status": "dry_run_pending_fetch", "provider": target.provider}
    fetched = fetcher(target)
    if not fetched.work:
        record_attempt(
            conn,
            target,
            status="fetch_failed",
            http_status=fetched.http_status,
            error=fetched.error,
            source_queue=source_queue,
        )
        return {"status": "fetch_failed", "provider": target.provider, "error": fetched.error}
    ok, error = validate_work_identity(target, fetched.work)
    if not ok:
        record_attempt(
            conn,
            target,
            status="identity_mismatch",
            http_status=fetched.http_status,
            error=error,
            source_queue=source_queue,
        )
        return {"status": "identity_mismatch", "provider": target.provider, "error": error}
    payload = paper_payload_from_work(fetched.work, corpus_id=corpus_id, ingestion_job_id=ingestion_job_id)
    paper_id, inserted = upsert_paper_from_work(conn, payload)
    assign_backfilled_paper_to_corpus(conn, paper_id, corpus_id)
    refs = insert_openalex_references(conn, paper_id, fetched.work)
    status = "inserted" if inserted else "updated_existing_after_fetch"
    record_attempt(
        conn,
        target,
        status=status,
        local_paper_id=paper_id,
        payload=payload,
        http_status=fetched.http_status,
        referenced_work_count=refs,
        source_queue=source_queue,
    )
    return {
        "status": status,
        "provider": target.provider,
        "local_paper_id": paper_id,
        "openalex_id": payload.get("openalex_id"),
        "doi": payload.get("doi"),
        "title": payload.get("title"),
        "referenced_work_count": refs,
    }


def write_reports(
    *,
    out_dir: Path,
    results: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "cited_work_backfill_run.json"
    md_path = out_dir / "cited_work_backfill_run.md"
    payload = {
        "generated_at": summary["generated_at"],
        "summary": summary,
        "results": results[:200],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = Counter(str(row.get("status") or "unknown") for row in results)
    provider_counts = Counter(str(row.get("provider") or "unknown") for row in results)
    lines = [
        "# V14B Cited Work Backfill Run",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- queue targets considered: {int(summary.get('targets_considered') or 0):,}",
        f"- processed targets: {len(results):,}",
        f"- dry_run: `{summary.get('dry_run')}`",
        f"- corpus_id: `{summary.get('corpus_id')}`",
        "",
        "## Status Counts",
        "",
        "| status | targets |",
        "| --- | ---: |",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f"| {status} | {count:,} |")
    lines.extend(["", "## Provider Counts", "", "| provider | targets |", "| --- | ---: |"])
    for provider, count in sorted(provider_counts.items()):
        lines.append(f"| {provider} | {count:,} |")
    if summary.get("relink_apply_result"):
        lines.extend(["", "## Exact Relink Apply", "", "```json", json.dumps(summary["relink_apply_result"], ensure_ascii=False, indent=2, sort_keys=True), "```"])
    lines.extend(
        [
            "",
            "## Product Interpretation",
            "",
            "Inserted cited works strengthen the local evidence corpus only after exact relinking connects them to existing references. "
            "They remain evidence acquisition records, not branch, main-path, bottleneck, or Radar conclusions.",
            "",
            "## Sample Results",
            "",
            "| status | provider | local_paper_id | title | refs |",
            "| --- | --- | --- | --- | ---: |",
        ]
    )
    for row in results[:30]:
        lines.append(
            f"| {row.get('status')} | {row.get('provider')} | `{row.get('local_paper_id') or ''}` | "
            f"{clean_text(row.get('title'))[:100]} | {int(row.get('referenced_work_count') or 0)} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def load_cited_work_backfill_run_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "path": str(path)}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"available": False, "path": str(path), "reason": str(exc)}
    summary = loaded.get("summary") if isinstance(loaded, dict) else {}
    if not isinstance(summary, dict):
        return {"available": False, "path": str(path), "reason": "missing_summary"}
    status_counts = summary.get("status_counts") or {}
    inserted = int(status_counts.get("inserted") or 0) + int(status_counts.get("updated_existing_after_fetch") or 0)
    return {
        "available": True,
        "path": str(path),
        "status": "ran" if int(summary.get("processed_targets") or 0) else "empty",
        "generated_at": loaded.get("generated_at"),
        "processed_targets": int(summary.get("processed_targets") or 0),
        "inserted_or_updated": inserted,
        "status_counts": status_counts,
        "provider_counts": summary.get("provider_counts") or {},
        "dry_run": bool(summary.get("dry_run")),
        "relink_updates_applied": (
            ((summary.get("relink_apply_result") or {}).get("apply_result") or {}).get("link_updates_applied")
        ),
    }


def run_backfill(
    *,
    db_main: Path = DB_MAIN,
    queue_path: Path = Path("data/v14b/cited_work_backfill_queue.csv"),
    out_dir: Path = Path("reports/v14b_pilot"),
    limit: int = 25,
    providers: tuple[str, ...] = ("openalex", "doi"),
    corpus_id: str | None = "optics",
    delay: float = 1.2,
    dry_run: bool = False,
    apply_relinks: bool = False,
    fetcher: FetchCallable | None = None,
) -> dict[str, Any]:
    targets = load_queue_targets(queue_path, limit=limit, providers=providers)
    conn = sqlite3.connect(str(db_main), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_attempt_table(conn)
    if corpus_id:
        ensure_corpus_schema(conn)
    ingestion_job_id = ulid_new()
    client = httpx.Client(timeout=45.0)
    try:
        if fetcher is None:
            def real_fetch(target: QueueTarget) -> FetchResult:
                return default_fetcher(client, target, delay=delay)
            fetch = real_fetch
        else:
            fetch = fetcher
        results = [
            process_target(
                conn,
                target,
                fetcher=fetch,
                corpus_id=corpus_id,
                ingestion_job_id=ingestion_job_id,
                dry_run=dry_run,
                source_queue=queue_path,
            )
            for target in targets
        ]
        conn.commit()
        relink_result = None
        if apply_relinks and not dry_run:
            relink_result = apply_exact_relinks(conn)
            conn.commit()
        status_counts = Counter(str(row.get("status") or "unknown") for row in results)
        provider_counts = Counter(str(row.get("provider") or "unknown") for row in results)
        summary = {
            "generated_at": utc_now(),
            "queue_path": str(queue_path),
            "targets_considered": len(targets),
            "processed_targets": len(results),
            "status_counts": dict(sorted(status_counts.items())),
            "provider_counts": dict(sorted(provider_counts.items())),
            "corpus_id": corpus_id,
            "dry_run": dry_run,
            "apply_relinks": apply_relinks,
            "relink_apply_result": relink_result,
        }
        paths = write_reports(out_dir=out_dir, results=results, summary=summary)
        return {
            "generated_at": summary["generated_at"],
            "summary": summary,
            "paths": paths,
        }
    finally:
        client.close()
        conn.close()


def _parse_providers(value: str) -> tuple[str, ...]:
    providers = tuple(p.strip().lower() for p in value.split(",") if p.strip())
    return providers or ("openalex", "doi")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fetch exact-ID cited-work backfill targets through OpenAlex.")
    parser.add_argument("--db", type=Path, default=DB_MAIN)
    parser.add_argument("--queue", type=Path, default=Path("data/v14b/cited_work_backfill_queue.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/v14b_pilot"))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--providers", default="openalex,doi")
    parser.add_argument("--corpus-id", default="optics")
    parser.add_argument("--delay", type=float, default=1.2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply-relinks", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    setup_logging("cited_work_backfill", level=getattr(logging, str(args.log_level).upper()))
    result = run_backfill(
        db_main=args.db,
        queue_path=args.queue,
        out_dir=args.out_dir,
        limit=args.limit,
        providers=_parse_providers(args.providers),
        corpus_id=args.corpus_id,
        delay=args.delay,
        dry_run=args.dry_run,
        apply_relinks=args.apply_relinks,
    )
    print(jdumps({"summary": result["summary"], "paths": result["paths"]}))


if __name__ == "__main__":
    main()
