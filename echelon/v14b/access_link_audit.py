"""Audit access-link completeness for decision-critical papers.

The visual graph must not make researchers hunt for key papers manually.  This
audit selects papers that affect product claims (main-path turning papers,
branch split drivers, future endpoints, and top keystones), synthesizes access
links from local IDs, and records explicit access gaps.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, DB_V14, REPORT_DIR
from echelon.v14b.id_normalization import (
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_work_id,
    normalize_s2_paper_id,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def jdumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def loads(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def ensure_schema(conn_v14: sqlite3.Connection) -> None:
    conn_v14.executescript(
        """
        CREATE TABLE IF NOT EXISTS access_link_audit_items (
            paper_id TEXT PRIMARY KEY,
            roles_json TEXT NOT NULL,
            title TEXT,
            publication_year INTEGER,
            arxiv_id TEXT,
            doi TEXT,
            s2_paper_id TEXT,
            openalex_id TEXT,
            synthesized_links_json TEXT NOT NULL,
            access_gap INTEGER NOT NULL DEFAULT 0,
            local_evidence_json TEXT NOT NULL,
            audit_ts TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_access_gap
            ON access_link_audit_items(access_gap, publication_year DESC);
        """
    )
    conn_v14.commit()


def add_role(
    roles: dict[str, set[str]],
    scores: Counter[str],
    paper_id: Any,
    role: str,
    weight: float,
) -> None:
    if paper_id is None:
        return
    pid = str(paper_id).strip()
    if not pid:
        return
    roles[pid].add(role)
    scores[pid] += weight


def collect_decision_papers(conn_v14: sqlite3.Connection, *, limit: int) -> tuple[list[str], dict[str, list[str]]]:
    roles: dict[str, set[str]] = defaultdict(set)
    scores: Counter[str] = Counter()

    if table_exists(conn_v14, "main_path_edges"):
        cols = columns(conn_v14, "main_path_edges")
        src = "source_paper_id" if "source_paper_id" in cols else "citing_id"
        dst = "target_paper_id" if "target_paper_id" in cols else "cited_id"
        weight_terms = [c for c in ("main_path_weight", "spc", "v13_weight") if c in cols]
        weight = f"COALESCE({', '.join(weight_terms)}, 0)" if weight_terms else "0"
        for row in conn_v14.execute(
            f"""
            SELECT {src} AS src, {dst} AS dst, {weight} AS w
            FROM main_path_edges
            WHERE COALESCE(is_main_path, 0) = 1
            ORDER BY {weight} DESC
            LIMIT ?
            """,
            (max(limit, 3000),),
        ).fetchall():
            add_role(roles, scores, row["src"], "main_path_turning_source", 10.0)
            add_role(roles, scores, row["dst"], "main_path_turning_target", 10.0)

    if table_exists(conn_v14, "branch_lineages"):
        bl_cols = columns(conn_v14, "branch_lineages")
        evidence_col = "split_evidence_json" if "split_evidence_json" in bl_cols else "why_json"
        conf_terms = [c for c in ("split_confidence", "strength") if c in bl_cols]
        conf_expr = f"COALESCE({', '.join(conf_terms)}, 0)" if conf_terms else "0"
        for row in conn_v14.execute(
            f"""
            SELECT {evidence_col} AS evidence
            FROM branch_lineages
            ORDER BY {conf_expr} DESC
            LIMIT ?
            """,
            (max(limit, 6000),),
        ).fetchall():
            payload = loads(row["evidence"], {})
            if not isinstance(payload, dict):
                continue
            pids = []
            for key in ("driver_papers", "papers", "evidence_papers", "turning_papers"):
                pids.extend(payload.get(key) or [])
            for pid in pids:
                add_role(roles, scores, pid, "branch_split_driver", 9.0)

    if table_exists(conn_v14, "predicted_future_edges"):
        cols = columns(conn_v14, "predicted_future_edges")
        conf_terms = [c for c in ("prediction_confidence", "calibrated_prob", "predicted_prob") if c in cols]
        conf_expr = f"COALESCE({', '.join(conf_terms)}, 0)" if conf_terms else "0"
        for row in conn_v14.execute(
            f"""
            SELECT src_paper_id, dst_paper_id, {conf_expr} AS conf
            FROM predicted_future_edges
            ORDER BY {conf_expr} DESC
            LIMIT ?
            """,
            (max(limit, 2000),),
        ).fetchall():
            add_role(roles, scores, row["src_paper_id"], "future_endpoint_source", 8.0)
            add_role(roles, scores, row["dst_paper_id"], "future_endpoint_target", 8.0)

    if table_exists(conn_v14, "subgraph_nodes"):
        for row in conn_v14.execute(
            """
            SELECT paper_id
            FROM subgraph_nodes
            ORDER BY COALESCE(keystone_score_v14, 0) DESC, COALESCE(node_size, 0) DESC
            LIMIT ?
            """,
            (max(1000, limit // 2),),
        ).fetchall():
            add_role(roles, scores, row["paper_id"], "top_keystone", 7.0)

    selected = [pid for pid, _ in scores.most_common(limit)]
    return selected, {pid: sorted(roles[pid]) for pid in selected}


def synthesize_links(row: dict[str, Any]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(kind: str, label: str, url: str, access_level: str) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        links.append({"kind": kind, "label": label, "url": url, "access_level": access_level})

    arxiv_id = normalize_arxiv_id(row.get("arxiv_id"))
    doi = normalize_doi(row.get("doi"))
    s2_id = normalize_s2_paper_id(row.get("s2_paper_id"))
    openalex_id = normalize_openalex_work_id(row.get("openalex_id"))
    if arxiv_id:
        add("arxiv_abs", "arXiv abstract", f"https://arxiv.org/abs/{arxiv_id}", "open")
        add("arxiv_pdf", "arXiv PDF", f"https://arxiv.org/pdf/{arxiv_id}.pdf", "open")
    if doi:
        add("doi", "Publisher DOI", f"https://doi.org/{doi}", "external")
    if s2_id:
        add("semantic_scholar", "Semantic Scholar", f"https://www.semanticscholar.org/paper/{s2_id}", "metadata")
    if openalex_id:
        add("openalex", "OpenAlex work", f"https://openalex.org/{openalex_id}", "metadata")
    return links


def load_paper_meta(conn_main: sqlite3.Connection, paper_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not paper_ids:
        return {}
    ph = ",".join("?" for _ in paper_ids)
    rows = conn_main.execute(
        f"""
        SELECT id, title, publication_year, arxiv_id, doi, s2_paper_id, openalex_id
        FROM papers
        WHERE id IN ({ph})
        """,
        paper_ids,
    ).fetchall()
    return {str(row["id"]): dict(row) for row in rows}


def load_local_evidence(conn_main: sqlite3.Connection, conn_v14: sqlite3.Connection, paper_ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {
        pid: {"section_count": 0, "primary_section_count": 0, "limitation_atoms": 0}
        for pid in paper_ids
    }
    if paper_ids and table_exists(conn_main, "paper_sections"):
        ph = ",".join("?" for _ in paper_ids)
        for row in conn_main.execute(
            f"""
            SELECT paper_id,
                   COUNT(*) AS section_count,
                   SUM(CASE WHEN section_name IN ('limitations','discussion','conclusion','future_work','results','error_analysis','ablation','method','experiments')
                             AND length(trim(section_text)) >= 80
                            THEN 1 ELSE 0 END) AS primary_section_count
            FROM paper_sections
            WHERE paper_id IN ({ph})
            GROUP BY paper_id
            """,
            paper_ids,
        ).fetchall():
            out[str(row["paper_id"])]["section_count"] = int(row["section_count"] or 0)
            out[str(row["paper_id"])]["primary_section_count"] = int(row["primary_section_count"] or 0)
    if paper_ids and table_exists(conn_v14, "limitation_atoms"):
        ph = ",".join("?" for _ in paper_ids)
        for row in conn_v14.execute(
            f"""
            SELECT paper_id, COUNT(*) AS n
            FROM limitation_atoms
            WHERE paper_id IN ({ph})
            GROUP BY paper_id
            """,
            paper_ids,
        ).fetchall():
            out[str(row["paper_id"])]["limitation_atoms"] = int(row["n"] or 0)
    return out


def run_access_link_audit(
    *,
    db_main: Path = Path(DB_MAIN),
    db_v14: Path = Path(DB_V14),
    out_dir: Path = Path(REPORT_DIR),
    limit: int = 12000,
) -> dict[str, Any]:
    audit_ts = utc_now()
    with connect(db_main) as conn_main, connect(db_v14) as conn_v14:
        ensure_schema(conn_v14)
        paper_ids, role_map = collect_decision_papers(conn_v14, limit=limit)
        meta = load_paper_meta(conn_main, paper_ids)
        local = load_local_evidence(conn_main, conn_v14, paper_ids)
        rows = []
        role_counts: Counter[str] = Counter()
        gap_by_role: Counter[str] = Counter()
        for pid in paper_ids:
            row = meta.get(pid, {"id": pid, "title": None})
            links = synthesize_links(row)
            roles = role_map.get(pid, [])
            for role in roles:
                role_counts[role] += 1
            access_gap = int(not links)
            if access_gap:
                for role in roles:
                    gap_by_role[role] += 1
            rows.append(
                {
                    "paper_id": pid,
                    "roles_json": jdumps(roles),
                    "title": row.get("title"),
                    "publication_year": row.get("publication_year"),
                    "arxiv_id": normalize_arxiv_id(row.get("arxiv_id")),
                    "doi": normalize_doi(row.get("doi")),
                    "s2_paper_id": normalize_s2_paper_id(row.get("s2_paper_id")),
                    "openalex_id": normalize_openalex_work_id(row.get("openalex_id")),
                    "synthesized_links_json": jdumps(links),
                    "access_gap": access_gap,
                    "local_evidence_json": jdumps(local.get(pid, {})),
                    "audit_ts": audit_ts,
                }
            )
        conn_v14.execute("DELETE FROM access_link_audit_items")
        if rows:
            conn_v14.executemany(
                """
                INSERT INTO access_link_audit_items (
                    paper_id, roles_json, title, publication_year, arxiv_id, doi,
                    s2_paper_id, openalex_id, synthesized_links_json, access_gap,
                    local_evidence_json, audit_ts
                ) VALUES (
                    :paper_id, :roles_json, :title, :publication_year, :arxiv_id, :doi,
                    :s2_paper_id, :openalex_id, :synthesized_links_json, :access_gap,
                    :local_evidence_json, :audit_ts
                )
                """,
                rows,
            )
        conn_v14.commit()

    total = len(rows)
    gap_n = sum(int(r["access_gap"]) for r in rows)
    local_primary = sum(1 for r in rows if loads(r["local_evidence_json"], {}).get("primary_section_count", 0) > 0)
    summary = {
        "audit_ts": audit_ts,
        "decision_papers": total,
        "access_gaps": gap_n,
        "access_gap_rate": gap_n / max(1, total),
        "with_primary_local_evidence": local_primary,
        "primary_local_evidence_rate": local_primary / max(1, total),
        "role_counts": dict(role_counts),
        "gap_by_role": dict(gap_by_role),
        "sample_gaps": [
            {
                "paper_id": r["paper_id"],
                "title": r["title"],
                "roles": loads(r["roles_json"], []),
                "local_evidence": loads(r["local_evidence_json"], {}),
            }
            for r in rows
            if r["access_gap"]
        ][:30],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "access_link_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "access_link_audit.md").write_text(render_markdown(summary), encoding="utf-8")
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Access Link Audit",
        "",
        f"- Audit: `{summary['audit_ts']}`",
        f"- Decision-critical papers: {summary['decision_papers']:,}",
        f"- Access gaps: {summary['access_gaps']:,} ({summary['access_gap_rate']:.1%})",
        f"- With primary local evidence: {summary['with_primary_local_evidence']:,} ({summary['primary_local_evidence_rate']:.1%})",
        "",
        "## Role Coverage",
        "",
        "| Role | Papers | Access gaps |",
        "| --- | ---: | ---: |",
    ]
    roles = sorted(set(summary["role_counts"]) | set(summary["gap_by_role"]))
    for role in roles:
        lines.append(f"| {role} | {summary['role_counts'].get(role, 0):,} | {summary['gap_by_role'].get(role, 0):,} |")
    lines.extend(["", "## Sample Access Gaps", ""])
    for item in summary["sample_gaps"][:20]:
        lines.append(
            f"- `{item['paper_id']}` {item.get('title') or ''} "
            f"roles={', '.join(item.get('roles') or [])} local={item.get('local_evidence')}"
        )
    if not summary["sample_gaps"]:
        lines.append("- No access gaps in audited decision-critical set.")
    lines.extend(
        [
            "",
            "## Product Rule",
            "",
            "Paper detail must show local evidence, synthesized external access links, or an explicit access gap. "
            "A key turning paper without local evidence can still be useful if external access is present, but it cannot support strong section-level claims until section ingest covers it.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit access links for decision-critical V14B papers.")
    parser.add_argument("--db", default=DB_MAIN)
    parser.add_argument("--db-v14", default=DB_V14)
    parser.add_argument("--out-dir", default=str(REPORT_DIR))
    parser.add_argument("--limit", type=int, default=12000)
    args = parser.parse_args(argv)
    summary = run_access_link_audit(
        db_main=Path(args.db),
        db_v14=Path(args.db_v14),
        out_dir=Path(args.out_dir),
        limit=args.limit,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
