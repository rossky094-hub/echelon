#!/usr/bin/env python3
"""Download raw paper PDFs to an external object store.

The downloader intentionally keeps its manifest on the external disk instead
of writing to the main Echelon SQLite database.  That lets it run beside
section ingest without adding SQLite writer contention to the live pipeline.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx

from echelon.v14b.config import DB_MAIN, S2_DELAY, SEMANTIC_SCHOLAR_API_KEY
from echelon.v14b.id_normalization import normalize_arxiv_id, normalize_doi, normalize_s2_paper_id


DEFAULT_STORE_ROOT = Path("/Volumes/LaCie/Echelon_Paper_Raw_Data")
DEFAULT_MANIFEST = DEFAULT_STORE_ROOT / "manifests" / "raw_pdf_downloads.sqlite3"
DEFAULT_USER_AGENT = (
    "EchelonV14B/1.0 raw-pdf-downloader "
    "(research corpus preservation; contact configured locally)"
)


@dataclass(frozen=True)
class PaperTarget:
    paper_id: str
    arxiv_id: str | None
    doi: str | None
    s2_paper_id: str | None
    title: str
    source_provider: str


class StartRateLimiter:
    """Limit request starts while still allowing active downloads to overlap."""

    def __init__(self, min_interval_s: float) -> None:
        self.min_interval_s = max(0.0, float(min_interval_s))
        self._lock = asyncio.Lock()
        self._last_start = 0.0

    async def wait(self) -> None:
        if self.min_interval_s <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait_s = self.min_interval_s - (now - self._last_start)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            self._last_start = time.monotonic()


def utc_now() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def ensure_store(root: Path) -> None:
    for rel in ("pdfs", "metadata", "sections", "manifests", "logs", "tmp"):
        (root / rel).mkdir(parents=True, exist_ok=True)


def connect_manifest(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS raw_pdf_downloads (
            paper_id TEXT PRIMARY KEY,
            arxiv_id TEXT,
            doi TEXT,
            s2_paper_id TEXT,
            title TEXT,
            source_provider TEXT,
            source_url TEXT,
            storage_path TEXT,
            status TEXT NOT NULL,
            http_status INTEGER,
            size_bytes INTEGER,
            sha256 TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            first_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            downloaded_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_raw_pdf_downloads_status
            ON raw_pdf_downloads(status);
        CREATE INDEX IF NOT EXISTS idx_raw_pdf_downloads_arxiv
            ON raw_pdf_downloads(arxiv_id);

        CREATE TABLE IF NOT EXISTS raw_pdf_download_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            db_main TEXT NOT NULL,
            store_root TEXT NOT NULL,
            limit_n INTEGER,
            concurrency INTEGER NOT NULL,
            request_delay_s REAL NOT NULL,
            counts_json TEXT NOT NULL
        );
        """
    )
    return conn


def successful_paper_ids(conn: sqlite3.Connection, store_root: Path) -> set[str]:
    rows = conn.execute(
        """
        SELECT paper_id, storage_path
        FROM raw_pdf_downloads
        WHERE status = 'success'
          AND COALESCE(storage_path, '') != ''
        """
    ).fetchall()
    out: set[str] = set()
    for row in rows:
        path = Path(str(row["storage_path"]))
        if not path.is_absolute():
            path = store_root / path
        if path.exists() and path.stat().st_size > 0:
            out.add(str(row["paper_id"]))
    return out


def load_targets(
    db_main: Path,
    *,
    limit: int | None,
    include_non_arxiv: bool,
    skip_paper_ids: set[str],
) -> list[PaperTarget]:
    uri = f"file:{db_main}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        where = "1=1" if include_non_arxiv else "arxiv_id IS NOT NULL AND trim(arxiv_id) != ''"
        rows = conn.execute(
            f"""
            SELECT id, arxiv_id, doi, s2_paper_id, title, source_provider
            FROM papers
            WHERE {where}
            ORDER BY publication_year, id
            """
        ).fetchall()
    finally:
        conn.close()

    targets: list[PaperTarget] = []
    for row in rows:
        paper_id = str(row["id"] or "").strip()
        if not paper_id or paper_id in skip_paper_ids:
            continue
        target = PaperTarget(
            paper_id=paper_id,
            arxiv_id=normalize_arxiv_id(row["arxiv_id"]),
            doi=normalize_doi(row["doi"]),
            s2_paper_id=normalize_s2_paper_id(row["s2_paper_id"]),
            title=str(row["title"] or ""),
            source_provider=str(row["source_provider"] or ""),
        )
        if not include_non_arxiv and not target.arxiv_id:
            continue
        targets.append(target)
        if limit and len(targets) >= limit:
            break
    return targets


