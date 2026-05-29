"""
Step 0.5: Coverage / Quality Audit for the V14B optics library.

This step is intentionally algorithmic and reproducible. It does not ask an
LLM to judge data completeness. Instead it produces:

- coverage_quality_audit.json
- coverage_quality_audit.md
- missing_by_year.csv
- provider_coverage.csv
- reference_linkage_report.csv
- id_collision_report.csv
- sample_for_llm_review.jsonl
- expert_review_sample.csv

LLM and human review should start from those samples, after the full-library
statistics are already known.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Optional

from echelon.v14b.config import DB_MAIN, REPORT_DIR, LOG_DIR
from echelon.v14b.utils import setup_logging, table_columns
from echelon.v14b.corpus_registry import create_temp_corpus_table, ensure_corpus_schema

logger = logging.getLogger("echelon.v14b.step0_quality_audit")

DEFAULT_SCOPE_WHERE = "1=1"


def scope_where_expr(
    *,
    corpus_id: str | None,
    alias: str = "",
    id_col: str = "id",
) -> str:
    """Return SQL where-clause for full library or a corpus temp table."""
    if not corpus_id:
        return DEFAULT_SCOPE_WHERE
    prefix = f"{alias}." if alias else ""
    return f"{prefix}{id_col} IN (SELECT paper_id FROM v14b_corpus_papers)"


@dataclass
class Gate:
    name: str
    status: str
    value: Any
    threshold: str
    note: str


def _fetchone(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0]


def _fetchall_dict(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def pct(n: int | float, d: int | float) -> float:
    return 0.0 if not d else float(n) / float(d)


def pct_str(x: float) -> str:
    return f"{100 * x:.2f}%"


def status_for(value: float, fail_below: float, warn_below: float) -> str:
    if value < fail_below:
        return "fail"
    if value < warn_below:
        return "warn"
    return "pass"


def arxiv_year(arxiv_id: str | None) -> Optional[int]:
    if not arxiv_id:
        return None
    aid = arxiv_id.strip()
    m = re.match(r"^(\d{2})(\d{2})\.\d{4,5}$", aid)
    if m:
        yy = int(m.group(1))
        return 2000 + yy if yy <= 90 else 1900 + yy
    m = re.match(r"^[a-z-]+/(\d{2})(\d{2})\d+", aid, re.I)
    if m:
        yy = int(m.group(1))
        return 2000 + yy if yy <= 90 else 1900 + yy
    return None


def parse_expected_total(report_path: Path) -> Optional[int]:
    if not report_path.exists():
        return None
    text = report_path.read_text(encoding="utf-8", errors="ignore")
    patterns = [
        r"API totalResults .*?\*\*(\d+)\*\*",
        r"API cat:physics\.optics totalResults=(\d+)",
        r"totalResults[^\d]+(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return int(m.group(1))
    return None


def read_missing_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]


def percentile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    idx = min(len(xs) - 1, max(0, round((len(xs) - 1) * q)))
    return float(xs[idx])


def write_csv(path: Path, rows: Iterable[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fieldnames})


def normalize_event_type(line: str) -> Optional[str]:
    if "doi_collision" in line:
        return "doi_collision"
    if "Semantic Scholar 429" in line or " 429" in line:
        return "rate_limit_429"
    if "] FAIL " in line:
        return "fetch_fail"
    if "] ERROR " in line:
        return "fetch_error"
    if "UNIQUE constraint failed" in line:
        return "unique_constraint"
    return None


def collect_log_events(log_paths: list[Path]) -> tuple[list[dict], dict[str, int]]:
    events: list[dict] = []
    counts: Counter[str] = Counter()
    for path in log_paths:
        if not path.exists():
            continue
        for line_no, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            typ = normalize_event_type(line)
            if not typ:
                continue
            counts[typ] += 1
            aid = None
            m = re.search(r"(?:ARXIV:)?(\d{4}\.\d{4,5}|[a-z-]+/\d{7})", line, re.I)
            if m:
                aid = m.group(1)
            events.append({
                "file": str(path),
                "line": line_no,
                "event_type": typ,
                "arxiv_id": aid,
                "message": line[:500],
            })
    return events, dict(counts)


def provider_rows(conn: sqlite3.Connection, scoped_total: int, scope_where: str) -> list[dict]:
    rows = _fetchall_dict(conn, f"""
        SELECT COALESCE(source_provider, '(null)') AS provider,
               COUNT(*) AS papers,
               SUM(CASE WHEN openalex_enriched = 1 THEN 1 ELSE 0 END) AS enriched,
               SUM(CASE WHEN abstract IS NOT NULL AND length(trim(abstract)) > 0 THEN 1 ELSE 0 END) AS with_abstract,
               SUM(CASE WHEN doi IS NOT NULL AND length(trim(doi)) > 0 THEN 1 ELSE 0 END) AS with_doi,
               SUM(CASE WHEN openalex_id IS NOT NULL AND length(trim(openalex_id)) > 0 THEN 1 ELSE 0 END) AS with_external_work_id
        FROM papers
        WHERE {scope_where}
        GROUP BY COALESCE(source_provider, '(null)')
        ORDER BY papers DESC
    """)
    for r in rows:
        r["paper_pct"] = f"{100 * pct(r['papers'], scoped_total):.2f}"
        r["enriched_pct_within_provider"] = f"{100 * pct(r['enriched'] or 0, r['papers']):.2f}"
        r["abstract_pct_within_provider"] = f"{100 * pct(r['with_abstract'] or 0, r['papers']):.2f}"
    return rows


def reference_rows(conn: sqlite3.Connection, scope_where: str) -> list[dict]:
    return _fetchall_dict(conn, f"""
        WITH optic AS (
            SELECT id, CAST(substr(publication_date, 1, 4) AS INTEGER) AS year
            FROM papers
            WHERE {scope_where}
        ),
        ref_by_paper AS (
            SELECT o.id, o.year,
                   COUNT(r.cited_paper_id_external) AS refs,
                   SUM(CASE WHEN r.cited_paper_id_internal IS NOT NULL THEN 1 ELSE 0 END) AS linked_refs
            FROM optic o
            LEFT JOIN paper_references r ON r.citing_paper_id = o.id
            GROUP BY o.id, o.year
        )
        SELECT year,
               COUNT(*) AS papers,
               SUM(CASE WHEN refs > 0 THEN 1 ELSE 0 END) AS papers_with_refs,
               SUM(refs) AS refs,
               SUM(linked_refs) AS linked_refs
        FROM ref_by_paper
        GROUP BY year
        ORDER BY year
    """)


def sample_rows(conn: sqlite3.Connection, limit: int, scope_where: str) -> list[dict]:
    suspicious = _fetchall_dict(conn, f"""
        SELECT id, arxiv_id, doi, title, abstract, publication_date, source_provider,
               primary_topic_id, cited_by_count, openalex_enriched,
               CASE WHEN abstract IS NULL OR length(trim(abstract)) = 0 THEN 1 ELSE 0 END AS missing_abstract,
               CASE WHEN COALESCE(refs.ref_count, 0) = 0 THEN 1 ELSE 0 END AS zero_refs
        FROM papers p
        LEFT JOIN (
            SELECT citing_paper_id, COUNT(*) AS ref_count
            FROM paper_references
            GROUP BY citing_paper_id
        ) refs ON refs.citing_paper_id = p.id
        WHERE {scope_where}
          AND (
              abstract IS NULL OR length(trim(abstract)) = 0
              OR COALESCE(refs.ref_count, 0) = 0
              OR primary_topic_id IS NULL
          )
        ORDER BY cited_by_count DESC, publication_date DESC
        LIMIT ?
    """, (max(1, limit // 2),))
    broad = _fetchall_dict(conn, f"""
        SELECT id, arxiv_id, doi, title, abstract, publication_date, source_provider,
               primary_topic_id, cited_by_count, openalex_enriched,
               0 AS missing_abstract, 0 AS zero_refs
        FROM papers p
        WHERE {scope_where}
        ORDER BY abs(random())
        LIMIT ?
    """, (max(1, limit - len(suspicious)),))
    seen = set()
    out = []
    for row in suspicious + broad:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        out.append(row)
    return out[:limit]


def expert_rows(conn: sqlite3.Connection, limit: int, scope_where: str) -> list[dict]:
    rows = _fetchall_dict(conn, f"""
        SELECT p.id, p.arxiv_id, p.doi, p.title, p.publication_date,
               p.source_provider, p.primary_topic_id, p.cited_by_count,
               p.openalex_enriched, COALESCE(refs.ref_count, 0) AS ref_count,
               p.keystone_score_v14, p.lifecycle_v14
        FROM papers p
        LEFT JOIN (
            SELECT citing_paper_id, COUNT(*) AS ref_count
            FROM paper_references
            GROUP BY citing_paper_id
        ) refs ON refs.citing_paper_id = p.id
        WHERE {scope_where}
        ORDER BY COALESCE(p.keystone_score_v14, 0) DESC,
                 COALESCE(p.cited_by_count, 0) DESC,
                 p.publication_date DESC
        LIMIT ?
    """, (limit,))
    return rows


def build_audit(
    conn: sqlite3.Connection,
    *,
    corpus_id: str | None,
    scope_where: str,
    out_dir: Path,
    expected_total: Optional[int],
    missing_ids: list[str],
    log_event_counts: dict[str, int],
    sample_limit: int,
    expert_limit: int,
) -> dict:
    cols = table_columns(conn, "papers")
    scoped_total = int(_fetchone(conn, f"SELECT COUNT(*) FROM papers WHERE {scope_where}") or 0)
    total_papers = int(_fetchone(conn, "SELECT COUNT(*) FROM papers") or 0)
    enriched = int(_fetchone(conn, f"""
        SELECT COUNT(*) FROM papers WHERE {scope_where} AND openalex_enriched = 1
    """) or 0)
    with_abstract = int(_fetchone(conn, f"""
        SELECT COUNT(*) FROM papers WHERE {scope_where}
          AND abstract IS NOT NULL AND length(trim(abstract)) > 0
    """) or 0)
    with_doi = int(_fetchone(conn, f"""
        SELECT COUNT(*) FROM papers WHERE {scope_where}
          AND doi IS NOT NULL AND length(trim(doi)) > 0
    """) or 0)
    with_external = int(_fetchone(conn, f"""
        SELECT COUNT(*) FROM papers WHERE {scope_where}
          AND openalex_id IS NOT NULL AND length(trim(openalex_id)) > 0
    """) or 0)
    with_field = int(_fetchone(conn, f"""
        SELECT COUNT(*) FROM papers WHERE {scope_where}
          AND primary_field_id IS NOT NULL AND length(trim(primary_field_id)) > 0
    """) or 0)
    signal_cols = [
        "c_recency", "c_venue", "c_team_disrupt", "c_recent_burst",
        "c_review_filter", "c_bib_breadth", "c_cocite_breadth",
        "c_bridging_centrality", "c_cd_subdomain", "c_semantic_outlier",
        "c_breakthrough_lang", "c_mechanism_novelty",
    ]
    present_signal_cols = [c for c in signal_cols if c in cols]
    signal_ready = 0
    if present_signal_cols:
        signal_ready = int(_fetchone(conn, f"""
            SELECT COUNT(*) FROM papers WHERE {scope_where}
              AND {" AND ".join(f"{c} IS NOT NULL" for c in present_signal_cols)}
        """) or 0)
    embedding_ready = 0
    if _fetchone(conn, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='paper_embeddings'"):
        embedding_ready = int(_fetchone(conn, f"""
            SELECT COUNT(*)
            FROM papers p
            JOIN paper_embeddings e ON e.paper_id = p.id
            WHERE {scope_where_expr(corpus_id=corpus_id, alias='p')}
        """) or 0)
    s2_in_openalex_col = int(_fetchone(conn, f"""
        SELECT COUNT(*) FROM papers WHERE {scope_where}
          AND openalex_id IS NOT NULL
          AND openalex_id NOT LIKE 'W%'
          AND source_provider = 'semantic_scholar'
    """) or 0)
    missing_abstract_top_cited = _fetchall_dict(conn, f"""
        SELECT arxiv_id, title, cited_by_count, publication_date, source_provider
        FROM papers
        WHERE {scope_where}
          AND (abstract IS NULL OR length(trim(abstract)) = 0)
        ORDER BY cited_by_count DESC
        LIMIT 20
    """)

    ref_counts = [
        int(r[0])
        for r in conn.execute(f"""
            SELECT COUNT(pr.cited_paper_id_external)
            FROM papers p
            LEFT JOIN paper_references pr ON pr.citing_paper_id = p.id
            WHERE {scope_where_expr(corpus_id=corpus_id, alias='p')}
            GROUP BY p.id
        """).fetchall()
    ]
    refs_total = int(_fetchone(conn, f"""
        SELECT COUNT(*)
        FROM paper_references pr
        JOIN papers p ON p.id = pr.citing_paper_id
        WHERE {scope_where_expr(corpus_id=corpus_id, alias='p')}
    """) or 0)
    linked_refs = int(_fetchone(conn, f"""
        SELECT COUNT(*)
        FROM paper_references pr
        JOIN papers p ON p.id = pr.citing_paper_id
        WHERE {scope_where_expr(corpus_id=corpus_id, alias='p')}
          AND pr.cited_paper_id_internal IS NOT NULL
    """) or 0)
    papers_with_refs = sum(1 for x in ref_counts if x > 0)

    dup_doi = int(_fetchone(conn, """
        SELECT COUNT(*) FROM (
            SELECT lower(doi) AS d, COUNT(*) AS n
            FROM papers
            WHERE doi IS NOT NULL AND length(trim(doi)) > 0
            GROUP BY lower(doi)
            HAVING n > 1
        )
    """) or 0)
    dup_arxiv = int(_fetchone(conn, """
        SELECT COUNT(*) FROM (
            SELECT lower(arxiv_id) AS a, COUNT(*) AS n
            FROM papers
            WHERE arxiv_id IS NOT NULL AND length(trim(arxiv_id)) > 0
            GROUP BY lower(arxiv_id)
            HAVING n > 1
        )
    """) or 0)

    expected = expected_total or scoped_total
    coverage_ratio = pct(scoped_total, expected)
    missing_ratio = pct(len(missing_ids), expected)
    enrich_ratio = pct(enriched, scoped_total)
    abstract_ratio = pct(with_abstract, scoped_total)
    refs_ratio = pct(papers_with_refs, scoped_total)
    linked_ratio = pct(linked_refs, refs_total)
    field_ratio = pct(with_field, scoped_total)
    signal_ratio = pct(signal_ready, scoped_total) if len(present_signal_cols) == len(signal_cols) else 0.0
    embedding_ratio = pct(embedding_ready, scoped_total)

    gates = [
        Gate(
            "scope_coverage",
            status_for(coverage_ratio, 0.97, 0.995),
            pct_str(coverage_ratio),
            "pass >= 99.5%, warn >= 97%",
            f"scoped={scoped_total}, expected={expected}",
        ),
        Gate(
            "missing_id_file",
            "pass" if len(missing_ids) == 0 else ("warn" if missing_ratio < 0.01 else "fail"),
            len(missing_ids),
            "pass = 0, warn < 1% of expected",
            "Remaining IDs from the latest arXiv-vs-DB diff.",
        ),
        Gate(
            "enrich_coverage",
            status_for(enrich_ratio, 0.85, 0.95),
            pct_str(enrich_ratio),
            "pass >= 95%, warn >= 85%",
            f"enriched={enriched}, scoped={scoped_total}",
        ),
        Gate(
            "abstract_completeness",
            status_for(abstract_ratio, 0.90, 0.98),
            pct_str(abstract_ratio),
            "pass >= 98%, warn >= 90%",
            f"with_abstract={with_abstract}, scoped={scoped_total}",
        ),
        Gate(
            "reference_coverage",
            status_for(refs_ratio, 0.60, 0.80),
            pct_str(refs_ratio),
            "pass >= 80%, warn >= 60%",
            f"papers_with_refs={papers_with_refs}, scoped={scoped_total}",
        ),
        Gate(
            "reference_internal_linkage",
            "pass" if linked_ratio >= 0.25 else ("warn" if linked_ratio >= 0.05 else "fail"),
            pct_str(linked_ratio),
            "pass >= 25%, warn >= 5%",
            f"linked_refs={linked_refs}, refs={refs_total}",
        ),
        Gate(
            "openalex_field_coverage",
            status_for(field_ratio, 0.60, 0.90),
            pct_str(field_ratio),
            "pass >= 90%, warn >= 60%",
            f"with_field={with_field}, scoped={scoped_total}",
        ),
        Gate(
            "graph_signal_coverage",
            status_for(signal_ratio, 0.85, 0.95),
            pct_str(signal_ratio),
            "pass >= 95%, warn >= 85%",
            f"signal_ready={signal_ready}, present_signal_cols={len(present_signal_cols)}/12",
        ),
        Gate(
            "embedding_coverage",
            status_for(embedding_ratio, 0.85, 0.95),
            pct_str(embedding_ratio),
            "pass >= 95%, warn >= 85%",
            f"embedding_ready={embedding_ready}, scoped={scoped_total}",
        ),
        Gate(
            "duplicate_core_ids",
            "pass" if dup_doi == 0 and dup_arxiv == 0 else "fail",
            {"duplicate_doi_groups": dup_doi, "duplicate_arxiv_groups": dup_arxiv},
            "pass = no duplicate DOI/arXiv groups",
            "SQLite unique constraints should normally keep this at zero.",
        ),
        Gate(
            "provider_id_semantics",
            "fail" if s2_in_openalex_col else "pass",
            s2_in_openalex_col,
            "pass = 0 S2 IDs stored in openalex_id",
            "S2 IDs must be stored in s2_paper_id, not openalex_id.",
        ),
    ]

    fail_count = sum(1 for g in gates if g.status == "fail")
    warn_count = sum(1 for g in gates if g.status == "warn")
    overall = "fail" if fail_count else ("warn" if warn_count else "pass")

    by_year = Counter(y for y in (arxiv_year(x) for x in missing_ids) if y)
    missing_by_year = [
        {"year": year, "missing_ids": count}
        for year, count in sorted(by_year.items())
    ]

    ref_stats = {
        "papers_with_refs": papers_with_refs,
        "papers_zero_refs": scoped_total - papers_with_refs,
        "refs_total": refs_total,
        "linked_refs": linked_refs,
        "refs_per_paper_median": median(ref_counts) if ref_counts else 0,
        "refs_per_paper_p10": percentile(ref_counts, 0.10),
        "refs_per_paper_p90": percentile(ref_counts, 0.90),
        "refs_per_paper_max": max(ref_counts) if ref_counts else 0,
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall,
        "summary": {
            "total_papers": total_papers,
            "scoped_papers": scoped_total,
            "optics_papers": scoped_total,
            "corpus_id": corpus_id,
            "expected_total": expected_total,
            "coverage_ratio": coverage_ratio,
            "missing_ids": len(missing_ids),
            "enriched": enriched,
            "enrich_ratio": enrich_ratio,
            "with_abstract": with_abstract,
            "abstract_ratio": abstract_ratio,
            "with_doi": with_doi,
            "doi_ratio": pct(with_doi, scoped_total),
            "with_external_work_id": with_external,
            "external_work_id_ratio": pct(with_external, scoped_total),
            "with_field": with_field,
            "field_ratio": field_ratio,
            "signal_ready": signal_ready,
            "signal_ratio": signal_ratio,
            "embedding_ready": embedding_ready,
            "embedding_ratio": embedding_ratio,
            "papers_columns": sorted(cols),
        },
        "references": ref_stats,
        "ids": {
            "duplicate_doi_groups": dup_doi,
            "duplicate_arxiv_groups": dup_arxiv,
            "semantic_scholar_ids_in_openalex_id": s2_in_openalex_col,
        },
        "log_event_counts": log_event_counts,
        "gates": [g.__dict__ for g in gates],
        "missing_by_year": missing_by_year,
        "missing_abstract_top_cited": missing_abstract_top_cited,
        "scope_where": scope_where,
        "sample_limit": sample_limit,
        "expert_limit": expert_limit,
    }


def write_markdown(path: Path, audit: dict) -> None:
    s = audit["summary"]
    r = audit["references"]
    corpus_label = s.get("corpus_id") or "all"
    lines = [
        "# V14B Coverage / Quality Audit",
        "",
        f"- Generated: {audit['generated_at']}",
        f"- Corpus scope: **{corpus_label}**",
        f"- Overall status: **{audit['overall_status'].upper()}**",
        "",
        "## Core Metrics",
        "",
        f"- Scoped papers: **{s['scoped_papers']}**",
        f"- Expected total: **{s['expected_total'] or '(not supplied)'}**",
        f"- Coverage: **{pct_str(s['coverage_ratio'])}**",
        f"- Missing IDs in latest diff file: **{s['missing_ids']}**",
        f"- Enriched: **{s['enriched']}** ({pct_str(s['enrich_ratio'])})",
        f"- Abstract completeness: **{s['with_abstract']}** ({pct_str(s['abstract_ratio'])})",
        f"- DOI coverage: **{s['with_doi']}** ({pct_str(s['doi_ratio'])})",
        f"- External work ID coverage: **{s['with_external_work_id']}** ({pct_str(s['external_work_id_ratio'])})",
        f"- OpenAlex Field coverage: **{s['with_field']}** ({pct_str(s['field_ratio'])})",
        f"- Graph signal coverage: **{s['signal_ready']}** ({pct_str(s['signal_ratio'])})",
        f"- Embedding coverage: **{s['embedding_ready']}** ({pct_str(s['embedding_ratio'])})",
        f"- References: **{r['refs_total']}**",
        f"- Papers with references: **{r['papers_with_refs']}**",
        f"- Internal linked references: **{r['linked_refs']}** ({pct_str(pct(r['linked_refs'], r['refs_total']))})",
        "",
        "## Gates",
        "",
        "| Gate | Status | Value | Threshold | Note |",
        "|---|---:|---:|---|---|",
    ]
    for g in audit["gates"]:
        value = g["value"]
        if isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)
        lines.append(
            f"| {g['name']} | **{g['status']}** | {value} | {g['threshold']} | {g['note']} |"
        )
    lines.extend([
        "",
        "## Missing IDs By Year",
        "",
    ])
    if audit["missing_by_year"]:
        lines.extend(
            f"- {row['year']}: {row['missing_ids']}"
            for row in audit["missing_by_year"][:40]
        )
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Notes",
        "",
        "- Algorithmic audit is the source of truth for coverage and consistency.",
        "- `sample_for_llm_review.jsonl` is for semantic spot-checking, not full-library counting.",
        "- `expert_review_sample.csv` is for final human validation of high-impact / high-score papers.",
        "- `provider_id_semantics` warns when Semantic Scholar IDs are stored in the historical `openalex_id` column.",
        "- Set `--corpus-id` to audit an isolated corpus (optics/cs/materials).",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_llm_sample(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            payload = {
                "task": "Judge whether the paper is genuinely relevant to optics / photonics and whether the title/abstract metadata is coherent.",
                "paper": {
                    "id": row.get("id"),
                    "arxiv_id": row.get("arxiv_id"),
                    "doi": row.get("doi"),
                    "title": row.get("title"),
                    "abstract": row.get("abstract"),
                    "publication_date": row.get("publication_date"),
                    "source_provider": row.get("source_provider"),
                    "primary_topic_id": row.get("primary_topic_id"),
                    "cited_by_count": row.get("cited_by_count"),
                    "openalex_enriched": row.get("openalex_enriched"),
                },
                "audit_flags": {
                    "missing_abstract": bool(row.get("missing_abstract")),
                    "zero_refs": bool(row.get("zero_refs")),
                    "primary_topic_not_optics": "optics" not in (row.get("primary_topic_id") or "").lower(),
                },
                "expected_output_schema": {
                    "is_optics_relevant": "yes/no/unclear",
                    "metadata_quality": "good/partial/bad",
                    "reason": "short explanation",
                },
            }
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_audit(
    *,
    db_path: Path,
    out_dir: Path,
    corpus_id: str | None = None,
    expected_total: Optional[int] = None,
    missing_file: Optional[Path] = None,
    sample_limit: int = 200,
    expert_limit: int = 120,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    missing_file = missing_file or out_dir / "arxiv_optics_missing_ids.txt"
    if expected_total is None:
        expected_total = parse_expected_total(out_dir / "arxiv_optics_gap_report.md")

    missing_ids = read_missing_ids(missing_file)
    log_events, log_counts = collect_log_events([
        LOG_DIR / "fetch_missing_arxiv_optics.log",
        LOG_DIR / "arxiv_optics_harvest.log",
        LOG_DIR / "step1_arxiv_enrich.log",
    ])

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    try:
        ensure_corpus_schema(conn)
        scoped_count = create_temp_corpus_table(conn, corpus_id)
        scope_where = scope_where_expr(corpus_id=corpus_id)
        if corpus_id:
            logger.info("Quality audit scope: corpus_id=%s papers=%d", corpus_id, scoped_count)
        # Keep all audit queries on one read snapshot even while crawlers write.
        conn.execute("BEGIN")
        audit = build_audit(
            conn,
            corpus_id=corpus_id,
            scope_where=scope_where,
            out_dir=out_dir,
            expected_total=expected_total,
            missing_ids=missing_ids,
            log_event_counts=log_counts,
            sample_limit=sample_limit,
            expert_limit=expert_limit,
        )
        providers = provider_rows(conn, audit["summary"]["scoped_papers"], scope_where)
        refs_by_year = reference_rows(conn, scope_where)
        llm_sample = sample_rows(conn, sample_limit, scope_where)
        expert_sample = expert_rows(conn, expert_limit, scope_where)
        conn.rollback()
    finally:
        conn.close()

    write_csv(
        out_dir / "missing_by_year.csv",
        audit["missing_by_year"],
        ["year", "missing_ids"],
    )
    write_csv(
        out_dir / "provider_coverage.csv",
        providers,
        [
            "provider", "papers", "paper_pct", "enriched",
            "enriched_pct_within_provider", "with_abstract",
            "abstract_pct_within_provider", "with_doi", "with_external_work_id",
        ],
    )
    write_csv(
        out_dir / "reference_linkage_report.csv",
        refs_by_year,
        ["year", "papers", "papers_with_refs", "refs", "linked_refs"],
    )
    write_csv(
        out_dir / "id_collision_report.csv",
        log_events,
        ["file", "line", "event_type", "arxiv_id", "message"],
    )
    write_csv(
        out_dir / "expert_review_sample.csv",
        expert_sample,
        [
            "id", "arxiv_id", "doi", "title", "publication_date",
            "source_provider", "primary_topic_id", "cited_by_count",
            "openalex_enriched", "ref_count", "keystone_score_v14", "lifecycle_v14",
        ],
    )
    write_llm_sample(out_dir / "sample_for_llm_review.jsonl", llm_sample)

    (out_dir / "coverage_quality_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_markdown(out_dir / "coverage_quality_audit.md", audit)
    logger.info(
        "Quality audit done: status=%s scoped=%s missing=%s corpus=%s",
        audit["overall_status"],
        audit["summary"]["scoped_papers"],
        audit["summary"]["missing_ids"],
        audit["summary"].get("corpus_id"),
    )
    return audit


def should_fail(audit: dict, fail_on: str) -> bool:
    if fail_on == "none":
        return False
    if fail_on == "warn":
        return audit["overall_status"] in {"warn", "fail"}
    if fail_on == "fail":
        return audit["overall_status"] == "fail"
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step0_quality_audit",
        description="Step 0.5: algorithmic coverage / quality audit for the optics library",
    )
    parser.add_argument("--db", default=str(DB_MAIN))
    parser.add_argument("--out-dir", default=str(REPORT_DIR))
    parser.add_argument("--expected-total", type=int, default=None)
    parser.add_argument("--missing-file", default=None)
    parser.add_argument("--sample-limit", type=int, default=200)
    parser.add_argument("--expert-limit", type=int, default=120)
    parser.add_argument("--corpus-id", default=None, help="仅审计该 corpus")
    parser.add_argument("--fail-on", choices=("none", "warn", "fail"), default="none")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    level = getattr(logging, args.log_level.upper(), logging.INFO)
    setup_logging("step0_quality_audit", level=level)

    audit = run_audit(
        db_path=Path(args.db),
        out_dir=Path(args.out_dir),
        corpus_id=args.corpus_id,
        expected_total=args.expected_total,
        missing_file=Path(args.missing_file) if args.missing_file else None,
        sample_limit=args.sample_limit,
        expert_limit=args.expert_limit,
    )
    if should_fail(audit, args.fail_on):
        print(
            f"quality audit status={audit['overall_status']} "
            f"(fail-on={args.fail_on}); see {Path(args.out_dir) / 'coverage_quality_audit.md'}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
