#!/usr/bin/env bash
# LEGACY compatibility: old arXiv gap-first closure helper.
# Not current V14B decision workflow; prefer product-chain/post-frontfill-chain.
# Directed ingest for arXiv IDs listed in reports/v14b_pilot/arxiv_optics_missing_ids.txt.
#
# Default path uses the existing V14B Semantic Scholar provider. arXiv remains
# available as a fallback:
#   MISSING_FETCH_PROVIDER=arxiv bash scripts/fetch_missing_arxiv_optics.sh
set -euo pipefail
if [[ "${V14B_RUN_LEGACY_ARXIV_FLOW:-0}" != "1" ]]; then
  echo "LEGACY compatibility script: old arXiv gap-first flow is not the current V14B decision workflow."
  echo "Set V14B_RUN_LEGACY_ARXIV_FLOW=1 to run it intentionally; otherwise use make product-chain or make post-frontfill-chain."
  exit 2
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DB="${ECHELON_LIBRARY_DB:-$ROOT/db/echelon_library.sqlite3}"
IDS_FILE="${1:-$ROOT/reports/v14b_pilot/arxiv_optics_missing_ids.txt}"
PROVIDER="${MISSING_FETCH_PROVIDER:-s2}"
LOG="${2:-$ROOT/logs/v14b/fetch_missing_arxiv_optics.log}"
mkdir -p "$(dirname "$LOG")"
if [[ ! -s "$IDS_FILE" ]]; then
  echo "No missing IDs file or empty: $IDS_FILE" | tee -a "$LOG"
  exit 0
fi
echo "[$(date '+%F %T')] fetch_missing start provider=${PROVIDER} ids=$(wc -l < "$IDS_FILE" | tr -d ' ')" | tee -a "$LOG"
export PYTHONPATH="$ROOT"
python3 -u << PYEOF 2>&1 | tee -a "$LOG"
import asyncio
import re
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

ROOT = Path("$ROOT")
sys.path.insert(0, str(ROOT))
IDS = [ln.strip() for ln in Path("$IDS_FILE").read_text().splitlines() if ln.strip()]
DB = "$DB"
PROVIDER = "$PROVIDER".strip().lower()


def norm_arxiv_id(raw):
    raw = (raw or "").strip()
    raw = re.sub(r"^arxiv:", "", raw, flags=re.I)
    raw = re.sub(r"v\\d+$", "", raw, flags=re.I)
    return raw


def clean_doi(raw):
    if not raw:
        return None
    d = str(raw).strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/", "doi:"):
        if d.lower().startswith(prefix):
            d = d[len(prefix):]
    return d or None


def arxiv_date_fallback(aid):
    m = re.match(r"(\\d{2})(\\d{2})\\.\\d+", aid or "")
    if m:
        yy = int(m.group(1))
        year = 2000 + yy if yy <= 90 else 1900 + yy
        month = max(1, min(12, int(m.group(2))))
        return date(year, month, 1)
    return date.today()


def s2_publication_date(data, aid):
    raw = data.get("publicationDate")
    if raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    year = data.get("year")
    if isinstance(year, int) and year > 0:
        return date(year, 1, 1)
    return arxiv_date_fallback(aid)


def s2_ref_external_id(ref):
    ext = ref.get("externalIds") or {}
    if ext.get("DOI"):
        return clean_doi(ext.get("DOI"))
    if ext.get("ArXiv"):
        return norm_arxiv_id(ext.get("ArXiv"))
    if ref.get("paperId"):
        return str(ref["paperId"])
    return None


def existing_row(arxiv_id, doi=None, s2_id=None):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, arxiv_id, doi, openalex_id FROM papers WHERE arxiv_id = ?",
            (arxiv_id,),
        ).fetchone()
        if row:
            return dict(row), "arxiv_id"
        if doi:
            row = conn.execute(
                "SELECT id, arxiv_id, doi, openalex_id FROM papers WHERE lower(doi) = lower(?)",
                (doi,),
            ).fetchone()
            if row:
                return dict(row), "doi"
        if s2_id:
            row = conn.execute(
                "SELECT id, arxiv_id, doi, openalex_id FROM papers WHERE openalex_id = ?",
                (s2_id,),
            ).fetchone()
            if row:
                return dict(row), "s2"
    return None, None


def s2_to_paper(aid, data):
    from echelon.core.ulid_utils import ulid_new
    from echelon.library.schema import Author, OpenAccessInfo, Paper

    ext = data.get("externalIds") or {}
    arxiv_id = norm_arxiv_id(ext.get("ArXiv") or aid)
    doi = clean_doi(ext.get("DOI"))
    authors = []
    for item in data.get("authors") or []:
        name = (item or {}).get("name")
        if name:
            authors.append(Author(id=ulid_new(), display_name=name.strip()))
    refs = [x for x in (s2_ref_external_id(r) for r in data.get("references") or []) if x]
    oa_pdf = data.get("openAccessPdf") or {}
    raw_jsonb = {
        "arxiv_id": arxiv_id,
        "arxiv_category": "physics.optics",
        "source": "semantic_scholar_directed_missing",
        "semantic_scholar": data,
    }
    return Paper(
        id=ulid_new(),
        openalex_id=data.get("paperId"),
        doi=doi,
        arxiv_id=arxiv_id,
        title=(data.get("title") or f"arXiv:{arxiv_id}").strip(),
        abstract=data.get("abstract"),
        publication_date=s2_publication_date(data, arxiv_id),
        n_authors=len(authors),
        cited_by_count=data.get("citationCount") or 0,
        primary_topic_id="physics.optics",
        language="en",
        open_access=OpenAccessInfo(
            is_oa=True,
            oa_status="green",
            oa_url=(oa_pdf.get("url") if isinstance(oa_pdf, dict) else None) or f"https://arxiv.org/abs/{arxiv_id}",
        ),
        raw_jsonb=raw_jsonb,
        source_provider="semantic_scholar",
        first_ingested_at=datetime.now(timezone.utc),
        authors=authors,
        references_external=refs,
    )


