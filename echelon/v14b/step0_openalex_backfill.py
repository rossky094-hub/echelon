"""Step 0.25: slow OpenAlex topic/reference backfill for graph readiness."""
from __future__ import annotations

import argparse
import asyncio
from difflib import SequenceMatcher
import logging
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx

from echelon.v14b.config import DB_MAIN, OPENALEX_EMAIL
from echelon.v14b.id_normalization import normalize_arxiv_id, normalize_doi
from echelon.v14b.step1_enrich import (
    ensure_enrich_tables,
    link_paper_reference_internals,
    parse_openalex_work,
    write_enrich_result,
)
from echelon.v14b.utils import make_progress, setup_logging

logger = logging.getLogger("echelon.v14b.step0_openalex_backfill")

OPENALEX_FIELDS = (
    "id,doi,title,publication_year,cited_by_count,primary_topic,topics,"
    "referenced_works,authorships,locations,ids"
)


def available_memory_gb() -> Optional[float]:
    """Best-effort macOS available memory estimate for concurrency caps."""
    try:
        out = subprocess.check_output(["vm_stat"], text=True, timeout=3)
    except Exception:
        return None
    page_size = 16384
    m = re.search(r"page size of (\d+) bytes", out)
    if m:
        page_size = int(m.group(1))
    pages = {}
    for key in ("Pages free", "Pages speculative", "Pages inactive", "Pages purgeable"):
        m = re.search(rf"{key}:\s+(\d+)", out)
        if m:
            pages[key] = int(m.group(1))
    available_bytes = (
        pages.get("Pages free", 0)
        + pages.get("Pages speculative", 0)
        + pages.get("Pages inactive", 0)
        + pages.get("Pages purgeable", 0)
    ) * page_size
    return available_bytes / (1024 ** 3)


def memory_capped_concurrency(requested: int) -> int:
    avail_gb = available_memory_gb()
    if avail_gb is None:
        return max(1, requested)
    if avail_gb < 1.5:
        cap = 1
    elif avail_gb < 3.0:
        cap = 2
    else:
        cap = requested
    capped = max(1, min(requested, cap))
    if capped != requested:
        logger.warning(
            "Capping OpenAlex concurrency from %d to %d because available memory is %.2f GiB",
            requested,
            capped,
            avail_gb,
        )
    else:
        logger.info("OpenAlex concurrency=%d; available memory %.2f GiB", capped, avail_gb)
    return capped


def load_targets(conn: sqlite3.Connection, limit: Optional[int] = None) -> list[dict]:
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(papers)").fetchall()}
    title_expr = "title" if "title" in cols else "'' AS title"
    if "publication_year" in cols:
        year_expr = "publication_year"
    elif "publication_date" in cols:
        year_expr = "CAST(substr(publication_date, 1, 4) AS INTEGER) AS publication_year"
    else:
        year_expr = "NULL AS publication_year"
    order_date_expr = "publication_date" if "publication_date" in cols else "id"
    q = f"""
        SELECT id, {title_expr}, doi, arxiv_id, {year_expr}
        FROM papers
        WHERE (
              openalex_id IS NULL
              OR openalex_id NOT LIKE 'W%'
              OR primary_field_id IS NULL
              OR primary_topic_id LIKE 'S2F:%'
          )
          AND (
              (doi IS NOT NULL AND doi != '')
              OR (arxiv_id IS NOT NULL AND arxiv_id != '')
          )
        ORDER BY
          -- DOI lookups are exact and high-yield.  Run them before arXiv-only
          -- lookups so an interrupted conservative backfill improves OpenAlex
          -- coverage instead of spending hours on low-yield arXiv URL misses.
          CASE
            WHEN doi IS NOT NULL AND doi != '' THEN 0
            ELSE 1
          END,
              CASE
                WHEN openalex_id IS NULL OR openalex_id NOT LIKE 'W%' THEN 0
                ELSE 1
              END,
              {order_date_expr},
              id
    """
    if limit:
        q += f" LIMIT {int(limit)}"
    return [dict(r) for r in conn.execute(q).fetchall()]


