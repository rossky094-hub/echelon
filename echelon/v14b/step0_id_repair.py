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

logger = logging.getLogger("echelon.v14b.step0_id_repair")


def repair_ids(db_path: Path = DB_MAIN) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

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

    rows = conn.execute("""
        SELECT id, openalex_id, doi, arxiv_id, s2_paper_id, source_provider
        FROM papers
        WHERE openalex_id IS NOT NULL
          AND length(trim(openalex_id)) > 0
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
    for row in conn.execute("SELECT id, openalex_id FROM papers WHERE openalex_id IS NOT NULL"):
        if normalize_openalex_work_id(row["openalex_id"]) is None:
            invalid_openalex += 1

    ref_rows = conn.execute("""
        SELECT citing_paper_id, cited_paper_id_external
        FROM paper_references
        WHERE cited_paper_id_external IS NOT NULL
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
    }
    logger.info("ID repair stats: %s", stats)
    conn.commit()
    conn.close()
    return stats


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Repair V14B provider IDs and relink references")
    parser.add_argument("--db", type=Path, default=DB_MAIN)
    args = parser.parse_args(argv)
    setup_logging("step0_id_repair")
    repair_ids(args.db)


if __name__ == "__main__":
    main()
