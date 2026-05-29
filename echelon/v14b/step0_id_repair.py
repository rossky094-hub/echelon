"""Step 0.2: provider ID repair and internal reference relinking."""
from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

from echelon.v14b.config import DB_MAIN
from echelon.v14b.id_normalization import (
    classify_external_id,
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_work_id,
    normalize_s2_paper_id,
)
from echelon.v14b.step1_enrich import ensure_enrich_tables, link_paper_reference_internals
from echelon.v14b.utils import setup_logging
from echelon.v14b.corpus_registry import create_temp_corpus_table, ensure_corpus_schema

logger = logging.getLogger("echelon.v14b.step0_id_repair")

S2F_FIELD_MAP = {
    "s2f:physics": "31",
    "s2f:materials_science": "25",
    "s2f:computer_science": "17",
    "s2f:medicine": "27",
    "s2f:engineering": "22",
    "s2f:mathematics": "26",
    "s2f:chemistry": "16",
    "s2f:biology": "13",
    "s2f:economics": "20",
}

ARXIV_EXACT_FIELD_MAP = {
    "physics.optics": "31",
    "quant-ph": "31",
    "cond-mat.mtrl-sci": "25",
}

ARXIV_PREFIX_FIELD_MAP = (
    ("physics.", "31"),
    ("cond-mat.", "31"),
    ("hep-", "31"),
    ("astro-ph", "31"),
    ("gr-qc", "31"),
    ("nucl-", "31"),
    ("nlin.", "31"),
    ("cs.", "17"),
    ("eess.", "22"),
    ("math.", "26"),
    ("stat.", "26"),
    ("q-fin.", "20"),
    ("q-bio.", "13"),
)


def infer_field_from_topic(topic_id: str | None) -> str | None:
    if not topic_id:
        return None
    t = str(topic_id).strip().lower()
    if not t:
        return None
    if t in ARXIV_EXACT_FIELD_MAP:
        return ARXIV_EXACT_FIELD_MAP[t]
    if t in S2F_FIELD_MAP:
        return S2F_FIELD_MAP[t]
    for prefix, field_id in ARXIV_PREFIX_FIELD_MAP:
        if t.startswith(prefix):
            return field_id
    return None


def backfill_field_topic_local(conn: sqlite3.Connection) -> dict:
    """Local coverage repair before slow OpenAlex backfill."""
    # 1) Fill from topics_hierarchy where topic_id already known.
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    from_topic_rows = []
    if "topics_hierarchy" in tables:
        from_topic_rows = conn.execute(
            """
            SELECT p.id, t.field_id, t.subfield_id, t.domain_id
            FROM papers p
            JOIN topics_hierarchy t ON t.topic_id = p.primary_topic_id
            WHERE (p.primary_field_id IS NULL OR trim(p.primary_field_id) = '')
              AND t.field_id IS NOT NULL AND trim(t.field_id) <> ''
            """
        ).fetchall()
    for row in from_topic_rows:
        conn.execute(
            """
            UPDATE papers
            SET primary_field_id = COALESCE(NULLIF(primary_field_id, ''), ?),
                primary_subfield_id = COALESCE(NULLIF(primary_subfield_id, ''), ?),
                primary_domain_id = COALESCE(NULLIF(primary_domain_id, ''), ?)
            WHERE id = ?
            """,
            (row[1], row[2], row[3], row[0]),
        )

    # 2) Fill residual missing rows using deterministic S2F/arXiv category map.
    rows = conn.execute(
        """
        SELECT id, primary_topic_id
        FROM papers
        WHERE primary_topic_id IS NOT NULL
          AND (primary_field_id IS NULL OR trim(primary_field_id) = '')
        """
    ).fetchall()
    mapped = 0
    for row in rows:
        fid = infer_field_from_topic(row[1])
        if not fid:
            continue
        conn.execute(
            "UPDATE papers SET primary_field_id = ? WHERE id = ?",
            (fid, row[0]),
        )
        mapped += 1

    conn.commit()
    return {
        "field_backfill_from_topics_hierarchy": len(from_topic_rows),
        "field_backfill_from_local_rules": mapped,
    }


