"""Step 0.4: derive graph-ready V14 signal columns from available metadata."""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

from echelon.v14b.config import DB_MAIN
from echelon.v14b.utils import setup_logging, table_columns
from echelon.v14b.corpus_registry import create_temp_corpus_table, ensure_corpus_schema

logger = logging.getLogger("echelon.v14b.step0_graph_features")

SIGNAL_COLUMNS = [
    "c_recency",
    "c_venue",
    "c_team_disrupt",
    "c_recent_burst",
    "c_review_filter",
    "c_bib_breadth",
    "c_cocite_breadth",
    "c_bridging_centrality",
    "c_cd_subdomain",
    "c_semantic_outlier",
    "c_breakthrough_lang",
    "c_mechanism_novelty",
]

BREAKTHROUGH_TERMS = re.compile(
    r"\b(breakthrough|first|novel|unprecedented|record|ultrafast|ultralow|"
    r"topological|quantum|nonlinear|metasurface|integrated|chip-scale|"
    r"inverse design|single-photon|strong coupling)\b",
    re.I,
)
MECHANISM_TERMS = re.compile(
    r"\b(mechanism|principle|model|framework|theory|platform|architecture|"
    r"phase matching|dispersion|coupling|resonator|waveguide|cavity|"
    r"metamaterial|nanophotonic|plasmonic)\b",
    re.I,
)
REVIEW_TERMS = re.compile(r"\b(review|survey|tutorial|perspective|roadmap)\b", re.I)