def _text_key(text: Optional[str]) -> str:
    value = (text or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _title_similarity(a: Optional[str], b: Optional[str]) -> float:
    left = _text_key(a)
    right = _text_key(b)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _work_mentions_arxiv(work: dict, clean_arxiv: Optional[str]) -> bool:
    if not clean_arxiv:
        return False
    compact = clean_arxiv.lower().replace("arxiv:", "")
    payload = str(work.get("ids") or "") + " " + str(work.get("locations") or "")
    return compact in payload.lower()


def _verified_search_match(paper: dict, work: dict) -> bool:
    """Conservative guard for title-search fallback results."""

    clean_doi = normalize_doi(paper.get("doi"))
    work_doi = normalize_doi(work.get("doi"))
    if clean_doi and work_doi and clean_doi == work_doi:
        return True

    clean_arxiv = normalize_arxiv_id(paper.get("arxiv_id"))
    if _work_mentions_arxiv(work, clean_arxiv):
        return True

    sim = _title_similarity(paper.get("title"), work.get("title"))
    if sim >= 0.94:
        return True
    paper_year = paper.get("publication_year")
    work_year = work.get("publication_year")
    try:
        year_close = abs(int(paper_year) - int(work_year)) <= 1
    except Exception:
        year_close = False
    return bool(year_close and sim >= 0.90)


def openalex_urls(paper: dict) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    clean_doi = normalize_doi(paper.get("doi"))
    clean_arxiv = normalize_arxiv_id(paper.get("arxiv_id"))
    if clean_doi:
        urls.append((
            "https://api.openalex.org/works/doi:"
            f"{clean_doi}?select={OPENALEX_FIELDS}&mailto={OPENALEX_EMAIL}",
            "doi",
        ))
    if clean_arxiv:
        urls.append((
            "https://api.openalex.org/works?"
            f"filter=locations.landing_page_url:https://arxiv.org/abs/{clean_arxiv}"
            f"&per_page=1&select={OPENALEX_FIELDS}&mailto={OPENALEX_EMAIL}",
            "arxiv_url",
        ))
    title = _text_key(paper.get("title"))
    if len(title) >= 12:
        urls.append(
            (
                "https://api.openalex.org/works?"
                + urlencode(
                    {
                        "search": paper.get("title") or title,
                        "per_page": "3",
                        "select": OPENALEX_FIELDS,
                        "mailto": OPENALEX_EMAIL,
                    }
                ),
                "title_verified",
            )
        )
    return urls


async def fetch_openalex_one(client: httpx.AsyncClient, paper: dict, delay: float) -> Optional[dict]:
    for url, mode in openalex_urls(paper):
        for attempt in range(6):
            resp = await client.get(url, timeout=45.0)
            if resp.status_code == 200:
                data = resp.json()
                await asyncio.sleep(delay)
                if isinstance(data, dict) and "results" in data:
                    results = data.get("results") or []
                    if not results:
                        break
                    if mode == "title_verified":
                        for candidate in results:
                            if isinstance(candidate, dict) and _verified_search_match(paper, candidate):
                                return candidate
                        logger.debug("OpenAlex title search rejected paper=%s", paper.get("id"))
                        break
                    return results[0]
                return data
            if resp.status_code == 404:
                break
            if resp.status_code == 429:
                retry_after = resp.headers.get("retry-after")
                try:
                    wait = float(retry_after) if retry_after else 0.0
                except ValueError:
                    wait = 0.0
                wait = max(wait, delay, min(300.0, 60.0 * (attempt + 1)))
                logger.warning("OpenAlex 429, cooldown %.1fs", wait)
                await asyncio.sleep(wait)
                continue
            logger.warning("OpenAlex HTTP %s: %s", resp.status_code, resp.text[:160])
            await asyncio.sleep(delay)
    return None


async def run_backfill_async(
    db_path: Path,
    *,
    limit: Optional[int],
    concurrency: int,
    delay: float,
) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_enrich_tables(conn)
    targets = load_targets(conn, limit)
    logger.info("OpenAlex backfill targets: %d", len(targets))

    worker_n = memory_capped_concurrency(max(1, concurrency))
    ok = 0
    fail = 0
    processed = 0
    linked_at = 0

    async with httpx.AsyncClient(timeout=45.0) as client:
        queue: asyncio.Queue[Optional[dict]] = asyncio.Queue()
        for paper in targets:
            queue.put_nowait(paper)
        for _ in range(worker_n):
            queue.put_nowait(None)

        async def worker() -> None:
            nonlocal ok, fail, processed, linked_at
            while True:
                paper = await queue.get()
                try:
                    if paper is None:
                        return
                    try:
                        raw = await fetch_openalex_one(client, paper, delay)
                    except Exception as exc:
                        logger.warning("OpenAlex fetch failed paper=%s: %s", paper.get("id"), exc)
                        raw = None
                    if not raw:
                        fail += 1
                    else:
                        try:
                            write_enrich_result(conn, parse_openalex_work(paper["id"], raw))
                            conn.commit()
                            ok += 1
                        except Exception as exc:
                            logger.warning("OpenAlex write failed paper=%s: %s", paper["id"], exc)
                            fail += 1
                    if ok and ok % 100 == 0 and ok != linked_at:
                        link_paper_reference_internals(conn)
                        linked_at = ok
                    processed += 1
                    if processed % 500 == 0:
                        logger.info(
                            "OpenAlex backfill progress: processed=%d/%d ok=%d fail=%d",
                            processed,
                            len(targets),
                            ok,
                            fail,
                        )
                    pbar.update(1)
                    pbar.set_postfix(ok=ok, fail=fail)
                finally:
                    queue.task_done()

        with make_progress(
            range(len(targets)),
            desc="OpenAlex backfill",
            total=len(targets),
            disable=not sys.stderr.isatty(),
            mininterval=10,
        ) as pbar:
            workers = [asyncio.create_task(worker()) for _ in range(worker_n)]
            await queue.join()
            await asyncio.gather(*workers)

    link_paper_reference_internals(conn)
    conn.close()
    stats = {"records_n": ok, "failed": fail}
    logger.info("OpenAlex backfill done: %s", stats)
    return stats


def run_backfill(
    db_path: Path = DB_MAIN,
    *,
    limit: Optional[int] = None,
    concurrency: int = 1,
    delay: float = 1.2,
) -> dict:
    return asyncio.run(
        run_backfill_async(db_path, limit=limit, concurrency=concurrency, delay=delay)
    )


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Backfill OpenAlex topics/references")
    parser.add_argument("--db", type=Path, default=DB_MAIN)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--delay", type=float, default=1.2)
    args = parser.parse_args(argv)
    setup_logging("step0_openalex_backfill")
    run_backfill(args.db, limit=args.limit, concurrency=args.concurrency, delay=args.delay)


if __name__ == "__main__":
    main()
