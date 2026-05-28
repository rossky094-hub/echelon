"""Step 5s: ingest section-level evidence for limitation tracking.

This step materializes `paper_sections` in the main library DB so Step5c can
read limitation/discussion/conclusion/future-work evidence from full text
instead of falling back to abstract-only extraction.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from echelon.pdf.parser import parse_pdf_pages
from echelon.v14b.config import (
    DB_MAIN,
    DB_V14,
    LIMIT,
    LIMITATION_TOP_N,
    SEMANTIC_SCHOLAR_API_KEY,
    SECTION_INGEST_CONCURRENCY,
    SECTION_INGEST_MAX_CHARS,
    SECTION_INGEST_MIN_CHARS,
    SECTION_INGEST_REQUIRE_ARXIV,
    SECTION_INGEST_TIMEOUT_SEC,
    SECTION_INGEST_TOP_N,
)
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.id_normalization import normalize_arxiv_id, normalize_doi
from echelon.v14b.utils import Checkpoint, add_common_args, make_progress, setup_logging

logger = logging.getLogger("echelon.v14b.step5s_section_ingest")

PRIMARY_SECTION_NAMES = (
    "limitations",
    "discussion",
    "conclusion",
    "future_work",
)

# Beyond the four core section types, these sections provide additional
# interpretable constraints/mechanism evidence for branch diagnostics.
SECONDARY_SECTION_NAMES = (
    "results",
    "error_analysis",
    "ablation",
    "method",
    "experiments",
)

SECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("limitations", re.compile(r"^\s*(\d+(\.\d+)?)?\s*(limitation|limitations|open challenges?)\s*$", re.I)),
    ("discussion", re.compile(r"^\s*(\d+(\.\d+)?)?\s*discussion\s*$", re.I)),
    ("conclusion", re.compile(r"^\s*(\d+(\.\d+)?)?\s*(conclusion|conclusions|concluding remarks?)\s*$", re.I)),
    ("future_work", re.compile(r"^\s*(\d+(\.\d+)?)?\s*(future work|outlook|perspective|perspectives)\s*$", re.I)),
    ("results", re.compile(r"^\s*(\d+(\.\d+)?)?\s*(results?|evaluation)\s*$", re.I)),
    ("error_analysis", re.compile(r"^\s*(\d+(\.\d+)?)?\s*(error analysis|failure analysis|limitations and discussion)\s*$", re.I)),
    ("ablation", re.compile(r"^\s*(\d+(\.\d+)?)?\s*ablation( study)?\s*$", re.I)),
    ("method", re.compile(r"^\s*(\d+(\.\d+)?)?\s*(method|methods|methodology|approach)\s*$", re.I)),
    ("experiments", re.compile(r"^\s*(\d+(\.\d+)?)?\s*(experiment|experiments|experimental setup)\s*$", re.I)),
]


def ensure_sections_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_sections (
            paper_id TEXT NOT NULL,
            section_name TEXT NOT NULL,
            section_text TEXT NOT NULL,
            source_type TEXT,
            parser_name TEXT,
            source_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (paper_id, section_name)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_sections_paper ON paper_sections(paper_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_sections_name ON paper_sections(section_name)"
    )
    conn.commit()


def _arxiv_pdf_url(arxiv_id: Optional[str], doi: Optional[str]) -> Optional[str]:
    aid = normalize_arxiv_id(arxiv_id)
    if not aid and doi:
        clean_doi = normalize_doi(doi) or ""
        m = re.match(r"^10\.48550/arxiv\.(.+)$", clean_doi, re.I)
        if m:
            aid = normalize_arxiv_id(m.group(1))
    if not aid:
        return None
    return f"https://arxiv.org/pdf/{aid}.pdf"


def _select_candidate_ids(conn_v14: sqlite3.Connection, top_n: int) -> list[str]:
    rows = conn_v14.execute(
        """
        SELECT paper_id
        FROM subgraph_nodes
        WHERE is_keystone = 1
        ORDER BY keystone_score_v14 DESC
        LIMIT ?
        """,
        (top_n,),
    ).fetchall()
    ids = [row[0] for row in rows]
    if ids:
        return ids
    rows = conn_v14.execute(
        "SELECT paper_id FROM subgraph_nodes LIMIT ?",
        (top_n,),
    ).fetchall()
    return [row[0] for row in rows]


def load_candidates(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    top_n: int,
) -> list[dict]:
    ids = _select_candidate_ids(conn_v14, top_n)
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = conn_main.execute(
        f"""
        SELECT id, title, arxiv_id, doi, s2_paper_id
        FROM papers
        WHERE id IN ({placeholders})
        ORDER BY publication_date DESC, id
        """,
        ids,
    ).fetchall()
    papers = [dict(r) for r in rows]

    if SECTION_INGEST_REQUIRE_ARXIV:
        papers = [
            p for p in papers
            if _arxiv_pdf_url(p.get("arxiv_id"), p.get("doi"))
        ]
    return papers


def _heading_to_section(line: str) -> Optional[str]:
    normalized = re.sub(r"\s+", " ", line.strip())
    normalized = normalized[:120]
    if not normalized:
        return None
    for sec_name, pattern in SECTION_PATTERNS:
        if pattern.match(normalized):
            return sec_name
    return None


def extract_sections_from_blocks(blocks) -> dict[str, str]:
    sections: dict[str, list[str]] = {name: [] for name, _ in SECTION_PATTERNS}
    current: Optional[str] = None

    for block in blocks:
        text = (block.text or "").replace("\x00", " ").strip()
        if not text:
            continue

        # Keep parser-level section hints as a weak backup.
        hint = (block.section_hint or "").lower()
        if hint == "limitations":
            sections["limitations"].append(text[:1200])
        elif hint == "conclusion":
            sections["conclusion"].append(text[:1200])

        for line in text.splitlines():
            clean = line.strip()
            if not clean:
                continue
            heading = _heading_to_section(clean)
            if heading:
                current = heading
                continue
            if current:
                sections[current].append(clean)

    merged: dict[str, str] = {}
    for sec_name, lines in sections.items():
        if not lines:
            continue
        blob = re.sub(r"\s+", " ", " ".join(lines)).strip()
        if len(blob) < SECTION_INGEST_MIN_CHARS:
            continue
        merged[sec_name] = blob[:SECTION_INGEST_MAX_CHARS]
    return merged


def _has_primary_sections(conn: sqlite3.Connection, paper_id: str) -> bool:
    placeholders = ",".join("?" * len(PRIMARY_SECTION_NAMES))
    row = conn.execute(
        f"""
        SELECT COUNT(*) FROM paper_sections
        WHERE paper_id = ?
          AND section_name IN ({placeholders})
          AND section_text IS NOT NULL
          AND length(trim(section_text)) >= ?
        """,
        (paper_id, *PRIMARY_SECTION_NAMES, SECTION_INGEST_MIN_CHARS),
    ).fetchone()
    return bool(row and row[0])


def upsert_sections(
    conn: sqlite3.Connection,
    paper_id: str,
    sections: dict[str, str],
    source_url: str,
) -> int:
    inserted = 0
    parser_name = "v14b_section_ingest_v2"
    for sec_name, sec_text in sections.items():
        conn.execute(
            """
            INSERT INTO paper_sections
                (paper_id, section_name, section_text, source_type, parser_name, source_url)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_id, section_name) DO UPDATE SET
                section_text = CASE
                    WHEN length(excluded.section_text) > length(paper_sections.section_text)
                    THEN excluded.section_text ELSE paper_sections.section_text END,
                source_type = excluded.source_type,
                parser_name = excluded.parser_name,
                source_url = excluded.source_url
            """,
            (paper_id, sec_name, sec_text, "arxiv_pdf", parser_name, source_url),
        )
        inserted += 1
    return inserted


def download_pdf(client: httpx.Client, url: str) -> Optional[bytes]:
    for attempt in range(3):
        try:
            resp = client.get(url, timeout=SECTION_INGEST_TIMEOUT_SEC)
            if resp.status_code == 200 and resp.content:
                return resp.content
            if resp.status_code in (429, 503):
                wait_s = min(30, 4 * (attempt + 1))
                logger.warning("PDF fetch %s -> %s, retry in %ss", url, resp.status_code, wait_s)
                import time

                time.sleep(wait_s)
                continue
            logger.debug("PDF fetch failed %s status=%s", url, resp.status_code)
            return None
        except Exception as exc:
            logger.debug("PDF fetch error %s: %s", url, exc)
    return None


def semantic_pdf_url(client: httpx.Client, paper: dict) -> Optional[str]:
    headers = {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}
    ids = []
    if paper.get("s2_paper_id"):
        ids.append(str(paper["s2_paper_id"]).strip())
    if paper.get("doi"):
        ids.append(f"DOI:{normalize_doi(paper['doi'])}")
    if paper.get("arxiv_id"):
        ids.append(f"ARXIV:{normalize_arxiv_id(paper['arxiv_id'])}")
    ids = [x for x in ids if x and not x.endswith(":None")]
    if not ids:
        return None

    for pid in ids:
        try:
            resp = client.get(
                f"https://api.semanticscholar.org/graph/v1/paper/{pid}",
                params={"fields": "openAccessPdf"},
                headers=headers,
                timeout=SECTION_INGEST_TIMEOUT_SEC,
            )
            if resp.status_code != 200:
                continue
            data = resp.json() or {}
            open_pdf = data.get("openAccessPdf") or {}
            pdf_url = open_pdf.get("url")
            if pdf_url and isinstance(pdf_url, str):
                return pdf_url
        except Exception:
            continue
    return None


def resolve_pdf_url(client: httpx.Client, paper: dict) -> Optional[str]:
    arxiv_url = _arxiv_pdf_url(paper.get("arxiv_id"), paper.get("doi"))
    if arxiv_url:
        return arxiv_url
    if SECTION_INGEST_REQUIRE_ARXIV:
        return None
    return semantic_pdf_url(client, paper)


def run_section_ingest(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    top_n: int = SECTION_INGEST_TOP_N,
    limit: Optional[int] = None,
    resume: bool = True,
) -> dict:
    step_name = "step5s_section_ingest"
    ck = Checkpoint(step_name)
    if resume and ck.done():
        data = ck.load()
        logger.info("Step5s 已完成 (%d sections), 跳过", data.get("records_n", 0))
        return data

    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    conn_main.execute("PRAGMA journal_mode=WAL")
    ensure_sections_table(conn_main)

    conn_v14 = get_v14b_conn(db_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    n_target = int(limit or top_n or LIMITATION_TOP_N)
    papers = load_candidates(conn_main, conn_v14, n_target)
    if limit:
        papers = papers[: int(limit)]

    logger.info("Step5s candidates=%d (top_n=%d)", len(papers), n_target)
    if not papers:
        stats = {"records_n": 0, "papers_n": 0, "with_primary_sections": 0}
        ck.mark_done(records_n=0, meta=stats)
        upsert_step_meta(conn_v14, step_name, "done", records_n=0)
        conn_main.close()
        conn_v14.close()
        return stats

    primary_hit = 0
    inserted_sections = 0
    parsed_papers = 0
    skipped_existing = 0
    skipped_no_pdf = 0
    failed_parse = 0
    section_counter = {name: 0 for name, _ in SECTION_PATTERNS}

    # Keep concurrency intentionally low to avoid memory pressure on local Macs.
    limits = httpx.Limits(max_connections=max(1, SECTION_INGEST_CONCURRENCY))
    with httpx.Client(limits=limits, follow_redirects=True) as client:
        with make_progress(papers, desc="Step5s sections") as pbar:
            for paper in pbar:
                pid = paper["id"]
                if _has_primary_sections(conn_main, pid):
                    skipped_existing += 1
                    primary_hit += 1
                    continue

                pdf_url = resolve_pdf_url(client, paper)
                if not pdf_url:
                    skipped_no_pdf += 1
                    continue
                blob = download_pdf(client, pdf_url)
                if not blob:
                    skipped_no_pdf += 1
                    continue

                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(blob)
                    tmp_path = tmp.name
                try:
                    blocks = parse_pdf_pages(tmp_path)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                if not blocks:
                    failed_parse += 1
                    continue

                sections = extract_sections_from_blocks(blocks)
                if not sections:
                    failed_parse += 1
                    continue

                parsed_papers += 1
                inserted_sections += upsert_sections(conn_main, pid, sections, pdf_url)
                for sec_name in sections:
                    section_counter[sec_name] = section_counter.get(sec_name, 0) + 1
                conn_main.commit()
                if any(sec in sections for sec in PRIMARY_SECTION_NAMES):
                    primary_hit += 1

                pbar.set_postfix(
                    parsed=parsed_papers,
                    primary=primary_hit,
                    sections=inserted_sections,
                )

    coverage = primary_hit / max(1, len(papers))
    stats = {
        "records_n": inserted_sections,
        "papers_n": len(papers),
        "parsed_papers": parsed_papers,
        "with_primary_sections": primary_hit,
        "primary_section_coverage": coverage,
        "skipped_existing": skipped_existing,
        "skipped_no_pdf": skipped_no_pdf,
        "failed_parse": failed_parse,
        "section_counter": section_counter,
        "extra_sections_enabled": list(SECONDARY_SECTION_NAMES),
    }
    logger.info("Step5s done: %s", stats)
    ck.mark_done(records_n=inserted_sections, meta=stats)
    upsert_step_meta(conn_v14, step_name, "done", records_n=inserted_sections)

    conn_main.close()
    conn_v14.close()
    return stats


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step5s_section_ingest",
        description="Step 5s: ingest PDF section evidence into paper_sections",
    )
    add_common_args(parser)
    parser.add_argument("--top-n", type=int, default=SECTION_INGEST_TOP_N)
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step5s_section_ingest", level=log_level)
    run_section_ingest(
        db_main=Path(args.db) if args.db else DB_MAIN,
        db_v14=Path(args.db_v14) if args.db_v14 else DB_V14,
        top_n=args.top_n,
        limit=args.limit or LIMIT,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
