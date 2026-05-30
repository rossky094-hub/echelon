"""Deterministic reference relinking audit for the V14B evidence backbone.

This tool intentionally does *not* do fuzzy title matching.  It only audits or
applies exact provider-ID joins across DOI, OpenAlex, Semantic Scholar, and
arXiv identifiers.  That keeps the citation backbone trustworthy enough for
Main Path, branch lineage, and future-growth calibration.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN
from echelon.v14b.id_normalization import (
    classify_external_id,
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_work_id,
    normalize_s2_paper_id,
)
from echelon.v14b.utils import setup_logging

logger = logging.getLogger("echelon.v14b.reference_relink_audit")

PROVIDERS = ("doi", "openalex", "arxiv", "s2")


@dataclass(frozen=True)
class RefCandidate:
    rowid: int
    citing_paper_id: str
    cited_paper_id_external: str
    provider: str | None
    norm: str | None
    target_id: str | None
    status: str
    stale_provider: str | None = None
    stale_norm: str | None = None
    needs_norm_update: bool = False


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def jdumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def table_columns(conn: sqlite3.Connection, name: str) -> set[str]:
    if not table_exists(conn, name):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({name})").fetchall()}


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def doi_to_arxiv(doi_value: str | None) -> str | None:
    doi_norm = normalize_doi(doi_value)
    if not doi_norm:
        return None
    match = re.match(r"^10\.48550/arxiv\.(.+)$", doi_norm, flags=re.I)
    if not match:
        return None
    return normalize_arxiv_id(match.group(1))


def normalize_provider_norm(
    provider: str | None,
    norm: str | None,
    external: str | None,
) -> tuple[str | None, str | None]:
    """Return a canonical (provider, norm) pair, preferring explicit columns."""
    p = (provider or "").strip().lower() or None
    n = (norm or "").strip() or None

    if p == "doi":
        return "doi", normalize_doi(n or external)
    if p == "openalex":
        return "openalex", normalize_openalex_work_id(n or external)
    if p in {"arxiv", "arxiv_id"}:
        return "arxiv", normalize_arxiv_id(n or external)
    if p in {"s2", "semantic_scholar", "semanticscholar"}:
        return "s2", normalize_s2_paper_id(n or external)

    p2, n2 = classify_external_id(external)
    if p2 in PROVIDERS:
        return p2, n2
    return p2, n2


def _add_id(id_maps: dict[str, dict[str, set[str]]], provider: str, norm: str | None, paper_id: str) -> None:
    if not norm:
        return
    id_maps[provider][norm].add(paper_id)


def build_paper_id_maps(conn: sqlite3.Connection) -> dict[str, dict[str, set[str]]]:
    cols = table_columns(conn, "papers")
    if not {"id", "openalex_id", "doi", "arxiv_id"}.issubset(cols):
        missing = sorted({"id", "openalex_id", "doi", "arxiv_id"} - cols)
        raise RuntimeError(f"papers table missing required columns: {missing}")

    has_s2 = "s2_paper_id" in cols
    select_cols = "id, openalex_id, doi, arxiv_id" + (", s2_paper_id" if has_s2 else "")
    rows = conn.execute(f"SELECT {select_cols} FROM papers").fetchall()
    id_maps: dict[str, dict[str, set[str]]] = {
        provider: defaultdict(set) for provider in PROVIDERS
    }

    for row in rows:
        paper_id = str(row["id"])
        openalex = normalize_openalex_work_id(row["openalex_id"])
        doi = normalize_doi(row["doi"])
        arxiv = normalize_arxiv_id(row["arxiv_id"])
        s2 = normalize_s2_paper_id(row["s2_paper_id"]) if has_s2 else None

        _add_id(id_maps, "openalex", openalex, paper_id)
        _add_id(id_maps, "doi", doi, paper_id)
        _add_id(id_maps, "arxiv", arxiv, paper_id)
        _add_id(id_maps, "s2", s2, paper_id)

        legacy_s2 = normalize_s2_paper_id(row["openalex_id"]) if not openalex else None
        _add_id(id_maps, "s2", legacy_s2, paper_id)

        arxiv_alias = doi_to_arxiv(doi)
        _add_id(id_maps, "arxiv", arxiv_alias, paper_id)

    return id_maps


def id_map_stats(id_maps: dict[str, dict[str, set[str]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for provider, mapping in id_maps.items():
        collisions = {norm: sorted(ids) for norm, ids in mapping.items() if len(ids) > 1}
        out[provider] = {
            "unique_ids": len(mapping),
            "collision_ids": len(collisions),
            "sample_collisions": dict(list(collisions.items())[:10]),
        }
    return out


def evaluate_reference(
    row: sqlite3.Row,
    id_maps: dict[str, dict[str, set[str]]],
) -> RefCandidate:
    external = row["cited_paper_id_external"]
    old_provider = row["cited_paper_id_provider"] if "cited_paper_id_provider" in row.keys() else None
    old_norm = row["cited_paper_id_norm"] if "cited_paper_id_norm" in row.keys() else None
    provider, norm = normalize_provider_norm(old_provider, old_norm, external)
    stale = (old_provider or None, old_norm or None) != (provider, norm)

    if provider not in PROVIDERS or not norm:
        return RefCandidate(
            rowid=int(row["rowid"]),
            citing_paper_id=row["citing_paper_id"],
            cited_paper_id_external=external,
            provider=provider,
            norm=norm,
            target_id=None,
            status="unclassifiable",
            stale_provider=old_provider if stale else None,
            stale_norm=old_norm if stale else None,
            needs_norm_update=stale,
        )

    targets = id_maps.get(provider, {}).get(norm, set())
    target_provider = provider
    target_norm = norm
    if not targets and provider == "doi":
        arxiv_alias = doi_to_arxiv(norm)
        if arxiv_alias:
            targets = id_maps["arxiv"].get(arxiv_alias, set())
            if targets:
                target_provider = "arxiv"
                target_norm = arxiv_alias

    if len(targets) == 1:
        return RefCandidate(
            rowid=int(row["rowid"]),
            citing_paper_id=row["citing_paper_id"],
            cited_paper_id_external=external,
            provider=target_provider,
            norm=target_norm,
            target_id=next(iter(targets)),
            status="exact_linkable",
            stale_provider=old_provider if stale else None,
            stale_norm=old_norm if stale else None,
            needs_norm_update=stale,
        )
    if len(targets) > 1:
        return RefCandidate(
            rowid=int(row["rowid"]),
            citing_paper_id=row["citing_paper_id"],
            cited_paper_id_external=external,
            provider=target_provider,
            norm=target_norm,
            target_id=None,
            status="ambiguous_local_match",
            stale_provider=old_provider if stale else None,
            stale_norm=old_norm if stale else None,
            needs_norm_update=stale,
        )
    return RefCandidate(
        rowid=int(row["rowid"]),
        citing_paper_id=row["citing_paper_id"],
        cited_paper_id_external=external,
        provider=provider,
        norm=norm,
        target_id=None,
        status="no_local_match",
        stale_provider=old_provider if stale else None,
        stale_norm=old_norm if stale else None,
        needs_norm_update=stale,
    )


def fetch_unlinked_reference_rows(conn: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    cols = table_columns(conn, "paper_references")
    if not {"citing_paper_id", "cited_paper_id_external", "cited_paper_id_internal"}.issubset(cols):
        missing = sorted(
            {"citing_paper_id", "cited_paper_id_external", "cited_paper_id_internal"} - cols
        )
        raise RuntimeError(f"paper_references table missing required columns: {missing}")

    provider_sql = "cited_paper_id_provider" if "cited_paper_id_provider" in cols else "NULL AS cited_paper_id_provider"
    norm_sql = "cited_paper_id_norm" if "cited_paper_id_norm" in cols else "NULL AS cited_paper_id_norm"
    sql = f"""
        SELECT rowid, citing_paper_id, cited_paper_id_external,
               {provider_sql}, {norm_sql}
        FROM paper_references
        WHERE cited_paper_id_external IS NOT NULL
          AND trim(cited_paper_id_external) <> ''
          AND COALESCE(cited_paper_id_internal, '') = ''
        ORDER BY rowid
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql).fetchall()