def persist_paper(paper):
    from echelon.library.db import (
        link_paper_author,
        upsert_author,
        upsert_paper,
        upsert_paper_references,
    )

    existing, how = existing_row(paper.arxiv_id, paper.doi, paper.openalex_id)
    if existing:
        if how == "doi" and existing.get("arxiv_id") and existing["arxiv_id"] != paper.arxiv_id:
            return "doi_collision", 0
        paper.id = existing["id"]
    d = paper.model_dump(exclude={"authors", "references_external"})
    if paper.open_access:
        d["open_access"] = paper.open_access.model_dump()
    upsert_paper(d, db_path=DB, refresh=bool(existing))
    for idx, author in enumerate(paper.authors):
        upsert_author(author.model_dump(), db_path=DB)
        link_paper_author(paper.id, author.id, idx, db_path=DB)
    nrefs = upsert_paper_references(paper.id, paper.references_external, db_path=DB)
    return ("refresh" if existing else "new"), nrefs


async def fetch_s2_missing():
    from echelon.v14b.config import SEMANTIC_SCHOLAR_API_KEY
    from echelon.v14b.enrich_providers import fetch_semantic_scholar

    if not SEMANTIC_SCHOLAR_API_KEY:
        raise RuntimeError("SEMANTIC_SCHOLAR_API_KEY is not set")
    new = refresh = skip = fail = refs = 0
    async with httpx.AsyncClient(timeout=45.0) as client:
        for i, aid in enumerate(IDS, 1):
            aid = norm_arxiv_id(aid)
            row, _ = existing_row(aid)
            if row:
                skip += 1
                print(f"[{i}/{len(IDS)}] exists {aid}")
                continue
            try:
                raw = await fetch_semantic_scholar(client, aid, None)
                if not raw:
                    fail += 1
                    print(f"[{i}/{len(IDS)}] FAIL s2 not found {aid}")
                    continue
                paper = s2_to_paper(aid, raw)
                status, nrefs = persist_paper(paper)
                refs += nrefs
                if status == "new":
                    new += 1
                    print(f"[{i}/{len(IDS)}] NEW s2 {aid} refs={nrefs}")
                elif status == "refresh":
                    refresh += 1
                    print(f"[{i}/{len(IDS)}] refresh s2 {aid} refs={nrefs}")
                else:
                    fail += 1
                    print(f"[{i}/{len(IDS)}] SKIP {status} {aid}")
            except Exception as exc:
                fail += 1
                print(f"[{i}/{len(IDS)}] ERROR s2 {aid}: {exc}")
    print(f"DONE provider=s2 new={new} refreshed={refresh} exists={skip} fail={fail} refs={refs} total={len(IDS)}")


async def fetch_arxiv_missing():
    from echelon.core.ulid_utils import ulid_new
    from echelon.crawler.arxiv_harvester import ArxivHarvester

    h = ArxivHarvester(request_delay=3.0)
    new = refresh = skip = fail = refs = 0
    for i, aid in enumerate(IDS, 1):
        aid = norm_arxiv_id(aid)
        if existing_row(aid)[0]:
            skip += 1
            print(f"[{i}/{len(IDS)}] exists {aid}")
            continue
        try:
            paper = await h.fetch_by_id(aid)
            if not paper:
                fail += 1
                print(f"[{i}/{len(IDS)}] FAIL arxiv not found {aid}")
                continue
            paper.id = paper.id or ulid_new()
            status, nrefs = persist_paper(paper)
            refs += nrefs
            if status == "new":
                new += 1
                print(f"[{i}/{len(IDS)}] NEW arxiv {aid}")
            elif status == "refresh":
                refresh += 1
                print(f"[{i}/{len(IDS)}] refresh arxiv {aid}")
            else:
                fail += 1
                print(f"[{i}/{len(IDS)}] SKIP {status} {aid}")
        except Exception as exc:
            fail += 1
            print(f"[{i}/{len(IDS)}] ERROR arxiv {aid}: {exc}")
    print(f"DONE provider=arxiv new={new} refreshed={refresh} exists={skip} fail={fail} refs={refs} total={len(IDS)}")


async def main():
    if PROVIDER in ("s2", "semantic", "semantic_scholar", "semanticscholar"):
        await fetch_s2_missing()
    elif PROVIDER == "arxiv":
        await fetch_arxiv_missing()
    else:
        raise SystemExit(f"unknown MISSING_FETCH_PROVIDER={PROVIDER!r}")


asyncio.run(main())
PYEOF
echo "[$(date '+%F %T')] fetch_missing done provider=${PROVIDER}" | tee -a "$LOG"