def repair_ids(db_path: Path = DB_MAIN, corpus_id: str | None = None) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_corpus_schema(conn)
    scoped_count = create_temp_corpus_table(conn, corpus_id)

    ensure_enrich_tables(conn)

    conn.execute("""
        UPDATE papers
        SET openalex_id = NULL
        WHERE openalex_id IS NOT NULL
          AND length(trim(openalex_id)) = 0
    """)

    moved_s2 = 0
    moved_doi = 0
    moved_arxiv = 0
    doi_collisions = 0
    arxiv_collisions = 0
    normalized_openalex = 0
    unresolved_provider_ids = 0

    scope_filter = (
        "AND id IN (SELECT paper_id FROM temp.v14b_corpus_papers)"
        if corpus_id
        else ""
    )
    rows = conn.execute(f"""
        SELECT id, openalex_id, doi, arxiv_id, s2_paper_id, source_provider
        FROM papers
        WHERE openalex_id IS NOT NULL
          AND length(trim(openalex_id)) > 0
          {scope_filter}
    """).fetchall()
    for row in rows:
        paper_id = row["id"]
        raw_id = row["openalex_id"]
        openalex_id = normalize_openalex_work_id(raw_id)
        if openalex_id:
            if openalex_id != raw_id.strip():
                conn.execute(
                    "UPDATE papers SET openalex_id = ? WHERE id = ?",
                    (openalex_id, paper_id),
                )
                normalized_openalex += 1
            continue

        provider, norm = classify_external_id(raw_id)
        if provider == "doi" and norm:
            clean_doi = normalize_doi(norm)
            existing = conn.execute(
                "SELECT id FROM papers WHERE lower(doi) = lower(?) AND id != ? LIMIT 1",
                (clean_doi, paper_id),
            ).fetchone() if clean_doi else None
            if existing:
                conn.execute("UPDATE papers SET openalex_id = NULL WHERE id = ?", (paper_id,))
                doi_collisions += 1
            else:
                conn.execute("""
                    UPDATE papers
                    SET doi = COALESCE(NULLIF(doi, ''), ?),
                        openalex_id = NULL
                    WHERE id = ?
                """, (clean_doi, paper_id))
            moved_doi += 1
        elif provider == "arxiv" and norm:
            clean_arxiv = normalize_arxiv_id(norm)
            existing = conn.execute(
                "SELECT id FROM papers WHERE arxiv_id = ? AND id != ? LIMIT 1",
                (clean_arxiv, paper_id),
            ).fetchone() if clean_arxiv else None
            if existing:
                conn.execute("UPDATE papers SET openalex_id = NULL WHERE id = ?", (paper_id,))
                arxiv_collisions += 1
            else:
                conn.execute("""
                    UPDATE papers
                    SET arxiv_id = COALESCE(NULLIF(arxiv_id, ''), ?),
                        openalex_id = NULL
                    WHERE id = ?
                """, (clean_arxiv, paper_id))
            moved_arxiv += 1
        elif provider == "s2" and norm:
            conn.execute("""
                UPDATE papers
                SET s2_paper_id = COALESCE(NULLIF(s2_paper_id, ''), ?),
                    openalex_id = NULL
                WHERE id = ?
            """, (normalize_s2_paper_id(norm), paper_id))
            moved_s2 += 1
        elif row["source_provider"] == "semantic_scholar" and norm:
            conn.execute("""
                UPDATE papers
                SET s2_paper_id = COALESCE(NULLIF(s2_paper_id, ''), ?),
                    openalex_id = NULL
                WHERE id = ?
            """, (normalize_s2_paper_id(norm), paper_id))
            moved_s2 += 1
        else:
            unresolved_provider_ids += 1

    invalid_openalex = 0
    for row in conn.execute(f"SELECT id, openalex_id FROM papers WHERE openalex_id IS NOT NULL {scope_filter}"):
        if normalize_openalex_work_id(row["openalex_id"]) is None:
            invalid_openalex += 1

    ref_scope = (
        "AND citing_paper_id IN (SELECT paper_id FROM temp.v14b_corpus_papers)"
        if corpus_id
        else ""
    )
    ref_rows = conn.execute(f"""
        SELECT citing_paper_id, cited_paper_id_external
        FROM paper_references
        WHERE cited_paper_id_external IS NOT NULL
        {ref_scope}
    """).fetchall()
    ref_updates = []
    for row in ref_rows:
        provider, norm = classify_external_id(row["cited_paper_id_external"])
        ref_updates.append((provider, norm, row["citing_paper_id"], row["cited_paper_id_external"]))
    if ref_updates:
        conn.executemany("""
            UPDATE paper_references
            SET cited_paper_id_provider = ?,
                cited_paper_id_norm = ?
            WHERE citing_paper_id = ?
              AND cited_paper_id_external = ?
        """, ref_updates)

    # Clean common historical S2 prefix variants.
    conn.execute("""
        UPDATE papers
        SET s2_paper_id = substr(s2_paper_id, 4)
        WHERE s2_paper_id LIKE 'S2:%'
    """)

    linked_before = conn.execute(
        "SELECT COUNT(*) FROM paper_references WHERE cited_paper_id_internal IS NOT NULL"
    ).fetchone()[0]
    newly_linked = link_paper_reference_internals(conn)
    linked_after = conn.execute(
        "SELECT COUNT(*) FROM paper_references WHERE cited_paper_id_internal IS NOT NULL"
    ).fetchone()[0]

    field_stats = backfill_field_topic_local(conn)
    field_cov = conn.execute(
        f"""
        SELECT COUNT(*) FROM papers
        WHERE primary_field_id IS NOT NULL AND trim(primary_field_id) <> ''
        {scope_filter}
        """
    ).fetchone()[0]
    total_papers = conn.execute(f"SELECT COUNT(*) FROM papers WHERE 1=1 {scope_filter}").fetchone()[0]

    stats = {
        "moved_s2_from_openalex_id": moved_s2,
        "moved_doi_from_openalex_id": moved_doi,
        "moved_arxiv_from_openalex_id": moved_arxiv,
        "doi_collision_openalex_id_cleared": doi_collisions,
        "arxiv_collision_openalex_id_cleared": arxiv_collisions,
        "normalized_openalex_ids": normalized_openalex,
        "unresolved_provider_ids": unresolved_provider_ids,
        "invalid_openalex_id_remaining": invalid_openalex,
        "reference_rows_normalized": len(ref_updates),
        "linked_before": linked_before,
        "newly_linked": newly_linked,
        "linked_after": linked_after,
        "corpus_id": corpus_id,
        "scoped_papers": scoped_count if corpus_id else total_papers,
        "primary_field_coverage_after": {
            "with_field": field_cov,
            "total": total_papers,
            "ratio": round(field_cov / max(1, total_papers), 4),
        },
        **field_stats,
    }
    logger.info("ID repair stats: %s", stats)
    conn.commit()
    conn.close()
    return stats


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Repair V14B provider IDs and relink references")
    parser.add_argument("--db", type=Path, default=DB_MAIN)
    parser.add_argument("--corpus-id", type=str, default=None)
    args = parser.parse_args(argv)
    setup_logging("step0_id_repair")
    repair_ids(args.db, corpus_id=args.corpus_id)


if __name__ == "__main__":
    main()