def apply_candidates(conn: sqlite3.Connection, candidates: list[RefCandidate], chunk_size: int) -> dict[str, int]:
    link_updates = [
        (c.target_id, c.provider, c.norm, c.rowid)
        for c in candidates
        if c.status == "exact_linkable" and c.target_id
    ]
    norm_updates = [
        (c.provider, c.norm, c.rowid)
        for c in candidates
        if c.provider and c.norm and c.needs_norm_update
    ]

    for start in range(0, len(norm_updates), chunk_size):
        conn.executemany(
            """
            UPDATE paper_references
            SET cited_paper_id_provider = ?,
                cited_paper_id_norm = ?
            WHERE rowid = ?
              AND COALESCE(cited_paper_id_internal, '') = ''
            """,
            norm_updates[start : start + chunk_size],
        )
        conn.commit()

    for start in range(0, len(link_updates), chunk_size):
        conn.executemany(
            """
            UPDATE paper_references
            SET cited_paper_id_internal = ?,
                cited_paper_id_provider = ?,
                cited_paper_id_norm = ?
            WHERE rowid = ?
              AND COALESCE(cited_paper_id_internal, '') = ''
            """,
            link_updates[start : start + chunk_size],
        )
        conn.commit()

    return {
        "norm_updates_applied": len(norm_updates),
        "link_updates_applied": len(link_updates),
    }