def _clip(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _p95(values: list[float]) -> float:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 1.0
    idx = min(len(vals) - 1, max(0, int(0.95 * (len(vals) - 1))))
    return max(vals[idx], 1.0)


def ensure_signal_columns(conn: sqlite3.Connection) -> None:
    cols = table_columns(conn, "papers")
    for col in SIGNAL_COLUMNS:
        if col not in cols:
            try:
                conn.execute(f"ALTER TABLE papers ADD COLUMN {col} REAL")
            except Exception:
                pass
    conn.commit()


def derive_graph_features(
    db_path: Path = DB_MAIN,
    limit: Optional[int] = None,
    corpus_id: Optional[str] = None,
) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_corpus_schema(conn)
    scoped_count = create_temp_corpus_table(conn, corpus_id)
    ensure_signal_columns(conn)

    scope_join = (
        "JOIN temp.v14b_corpus_papers cp ON cp.paper_id = p.id"
        if corpus_id
        else ""
    )
    rows = conn.execute(f"""
        SELECT p.id, p.title, p.abstract, p.publication_year, p.publication_date,
               p.cited_by_count, p.venue_id,
               COALESCE(refs.ref_count, 0) AS ref_count,
               COALESCE(linked.linked_refs, 0) AS linked_refs
        FROM papers p
        {scope_join}
        LEFT JOIN (
            SELECT citing_paper_id, COUNT(*) AS ref_count
            FROM paper_references
            {"WHERE citing_paper_id IN (SELECT paper_id FROM temp.v14b_corpus_papers)" if corpus_id else ""}
            GROUP BY citing_paper_id
        ) refs ON refs.citing_paper_id = p.id
        LEFT JOIN (
            SELECT citing_paper_id, COUNT(*) AS linked_refs
            FROM paper_references
            WHERE cited_paper_id_internal IS NOT NULL
            {"AND citing_paper_id IN (SELECT paper_id FROM temp.v14b_corpus_papers)" if corpus_id else ""}
            GROUP BY citing_paper_id
        ) linked ON linked.citing_paper_id = p.id
        ORDER BY p.id
    """).fetchall()
    if limit:
        rows = rows[:limit]

    ref_p95 = _p95([float(r["ref_count"] or 0) for r in rows])
    cite_rate_values = []
    this_year = date.today().year
    for r in rows:
        year = int(r["publication_year"] or this_year)
        age = max(1, this_year - year + 1)
        cite_rate_values.append(float(r["cited_by_count"] or 0) / age)
    cite_rate_p95 = _p95(cite_rate_values)

    # Cross-field bridge score from direct linked neighbors.
    bridge_scores: dict[str, float] = {}
    bridge_rows = conn.execute(f"""
        WITH neighbor_fields AS (
            SELECT pr.citing_paper_id AS paper_id, p.primary_field_id AS field_id
            FROM paper_references pr
            JOIN papers p ON p.id = pr.cited_paper_id_internal
            WHERE p.primary_field_id IS NOT NULL
              {"AND pr.citing_paper_id IN (SELECT paper_id FROM temp.v14b_corpus_papers) AND pr.cited_paper_id_internal IN (SELECT paper_id FROM temp.v14b_corpus_papers)" if corpus_id else ""}
            UNION
            SELECT pr.cited_paper_id_internal AS paper_id, p.primary_field_id AS field_id
            FROM paper_references pr
            JOIN papers p ON p.id = pr.citing_paper_id
            WHERE pr.cited_paper_id_internal IS NOT NULL
              AND p.primary_field_id IS NOT NULL
              {"AND pr.citing_paper_id IN (SELECT paper_id FROM temp.v14b_corpus_papers) AND pr.cited_paper_id_internal IN (SELECT paper_id FROM temp.v14b_corpus_papers)" if corpus_id else ""}
        )
        SELECT paper_id, COUNT(DISTINCT field_id) AS n_fields
        FROM neighbor_fields
        GROUP BY paper_id
    """).fetchall()
    for row in bridge_rows:
        bridge_scores[row["paper_id"]] = _clip(float(row["n_fields"] or 0) / 26.0)

    updates = []
    for i, r in enumerate(rows):
        year = int(r["publication_year"] or this_year)
        age = max(1, this_year - year + 1)
        cited = float(r["cited_by_count"] or 0)
        ref_count = float(r["ref_count"] or 0)
        linked_refs = float(r["linked_refs"] or 0)
        text = f"{r['title'] or ''}\n{r['abstract'] or ''}"

        c_recency = _clip(1.0 - max(0, this_year - year) / 35.0)
        c_venue = 0.65 if r["venue_id"] else 0.5
        c_team_disrupt = 0.5
        c_recent_burst = _clip((cited / age) / cite_rate_p95)
        c_review_filter = 1.0 if REVIEW_TERMS.search(text) else 0.0
        c_bib_breadth = _clip(ref_count / ref_p95)
        c_cocite_breadth = _clip(linked_refs / max(ref_count, 1.0))
        c_bridging_centrality = bridge_scores.get(r["id"], 0.0)
        c_cd_subdomain = _clip(c_recent_burst * (1.0 - min(c_bib_breadth, 0.9)))
        c_semantic_outlier = 0.5
        c_breakthrough_lang = _clip(len(BREAKTHROUGH_TERMS.findall(text)) / 6.0)
        c_mechanism_novelty = _clip(len(MECHANISM_TERMS.findall(text)) / 8.0)

        updates.append((
            c_recency, c_venue, c_team_disrupt, c_recent_burst,
            c_review_filter, c_bib_breadth, c_cocite_breadth,
            c_bridging_centrality, c_cd_subdomain, c_semantic_outlier,
            c_breakthrough_lang, c_mechanism_novelty, r["id"],
        ))

    conn.executemany("""
        UPDATE papers SET
            c_recency = ?,
            c_venue = ?,
            c_team_disrupt = ?,
            c_recent_burst = ?,
            c_review_filter = ?,
            c_bib_breadth = ?,
            c_cocite_breadth = ?,
            c_bridging_centrality = ?,
            c_cd_subdomain = ?,
            c_semantic_outlier = ?,
            c_breakthrough_lang = ?,
            c_mechanism_novelty = ?
        WHERE id = ?
    """, updates)
    conn.commit()
    conn.close()

    stats = {
        "records_n": len(updates),
        "corpus_id": corpus_id,
        "scoped_papers": scoped_count if corpus_id else len(updates),
    }
    logger.info("Graph feature derivation done: %s", stats)
    return stats


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Derive V14B graph feature signals")
    parser.add_argument("--db", type=Path, default=DB_MAIN)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--corpus-id", type=str, default=None)
    args = parser.parse_args(argv)
    setup_logging("step0_graph_features")
    derive_graph_features(args.db, limit=args.limit, corpus_id=args.corpus_id)


if __name__ == "__main__":
    main()
