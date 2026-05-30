#!/usr/bin/env python3
"""LEGACY compatibility: diff cat:physics.optics arXiv IDs vs the DB.

This is not the current V14B decision workflow.  The current path is
section evidence top12000 plus OpenAlex/local field-topic backfill, then
`make product-chain` or `make post-frontfill-chain`.
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ARXIV_API = "https://export.arxiv.org/api/query"
CATEGORY = "physics.optics"
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
PAGE_SIZE = 2000
MAX_START = 10000
DEFAULT_DELAY = 3.0
LEGACY_OPT_IN_ENV = "V14B_RUN_LEGACY_ARXIV_FLOW"


def require_legacy_opt_in() -> None:
    if os.environ.get(LEGACY_OPT_IN_ENV) == "1":
        return
    print(
        "LEGACY compatibility script: old arXiv gap-first flow is not the current "
        "V14B decision workflow. Set V14B_RUN_LEGACY_ARXIV_FLOW=1 to run it intentionally; "
        "otherwise use make product-chain or make post-frontfill-chain.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def log(message: str) -> None:
    print(message, flush=True)


def norm_arxiv_id(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"v\d+$", "", raw, flags=re.I)
    m = re.search(r"(\d{4}\.\d{4,5}|[a-z-]+/\d{7,})", raw, re.I)
    return m.group(1) if m else raw


def iter_months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def api_query(search_query: str, start: int, delay: float) -> bytes:
    import urllib.error

    params = {
        "search_query": search_query,
        "start": start,
        "max_results": PAGE_SIZE,
        "sortBy": "submittedDate",
        "sortOrder": "ascending",
    }
    url = ARXIV_API + "?" + urllib.parse.urlencode(params)
    backoff = max(delay, 10.0)
    for attempt in range(8):
        time.sleep(delay if attempt == 0 else backoff)
        req = urllib.request.Request(url, headers={"User-Agent": "Echelon-diff/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < 7:
                log(f"WARN HTTP {e.code} retry {attempt+1} query start={start}")
                backoff = min(backoff * 1.5, 120.0)
                continue
            raise


def parse_feed(content: bytes) -> tuple[int, list[str]]:
    root = ET.fromstring(content)
    total_el = root.find("opensearch:totalResults", ATOM_NS)
    total = int(total_el.text) if total_el is not None and total_el.text else 0
    ids: list[str] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        id_el = entry.find("atom:id", ATOM_NS)
        if id_el is None or not id_el.text:
            continue
        m = re.search(r"arxiv\.org/abs/([^/\s]+)", id_el.text)
        if m:
            ids.append(norm_arxiv_id(m.group(1)))
    return total, ids


def fetch_ids_for_query(search_query: str, delay: float) -> set[str]:
    out: set[str] = set()
    start = 0
    while start <= MAX_START:
        content = api_query(search_query, start, delay)
        total, ids = parse_feed(content)
        out.update(ids)
        start += len(ids)
        if start >= total or not ids or len(ids) < PAGE_SIZE:
            break
        if start > MAX_START:
            log(f"WARN hit API start cap for query={search_query!r} collected={len(out)} total={total}")
            break
    return out


def read_cached_ids(path: Path) -> set[str] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        return {norm_arxiv_id(x) for x in payload.get("ids", []) if x}
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def write_cached_ids(path: Path, query: str, ids: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"query": query, "ids": sorted(ids)}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n")
    tmp.replace(path)


def fetch_cached_window(cache_dir: Path, label: str, query: str, delay: float) -> tuple[set[str], bool]:
    cache_path = cache_dir / f"{label}.json"
    cached = read_cached_ids(cache_path)
    if cached is not None:
        return cached, True
    ids = fetch_ids_for_query(query, delay)
    write_cached_ids(cache_path, query, ids)
    return ids, False


def fetch_all_arxiv_ids(
    from_d: date,
    to_d: date,
    delay: float,
    window: str,
    cache_dir: Path,
) -> set[str]:
    all_ids: set[str] = set()
    cache_dir.mkdir(parents=True, exist_ok=True)
    if window == "year":
        for year in range(from_d.year, to_d.year + 1):
            q = f"cat:{CATEGORY} AND submittedDate:[{year}0101000000 TO {year}1231235959]"
            year_ids, from_cache = fetch_cached_window(cache_dir / "year", str(year), q, delay)
            all_ids.update(year_ids)
            source = "cache" if from_cache else "api"
            log(f"{year}: {source}={len(year_ids)} cumulative={len(all_ids)}")
        return all_ids

    for year, month in iter_months(from_d, to_d):
        last_day = calendar.monthrange(year, month)[1]
        q = (
            f"cat:{CATEGORY} AND "
            f"submittedDate:[{year}{month:02d}01000000 TO {year}{month:02d}{last_day:02d}235959]"
        )
        label = f"{year}-{month:02d}"
        month_ids, from_cache = fetch_cached_window(cache_dir / "month", label, q, delay)
        all_ids.update(month_ids)
        source = "cache" if from_cache else "api"
        log(f"{label}: {source}={len(month_ids)} cumulative={len(all_ids)}")
    return all_ids


def load_db_ids(db_path: Path) -> dict[str, dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT arxiv_id, id, primary_topic_id, raw_jsonb FROM papers WHERE arxiv_id IS NOT NULL"
    ).fetchall()
    conn.close()
    by_id: dict[str, dict] = {}
    for r in rows:
        aid = norm_arxiv_id(r["arxiv_id"] or "")
        if aid:
            by_id[aid] = dict(r)
    return by_id


def api_total() -> int:
    content = api_query(f"cat:{CATEGORY}", 0, 0.5)
    total, _ = parse_feed(content)
    return total


def main() -> None:
    require_legacy_opt_in()
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="db/echelon_library.sqlite3")
    p.add_argument("--from", dest="from_date", default="1991-01-01")
    p.add_argument("--to", dest="to_date", default=None)
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    p.add_argument("--out-dir", default="reports/v14b_pilot")
    p.add_argument("--cache-dir", default="reports/v14b_pilot/checkpoints/arxiv_optics_diff")
    p.add_argument("--window", choices=("month", "year"), default="month")
    args = p.parse_args()

    root = Path(__file__).resolve().parents[1]
    db_path = (root / args.db).resolve()
    out_dir = (root / args.out_dir).resolve()
    cache_dir = (root / args.cache_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    to_d = date.fromisoformat(args.to_date) if args.to_date else date.today()
    from_d = date.fromisoformat(args.from_date)

    log("Querying API cat total...")
    cat_total = api_total()
    log(f"API cat:physics.optics totalResults={cat_total}")

    db_by_id = load_db_ids(db_path)
    log(f"DB arxiv_id rows={len(db_by_id)} papers total query next...")

    arxiv_ids = fetch_all_arxiv_ids(from_d, to_d, args.delay, args.window, cache_dir)
    missing = sorted(arxiv_ids - set(db_by_id.keys()))
    extra_in_db = sorted(set(db_by_id.keys()) - arxiv_ids)

    # filter mismatch: in DB, window fetched, but no physics.optics tag in metadata
    in_db_no_tag = []
    for aid in sorted(arxiv_ids & set(db_by_id.keys())):
        row = db_by_id[aid]
        raw = row.get("raw_jsonb") or ""
        topic = row.get("primary_topic_id") or ""
        if "physics.optics" not in raw and "optics" not in topic.lower():
            in_db_no_tag.append(aid)

    missing_path = out_dir / "arxiv_optics_missing_ids.txt"
    missing_path.write_text("\n".join(missing) + ("\n" if missing else ""))

    report = [
        "# arXiv physics.optics gap report",
        "",
        f"- Generated: {date.today().isoformat()}",
        f"- API totalResults (cat:{CATEGORY}): **{cat_total}**",
        f"- Enumeration window: {from_d} .. {to_d}",
        f"- Enumeration granularity: **{args.window}**",
        f"- Unique arXiv IDs fetched (window): **{len(arxiv_ids)}**",
        f"- DB papers with arxiv_id: **{len(db_by_id)}**",
        f"- In arXiv window but not in DB: **{len(missing)}**",
        f"- In DB but not in arXiv window fetch: **{len(extra_in_db)}**",
        f"- In both but monitor optics tag missing: **{len(in_db_no_tag)}**",
        "",
        "## Root cause notes",
        "",
        "1. **True crawl gap**: IDs in `arxiv_optics_missing_ids.txt`.",
        "2. **Filter artifact**: monitor uses `primary_topic_id LIKE '%optics%'` OR `raw_jsonb` contains `physics.optics`.",
        "3. **Backfill 10k cap**: `cat:physics.optics` without monthly `submittedDate` hits API start=10000 (500 errors in logs).",
        "4. **Worker `failed` counter**: often `UNIQUE constraint failed: papers.arxiv_id` on version collisions during refresh, not absent rows.",
        "5. **Target 56000**: approximate; live API total drifts (e.g. 56251).",
        "",
        "## Sample missing IDs (first 30)",
        "",
    ]
    report.extend(f"- `{x}`" for x in missing[:30])
    if not missing:
        report.append("- (none in this window)")
    report_path = out_dir / "arxiv_optics_gap_report.md"
    report_path.write_text("\n".join(report) + "\n")
    log(f"Wrote {missing_path} ({len(missing)} ids)")
    log(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