def sanitize_filename(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return clean.strip("._") or "unknown"


def arxiv_pdf_url(arxiv_id: str | None) -> str | None:
    aid = normalize_arxiv_id(arxiv_id)
    if not aid:
        return None
    return f"https://arxiv.org/pdf/{aid}.pdf"


def storage_relpath_for_arxiv(arxiv_id: str) -> Path:
    aid = normalize_arxiv_id(arxiv_id) or arxiv_id
    if "/" in aid:
        category, paper = aid.split("/", 1)
        return Path("pdfs") / "arxiv" / sanitize_filename(category) / f"{sanitize_filename(paper)}.pdf"
    prefix = sanitize_filename(aid[:4] or "misc")
    return Path("pdfs") / "arxiv" / prefix / f"{sanitize_filename(aid)}.pdf"


def fallback_storage_relpath(paper: PaperTarget) -> Path:
    sid = paper.s2_paper_id or paper.paper_id
    return Path("pdfs") / "other" / f"{sanitize_filename(sid)}.pdf"


def remove_appledouble_sidecar(path: Path) -> None:
    sidecar = path.with_name(f"._{path.name}")
    sidecar.unlink(missing_ok=True)


def register_seen(conn: sqlite3.Connection, targets: list[PaperTarget]) -> None:
    now = utc_now()
    conn.executemany(
        """
        INSERT INTO raw_pdf_downloads (
            paper_id, arxiv_id, doi, s2_paper_id, title, source_provider,
            status, attempts, first_seen_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            arxiv_id=excluded.arxiv_id,
            doi=excluded.doi,
            s2_paper_id=excluded.s2_paper_id,
            title=excluded.title,
            source_provider=excluded.source_provider,
            updated_at=excluded.updated_at
        """,
        [
            (
                t.paper_id,
                t.arxiv_id,
                t.doi,
                t.s2_paper_id,
                t.title,
                t.source_provider,
                now,
                now,
            )
            for t in targets
        ],
    )
    conn.commit()


async def resolve_semantic_open_pdf(client: httpx.AsyncClient, paper: PaperTarget, s2_limiter: StartRateLimiter) -> str | None:
    if not SEMANTIC_SCHOLAR_API_KEY:
        return None
    ids: list[str] = []
    if paper.s2_paper_id:
        ids.append(paper.s2_paper_id)
    if paper.doi:
        ids.append(f"DOI:{paper.doi}")
    if paper.arxiv_id:
        ids.append(f"ARXIV:{paper.arxiv_id}")
    headers = {"x-api-key": SEMANTIC_SCHOLAR_API_KEY}
    for pid in ids:
        try:
            await s2_limiter.wait()
            resp = await client.get(
                f"https://api.semanticscholar.org/graph/v1/paper/{pid}",
                params={"fields": "openAccessPdf"},
                headers=headers,
                timeout=30.0,
            )
            if resp.status_code != 200:
                continue
            data = resp.json() or {}
            pdf = data.get("openAccessPdf") or {}
            url = pdf.get("url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                return url
        except Exception:
            continue
    return None


def mark_attempt(
    conn: sqlite3.Connection,
    paper: PaperTarget,
    *,
    status: str,
    source_url: str | None,
    storage_path: Path | None,
    http_status: int | None = None,
    size_bytes: int | None = None,
    sha256: str | None = None,
    error: str | None = None,
) -> None:
    now = utc_now()
    downloaded_at = now if status == "success" else None
    storage_text = str(storage_path) if storage_path else None
    conn.execute(
        """
        UPDATE raw_pdf_downloads
        SET status = ?,
            source_url = ?,
            storage_path = COALESCE(?, storage_path),
            http_status = ?,
            size_bytes = COALESCE(?, size_bytes),
            sha256 = COALESCE(?, sha256),
            attempts = attempts + 1,
            error = ?,
            updated_at = ?,
            downloaded_at = COALESCE(?, downloaded_at)
        WHERE paper_id = ?
        """,
        (
            status,
            source_url,
            storage_text,
            http_status,
            size_bytes,
            sha256,
            error,
            now,
            downloaded_at,
            paper.paper_id,
        ),
    )
    conn.commit()


async def download_one(
    *,
    client: httpx.AsyncClient,
    paper: PaperTarget,
    store_root: Path,
    manifest_path: Path,
    request_limiter: StartRateLimiter,
    s2_limiter: StartRateLimiter,
    include_s2_fallback: bool,
    max_bytes: int,
    user_agent: str,
) -> str:
    url = arxiv_pdf_url(paper.arxiv_id)
    relpath = storage_relpath_for_arxiv(paper.arxiv_id) if paper.arxiv_id else fallback_storage_relpath(paper)
    if not url and include_s2_fallback:
        url = await resolve_semantic_open_pdf(client, paper, s2_limiter)
    if not url:
        with connect_manifest(manifest_path) as conn:
            mark_attempt(conn, paper, status="no_pdf_url", source_url=None, storage_path=None, error="no arXiv or OA PDF URL")
        return "no_pdf_url"

    final_path = store_root / relpath
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = store_root / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    if final_path.exists() and final_path.stat().st_size > 0:
        remove_appledouble_sidecar(final_path)
        with connect_manifest(manifest_path) as conn:
            mark_attempt(
                conn,
                paper,
                status="success",
                source_url=url,
                storage_path=final_path,
                size_bytes=final_path.stat().st_size,
                error=None,
            )
        return "already_present"

    tmp_file = tempfile.NamedTemporaryFile(
        prefix=f"{sanitize_filename(paper.paper_id)}.",
        suffix=".part",
        dir=str(tmp_dir),
        delete=False,
    )
    tmp_path = Path(tmp_file.name)
    sha = hashlib.sha256()
    size = 0
    first = b""
    http_status: int | None = None

    try:
        await request_limiter.wait()
        async with client.stream("GET", url, headers={"User-Agent": user_agent}, timeout=90.0) as resp:
            http_status = resp.status_code
            if resp.status_code != 200:
                tmp_file.close()
                tmp_path.unlink(missing_ok=True)
                with connect_manifest(manifest_path) as conn:
                    mark_attempt(
                        conn,
                        paper,
                        status="http_error",
                        source_url=url,
                        storage_path=None,
                        http_status=http_status,
                        error=f"http_status={resp.status_code}",
                    )
                return "http_error"
            async for chunk in resp.aiter_bytes(chunk_size=262_144):
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise RuntimeError(f"download exceeds max_bytes={max_bytes}")
                if len(first) < 8:
                    first += chunk[: 8 - len(first)]
                sha.update(chunk)
                tmp_file.write(chunk)
        tmp_file.close()
        if size == 0:
            raise RuntimeError("empty response")
        if not first.startswith(b"%PDF"):
            raise RuntimeError("response did not start with PDF magic")
        os.replace(tmp_path, final_path)
        remove_appledouble_sidecar(final_path)
        with connect_manifest(manifest_path) as conn:
            mark_attempt(
                conn,
                paper,
                status="success",
                source_url=url,
                storage_path=final_path,
                http_status=http_status,
                size_bytes=size,
                sha256=sha.hexdigest(),
                error=None,
            )
        return "success"
    except Exception as exc:
        tmp_file.close()
        tmp_path.unlink(missing_ok=True)
        with connect_manifest(manifest_path) as conn:
            mark_attempt(
                conn,
                paper,
                status="failed",
                source_url=url,
                storage_path=None,
                http_status=http_status,
                error=str(exc)[:500],
            )
        return "failed"


async def run_downloads(
    *,
    targets: list[PaperTarget],
    store_root: Path,
    manifest_path: Path,
    concurrency: int,
    request_delay_s: float,
    s2_delay_s: float,
    include_s2_fallback: bool,
    max_bytes: int,
    progress_every: int,
    user_agent: str,
) -> dict[str, int]:
    queue: asyncio.Queue[PaperTarget] = asyncio.Queue()
    for target in targets:
        queue.put_nowait(target)

    counts: dict[str, int] = {}
    done = 0
    total = len(targets)
    lock = asyncio.Lock()
    request_limiter = StartRateLimiter(request_delay_s)
    s2_limiter = StartRateLimiter(s2_delay_s)
    limits = httpx.Limits(max_connections=max(1, concurrency), max_keepalive_connections=max(1, concurrency))

    async with httpx.AsyncClient(follow_redirects=True, limits=limits, trust_env=False) as client:

        async def worker() -> None:
            nonlocal done
            while True:
                try:
                    paper = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                outcome = await download_one(
                    client=client,
                    paper=paper,
                    store_root=store_root,
                    manifest_path=manifest_path,
                    request_limiter=request_limiter,
                    s2_limiter=s2_limiter,
                    include_s2_fallback=include_s2_fallback,
                    max_bytes=max_bytes,
                    user_agent=user_agent,
                )
                async with lock:
                    done += 1
                    counts[outcome] = counts.get(outcome, 0) + 1
                    if done == total or done % max(1, progress_every) == 0:
                        print(
                            f"[{utc_now()}] raw-pdf progress {done}/{total} "
                            f"counts={_json_dumps(counts)}",
                            flush=True,
                        )
                queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(max(1, concurrency))]
        await asyncio.gather(*workers)
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download raw paper PDFs to an external disk.")
    parser.add_argument("--db", type=Path, default=DB_MAIN)
    parser.add_argument("--store-root", type=Path, default=DEFAULT_STORE_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--limit", type=int, default=None, help="Limit number of new targets. Omit for full corpus.")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--request-delay", type=float, default=0.75, help="Minimum seconds between PDF request starts.")
    parser.add_argument("--s2-delay", type=float, default=S2_DELAY, help="Minimum seconds between S2 API requests.")
    parser.add_argument("--include-non-arxiv", action="store_true")
    parser.add_argument("--include-s2-fallback", action="store_true")
    parser.add_argument("--no-skip-success", action="store_true", help="Revisit manifest successes instead of skipping.")
    parser.add_argument("--max-mb", type=int, default=200)
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_store(args.store_root)
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = args.store_root / manifest_path
    conn = connect_manifest(manifest_path)
    skip_ids = set() if args.no_skip_success else successful_paper_ids(conn, args.store_root)
    targets = load_targets(
        args.db,
        limit=args.limit,
        include_non_arxiv=args.include_non_arxiv,
        skip_paper_ids=skip_ids,
    )
    register_seen(conn, targets)

    run_id = f"raw_pdf_{utc_now().replace(':', '').replace('-', '')}"
    run_args = {
        "limit": args.limit,
        "concurrency": args.concurrency,
        "request_delay": args.request_delay,
        "s2_delay": args.s2_delay,
        "include_non_arxiv": args.include_non_arxiv,
        "include_s2_fallback": args.include_s2_fallback,
        "skip_successes": not args.no_skip_success,
    }
    initial_counts = {"targets": len(targets), "skipped_successes": len(skip_ids), "dry_run": int(args.dry_run)}
    conn.execute(
        """
        INSERT INTO raw_pdf_download_runs (
            run_id, started_at, status, db_main, store_root, limit_n,
            concurrency, request_delay_s, counts_json
        )
        VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            utc_now(),
            str(args.db),
            str(args.store_root),
            args.limit,
            args.concurrency,
            args.request_delay,
            _json_dumps({**initial_counts, "args": run_args}),
        ),
    )
    conn.commit()
    conn.close()

    print(
        _json_dumps(
            {
                "run_id": run_id,
                "targets": len(targets),
                "skipped_successes": len(skip_ids),
                "store_root": str(args.store_root),
                "manifest": str(manifest_path),
                "dry_run": bool(args.dry_run),
            }
        ),
        flush=True,
    )

    if args.dry_run:
        counts = initial_counts
        status = "dry_run"
    else:
        counts = asyncio.run(
            run_downloads(
                targets=targets,
                store_root=args.store_root,
                manifest_path=manifest_path,
                concurrency=args.concurrency,
                request_delay_s=args.request_delay,
                s2_delay_s=args.s2_delay,
                include_s2_fallback=args.include_s2_fallback,
                max_bytes=max(1, args.max_mb) * 1024 * 1024,
                progress_every=args.progress_every,
                user_agent=args.user_agent,
            )
        )
        status = "done"

    with connect_manifest(manifest_path) as conn:
        conn.execute(
            """
            UPDATE raw_pdf_download_runs
            SET finished_at = ?, status = ?, counts_json = ?
            WHERE run_id = ?
            """,
            (utc_now(), status, _json_dumps(counts), run_id),
        )
        conn.commit()
    print(_json_dumps({"run_id": run_id, "status": status, "counts": counts}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