def summarize_candidates(candidates: list[RefCandidate]) -> dict[str, Any]:
    by_status = Counter(c.status for c in candidates)
    by_provider_status: dict[str, Counter[str]] = defaultdict(Counter)
    stale_by_provider = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for c in candidates:
        provider = c.provider or "unknown"
        by_provider_status[provider][c.status] += 1
        if c.needs_norm_update:
            stale_by_provider[provider] += 1
        if len(samples[c.status]) < 10:
            samples[c.status].append(
                {
                    "rowid": c.rowid,
                    "citing_paper_id": c.citing_paper_id,
                    "external": c.cited_paper_id_external,
                    "provider": c.provider,
                    "norm": c.norm,
                    "target_id": c.target_id,
                    "old_provider": c.stale_provider,
                    "old_norm": c.stale_norm,
                }
            )

    return {
        "scanned_unlinked_refs": len(candidates),
        "status_counts": dict(by_status),
        "provider_status_counts": {
            provider: dict(counter) for provider, counter in sorted(by_provider_status.items())
        },
        "stale_norm_updates": dict(stale_by_provider),
        "samples": dict(samples),
    }


def evaluate_unlinked_references(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> tuple[dict[str, dict[str, set[str]]], list[RefCandidate]]:
    """Evaluate exact provider-ID relinks without mutating the database."""
    id_maps = build_paper_id_maps(conn)
    rows = fetch_unlinked_reference_rows(conn, limit=limit)
    return id_maps, [evaluate_reference(row, id_maps) for row in rows]


def apply_exact_relinks(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    chunk_size: int = 5000,
) -> dict[str, Any]:
    """Apply only exact, unambiguous provider-ID relinks.

    Unlike the historical enrich helper, duplicate local IDs stay unlinked.
    Provider/norm columns are still canonicalized for no-local-match rows so
    later OpenAlex/S2/DOI backfills can be re-run deterministically.
    """
    before = {
        "refs": int(scalar(conn, "SELECT COUNT(*) FROM paper_references") or 0),
        "linked_refs": int(
            scalar(
                conn,
                "SELECT COUNT(*) FROM paper_references WHERE COALESCE(cited_paper_id_internal, '') <> ''",
            )
            or 0
        ),
    }
    id_maps, candidates = evaluate_unlinked_references(conn, limit=limit)
    apply_result = apply_candidates(conn, candidates, chunk_size=chunk_size)
    after = {
        "refs": int(scalar(conn, "SELECT COUNT(*) FROM paper_references") or 0),
        "linked_refs": int(
            scalar(
                conn,
                "SELECT COUNT(*) FROM paper_references WHERE COALESCE(cited_paper_id_internal, '') <> ''",
            )
            or 0
        ),
    }
    return {
        "before": before,
        "after": after,
        "paper_id_map_stats": id_map_stats(id_maps),
        "candidate_summary": summarize_candidates(candidates),
        "apply_result": apply_result,
    }


def write_report(result: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "reference_relink_audit.json"
    md_path = out_dir / "reference_relink_audit.md"
    json_path.write_text(jdumps(result) + "\n", encoding="utf-8")

    summary = result["candidate_summary"]
    status = summary["status_counts"]
    lines = [
        "# V14B Reference Relink Audit",
        "",
        f"- generated_at: `{result['generated_at']}`",
        f"- mode: `{'apply' if result['applied'] else 'dry_run'}`",
        f"- scanned unlinked refs: {summary['scanned_unlinked_refs']:,}",
        f"- exact linkable refs: {int(status.get('exact_linkable', 0)):,}",
        f"- ambiguous local matches: {int(status.get('ambiguous_local_match', 0)):,}",
        f"- no local match: {int(status.get('no_local_match', 0)):,}",
        f"- unclassifiable: {int(status.get('unclassifiable', 0)):,}",
        "",
        "## Provider Breakdown",
        "",
        "| provider | exact | ambiguous | no local | unclassifiable | stale norm |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    stale = summary["stale_norm_updates"]
    for provider, counts in summary["provider_status_counts"].items():
        lines.append(
            f"| {provider} | {int(counts.get('exact_linkable', 0)):,} | "
            f"{int(counts.get('ambiguous_local_match', 0)):,} | "
            f"{int(counts.get('no_local_match', 0)):,} | "
            f"{int(counts.get('unclassifiable', 0)):,} | "
            f"{int(stale.get(provider, 0)):,} |"
        )

    lines.extend(
        [
            "",
            "## Paper ID Collision Summary",
            "",
            "| provider | unique local IDs | collision IDs |",
            "| --- | ---: | ---: |",
        ]
    )
    for provider, stats in result["paper_id_map_stats"].items():
        lines.append(
            f"| {provider} | {int(stats['unique_ids']):,} | {int(stats['collision_ids']):,} |"
        )

    if result.get("apply_result"):
        ar = result["apply_result"]
        lines.extend(
            [
                "",
                "## Apply Result",
                "",
                f"- norm updates applied: {int(ar.get('norm_updates_applied', 0)):,}",
                f"- link updates applied: {int(ar.get('link_updates_applied', 0)):,}",
            ]
        )

    lines.extend(
        [
            "",
            "## Product Interpretation",
            "",
            "Exact relinks strengthen the citation evidence bone without inventing edges. "
            "Ambiguous matches must stay unlinked until duplicate papers are resolved. "
            "No-local-match references are external context, not missing internal graph edges.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "report": str(md_path)}


def run_audit(
    db_path: Path = DB_MAIN,
    out_dir: Path = Path("reports/v14b_pilot"),
    *,
    apply: bool = False,
    limit: int | None = None,
    chunk_size: int = 5000,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")

    before = {
        "refs": int(scalar(conn, "SELECT COUNT(*) FROM paper_references") or 0),
        "linked_refs": int(
            scalar(
                conn,
                "SELECT COUNT(*) FROM paper_references WHERE COALESCE(cited_paper_id_internal, '') <> ''",
            )
            or 0
        ),
    }
    id_maps, candidates = evaluate_unlinked_references(conn, limit=limit)
    result: dict[str, Any] = {
        "generated_at": utc_now(),
        "applied": apply,
        "limit": limit,
        "before": before,
        "paper_id_map_stats": id_map_stats(id_maps),
        "candidate_summary": summarize_candidates(candidates),
        "apply_result": None,
    }

    if apply:
        result["apply_result"] = apply_candidates(conn, candidates, chunk_size=chunk_size)
        result["after"] = {
            "refs": int(scalar(conn, "SELECT COUNT(*) FROM paper_references") or 0),
            "linked_refs": int(
                scalar(
                    conn,
                    "SELECT COUNT(*) FROM paper_references WHERE COALESCE(cited_paper_id_internal, '') <> ''",
                )
                or 0
            ),
        }
    else:
        result["after"] = before

    result["paths"] = write_report(result, out_dir)
    conn.close()
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Audit/apply deterministic V14B reference relinks.")
    parser.add_argument("--db", type=Path, default=DB_MAIN)
    parser.add_argument("--out-dir", type=Path, default=Path("reports/v14b_pilot"))
    parser.add_argument("--apply", action="store_true", help="Apply exact unambiguous relinks.")
    parser.add_argument("--limit", type=int, default=None, help="Limit unlinked refs scanned.")
    parser.add_argument("--chunk-size", type=int, default=5000)
    args = parser.parse_args(argv)
    setup_logging("reference_relink_audit")
    result = run_audit(
        db_path=args.db,
        out_dir=args.out_dir,
        apply=args.apply,
        limit=args.limit,
        chunk_size=args.chunk_size,
    )
    print(jdumps({"applied": result["applied"], **result["candidate_summary"], **result["paths"]}))


if __name__ == "__main__":
    main()
