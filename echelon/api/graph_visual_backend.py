"""
V14B visual graph API backend.

This module is intentionally thin and SQLite-native: Step10 materializes the
heavy graph product tables, while the API layer provides low-latency search,
paper hydration, and expert edit persistence without re-running graph builders.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

from echelon.schema.graph_visual_edit import GraphSearchQuery, GraphVisualEdit
from echelon.v14b.config import DB_MAIN, DB_V14
from echelon.v14b.id_normalization import (
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_work_id,
    normalize_s2_paper_id,
)

SCHEMA_VERSION = "V14B.visual.1"
REQUIRED_VISUAL_TABLES = (
    "visual_nodes",
    "visual_edges",
    "visual_clusters",
    "branch_lineages",
    "visual_paper_details",
)


def _db_v14_path() -> Path:
    return Path(
        os.environ.get("V14B_VISUAL_DB")
        or os.environ.get("V14B_DB_V14")
        or os.environ.get("ECHELON_DB_V14")
        or DB_V14
    )


def _db_main_path() -> Path:
    return Path(
        os.environ.get("V14B_DB_MAIN")
        or os.environ.get("ECHELON_DB_MAIN")
        or DB_MAIN
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_v14_path()), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _connect_main() -> sqlite3.Connection | None:
    path = _db_main_path()
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'virtual table') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _visual_ready(conn: sqlite3.Connection) -> tuple[bool, list[str]]:
    missing = [table for table in REQUIRED_VISUAL_TABLES if not _table_exists(conn, table)]
    return not missing, missing


def _loads(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def ensure_edit_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS graph_visual_edits (
            edit_id TEXT PRIMARY KEY,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            action TEXT NOT NULL,
            payload TEXT,
            rationale TEXT,
            expert_id TEXT NOT NULL,
            timestamp TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'accepted',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_graph_visual_edits_expert
            ON graph_visual_edits(expert_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_graph_visual_edits_target
            ON graph_visual_edits(target_type, target_id);
        """
    )
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(graph_visual_edits)").fetchall()
    }
    if "payload" not in columns:
        conn.execute("ALTER TABLE graph_visual_edits ADD COLUMN payload TEXT")
        columns.add("payload")
    if "payload_json" in columns:
        conn.execute(
            """
            UPDATE graph_visual_edits
            SET payload = COALESCE(payload, payload_json)
            WHERE payload IS NULL AND payload_json IS NOT NULL
            """
        )
    conn.commit()


def submit_visual_edit(edit: GraphVisualEdit) -> dict:
    with _connect() as conn:
        ensure_edit_schema(conn)
        conn.execute(
            """
            INSERT OR IGNORE INTO graph_visual_edits
                (edit_id, target_type, target_id, action, payload, rationale,
                 expert_id, timestamp, version, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'accepted')
            """,
            (
                edit.edit_id,
                edit.target_type,
                edit.target_id,
                edit.action,
                json.dumps(edit.payload, ensure_ascii=False, sort_keys=True),
                edit.rationale,
                edit.expert_id,
                edit.timestamp.isoformat(),
                edit.version,
            ),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT edit_id, target_type, target_id, action, expert_id, version,
                   status, created_at, updated_at
            FROM graph_visual_edits
            WHERE edit_id = ?
            """,
            (edit.edit_id,),
        ).fetchone()
    return {
        "schema_version": SCHEMA_VERSION,
        "accepted": True,
        "edit": dict(row) if row else {"edit_id": edit.edit_id, "status": "accepted"},
    }


def get_visual_edit_status(edit_id: str) -> dict:
    with _connect() as conn:
        ensure_edit_schema(conn)
        row = conn.execute(
            """
            SELECT edit_id, target_type, target_id, action, payload, rationale,
                   expert_id, timestamp, version, status, created_at, updated_at
            FROM graph_visual_edits
            WHERE edit_id = ?
            """,
            (edit_id,),
        ).fetchone()
    if not row:
        return {
            "schema_version": SCHEMA_VERSION,
            "edit_id": edit_id,
            "status": "not_found",
        }
    data = dict(row)
    data["payload"] = _loads(data.get("payload"), {})
    data["schema_version"] = SCHEMA_VERSION
    return data


def get_visual_edit_history(expert_id: str, limit: int = 100) -> dict:
    with _connect() as conn:
        ensure_edit_schema(conn)
        rows = conn.execute(
            """
            SELECT edit_id, target_type, target_id, action, payload, rationale,
                   expert_id, timestamp, version, status, created_at, updated_at
            FROM graph_visual_edits
            WHERE expert_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (expert_id, max(1, min(int(limit), 500))),
        ).fetchall()
    edits = []
    for row in rows:
        item = dict(row)
        item["payload"] = _loads(item.get("payload"), {})
        edits.append(item)
    return {
        "schema_version": SCHEMA_VERSION,
        "expert_id": expert_id,
        "edits": edits,
        "total_matches": len(edits),
    }


def _fts_query(text: str) -> str:
    tokens = re.findall(r"[\w\u4e00-\u9fff.-]+", text or "")
    # FTS5 treats OR as a boolean operator. Tokens are sanitized above, so this
    # stays simple and avoids syntax errors from raw user punctuation.
    return " OR ".join(tokens[:16])


def _candidate_ids_from_fts(
    conn: sqlite3.Connection,
    query_text: str | None,
    limit: int,
) -> tuple[list[str], dict[str, float]]:
    if not query_text:
        return [], {}
    if _table_exists(conn, "visual_search_fts"):
        q = _fts_query(query_text)
        if q:
            try:
                rows = conn.execute(
                    """
                    SELECT paper_id, bm25(visual_search_fts) AS rank_score
                    FROM visual_search_fts
                    WHERE visual_search_fts MATCH ?
                    ORDER BY rank_score
                    LIMIT ?
                    """,
                    (q, limit),
                ).fetchall()
                ids = [str(r["paper_id"]) for r in rows]
                scores = {
                    str(r["paper_id"]): 1.0 / (1.0 + abs(float(r["rank_score"] or 0.0)))
                    for r in rows
                }
                return ids, scores
            except sqlite3.OperationalError:
                pass

    pattern = f"%{query_text.lower()}%"
    rows = conn.execute(
        """
        SELECT n.paper_id
        FROM visual_nodes n
        JOIN visual_paper_details d ON d.paper_id = n.paper_id
        WHERE lower(COALESCE(d.metadata_json, '') || ' ' ||
                    COALESCE(d.abstract, '') || ' ' ||
                    COALESCE(d.sections_json, '') || ' ' ||
                    COALESCE(d.limitations_json, '')) LIKE ?
        ORDER BY COALESCE(n.node_size, 0) DESC
        LIMIT ?
        """,
        (pattern, limit),
    ).fetchall()
    ids = [str(r["paper_id"]) for r in rows]
    return ids, {pid: 0.5 for pid in ids}


DECISION_SECTION_NAMES = {
    "limitations",
    "discussion",
    "conclusion",
    "future_work",
    "results",
    "error_analysis",
    "ablation",
    "method",
    "experiments",
}


def _load_live_sections(paper_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    conn = _connect_main()
    if conn is None or not paper_ids:
        return {}
    try:
        if not _table_exists(conn, "paper_sections"):
            return {}
        placeholders = ",".join("?" for _ in paper_ids)
        rows = conn.execute(
            f"""
            SELECT paper_id, section_name, section_text, source_type, parser_name,
                   source_url, section_pages_json, section_meta_json
            FROM paper_sections
            WHERE paper_id IN ({placeholders})
            ORDER BY
              CASE section_name
                WHEN 'limitations' THEN 1
                WHEN 'discussion' THEN 2
                WHEN 'conclusion' THEN 3
                WHEN 'future_work' THEN 4
                WHEN 'results' THEN 5
                WHEN 'error_analysis' THEN 6
                WHEN 'ablation' THEN 7
                WHEN 'method' THEN 8
                WHEN 'experiments' THEN 9
                ELSE 20
              END
            """,
            paper_ids,
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()

    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        text = str(row["section_text"] or "").strip()
        if not text:
            continue
        section = {
            "section_name": row["section_name"],
            "section_type": row["section_name"],
            "section_text": text[:2800],
            "text": text[:2800],
            "source_type": row["source_type"],
            "parser_name": row["parser_name"],
            "source_url": row["source_url"],
            "pages": _loads(row["section_pages_json"], []),
            "meta": _loads(row["section_meta_json"], {}),
        }
        out.setdefault(str(row["paper_id"]), []).append(section)
    return out


def _load_live_limitations(
    conn: sqlite3.Connection,
    paper_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not paper_ids or not _table_exists(conn, "limitation_atoms"):
        return {}
    placeholders = ",".join("?" for _ in paper_ids)
    try:
        rows = conn.execute(
            f"""
            SELECT paper_id, description, keyword, severity, evidence_source,
                   evidence_quality, evidence_weight, source_section_name,
                   extractor_method
            FROM limitation_atoms
            WHERE paper_id IN ({placeholders})
            ORDER BY COALESCE(evidence_weight, 0) DESC, atom_id DESC
            """,
            paper_ids,
        ).fetchall()
    except sqlite3.Error:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["paper_id"]), []).append(
            {
                "description": row["description"],
                "keyword": row["keyword"],
                "severity": row["severity"],
                "evidence_source": row["evidence_source"],
                "evidence_quality": row["evidence_quality"],
                "evidence_weight": row["evidence_weight"],
                "source_section_name": row["source_section_name"],
                "extractor_method": row["extractor_method"],
            }
        )
    return out


def _external_links_from_ids(
    ids: dict[str, Any],
    sections: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(kind: str, label: str, url: str | None, access_level: str) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        links.append(
            {
                "kind": kind,
                "label": label,
                "url": url,
                "access_level": access_level,
            }
        )

    arxiv_id = normalize_arxiv_id(ids.get("arxiv_id"))
    doi = normalize_doi(ids.get("doi"))
    openalex_id = normalize_openalex_work_id(ids.get("openalex_work_id"))
    s2_id = normalize_s2_paper_id(ids.get("s2_paper_id"))
    if arxiv_id:
        add("arxiv_abs", "arXiv abstract", f"https://arxiv.org/abs/{arxiv_id}", "open")
        add("arxiv_pdf", "arXiv PDF", f"https://arxiv.org/pdf/{arxiv_id}.pdf", "open")
    if doi:
        add("doi", "Publisher DOI", f"https://doi.org/{doi}", "external")
    if openalex_id:
        add("openalex", "OpenAlex work", f"https://openalex.org/{openalex_id}", "metadata")
    if s2_id:
        add("semantic_scholar", "Semantic Scholar", f"https://www.semanticscholar.org/paper/{s2_id}", "metadata")
    for section in sections or []:
        source_url = section.get("source_url")
        if source_url:
            label = f"Evidence source: {section.get('section_name') or 'section'}"
            level = "open" if "arxiv.org" in str(source_url) else "external"
            add("section_source", label, str(source_url), level)
    return links


def _content_access_payload(
    ids: dict[str, Any],
    access: dict[str, Any],
    sections: list[dict[str, Any]],
    limitations: list[dict[str, Any]],
    claim_cards: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]], str]:
    access = access if isinstance(access, dict) else {}
    section_names = {
        str(s.get("section_name") or s.get("section_type") or "").strip()
        for s in sections
        if str(s.get("section_name") or s.get("section_type") or "").strip()
    }
    decision_sections = [
        s
        for s in sections
        if str(s.get("section_name") or s.get("section_type") or "") in DECISION_SECTION_NAMES
    ]
    links = access.get("external_links") or _external_links_from_ids(ids, sections)
    local_content = dict(access.get("local_content") or {})
    local_content.update(
        {
            "sections": sections[:10],
            "decision_evidence_sections": decision_sections[:10],
            "section_names": sorted(section_names),
            "limitation_atoms": len(limitations or []),
            "claim_cards": len(claim_cards or []),
        }
    )
    availability = dict(access.get("content_availability") or {})
    availability.update(
        {
            "has_local_sections": bool(sections),
            "has_primary_evidence_sections": bool(section_names.intersection(DECISION_SECTION_NAMES)),
            "has_limitation_atoms": bool(limitations),
            "has_claim_cards": bool(claim_cards),
            "full_text_cached": False,
        }
    )
    return (
        local_content,
        availability,
        links,
        str(access.get("storage_policy") or "pdf_not_cached"),
    )


def _hydrate_hits(
    conn: sqlite3.Connection,
    paper_ids: list[str],
    *,
    scores: dict[str, float] | None = None,
    reasons: dict[str, Any] | None = None,
) -> list[dict]:
    if not paper_ids:
        return []
    unique_ids = list(dict.fromkeys(paper_ids))
    placeholders = ",".join("?" for _ in unique_ids)
    detail_cols = _table_columns(conn, "visual_paper_details")
    claim_cards_sql = (
        "d.claim_cards_json"
        if "claim_cards_json" in detail_cols
        else "'[]' AS claim_cards_json"
    )
    access_sql = (
        "d.access_json"
        if "access_json" in detail_cols
        else "'{}' AS access_json"
    )
    rows = conn.execute(
        f"""
        SELECT
            n.paper_id, n.cluster_id, n.branch_id, n.x, n.y, n.z,
            n.publication_year, n.node_size, n.color_hex, n.visual_role,
            n.uncertainty_score, n.flags_json,
            c.label AS cluster_label,
            d.ids_json, d.metadata_json, d.abstract, d.sections_json,
            d.limitations_json, d.recommendation_json,
            {claim_cards_sql},
            {access_sql}
        FROM visual_nodes n
        LEFT JOIN visual_clusters c ON c.cluster_id = n.cluster_id
        LEFT JOIN visual_paper_details d ON d.paper_id = n.paper_id
        WHERE n.paper_id IN ({placeholders})
        """,
        unique_ids,
    ).fetchall()
    by_id = {str(row["paper_id"]): row for row in rows}
    live_sections_by_id = _load_live_sections(unique_ids)
    live_limitations_by_id = _load_live_limitations(conn, unique_ids)
    out = []
    for pid in unique_ids:
        row = by_id.get(pid)
        if not row:
            continue
        metadata = _loads(row["metadata_json"], {})
        ids = _loads(row["ids_json"], {})
        flags = _loads(row["flags_json"], {})
        recommendations = _loads(row["recommendation_json"], {})
        stored_sections = _loads(row["sections_json"], [])
        limitations = _loads(row["limitations_json"], [])
        if not limitations:
            limitations = live_limitations_by_id.get(pid, [])
        claim_cards = _loads(row["claim_cards_json"], [])
        access = _loads(row["access_json"], {})
        sections = live_sections_by_id.get(pid) or stored_sections
        local_content, availability, access_links, storage_policy = _content_access_payload(
            ids,
            access,
            sections if isinstance(sections, list) else [],
            limitations if isinstance(limitations, list) else [],
            claim_cards if isinstance(claim_cards, list) else [],
        )
        abstract = row["abstract"] or ""
        out.append(
            {
                "paper_id": pid,
                "title": metadata.get("title") or pid,
                "abstract": abstract[:1400],
                "year": metadata.get("year") or row["publication_year"],
                "cited_by_count": metadata.get("cited_by_count"),
                "ids": ids,
                "corpus_id": metadata.get("corpus_id"),
                "field": metadata.get("field"),
                "subfield": metadata.get("subfield"),
                "topic": metadata.get("topic"),
                "cluster_id": row["cluster_id"],
                "branch_id": row["branch_id"],
                "cluster_label": row["cluster_label"] or metadata.get("branch_label"),
                "coordinates": {"x": row["x"], "y": row["y"], "z": row["z"]},
                "visual": {
                    "node_size": row["node_size"],
                    "color_hex": row["color_hex"],
                    "role": row["visual_role"],
                    "uncertainty_score": row["uncertainty_score"],
                    "flags": flags,
                },
                "limitations": limitations[:5] if isinstance(limitations, list) else [],
                "claim_cards": claim_cards[:5] if isinstance(claim_cards, list) else [],
                "content_availability": availability,
                "local_content": local_content,
                "access_links": access_links,
                "storage_policy": storage_policy,
                "recommendations": recommendations,
                "score": float((scores or {}).get(pid, 0.0)),
                "reason": (reasons or {}).get(pid),
            }
        )
    return out


def _passes_filters(hit: dict, query: GraphSearchQuery) -> bool:
    filters = query.filters or {}
    year = hit.get("year")
    if filters.get("year_from") is not None and year is not None:
        if int(year) < int(filters["year_from"]):
            return False
    if filters.get("year_to") is not None and year is not None:
        if int(year) > int(filters["year_to"]):
            return False
    if filters.get("min_citations") is not None:
        citations = hit.get("cited_by_count") or 0
        if int(citations) < int(filters["min_citations"]):
            return False
    for key in ("cluster_id", "branch_id", "field", "subfield", "topic"):
        if filters.get(key) is not None and str(hit.get(key)) != str(filters[key]):
            return False
    if query.query_type in {"field", "subfield", "topic"} and query.query_text:
        value = str(hit.get(query.query_type) or "").lower()
        label = str(hit.get("cluster_label") or "").lower()
        text = query.query_text.lower()
        if text not in value and text not in label and text not in hit.get("title", "").lower():
            return False
    return True


def _generic_node_search(conn: sqlite3.Connection, query: GraphSearchQuery) -> list[dict]:
    limit = min(query.top_k * 8, 2000)
    if query.query_text:
        ids, scores = _candidate_ids_from_fts(conn, query.query_text, limit)
    else:
        rows = conn.execute(
            """
            SELECT paper_id, COALESCE(node_size, 0) AS score
            FROM visual_nodes
            ORDER BY score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        ids = [str(r["paper_id"]) for r in rows]
        scores = {str(r["paper_id"]): float(r["score"] or 0.0) for r in rows}
    hits = _hydrate_hits(conn, ids, scores=scores)
    return [hit for hit in hits if _passes_filters(hit, query)][: query.top_k]


def _recommendation_search(conn: sqlite3.Connection, mode: str, top_k: int) -> list[dict]:
    if not _table_exists(conn, "visual_recommendations"):
        return []
    rows = conn.execute(
        """
        SELECT paper_id, score, reason_json
        FROM visual_recommendations
        WHERE mode = ?
        ORDER BY rank ASC
        LIMIT ?
        """,
        (mode, top_k),
    ).fetchall()
    ids = [str(r["paper_id"]) for r in rows]
    scores = {str(r["paper_id"]): float(r["score"] or 0.0) for r in rows}
    reasons = {str(r["paper_id"]): _loads(r["reason_json"], {}) for r in rows}
    return _hydrate_hits(conn, ids, scores=scores, reasons=reasons)


def _citation_search(conn: sqlite3.Connection, query: GraphSearchQuery) -> list[dict]:
    target = (
        query.filters.get("paper_id")
        or query.filters.get("target_id")
        or query.query_text
    )
    if target:
        rows = conn.execute(
            """
            SELECT source_paper_id, target_paper_id, edge_type, layer, weight,
                   confidence, is_main_path, evidence_json
            FROM visual_edges
            WHERE source_paper_id = ? OR target_paper_id = ?
            ORDER BY is_main_path DESC, COALESCE(weight, 0) DESC
            LIMIT ?
            """,
            (target, target, min(query.top_k * 3, 500)),
        ).fetchall()
        ids: list[str] = []
        scores: dict[str, float] = {}
        reasons: dict[str, Any] = {}
        for row in rows:
            src, dst = str(row["source_paper_id"]), str(row["target_paper_id"])
            other = dst if src == target else src
            ids.append(other)
            scores[other] = max(scores.get(other, 0.0), float(row["weight"] or 0.0))
            reasons[other] = {
                "edge_type": row["edge_type"],
                "layer": row["layer"],
                "is_main_path": bool(row["is_main_path"]),
                "confidence": row["confidence"],
                "evidence": _loads(row["evidence_json"], {}),
            }
        return _hydrate_hits(conn, ids[: query.top_k], scores=scores, reasons=reasons)

    rows = conn.execute(
        """
        SELECT target_paper_id AS paper_id, COUNT(*) AS n_edges
        FROM visual_edges
        WHERE layer = 'citation'
        GROUP BY target_paper_id
        ORDER BY n_edges DESC
        LIMIT ?
        """,
        (query.top_k,),
    ).fetchall()
    ids = [str(r["paper_id"]) for r in rows]
    scores = {str(r["paper_id"]): float(r["n_edges"] or 0.0) for r in rows}
    return _hydrate_hits(conn, ids, scores=scores)


def _landmark_search(conn: sqlite3.Connection, query: GraphSearchQuery) -> list[dict]:
    target = query.filters.get("paper_id") or query.query_text
    if target:
        return _citation_search(conn, query)
    rows = conn.execute(
        """
        SELECT paper_id,
               CASE visual_role
                   WHEN 'main_path' THEN 1.0
                   WHEN 'future_anchor' THEN 0.8
                   WHEN 'limitation_bottleneck' THEN 0.7
                   ELSE 0.4
               END AS score
        FROM visual_nodes
        WHERE visual_role IN ('main_path', 'future_anchor', 'limitation_bottleneck')
        ORDER BY score DESC, COALESCE(node_size, 0) DESC
        LIMIT ?
        """,
        (query.top_k,),
    ).fetchall()
    ids = [str(r["paper_id"]) for r in rows]
    scores = {str(r["paper_id"]): float(r["score"] or 0.0) for r in rows}
    return _hydrate_hits(conn, ids, scores=scores)


def _expert_edited_search(conn: sqlite3.Connection, query: GraphSearchQuery) -> list[dict]:
    ensure_edit_schema(conn)
    where = ""
    params: list[Any] = []
    if query.expert_id:
        where = "WHERE expert_id = ?"
        params.append(query.expert_id)
    rows = conn.execute(
        f"""
        SELECT target_id, edit_id, action, expert_id, status, created_at
        FROM graph_visual_edits
        {where}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (*params, query.top_k),
    ).fetchall()
    ids = [str(r["target_id"]) for r in rows]
    reasons = {
        str(r["target_id"]): {
            "edit_id": r["edit_id"],
            "action": r["action"],
            "expert_id": r["expert_id"],
            "status": r["status"],
            "created_at": r["created_at"],
        }
        for r in rows
    }
    return _hydrate_hits(conn, ids, scores={pid: 1.0 for pid in ids}, reasons=reasons)


def search_visual_graph(query: GraphSearchQuery) -> dict:
    start = time.perf_counter()
    with _connect() as conn:
        ready, missing = _visual_ready(conn)
        if not ready:
            return {
                "query_id": query.query_id,
                "hits": [],
                "total_matches": 0,
                "elapsed_ms": _elapsed_ms(start),
                "schema_version": SCHEMA_VERSION,
                "ready": False,
                "missing_tables": missing,
                "message": "visual graph is not materialized yet; run `make visual-graph` after Step2-Step9",
            }

        if query.query_type == "cite":
            hits = _citation_search(conn, query)
        elif query.query_type == "landmark_proximity":
            hits = _landmark_search(conn, query)
        elif query.query_type == "bottleneck":
            hits = _recommendation_search(conn, "bottleneck", query.top_k)
        elif query.query_type == "expert_edited":
            hits = _expert_edited_search(conn, query)
        elif query.query_type == "novelty_range":
            hits = _recommendation_search(conn, "bridge", query.top_k)
        elif query.query_type == "lifecycle":
            mode = str(query.filters.get("mode") or query.query_text or "frontier")
            hits = _recommendation_search(conn, mode, query.top_k)
        else:
            hits = _generic_node_search(conn, query)

    return {
        "query_id": query.query_id,
        "hits": hits,
        "total_matches": len(hits),
        "elapsed_ms": _elapsed_ms(start),
        "schema_version": SCHEMA_VERSION,
        "ready": True,
        "query_type": query.query_type,
    }


def _token_set(text: str) -> set[str]:
    return {
        t.lower()
        for t in re.findall(r"[\w\u4e00-\u9fff.-]+", text or "")
        if len(t) >= 2
    }


def _visual_value_model(conn: sqlite3.Connection) -> dict[str, Any]:
    """Describe how the visual product should be interpreted.

    This is deliberately returned by the API instead of being only UI copy:
    downstream clients need to know which layers are evidence, which are layout,
    and whether the Step6/Step13 fused claim layer is actually materialized.
    """
    edge_counts: dict[str, int] = {}
    if _table_exists(conn, "visual_edges"):
        for row in conn.execute(
            """
            SELECT
                CASE
                    WHEN is_main_path = 1 OR edge_type = 'main_path' THEN 'main_path'
                    ELSE layer
                END AS layer_key,
                COUNT(*) AS n
            FROM visual_edges
            GROUP BY layer_key
            """
        ).fetchall():
            edge_counts[str(row["layer_key"])] = int(row["n"] or 0)

    future_directions = 0
    claim_cards = 0
    fusion_adequacy = "not_materialized"
    if _table_exists(conn, "future_directions"):
        future_directions = int(conn.execute("SELECT COUNT(*) FROM future_directions").fetchone()[0])
    if _table_exists(conn, "direction_claim_cards"):
        claim_cards = int(conn.execute("SELECT COUNT(*) FROM direction_claim_cards").fetchone()[0])
    if _table_exists(conn, "fusion_evidence_audit"):
        row = conn.execute(
            """
            SELECT adequacy_label
            FROM fusion_evidence_audit
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row:
            fusion_adequacy = str(row["adequacy_label"] or "unknown")

    return {
        "layout_distance": {
            "algorithm": "paper embeddings/TF-IDF-SVD + community layout, projected into a 2.5D evolution view",
            "relationship": (
                "Horizontal closeness means semantic/community proximity. Vertical/depth position is dominated by "
                "publication time. Distance is not itself a causal proof; causal evidence comes from the edge layers."
            ),
            "display": "The viewer blends semantic X/Y with year so the map reads as branches growing through time.",
        },
        "layers": {
            "main_path": {
                "algorithm": "Step2 SCC-condensed DAG + search path count (SPC) weighted by linked citation strength",
                "relationship": "high-throughput time-forward citation backbone: older cited work -> newer citing work",
                "display": "black thick edges; use it as the historical trunk, not as every local citation",
            },
            "citation": {
                "algorithm": "ID-normalized DOI/arXiv/OpenAlex/S2 reference relinking",
                "relationship": "real paper-to-paper citation in the local corpus, time-forward after V14B normalization",
                "display": "thin grey local edges, loaded on demand because the full layer is dense",
            },
            "topic": {
                "algorithm": "co-citation/co-reference community affinity",
                "relationship": "papers repeatedly cited together or sharing reference neighborhoods",
                "display": "blue-green soft edges that reveal topic blocks and branch neighborhoods",
            },
            "semantic": {
                "algorithm": "paper embedding kNN similarity",
                "relationship": "text/metadata/section-level similarity; useful for search and nearby ideas",
                "display": "thin blue edges; proximity aid, not historical causality",
            },
            "future": {
                "algorithm": "Step5b calibrated temporal link prediction + Step6/Step13 fusion when available",
                "relationship": "candidate future growth links from older enabling papers/bottlenecks toward newer or predicted directions",
                "display": "purple dashed arcs; treat as probability-ranked hypotheses with calibration status",
            },
            "bottleneck": {
                "algorithm": "Step5c/Step13 section-level limitation atoms and typed bottleneck lineage triples",
                "relationship": "unresolved constraints extracted from limitation/discussion/conclusion/results/error sections",
                "display": "red/orange paper markers; read together with evidence quality",
            },
            "uncertainty": {
                "algorithm": "coverage gates over linked refs, OpenAlex field coverage, section evidence, embedding and calibration",
                "relationship": "marks where the graph is structurally weaker or evidence is incomplete",
                "display": "amber markers/notes; uncertainty should lower claim scope, not hide the data",
            },
            "fusion_value": {
                "algorithm": "Step6 tiered fusion + Step13 Claim Card quality gates",
                "relationship": (
                    "combines main-path support, calibrated future probability, unresolved bottlenecks, section evidence, "
                    "branch lineage, and claim-card completeness into decision value"
                ),
                "display": "Radar/Claim Cards; unavailable as high-confidence if directions or claim cards are not materialized",
            },
        },
        "counts": {
            "edges_by_layer": edge_counts,
            "future_directions": future_directions,
            "claim_cards": claim_cards,
            "fusion_adequacy": fusion_adequacy,
        },
        "model_components": {
            "gnn_future_growth": {
                "name": "Step5b VGAE / GCN link-prediction model",
                "algorithm": "2-layer GCN encoder -> variational latent paper embeddings -> dot-product decoder -> calibrated temporal link probability",
                "source": "echelon/v14b/step5b_vgae.py",
                "role": (
                    "This is the project GNN. It proposes future-growth edges, but the product should only "
                    "treat them as high-value directions after Step6 fusion and Step13 Claim Cards add evidence."
                ),
            }
        },
        "layer_combinations": [
            {
                "layers": ["main_path"],
                "label": "Historical trunk",
                "question": "哪些论文真正承接了最多演化流量？",
                "relationship": "Main Path isolates the high-throughput citation backbone.",
                "display": "Only black trunk edges are emphasized; this is the cleanest view of lineage, not topic breadth.",
                "decision_use": "Use for key turning papers and historical dependency, not for future prediction.",
            },
            {
                "layers": ["main_path", "topic"],
                "label": "Trunk plus branch communities",
                "question": "主干周围为什么形成这些主题团？",
                "relationship": "Main gives temporal flow; co-citation reveals intellectual neighborhoods around the trunk.",
                "display": "Black trunk plus blue-green community edges; best default for explaining why the field branched.",
                "decision_use": "Use for Topic Dossier branch naming and driver-paper review.",
            },
            {
                "layers": ["main_path", "citation"],
                "label": "Trunk plus real citation support",
                "question": "主干链条有哪些真实局部引用支撑？",
                "relationship": "SPC trunk is checked against ID-relinked local citation edges.",
                "display": "Black trunk with thin grey supporting citations.",
                "decision_use": "Use to audit whether a claimed turning paper is structurally supported.",
            },
            {
                "layers": ["topic", "semantic"],
                "label": "Topic neighborhood search",
                "question": "这个 topic 附近还有哪些相似论文和主题块？",
                "relationship": "Co-citation captures shared citation context; semantic kNN captures text/section similarity.",
                "display": "Community edges plus similarity edges; good for related-work discovery.",
                "decision_use": "Use for Sci-Bot style retrieval, not as causal evolution evidence.",
            },
            {
                "layers": ["main_path", "topic", "bottleneck"],
                "label": "Why branches split",
                "question": "哪个卡点或使能条件导致分支裂变？",
                "relationship": "Main path and co-citation identify lineage/branch; bottleneck markers explain the constraint pressure.",
                "display": "Trunk and branches with red/orange bottleneck nodes.",
                "decision_use": "Use for Branch Dossier and Bottleneck Lineage review.",
            },
            {
                "layers": ["future", "bottleneck"],
                "label": "Bottleneck-driven future candidates",
                "question": "哪些未来候选是由未解卡点驱动的？",
                "relationship": "GNN/VGAE proposes future links; bottleneck evidence tests whether they address real constraints.",
                "display": "Purple dashed candidates with red/orange bottleneck evidence.",
                "decision_use": "Use as candidate pool only; it cannot become Radar without Claim Cards.",
            },
            {
                "layers": ["future", "bottleneck", "uncertainty"],
                "label": "R&D hypothesis audit",
                "question": "哪些方向值得验证，哪些证据太薄？",
                "relationship": "Future candidates are filtered by unresolved bottlenecks and penalized by coverage/calibration uncertainty.",
                "display": "Purple future arcs, bottleneck markers, and amber uncertainty warnings.",
                "decision_use": "Use before writing a validation experiment or investment memo.",
            },
            {
                "layers": ["main_path", "topic", "future", "bottleneck", "uncertainty"],
                "label": "Full decision context",
                "question": "这个 topic 为什么长成这样，未来哪里可能长，可信度如何？",
                "relationship": "Combines lineage, branch neighborhood, candidate generation, constraints, and evidence risk.",
                "display": "Dense decision overlay; zoom/filter before reading individual edges.",
                "decision_use": "Use for executive review after reading the Topic Dossier.",
            },
        ],
        "fusion_status": (
            "materialized"
            if future_directions and claim_cards
            else "graph_edges_only_until_step6_step13_rerun"
        ),
    }


TOPIC_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "into", "using", "based",
    "paper", "papers", "optical", "optics", "study", "toward", "towards", "high",
    "low", "new", "via", "can", "use", "used", "based", "enabled", "enables",
    "light", "photonic", "photonics", "metasurface", "metasurfaces", "metalens",
}
LABEL_STOPWORDS = {"the", "and", "for", "with", "from", "this", "that", "can", "using", "based"}

METALENS_BRANCH_FACETS = [
    {
        "name": "Imaging systems",
        "priority": 10,
        "keywords": ["imaging", "image", "microscope", "microscopy", "endoscopy", "camera", "in-the-wild"],
        "why": "Metalens work starts becoming system-relevant when the lens is evaluated as an imaging component rather than a single focusing demo.",
        "bottleneck": "system-level image quality, field of view, packaging, and application fit",
        "enabler": "integrated optical design plus application-specific evaluation pipelines",
    },
    {
        "name": "Broadband achromatic correction",
        "priority": 20,
        "keywords": ["achromatic", "chromatic", "broadband", "dispersion", "aberration", "wideband", "visible"],
        "why": "Chromatic and angular aberrations force a split from monochromatic focusing toward broadband imaging architectures.",
        "bottleneck": "dispersion control under broadband and off-axis conditions",
        "enabler": "hybrid materials, multi-layer design, inverse design, and computational correction",
    },
    {
        "name": "High-NA focusing performance",
        "priority": 30,
        "keywords": ["high-na", "numerical aperture", "ultra-high", "diffraction", "focus", "focusing", "resolution"],
        "why": "High numerical aperture pushes metalenses toward diffraction-limited performance and exposes efficiency/aberration tradeoffs.",
        "bottleneck": "maintaining efficiency and image quality at high NA",
        "enabler": "nanostructure optimization, polarization control, and better performance criteria",
    },
    {
        "name": "Tunable and multifunctional optics",
        "priority": 40,
        "keywords": ["tunable", "zoom", "multifunction", "multi-function", "multiplex", "polarization", "reconfigurable"],
        "why": "The branch appears when static metalenses are not enough for real systems that need switching, zoom, multiplexing, or multi-state operation.",
        "bottleneck": "active control without sacrificing aperture, efficiency, or manufacturability",
        "enabler": "phase-change materials, polarization multiplexing, MEMS/active platforms, and programmable design",
    },
    {
        "name": "Manufacturing scale-up",
        "priority": 50,
        "keywords": ["large-area", "centimeter", "manufacturing", "fabrication", "printing", "print", "lithography", "scalable", "scaling", "mass", "wafer"],
        "why": "Single-device demonstrations split into a scale-up branch once the constraint becomes repeatable area, cost, yield, and process compatibility.",
        "bottleneck": "large-area uniformity, process yield, cost, and reliability",
        "enabler": "nanoimprint/printing, hybrid materials, foundry-compatible lithography, and process metrology",
    },
    {
        "name": "Computational compensation and inverse design",
        "priority": 60,
        "keywords": ["inverse design", "computational", "neural", "algorithm", "optimization", "compensation", "aberrated", "burst"],
        "why": "When pure optics cannot remove all aberrations cheaply, the branch shifts part of the performance burden into design algorithms or computation.",
        "bottleneck": "joint optical-computational validation and robustness outside curated lab settings",
        "enabler": "inverse design, differentiable optics, neural reconstruction, and task-aware performance metrics",
    },
    {
        "name": "Integrated quantum/on-chip metalenses",
        "priority": 70,
        "keywords": ["integrat", "on-chip", "photonic crystal", "single photon", "spe", "hbn", "quantum", "emitter"],
        "why": "This branch grows when metalenses are used to couple, collect, or package emission inside compact photonic/quantum systems.",
        "bottleneck": "alignment, coupling efficiency, miniaturization, and heterogeneous integration",
        "enabler": "2D emitters, photonic crystal resonators, integrated packaging, and bulk/device engineering",
    },
]

BOTTLENECK_FACETS = [
    ("efficiency", ["efficiency", "throughput", "loss", "collection", "transmission"]),
    ("chromatic aberration", ["chromatic", "dispersion", "achromatic", "broadband", "wavelength"]),
    ("field of view and angular aberration", ["field of view", "fov", "angular", "off-axis", "aberration"]),
    ("manufacturing consistency", ["manufacturing", "fabrication", "scalable", "scalability", "large-area", "uniformity", "yield", "printing", "lithography"]),
    ("system integration", ["integration", "integrated", "on-chip", "packaging", "alignment", "coupling"]),
    ("cost and reliability", ["cost", "low-cost", "reliability", "robust", "mass", "commercial"]),
]


def _topic_branch_facets(topic: str) -> list[dict[str, Any]]:
    text = topic.lower()
    if "metalens" in text or "metasurface" in text or "meta-lens" in text:
        return METALENS_BRANCH_FACETS
    return []


def _paper_text(paper: dict[str, Any]) -> str:
    return " ".join(
        str(paper.get(k) or "")
        for k in ("title", "abstract", "cluster_label", "field", "subfield", "topic")
    ).lower()


def _facet_matches(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(k in lower for k in keywords)


def _paper_ref(paper: dict[str, Any], why: str | None = None) -> dict[str, Any]:
    return {
        "paper_id": paper.get("paper_id"),
        "title": paper.get("title"),
        "year": paper.get("year"),
        "cluster_id": paper.get("cluster_id"),
        "branch_id": paper.get("branch_id"),
        "cluster_label": paper.get("cluster_label"),
        "access_links": paper.get("access_links") or [],
        "why": why,
    }


def _build_topic_branch_splits(
    topic: str,
    hits: list[dict[str, Any]],
    turning_hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    facets = _topic_branch_facets(topic)
    source_papers = hits[:200]
    turning_by_id = {p.get("paper_id"): p for p in turning_hits}
    splits: list[dict[str, Any]] = []
    for facet in facets:
        matched = [
            p for p in source_papers
            if _facet_matches(_paper_text(p), facet["keywords"])
        ]
        if not matched:
            continue
        matched.sort(key=lambda p: (int(p.get("year") or 9999), -(p.get("score") or 0)))
        turning = [
            turning_by_id[p.get("paper_id")]
            for p in matched
            if p.get("paper_id") in turning_by_id
        ]
        evidence = turning[:3] or matched[:3]
        splits.append(
            {
                "name": facet["name"],
                "priority": facet.get("priority", 999),
                "paper_count": len(matched),
                "why_appeared": facet["why"],
                "historical_bottleneck": facet["bottleneck"],
                "enabling_condition": facet["enabler"],
                "first_seen_year": min((int(p.get("year")) for p in matched if p.get("year")), default=None),
                "driver_papers": [
                    _paper_ref(p, "turning/main-path evidence" if p.get("paper_id") in turning_by_id else "topic evidence")
                    for p in evidence
                ],
            }
        )
    if splits:
        splits.sort(key=lambda x: (x.get("priority", 999), -x["paper_count"], x.get("first_seen_year") or 9999))
        return splits[:7]

    branch_counter: Counter[str] = Counter(str(h.get("cluster_label") or h.get("cluster_id") or "branch") for h in hits)
    fallback = []
    for label, count in branch_counter.most_common(6):
        branch_hits = [h for h in hits if str(h.get("cluster_label") or h.get("cluster_id") or "branch") == label]
        fallback.append(
            {
                "name": _clean_branch_label(label, label),
                "paper_count": count,
                "why_appeared": "Detected from topic search concentration in a visual cluster; needs branch-lineage evidence for strong claims.",
                "historical_bottleneck": "unknown until limitation/section evidence is available",
                "enabling_condition": "unknown until section-level evidence is available",
                "first_seen_year": min((int(p.get("year")) for p in branch_hits if p.get("year")), default=None),
                "driver_papers": [_paper_ref(p, "representative topic evidence") for p in branch_hits[:3]],
            }
        )
    return fallback


def _classify_bottleneck(keyword: str | None, description: str | None) -> str:
    text = f"{keyword or ''} {description or ''}".lower()
    for label, terms in BOTTLENECK_FACETS:
        if any(term in text for term in terms):
            return label
    if keyword:
        return str(keyword)
    return "technical limitation"


def _build_bottleneck_dossiers(
    unresolved_limitations: list[dict[str, Any]],
    hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {h.get("paper_id"): h for h in hits}
    buckets: dict[str, list[dict[str, Any]]] = {}
    for lim in unresolved_limitations:
        label = _classify_bottleneck(lim.get("keyword"), lim.get("description"))
        buckets.setdefault(label, []).append(lim)
    dossiers = []
    for label, rows in sorted(buckets.items(), key=lambda x: len(x[1]), reverse=True)[:8]:
        papers = []
        seen: set[str] = set()
        for lim in rows:
            pid = lim.get("paper_id")
            if pid and pid not in seen:
                seen.add(pid)
                paper = by_id.get(pid) or {"paper_id": pid, "title": lim.get("title")}
                papers.append(_paper_ref(paper, f"limitation evidence: {lim.get('keyword') or label}"))
        dossiers.append(
            {
                "name": label,
                "status": "unresolved_or_partially_resolved",
                "evidence_count": len(rows),
                "evidence_quality": rows[0].get("evidence_quality") or "unknown",
                "why_it_matters": (
                    f"{label} recurs in the topic evidence. Treat as a hard constraint until section-level "
                    "resolution evidence proves it has been solved across branches."
                ),
                "evidence_papers": papers[:5],
                "sample_evidence": [
                    {
                        "paper_id": r.get("paper_id"),
                        "description": r.get("description"),
                        "keyword": r.get("keyword"),
                        "evidence_quality": r.get("evidence_quality"),
                    }
                    for r in rows[:4]
                ],
            }
        )
    return dossiers


def _build_validation_directions(
    topic: str,
    branch_splits: list[dict[str, Any]],
    bottlenecks: list[dict[str, Any]],
    future_growth: list[dict[str, Any]],
    rd_radar: dict[str, Any],
) -> list[dict[str, Any]]:
    if rd_radar.get("claim_cards"):
        return [
            {
                "name": item.get("title"),
                "claim_scope": item.get("claim_scope"),
                "evidence_strength": item.get("evidence_tier") or item.get("claim_card", {}).get("evidence_strength_level"),
                "why_worth_testing": item.get("plain_language"),
                "why_not_ready": None if item.get("eligible") else "Claim Card exists but high-confidence gates are not fully passed.",
                "evidence_papers": [],
                "source": "Step6/Step13 Claim Card",
            }
            for item in rd_radar.get("claim_cards", [])[:5]
        ]

    directions = []
    for idx, branch in enumerate(branch_splits[:5]):
        bottleneck = bottlenecks[idx % len(bottlenecks)] if bottlenecks else {}
        name = f"Validate {branch.get('name')} against {bottleneck.get('name') or branch.get('historical_bottleneck')}"
        directions.append(
            {
                "name": name,
                "claim_scope": "exploratory_candidate_pool",
                "evidence_strength": bottleneck.get("evidence_quality") or "weak_until_claim_card",
                "why_worth_testing": (
                    f"The topic evidence links the {branch.get('name')} branch to "
                    f"{bottleneck.get('name') or branch.get('historical_bottleneck')}. "
                    "This is a useful 6-18 month validation target, but it cannot enter Radar until Step13 produces a five-question Claim Card."
                ),
                "why_not_ready": "No complete Claim Card yet: missing root-constraint, historical failure, enabler, bottleneck evidence, or minimal experiment gates.",
                "minimal_validation_experiment": (
                    "Define one measurable system-level benchmark, reproduce the relevant branch driver paper, "
                    "then test whether the named bottleneck improves without degrading cost/manufacturability."
                ),
                "evidence_papers": (branch.get("driver_papers") or [])[:3] + (bottleneck.get("evidence_papers") or [])[:2],
                "source": "topic branch + limitation evidence",
            }
        )
    if not directions and future_growth:
        for edge in future_growth[:5]:
            directions.append(
                {
                    "name": f"Audit future candidate: {edge.get('source_paper_id')} -> {edge.get('target_paper_id')}",
                    "claim_scope": "gnn_candidate_only",
                    "evidence_strength": "calibrated_graph_only",
                    "why_worth_testing": "Step5b/GNN suggests a possible growth link; use it for candidate generation only.",
                    "why_not_ready": "Missing Step6 fusion and Step13 Claim Card.",
                    "minimal_validation_experiment": "Read both endpoint papers, map the shared bottleneck, then design a falsifiable experiment.",
                    "evidence_papers": [
                        _paper_ref(edge.get("source_paper") or {"paper_id": edge.get("source_paper_id")}, "future edge source"),
                        _paper_ref(edge.get("target_paper") or {"paper_id": edge.get("target_paper_id")}, "future edge target"),
                    ],
                    "source": "Step5b GNN candidate",
                }
            )
    return directions[:5]


def _top_terms_from_hits(hits: list[dict[str, Any]], limit: int = 10) -> list[str]:
    counter: Counter[str] = Counter()
    for hit in hits[:120]:
        text = " ".join(
            str(hit.get(k) or "")
            for k in ("title", "abstract", "cluster_label", "field", "subfield", "topic")
        ).lower()
        for term in re.findall(r"[a-z][a-z0-9-]{3,}", text):
            if term in TOPIC_STOPWORDS or term.isdigit():
                continue
            counter[term] += 1
    return [term for term, _ in counter.most_common(limit)]


def _clean_branch_label(label: Any, fallback: str) -> str:
    parts = [
        p.strip()
        for p in str(label or "").split(",")
        if p.strip()
    ]
    clean = [
        p
        for p in parts
        if p.lower() not in LABEL_STOPWORDS and len(p) >= 3
    ]
    return ", ".join(clean[:4]) or str(label or fallback)


def _extract_rep_ids(representatives: Any, max_n: int = 5) -> list[str]:
    reps = representatives
    if isinstance(reps, str):
        reps = _loads(reps, [])
    out: list[str] = []
    if isinstance(reps, list):
        for item in reps:
            if isinstance(item, dict):
                pid = item.get("paper_id")
            else:
                pid = item
            if pid:
                out.append(str(pid))
            if len(out) >= max_n:
                break
    return out


def _build_branch_dossiers(
    conn: sqlite3.Connection,
    cluster_distribution: list[dict[str, Any]],
    *,
    limit: int = 6,
) -> list[dict[str, Any]]:
    if not cluster_distribution:
        return []
    total = sum(int(c.get("n") or 0) for c in cluster_distribution) or 1
    selected = cluster_distribution[:limit]
    cluster_ids = [str(c.get("cluster_id")) for c in selected if c.get("cluster_id")]
    if not cluster_ids:
        return []
    ph = ",".join("?" for _ in cluster_ids)
    lineage_cols = _table_columns(conn, "branch_lineages")
    if lineage_cols:
        split_conf_expr = (
            "l.split_confidence"
            if "split_confidence" in lineage_cols
            else "l.strength"
            if "strength" in lineage_cols
            else "NULL"
        )
        split_evidence_expr = (
            "l.split_evidence_json"
            if "split_evidence_json" in lineage_cols
            else "l.why_json"
            if "why_json" in lineage_cols
            else "NULL"
        )
        parent_expr = "l.parent_branch_id" if "parent_branch_id" in lineage_cols else "NULL"
        split_year_expr = "l.split_year" if "split_year" in lineage_cols else "NULL"
        strength_expr = "l.strength" if "strength" in lineage_cols else "NULL"
        why_expr = "l.why_json" if "why_json" in lineage_cols else "NULL"
        future_expr = "l.future_json" if "future_json" in lineage_cols else "NULL"
        lineage_join = "LEFT JOIN branch_lineages l ON l.branch_id = c.branch_id"
    else:
        split_conf_expr = split_evidence_expr = parent_expr = "NULL"
        split_year_expr = strength_expr = why_expr = future_expr = "NULL"
        lineage_join = ""
    rows = conn.execute(
        f"""
        SELECT c.cluster_id, c.branch_id, c.label, c.n_nodes, c.year_start, c.year_end,
               c.top_terms_json, c.representative_papers_json, c.evidence_json,
               {parent_expr} AS parent_branch_id,
               {split_year_expr} AS split_year,
               {strength_expr} AS strength,
               {split_conf_expr} AS split_confidence,
               {split_evidence_expr} AS split_evidence_json,
               {why_expr} AS why_json,
               {future_expr} AS future_json
        FROM visual_clusters c
        {lineage_join}
        WHERE c.cluster_id IN ({ph})
        """,
        cluster_ids,
    ).fetchall()
    by_cluster = {str(r["cluster_id"]): dict(r) for r in rows}
    rep_ids: list[str] = []
    for row in rows:
        rep_ids.extend(_extract_rep_ids(row["representative_papers_json"], 3))
    reps = {p["paper_id"]: p for p in _hydrate_hits(conn, list(dict.fromkeys(rep_ids)), scores={})}

    dossiers: list[dict[str, Any]] = []
    for c in selected:
        cid = str(c.get("cluster_id"))
        row = by_cluster.get(cid, {})
        rep_papers = [
            reps.get(pid) or {"paper_id": pid}
            for pid in _extract_rep_ids(row.get("representative_papers_json"), 3)
        ]
        terms = _loads(row.get("top_terms_json"), [])
        if terms and isinstance(terms[0], dict):
            terms = [x.get("key") for x in terms if isinstance(x, dict)]
        split_evidence = _loads(row.get("split_evidence_json"), {})
        why = _loads(row.get("why_json"), {})
        future = _loads(row.get("future_json"), {})
        count = int(c.get("n") or 0)
        dossiers.append(
            {
                "cluster_id": cid,
                "branch_id": row.get("branch_id") or c.get("branch_id"),
                "label": _clean_branch_label(row.get("label"), cid),
                "topic_match_count": count,
                "topic_share": count / total,
                "global_paper_count": int(row.get("n_nodes") or 0),
                "year_range": [row.get("year_start"), row.get("year_end")],
                "parent_branch_id": row.get("parent_branch_id"),
                "split_year": row.get("split_year"),
                "split_confidence": row.get("split_confidence") if row.get("split_confidence") is not None else row.get("strength"),
                "split_evidence": split_evidence or why,
                "future_hint": future,
                "top_terms": [str(x) for x in (terms or [])[:8] if x],
                "representative_papers": rep_papers,
                "interpretation": (
                    f"This branch captures the topic's {row.get('label') or cid} neighborhood. "
                    "Use representative papers to inspect the branch; use split evidence to decide whether it is a real lineage split or just a layout cluster."
                ),
            }
        )
    return dossiers


def _build_bottleneck_lineage(
    principles: list[dict[str, Any]],
    history_events: list[dict[str, Any]],
    unresolved_limitations: list[dict[str, Any]],
) -> dict[str, Any]:
    event_by_principle: dict[str, list[dict[str, Any]]] = {}
    for event in history_events:
        event_by_principle.setdefault(str(event.get("principle_id")), []).append(event)
    limitation_counter: Counter[str] = Counter(
        str(x.get("keyword") or "limitation") for x in unresolved_limitations if x
    )
    constraints = []
    for p in principles[:5]:
        pid = str(p.get("principle_id") or "")
        keywords = _loads(p.get("top_keywords_json"), [])
        keyword_list = [
            str(x.get("key") if isinstance(x, dict) else x)
            for x in (keywords or [])[:6]
            if x
        ]
        constraints.append(
            {
                "principle_id": pid,
                "name": p.get("principle_name"),
                "root_cause": p.get("root_cause"),
                "risk_label": p.get("risk_label"),
                "bottleneck_score": p.get("bottleneck_score"),
                "unresolved_atoms": p.get("unresolved_atoms"),
                "resolved_atoms": p.get("resolved_atoms"),
                "current_backlog": p.get("current_backlog"),
                "peak_backlog_year": p.get("peak_backlog_year"),
                "top_keywords": keyword_list,
                "recent_events": event_by_principle.get(pid, [])[:8],
                "interpretation": (
                    "Root constraint lineage: opened/resolved backlog over time. "
                    "High backlog with weak section evidence remains exploratory."
                ),
            }
        )
    return {
        "summary": (
            "Bottleneck lineage links section-level limitations to root constraints and their historical backlog. "
            "It is the layer that prevents generic trend descriptions."
        ),
        "top_unresolved_keywords": [
            {"keyword": k, "count": v} for k, v in limitation_counter.most_common(8)
        ],
        "constraints": constraints,
        "evidence_quality": "section_level_when_available_else_weak",
    }


def _build_rd_radar(
    future_directions: list[dict[str, Any]],
    future_growth: list[dict[str, Any]],
) -> dict[str, Any]:
    claim_cards: list[dict[str, Any]] = []
    for d in future_directions[:12]:
        card = d.get("claim_card") or {}
        claim_cards.append(
            {
                "kind": "claim_card",
                "title": d.get("direction_name") or d.get("direction_id"),
                "priority": d.get("confidence"),
                "technical_probability": d.get("confidence"),
                "claim_scope": d.get("claim_scope"),
                "evidence_tier": d.get("evidence_tier"),
                "eligible": bool(card.get("high_confidence_eligible")),
                "claim_card": card,
                "plain_language": "Evidence-fused direction with Step6/Step13 support.",
            }
        )
    candidate_pool: list[dict[str, Any]] = []
    for e in future_growth[:20]:
        src = (e.get("source_paper") or {}).get("title") or e.get("source_paper_id")
        dst = (e.get("target_paper") or {}).get("title") or e.get("target_paper_id")
        conf = float(e.get("confidence") or e.get("weight") or 0.0)
        candidate_pool.append(
            {
                "kind": "candidate_edge",
                "title": f"{src} -> {dst}",
                "priority": round(conf * 0.55, 4),
                "technical_probability": conf,
                "commercial_relevance": None,
                "validation_cost": None,
                "claim_scope": "exploratory_candidate_pool",
                "eligible": False,
                "source_paper": e.get("source_paper"),
                "target_paper": e.get("target_paper"),
                "evidence_papers": [
                    _paper_ref(e.get("source_paper") or {"paper_id": e.get("source_paper_id")}, "GNN candidate source"),
                    _paper_ref(e.get("target_paper") or {"paper_id": e.get("target_paper_id")}, "GNN candidate target"),
                ],
                "missing_gates": [
                    "Step6 fusion evidence",
                    "Step13 five-question Claim Card",
                    "section-level bottleneck evidence",
                    "commercial relevance",
                    "minimal validation experiment",
                ],
                "plain_language": (
                    "This is a GNN/VGAE future-growth candidate. It is useful for discovery, "
                    "but not yet a decision-grade R&D direction."
                ),
            }
        )
    items = claim_cards or [
        {
            "kind": "radar_empty_state",
            "title": "No decision-grade Claim Cards yet",
            "claim_scope": "candidate_only",
            "eligible": False,
            "plain_language": (
                "Radar is intentionally empty because this topic currently has future candidates but no "
                "Step6/Step13 five-question Claim Card. Review the candidate pool, then rerun fusion and "
                "first-principles history after section evidence is complete."
            ),
        }
    ]
    return {
        "summary": (
            "R&D Radar only promotes decision-grade Claim Cards. GNN future edges stay in the candidate pool "
            "until Step6 fusion and Step13 evidence gates produce a complete five-question card."
        ),
        "items": items,
        "claim_cards": claim_cards,
        "candidate_pool": candidate_pool,
        "claim_cards_ready": bool(claim_cards),
    }


def _build_topic_dossier(
    *,
    topic: str,
    hits: list[dict[str, Any]],
    turning_hits: list[dict[str, Any]],
    branch_dossiers: list[dict[str, Any]],
    bottleneck_lineage: dict[str, Any],
    unresolved_limitations: list[dict[str, Any]],
    rd_radar: dict[str, Any],
    main_path_edges: list[dict[str, Any]],
    future_growth: list[dict[str, Any]],
    value_model: dict[str, Any],
) -> dict[str, Any]:
    years = [int(h.get("year")) for h in hits if h.get("year")]
    recent = sum(1 for y in years if y >= 2023)
    section_ready = sum(
        1 for h in hits
        if (h.get("content_availability") or {}).get("has_primary_evidence_sections")
    )
    limitation_ready = sum(
        1 for h in hits
        if (h.get("content_availability") or {}).get("has_limitation_atoms")
    )
    branch_labels = [b.get("label") for b in branch_dossiers[:4] if b.get("label")]
    terms = _top_terms_from_hits(hits, 8)
    bottlenecks = [
        x.get("keyword")
        for x in bottleneck_lineage.get("top_unresolved_keywords", [])[:5]
        if x.get("keyword")
    ]
    branch_splits = _build_topic_branch_splits(topic, hits, turning_hits)
    bottleneck_dossiers = _build_bottleneck_dossiers(unresolved_limitations, hits)
    validation_directions = _build_validation_directions(
        topic,
        branch_splits,
        bottleneck_dossiers,
        future_growth,
        rd_radar,
    )
    phase = (
        "frontier expansion"
        if years and recent / max(1, len(years)) >= 0.35
        else "mature branch with active refinements"
    )
    if "metalens" in topic.lower() or "meta-lens" in topic.lower():
        phase = "system-level manufacturable imaging transition"
    claim_status = (
        "decision-grade Claim Cards available"
        if rd_radar.get("claim_cards_ready")
        else "candidate-only until Step6/Step13 rerun"
    )
    if branch_splits:
        branch_text = ", ".join(x["name"] for x in branch_splits[:5])
    else:
        branch_text = ", ".join(branch_labels[:3]) or "several evidence branches"
    bottleneck_text = ", ".join(x["name"] for x in bottleneck_dossiers[:5]) or ", ".join(bottlenecks[:5])
    return {
        "headline": (
            f"{topic} is best read as a {phase} topic organized around {branch_text}."
        ),
        "value_claim": (
            f"The decision question is not whether {topic} exists, but whether it can keep verified performance "
            f"under {bottleneck_text or 'the current hard constraints'}."
        ),
        "decision_summary": (
            "Start with the branch splits and hard bottlenecks below; every claim links back to papers or evidence objects. "
            f"Current radar status: {claim_status}."
        ),
        "stage": phase,
        "branch_splits": branch_splits,
        "hard_bottlenecks": bottleneck_dossiers,
        "validation_directions": validation_directions,
        "solved_vs_open": {
            "partially_addressed": [
                b["name"]
                for b in bottleneck_dossiers
                if any(
                    term in " ".join(str(p.get("title") or "").lower() for p in b.get("evidence_papers", []))
                    for term in ("mitigat", "achromatic", "enabling", "improve", "hybrid", "compensation")
                )
            ],
            "still_open": [b["name"] for b in bottleneck_dossiers[:6]],
            "rule": (
                "A bottleneck is only treated as partially addressed when evidence titles/sections include solution language; "
                "it remains open until section-level resolution evidence is present."
            ),
        },
        "branch_labels": branch_labels,
        "emerging_terms": terms,
        "core_bottlenecks": bottlenecks,
        "evidence_strength": {
            "related_papers": len(hits),
            "main_path_context_edges": len(main_path_edges),
            "future_candidate_edges": len(future_growth),
            "primary_section_coverage_in_results": section_ready / max(1, len(hits)),
            "limitation_atom_coverage_in_results": limitation_ready / max(1, len(hits)),
            "fusion_status": value_model.get("fusion_status"),
        },
        "next_actions": [
            "Inspect top Branch Dossiers to verify whether branch labels match the topic intent.",
            "Read Key Turning Papers with access links and evidence sections before trusting a lineage claim.",
            "Treat GNN/VGAE future edges as discovery candidates until a Step13 Claim Card passes all five questions.",
        ],
        "warning": (
            "This dossier is evidence-linked, not a final scientific claim. Low section coverage or missing Claim Cards "
            "must keep the claim_scope exploratory."
        ),
    }


def _build_evidence_map(
    *,
    main_path_edges: list[dict[str, Any]],
    turning_hits: list[dict[str, Any]],
    future_growth: list[dict[str, Any]],
    branch_dossiers: list[dict[str, Any]],
    value_model: dict[str, Any],
) -> dict[str, Any]:
    return {
        "summary": "Evidence Map is for auditing the dossier, not for making users infer value from raw nodes.",
        "main_path": {
            "meaning": value_model.get("layers", {}).get("main_path", {}).get("relationship"),
            "edges": main_path_edges[:80],
            "key_turning_papers": turning_hits[:50],
        },
        "future_candidates": {
            "meaning": value_model.get("layers", {}).get("future", {}).get("relationship"),
            "edges": future_growth[:80],
        },
        "branches": [
            {
                "cluster_id": b.get("cluster_id"),
                "branch_id": b.get("branch_id"),
                "label": b.get("label"),
                "topic_share": b.get("topic_share"),
                "split_confidence": b.get("split_confidence"),
            }
            for b in branch_dossiers[:12]
        ],
        "recommended_layer_combinations": [
            {
                "layers": combo.get("layers"),
                "label": combo.get("label"),
                "question": combo.get("question"),
                "use": combo.get("decision_use"),
                "relationship": combo.get("relationship"),
                "display": combo.get("display"),
            }
            for combo in value_model.get("layer_combinations", [])
        ],
    }


def get_topic_lens(
    *,
    topic: str,
    top_k: int = 50,
    corpus_id: str | None = None,
) -> dict:
    start = time.perf_counter()
    topic_text = (topic or "").strip()
    if not topic_text:
        return {
            "schema_version": SCHEMA_VERSION,
            "ready": False,
            "topic": topic,
            "message": "topic is required",
            "elapsed_ms": _elapsed_ms(start),
        }

    with _connect() as conn:
        ready, missing = _visual_ready(conn)
        if not ready:
            return {
                "schema_version": SCHEMA_VERSION,
                "ready": False,
                "missing_tables": missing,
                "topic": topic_text,
                "elapsed_ms": _elapsed_ms(start),
            }

        value_model = _visual_value_model(conn)
        seed_limit = max(50, min(int(top_k) * 8, 1500))
        seed_ids, seed_scores = _candidate_ids_from_fts(conn, topic_text, seed_limit)
        all_hits = _hydrate_hits(conn, seed_ids, scores=seed_scores)
        if corpus_id:
            all_hits = [h for h in all_hits if str(h.get("corpus_id") or "") == str(corpus_id)]
        context_hits = all_hits[:500]
        hits = all_hits[: max(10, min(int(top_k), 200))]
        if not hits:
            return {
                "schema_version": SCHEMA_VERSION,
                "ready": True,
                "topic": topic_text,
                "related_papers": [],
                "total_related": 0,
                "value_model": value_model,
                "elapsed_ms": _elapsed_ms(start),
            }

        context_seed_ids = [h["paper_id"] for h in context_hits] or [h["paper_id"] for h in hits]
        context_placeholders = ",".join("?" for _ in context_seed_ids)

        cluster_rows = conn.execute(
            f"""
            SELECT cluster_id, branch_id, COUNT(*) AS n
            FROM visual_nodes
            WHERE paper_id IN ({context_placeholders})
            GROUP BY cluster_id, branch_id
            ORDER BY n DESC
            """,
            context_seed_ids,
        ).fetchall()
        cluster_distribution = [dict(r) for r in cluster_rows]
        top_cluster_ids = [
            str(r["cluster_id"])
            for r in cluster_rows[:8]
            if r["cluster_id"] is not None
        ]
        top_branch_ids = [
            str(r["branch_id"])
            for r in cluster_rows[:8]
            if r["branch_id"] is not None
        ]
        branch_dossiers = _build_branch_dossiers(conn, cluster_distribution)
        scope_clauses: list[str] = []
        scope_params: list[Any] = []
        if top_cluster_ids:
            ph = ",".join("?" for _ in top_cluster_ids)
            scope_clauses.append(f"(s.cluster_id IN ({ph}) OR t.cluster_id IN ({ph}))")
            scope_params.extend(top_cluster_ids)
            scope_params.extend(top_cluster_ids)
        if top_branch_ids:
            ph = ",".join("?" for _ in top_branch_ids)
            scope_clauses.append(f"(s.branch_id IN ({ph}) OR t.branch_id IN ({ph}))")
            scope_params.extend(top_branch_ids)
            scope_params.extend(top_branch_ids)
        context_scope = "direct_papers"
        if scope_clauses:
            context_scope = "topic_cluster_branch_context"

        main_rows = conn.execute(
            f"""
            SELECT edge_id, source_paper_id, target_paper_id, weight, confidence, evidence_json,
                   'direct_paper_match' AS relationship_scope
            FROM visual_edges
            WHERE layer = 'citation' AND is_main_path = 1
              AND (source_paper_id IN ({context_placeholders}) OR target_paper_id IN ({context_placeholders}))
            ORDER BY COALESCE(weight, 0) DESC
            LIMIT ?
            """,
            (*context_seed_ids, *context_seed_ids, max(50, int(top_k) * 4)),
        ).fetchall()
        if scope_clauses:
            cluster_main_rows = conn.execute(
                f"""
                SELECT e.edge_id, e.source_paper_id, e.target_paper_id,
                       e.weight, e.confidence, e.evidence_json,
                       'cluster_branch_context' AS relationship_scope
                FROM visual_edges e
                JOIN visual_nodes s ON s.paper_id = e.source_paper_id
                JOIN visual_nodes t ON t.paper_id = e.target_paper_id
                WHERE e.layer = 'citation' AND e.is_main_path = 1
                  AND ({' OR '.join(scope_clauses)})
                ORDER BY
                  CASE
                    WHEN e.source_paper_id IN ({context_placeholders})
                      OR e.target_paper_id IN ({context_placeholders})
                    THEN 1 ELSE 0 END DESC,
                  COALESCE(e.weight, 0) DESC
                LIMIT ?
                """,
                (*scope_params, *context_seed_ids, *context_seed_ids, max(80, int(top_k) * 6)),
            ).fetchall()
            rows_by_edge = {str(r["edge_id"]): r for r in main_rows}
            for row in cluster_main_rows:
                rows_by_edge.setdefault(str(row["edge_id"]), row)
            main_rows = list(rows_by_edge.values())[: max(80, int(top_k) * 6)]
        main_path_edges = []
        turning_ids: list[str] = []
        turning_scores: Counter[str] = Counter()
        turning_reasons: dict[str, dict[str, Any]] = {}
        for row in main_rows:
            item = dict(row)
            item["evidence"] = _loads(item.pop("evidence_json", None), {})
            item["evidence"]["relationship_scope"] = item.pop("relationship_scope", "direct_paper_match")
            main_path_edges.append(item)
            turning_ids.append(item["source_paper_id"])
            turning_ids.append(item["target_paper_id"])
            edge_weight = float(item.get("weight") or 0.0)
            for pid, role in (
                (item["source_paper_id"], "source/older enabling paper"),
                (item["target_paper_id"], "target/newer downstream paper"),
            ):
                turning_scores[pid] += edge_weight
                turning_reasons[pid] = {
                    "why": "This paper lies on the topic's high-throughput main-path context.",
                    "edge_id": item["edge_id"],
                    "role": role,
                    "relationship_scope": item["evidence"].get("relationship_scope"),
                    "main_path_weight": item.get("weight"),
                }
        turning_ids = list(dict.fromkeys(turning_ids))
        turning_ids = sorted(
            turning_ids,
            key=lambda pid: float(turning_scores.get(pid, 0.0)),
            reverse=True,
        )
        turning_hits = _hydrate_hits(
            conn,
            turning_ids[: max(20, int(top_k))],
            scores={pid: float(turning_scores.get(pid, 0.0)) for pid in turning_ids},
            reasons=turning_reasons,
        )

        future_rows = conn.execute(
            f"""
            SELECT edge_id, source_paper_id, target_paper_id, weight, confidence, evidence_json,
                   'direct_paper_match' AS relationship_scope
            FROM visual_edges
            WHERE layer = 'future'
              AND (source_paper_id IN ({context_placeholders}) OR target_paper_id IN ({context_placeholders}))
            ORDER BY COALESCE(confidence, 0) DESC, COALESCE(weight, 0) DESC
            LIMIT ?
            """,
            (*context_seed_ids, *context_seed_ids, max(40, int(top_k) * 3)),
        ).fetchall()
        if scope_clauses:
            cluster_future_rows = conn.execute(
                f"""
                SELECT e.edge_id, e.source_paper_id, e.target_paper_id,
                       e.weight, e.confidence, e.evidence_json,
                       'cluster_branch_context' AS relationship_scope
                FROM visual_edges e
                JOIN visual_nodes s ON s.paper_id = e.source_paper_id
                JOIN visual_nodes t ON t.paper_id = e.target_paper_id
                WHERE e.layer = 'future'
                  AND ({' OR '.join(scope_clauses)})
                ORDER BY
                  CASE
                    WHEN e.source_paper_id IN ({context_placeholders})
                      OR e.target_paper_id IN ({context_placeholders})
                    THEN 1 ELSE 0 END DESC,
                  COALESCE(e.confidence, 0) DESC,
                  COALESCE(e.weight, 0) DESC
                LIMIT ?
                """,
                (*scope_params, *context_seed_ids, *context_seed_ids, max(40, int(top_k) * 4)),
            ).fetchall()
            rows_by_edge = {str(r["edge_id"]): r for r in future_rows}
            for row in cluster_future_rows:
                rows_by_edge.setdefault(str(row["edge_id"]), row)
            future_rows = list(rows_by_edge.values())[: max(40, int(top_k) * 4)]
        future_growth = []
        for row in future_rows:
            item = dict(row)
            item["evidence"] = _loads(item.pop("evidence_json", None), {})
            item["evidence"]["relationship_scope"] = item.pop("relationship_scope", "direct_paper_match")
            future_growth.append(item)
        edge_paper_ids = list(
            dict.fromkeys(
                [
                    pid
                    for edge in [*main_path_edges[:80], *future_growth[:80]]
                    for pid in (edge.get("source_paper_id"), edge.get("target_paper_id"))
                    if pid
                ]
            )
        )
        edge_paper_map = {
            p["paper_id"]: p
            for p in _hydrate_hits(conn, edge_paper_ids, scores={})
        }
        for edge in main_path_edges:
            edge["source_paper"] = edge_paper_map.get(edge.get("source_paper_id"))
            edge["target_paper"] = edge_paper_map.get(edge.get("target_paper_id"))
            edge["plain_language"] = (
                "Main-path context: the source paper is an upstream enabling/anchor work and "
                "the target paper is a downstream paper in the same topic branch context."
            )
        for edge in future_growth:
            edge["source_paper"] = edge_paper_map.get(edge.get("source_paper_id"))
            edge["target_paper"] = edge_paper_map.get(edge.get("target_paper_id"))
            edge["plain_language"] = (
                "Future-growth candidate: the model predicts that the source-side idea/bottleneck "
                "may connect to the target-side direction; treat as calibrated exploratory evidence "
                "until Step6/Step13 Claim Cards are materialized."
            )

        unresolved_limitations = []
        for h in hits:
            lims = h.get("limitations") or []
            if not isinstance(lims, list):
                continue
            for lim in lims[:3]:
                unresolved_limitations.append(
                    {
                        "paper_id": h["paper_id"],
                        "title": h.get("title"),
                        "branch_id": h.get("branch_id"),
                        "cluster_id": h.get("cluster_id"),
                        "keyword": (lim or {}).get("keyword") if isinstance(lim, dict) else None,
                        "description": (lim or {}).get("description") if isinstance(lim, dict) else str(lim),
                        "severity": (lim or {}).get("severity") if isinstance(lim, dict) else None,
                        "evidence_quality": (lim or {}).get("evidence_quality") if isinstance(lim, dict) else None,
                    }
                )
        unresolved_limitations = unresolved_limitations[: max(20, int(top_k))]

        future_directions = []
        if _table_exists(conn, "future_directions"):
            has_claim_cards = _table_exists(conn, "direction_claim_cards")
            claim_join = "LEFT JOIN direction_claim_cards c ON c.direction_id = f.direction_id" if has_claim_cards else ""
            claim_cols = (
                """
                , c.claim_card_id,
                  c.root_constraint_json,
                  c.attempts_last_10y_json,
                  c.enabling_conditions_json,
                  c.unresolved_bottleneck_json,
                  c.minimal_validation_experiment_json,
                  c.evidence_strength_level,
                  c.five_question_complete,
                  c.high_confidence_eligible,
                  c.quality_gate_json
                """
                if has_claim_cards else
                """
                , NULL AS claim_card_id,
                  '{}' AS root_constraint_json,
                  '[]' AS attempts_last_10y_json,
                  '{}' AS enabling_conditions_json,
                  '{}' AS unresolved_bottleneck_json,
                  '{}' AS minimal_validation_experiment_json,
                  'unknown' AS evidence_strength_level,
                  0 AS five_question_complete,
                  0 AS high_confidence_eligible,
                  '{}' AS quality_gate_json
                """
            )
            rows = conn.execute(
                f"""
                SELECT f.direction_id, f.direction_name, f.confidence, f.evidence_tier, f.claim_scope,
                       f.main_path_evidence, f.vgae_evidence, f.limitation_evidence, f.paper_ids_json
                       {claim_cols}
                FROM future_directions f
                {claim_join}
                ORDER BY COALESCE(confidence, 0) DESC
                LIMIT 200
                """
            ).fetchall()
            topic_tokens = _token_set(topic_text)
            for row in rows:
                item = dict(row)
                text = " ".join(
                    str(item.get(k) or "")
                    for k in ("direction_name", "main_path_evidence", "vgae_evidence", "limitation_evidence")
                ).lower()
                score = 0
                if topic_tokens:
                    score += sum(1 for t in topic_tokens if t in text)
                paper_ids = _loads(item.get("paper_ids_json"), [])
                if isinstance(paper_ids, list):
                    score += sum(1 for pid in paper_ids if pid in context_seed_ids)
                if score > 0:
                    item["_topic_score"] = score
                    item["claim_card"] = {
                        "claim_card_id": item.pop("claim_card_id", None),
                        "root_constraint": _loads(item.pop("root_constraint_json", "{}"), {}),
                        "attempts_last_10y": _loads(item.pop("attempts_last_10y_json", "[]"), []),
                        "enabling_conditions": _loads(item.pop("enabling_conditions_json", "{}"), {}),
                        "unresolved_bottleneck": _loads(item.pop("unresolved_bottleneck_json", "{}"), {}),
                        "minimal_validation_experiment": _loads(item.pop("minimal_validation_experiment_json", "{}"), {}),
                        "evidence_strength_level": item.pop("evidence_strength_level", "unknown"),
                        "five_question_complete": bool(item.pop("five_question_complete", 0)),
                        "high_confidence_eligible": bool(item.pop("high_confidence_eligible", 0)),
                        "quality_gate": _loads(item.pop("quality_gate_json", "{}"), {}),
                    }
                    future_directions.append(item)
            future_directions.sort(
                key=lambda x: (x.get("_topic_score", 0), float(x.get("confidence") or 0.0)),
                reverse=True,
            )
            future_directions = future_directions[:20]
            for item in future_directions:
                item.pop("_topic_score", None)

        principles = []
        history_events = []
        if _table_exists(conn, "first_principles_principles"):
            rows = conn.execute(
                """
                SELECT principle_id, principle_name, root_cause, bottleneck_score,
                       unresolved_atoms, resolved_atoms, emergence_year, peak_backlog_year,
                       current_backlog, top_keywords_json, top_branches_json,
                       future_alignment_json, direction_tier_json, risk_label, notes_json
                FROM first_principles_principles
                ORDER BY bottleneck_score DESC
                """
            ).fetchall()
            topic_tokens = _token_set(
                " ".join(
                    [topic_text]
                    + [
                        str(x.get("keyword") or "")
                        for x in unresolved_limitations[:20]
                        if isinstance(x, dict)
                    ]
                    + [
                        str(h.get("cluster_label") or "")
                        for h in hits[:20]
                    ]
                )
            )
            scored = []
            for row in rows:
                item = dict(row)
                keywords = _loads(item.get("top_keywords_json"), [])
                kw_text = " ".join(
                    str(x.get("key") if isinstance(x, dict) else x) for x in (keywords or [])
                ).lower()
                score = sum(1 for t in topic_tokens if t in kw_text)
                if score > 0:
                    scored.append((score, item))
            scored.sort(key=lambda x: (x[0], float(x[1].get("bottleneck_score") or 0.0)), reverse=True)
            principles = [x[1] for x in scored[:5]]

        if _table_exists(conn, "first_principles_history_events") and principles:
            pids = [p.get("principle_id") for p in principles if p.get("principle_id")]
            ph = ",".join("?" for _ in pids)
            history_events = [
                dict(r)
                for r in conn.execute(
                    f"""
                    SELECT principle_id, event_year, opened_atoms, resolved_atoms,
                           backlog_score, top_keywords_json
                    FROM first_principles_history_events
                    WHERE principle_id IN ({ph})
                    ORDER BY event_year DESC
                    LIMIT 120
                    """,
                    pids,
                ).fetchall()
            ]

    cluster_hint = ", ".join(
        f"{c.get('cluster_id')}({c.get('n')})" for c in cluster_distribution[:4]
    ) or "N/A"
    main_hint = "; ".join(
        f"{p.get('title') or p.get('paper_id')} ({p.get('year') or '?'}, {((p.get('reason') or {}).get('role') or 'main path')})"
        for p in turning_hits[:5]
    ) or "N/A"
    lim_hint = ", ".join(
        x.get("keyword") or "limitation"
        for x in unresolved_limitations[:5]
    ) or "N/A"
    growth_hint = "; ".join(
        "{src} -> {dst} (conf={conf:.0%}, {scope})".format(
            src=(x.get("source_paper") or {}).get("title") or x.get("source_paper_id"),
            dst=(x.get("target_paper") or {}).get("title") or x.get("target_paper_id"),
            conf=float(x.get("confidence") or x.get("weight") or 0),
            scope=(x.get("evidence") or {}).get("relationship_scope", "graph"),
        )
        for x in future_growth[:5]
    ) or "N/A"
    top_claim_card = None
    for d in future_directions:
        cc = d.get("claim_card")
        if isinstance(cc, dict) and cc.get("five_question_complete"):
            top_claim_card = cc
            break
    if top_claim_card is None:
        for d in future_directions:
            cc = d.get("claim_card")
            if isinstance(cc, dict):
                top_claim_card = cc
                break

    if top_claim_card:
        root = top_claim_card.get("root_constraint") or {}
        attempts = top_claim_card.get("attempts_last_10y") or []
        enabling = top_claim_card.get("enabling_conditions") or {}
        unresolved = top_claim_card.get("unresolved_bottleneck") or {}
        experiment = top_claim_card.get("minimal_validation_experiment") or {}
        attempt_hint = ", ".join(
            f"{a.get('year')}:{(a.get('keyword') or 'attempt')}"
            for a in attempts[:4]
            if isinstance(a, dict)
        ) or "N/A"
        unresolved_items = unresolved.get("items") if isinstance(unresolved, dict) else []
        unresolved_hint = ", ".join(
            (x.get("keyword") or "limitation")
            for x in (unresolved_items or [])[:4]
            if isinstance(x, dict)
        ) or lim_hint
        first_principles_five_questions = [
            {
                "question": "Q1: 根约束是什么（物理/工程/数据/成本）？",
                "answer": f"{root.get('type', 'unknown')}: {root.get('constraint', 'N/A')}",
            },
            {
                "question": "Q2: 过去10年怎么尝试、为什么失败？",
                "answer": attempt_hint,
            },
            {
                "question": "Q3: 这次新增了什么使能条件？",
                "answer": ", ".join(enabling.get("new_enablers") or []) or "N/A",
            },
            {
                "question": "Q4: 哪个 bottleneck 仍未解，证据强度几级？",
                "answer": f"{unresolved_hint}; evidence_strength={top_claim_card.get('evidence_strength_level', 'unknown')}",
            },
            {
                "question": "Q5: 下一步最小验证实验是什么？",
                "answer": (
                    f"{experiment.get('experiment', 'N/A')} "
                    f"(cost={experiment.get('cost_level', 'N/A')}, "
                    f"cycle_weeks={experiment.get('cycle_weeks', 'N/A')})"
                ),
            },
        ]
    else:
        first_principles_five_questions = [
            {
                "question": "Q1: 这个 topic 当前主要长成了哪些分支结构？",
                "answer": f"主要集中在这些 cluster/branch：{cluster_hint}。",
            },
            {
                "question": "Q2: 这些分支背后的硬约束/第一性原理是什么？",
                "answer": "; ".join(
                    f"{p.get('principle_name')}({p.get('risk_label')})"
                    for p in principles[:3]
                ) or "当前还没有足够第一性原理证据匹配到该 topic。",
            },
            {
                "question": "Q3: 历史上为什么会分叉成现在这样？",
                "answer": f"topic 关联主路径/关键转折论文主要包括：{main_hint}。",
            },
            {
                "question": "Q4: 目前最未解决的卡点是什么？",
                "answer": f"未解决 limitation 关键词样本：{lim_hint}。",
            },
            {
                "question": "Q5: 未来最可能往哪长，下一步该怎么证伪？",
                "answer": (
                    f"候选未来生长边样本：{growth_hint}。应优先针对高频 limitation 关键词做可证伪实验设计，"
                    "并用后续季度回测验证预测边是否成真。"
                ),
            },
        ]

    bottleneck_lineage = _build_bottleneck_lineage(
        principles,
        history_events,
        unresolved_limitations,
    )
    rd_radar = _build_rd_radar(future_directions, future_growth)
    topic_dossier = _build_topic_dossier(
        topic=topic_text,
        hits=hits,
        turning_hits=turning_hits,
        branch_dossiers=branch_dossiers,
        bottleneck_lineage=bottleneck_lineage,
        unresolved_limitations=unresolved_limitations,
        rd_radar=rd_radar,
        main_path_edges=main_path_edges,
        future_growth=future_growth,
        value_model=value_model,
    )
    evidence_map = _build_evidence_map(
        main_path_edges=main_path_edges,
        turning_hits=turning_hits,
        future_growth=future_growth,
        branch_dossiers=branch_dossiers,
        value_model=value_model,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "ready": True,
        "topic": topic_text,
        "corpus_id": corpus_id,
        "topic_dossier": topic_dossier,
        "branch_dossiers": branch_dossiers,
        "bottleneck_lineage": bottleneck_lineage,
        "rd_radar": rd_radar,
        "evidence_map": evidence_map,
        "related_papers": hits[: max(10, min(int(top_k), 200))],
        "total_related": len(hits),
        "context": {
            "seed_matches": len(all_hits),
            "context_papers": len(context_seed_ids),
            "scope": context_scope,
            "top_cluster_ids": top_cluster_ids,
            "top_branch_ids": top_branch_ids,
            "note": (
                "Topic Lens expands from exact paper matches into dominant clusters/branches "
                "so mainstream directions can recover main-path and future-growth context."
            ),
        },
        "cluster_distribution": cluster_distribution,
        "history_main_path": {
            "edges": main_path_edges,
            "key_turning_papers": turning_hits[: max(10, min(int(top_k), 80))],
        },
        "unresolved_limitations": unresolved_limitations,
        "future_growth": {
            "predicted_edges": future_growth,
            "future_directions": future_directions,
        },
        "first_principles": {
            "principles": principles,
            "history_events": history_events,
            "five_questions": first_principles_five_questions,
        },
        "value_model": value_model,
        "elapsed_ms": _elapsed_ms(start),
    }


def get_visual_graph_status() -> dict:
    with _connect() as conn:
        ready, missing = _visual_ready(conn)
        counts: dict[str, int] = {}
        for table in (
            "visual_nodes",
            "visual_edges",
            "visual_clusters",
            "branch_lineages",
            "visual_tiles",
            "visual_story_steps",
            "visual_paper_details",
            "visual_recommendations",
            "visual_search_fts",
        ):
            if _table_exists(conn, table):
                try:
                    counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                except sqlite3.OperationalError:
                    counts[table] = 0
            else:
                counts[table] = 0
    return {
        "schema_version": SCHEMA_VERSION,
        "ready": ready,
        "missing_tables": missing,
        "counts": counts,
        "db_path": str(_db_v14_path()),
    }


def get_visual_tiles(
    *,
    lod_level: int = 0,
    cluster_id: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 200,
) -> dict:
    start = time.perf_counter()
    with _connect() as conn:
        ready, missing = _visual_ready(conn)
        if not ready or not _table_exists(conn, "visual_tiles"):
            return {
                "schema_version": SCHEMA_VERSION,
                "ready": False,
                "missing_tables": missing,
                "tiles": [],
                "elapsed_ms": _elapsed_ms(start),
            }
        clauses = ["lod_level = ?"]
        params: list[Any] = [int(lod_level)]
        if cluster_id:
            clauses.append("cluster_id = ?")
            params.append(cluster_id)
        if year_from is not None:
            clauses.append("(year_end IS NULL OR year_end >= ?)")
            params.append(int(year_from))
        if year_to is not None:
            clauses.append("(year_start IS NULL OR year_start <= ?)")
            params.append(int(year_to))
        params.append(max(1, min(int(limit), 2000)))
        rows = conn.execute(
            f"""
            SELECT tile_id, lod_level, cluster_id, year_start, year_end,
                   bounds_json, node_count, edge_count, payload_json
            FROM visual_tiles
            WHERE {' AND '.join(clauses)}
            ORDER BY node_count DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    tiles = []
    for row in rows:
        item = dict(row)
        item["bounds"] = _loads(item.pop("bounds_json", None), {})
        item["payload"] = _loads(item.pop("payload_json", None), {})
        tiles.append(item)
    return {
        "schema_version": SCHEMA_VERSION,
        "ready": True,
        "tiles": tiles,
        "total_matches": len(tiles),
        "elapsed_ms": _elapsed_ms(start),
    }


def get_visual_paper_detail(paper_id: str, *, edge_limit: int = 80) -> dict:
    start = time.perf_counter()
    with _connect() as conn:
        ready, missing = _visual_ready(conn)
        if not ready:
            return {
                "schema_version": SCHEMA_VERSION,
                "ready": False,
                "missing_tables": missing,
                "paper_id": paper_id,
                "elapsed_ms": _elapsed_ms(start),
            }
        hits = _hydrate_hits(conn, [paper_id], scores={paper_id: 1.0})
        if not hits:
            return {
                "schema_version": SCHEMA_VERSION,
                "ready": True,
                "paper_id": paper_id,
                "status": "not_found",
                "elapsed_ms": _elapsed_ms(start),
            }
        rows = conn.execute(
            """
            SELECT edge_id, source_paper_id, target_paper_id, edge_type, layer,
                   weight, confidence, is_directed, is_main_path, lod_min,
                   style_json, evidence_json
            FROM visual_edges
            WHERE source_paper_id = ? OR target_paper_id = ?
            ORDER BY is_main_path DESC, lod_min ASC, COALESCE(weight, 0) DESC
            LIMIT ?
            """,
            (paper_id, paper_id, max(1, min(int(edge_limit), 500))),
        ).fetchall()
    edges = []
    layer_counts: Counter[str] = Counter()
    main_weight = 0.0
    future_weight = 0.0
    for row in rows:
        item = dict(row)
        item["style"] = _loads(item.pop("style_json", None), {})
        item["evidence"] = _loads(item.pop("evidence_json", None), {})
        layer_key = "main_path" if item.get("is_main_path") else str(item.get("layer") or item.get("edge_type") or "edge")
        layer_counts[layer_key] += 1
        if item.get("is_main_path"):
            main_weight += float(item.get("weight") or 0.0)
        if item.get("layer") == "future" or item.get("edge_type") == "future_growth":
            future_weight += float(item.get("confidence") or item.get("weight") or 0.0)
        edges.append(item)
    paper = hits[0]
    visual_role = (paper.get("visual") or {}).get("role") or paper.get("visual_role") or "paper"
    why_parts = []
    if layer_counts.get("main_path"):
        why_parts.append(f"main-path node: {layer_counts['main_path']} loaded trunk edges, cumulative weight {main_weight:.2f}")
    if layer_counts.get("future"):
        why_parts.append(f"future anchor/candidate endpoint: {layer_counts['future']} future edges, cumulative confidence {future_weight:.2f}")
    if visual_role == "limitation_bottleneck" or (paper.get("limitations") or []):
        why_parts.append("bottleneck evidence paper: local limitation atoms are available or the visual role marks it as a bottleneck")
    if not why_parts:
        why_parts.append("related paper selected from Topic Lens/search/graph neighborhood")
    paper["paper_role"] = {
        "role": visual_role,
        "why_selected": why_parts,
        "edge_counts_by_layer": dict(layer_counts),
        "branch_id": paper.get("branch_id"),
        "cluster_id": paper.get("cluster_id"),
        "evidence_gap": (
            "section-level evidence available"
            if (paper.get("content_availability") or {}).get("has_primary_evidence_sections")
            else "no local section evidence yet; use abstract/metadata only for weak evidence"
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "ready": True,
        "paper": paper,
        "edges": edges,
        "elapsed_ms": _elapsed_ms(start),
    }


def get_visual_clusters(limit: int = 200) -> dict:
    with _connect() as conn:
        ready, missing = _visual_ready(conn)
        if not ready:
            return {
                "schema_version": SCHEMA_VERSION,
                "ready": False,
                "missing_tables": missing,
                "clusters": [],
            }
        rows = conn.execute(
            """
            SELECT cluster_id, branch_id, label, n_nodes, year_start, year_end,
                   centroid_x, centroid_y, centroid_z, top_terms_json,
                   representative_papers_json, evidence_json
            FROM visual_clusters
            ORDER BY n_nodes DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 2000)),),
        ).fetchall()
        lineage_cols = _table_columns(conn, "branch_lineages")
        split_conf_sql = (
            "split_confidence"
            if "split_confidence" in lineage_cols
            else "strength AS split_confidence"
        )
        split_evidence_sql = (
            "split_evidence_json"
            if "split_evidence_json" in lineage_cols
            else "why_json AS split_evidence_json"
        )
        lineage_rows = conn.execute(
            f"""
            SELECT branch_id, parent_branch_id, split_year, strength,
                   {split_conf_sql} AS split_confidence,
                   {split_evidence_sql} AS split_evidence_json,
                   why_json, future_json
            FROM branch_lineages
            """
        ).fetchall()
    clusters = []
    for row in rows:
        item = dict(row)
        item["centroid"] = {
            "x": item.pop("centroid_x"),
            "y": item.pop("centroid_y"),
            "z": item.pop("centroid_z"),
        }
        item["top_terms"] = _loads(item.pop("top_terms_json", None), [])
        item["representative_papers"] = _loads(item.pop("representative_papers_json", None), [])
        item["evidence"] = _loads(item.pop("evidence_json", None), {})
        clusters.append(item)
    lineages = []
    for row in lineage_rows:
        item = dict(row)
        item["split_evidence"] = _loads(item.pop("split_evidence_json", None), {})
        item["why"] = _loads(item.pop("why_json", None), {})
        item["future"] = _loads(item.pop("future_json", None), {})
        lineages.append(item)
    return {
        "schema_version": SCHEMA_VERSION,
        "ready": True,
        "clusters": clusters,
        "branch_lineages": lineages,
    }


def get_visual_story_steps() -> dict:
    with _connect() as conn:
        ready, missing = _visual_ready(conn)
        if not ready or not _table_exists(conn, "visual_story_steps"):
            return {
                "schema_version": SCHEMA_VERSION,
                "ready": False,
                "missing_tables": missing,
                "story_steps": [],
            }
        rows = conn.execute(
            """
            SELECT story_step_id, order_idx, year_start, year_end, title,
                   narrative, focus_cluster_id, focus_papers_json, evidence_json
            FROM visual_story_steps
            ORDER BY order_idx ASC
            """
        ).fetchall()
    steps = []
    for row in rows:
        item = dict(row)
        item["focus_papers"] = _loads(item.pop("focus_papers_json", None), [])
        item["evidence"] = _loads(item.pop("evidence_json", None), {})
        steps.append(item)
    return {
        "schema_version": SCHEMA_VERSION,
        "ready": True,
        "story_steps": steps,
    }


def get_visual_nodes(
    *,
    cluster_id: str | None = None,
    branch_id: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    role: str | None = None,
    limit: int = 5000,
    offset: int = 0,
) -> dict:
    start = time.perf_counter()
    with _connect() as conn:
        ready, missing = _visual_ready(conn)
        if not ready:
            return {
                "schema_version": SCHEMA_VERSION,
                "ready": False,
                "missing_tables": missing,
                "nodes": [],
                "elapsed_ms": _elapsed_ms(start),
            }
        clauses: list[str] = []
        params: list[Any] = []
        if cluster_id:
            clauses.append("n.cluster_id = ?")
            params.append(cluster_id)
        if branch_id:
            clauses.append("n.branch_id = ?")
            params.append(branch_id)
        if year_from is not None:
            clauses.append("(n.publication_year IS NULL OR n.publication_year >= ?)")
            params.append(int(year_from))
        if year_to is not None:
            clauses.append("(n.publication_year IS NULL OR n.publication_year <= ?)")
            params.append(int(year_to))
        if role:
            clauses.append("n.visual_role = ?")
            params.append(role)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        max_limit = 80000
        params.extend([max(1, min(int(limit), max_limit)), max(0, int(offset))])
        rows = conn.execute(
            f"""
            SELECT
                n.paper_id, n.cluster_id, n.branch_id, n.x, n.y, n.z,
                n.publication_year, n.node_size, n.color_hex, n.visual_role,
                n.uncertainty_score, n.flags_json, d.metadata_json
            FROM visual_nodes n
            LEFT JOIN visual_paper_details d ON d.paper_id = n.paper_id
            {where}
            ORDER BY COALESCE(n.node_size, 0) DESC, n.paper_id
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
    nodes = []
    for row in rows:
        metadata = _loads(row["metadata_json"], {})
        nodes.append(
            {
                "paper_id": row["paper_id"],
                "title": metadata.get("title") or row["paper_id"],
                "year": metadata.get("year") or row["publication_year"],
                "cluster_id": row["cluster_id"],
                "branch_id": row["branch_id"],
                "x": row["x"],
                "y": row["y"],
                "z": row["z"],
                "node_size": row["node_size"],
                "color_hex": row["color_hex"],
                "visual_role": row["visual_role"],
                "uncertainty_score": row["uncertainty_score"],
                "flags": _loads(row["flags_json"], {}),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "ready": True,
        "nodes": nodes,
        "total_matches": len(nodes),
        "limit": min(int(limit), 80000),
        "offset": max(0, int(offset)),
        "elapsed_ms": _elapsed_ms(start),
    }


def get_visual_edges(
    *,
    layer: str | None = None,
    cluster_id: str | None = None,
    lod_max: int = 1,
    limit: int = 20000,
    offset: int = 0,
) -> dict:
    start = time.perf_counter()
    with _connect() as conn:
        ready, missing = _visual_ready(conn)
        if not ready:
            return {
                "schema_version": SCHEMA_VERSION,
                "ready": False,
                "missing_tables": missing,
                "edges": [],
                "elapsed_ms": _elapsed_ms(start),
            }
        clauses = ["e.lod_min <= ?"]
        params: list[Any] = [int(lod_max)]
        if layer:
            clauses.append("e.layer = ?")
            params.append(layer)
        join = ""
        if cluster_id:
            join = """
            JOIN visual_nodes ns ON ns.paper_id = e.source_paper_id
            JOIN visual_nodes nt ON nt.paper_id = e.target_paper_id
            """
            clauses.append("(ns.cluster_id = ? OR nt.cluster_id = ?)")
            params.extend([cluster_id, cluster_id])
        params.extend([max(1, min(int(limit), 100000)), max(0, int(offset))])
        rows = conn.execute(
            f"""
            SELECT e.edge_id, e.source_paper_id, e.target_paper_id, e.edge_type,
                   e.layer, e.weight, e.confidence, e.is_directed,
                   e.is_main_path, e.lod_min, e.style_json, e.evidence_json
            FROM visual_edges e
            {join}
            WHERE {' AND '.join(clauses)}
            ORDER BY e.is_main_path DESC, e.lod_min ASC, COALESCE(e.weight, 0) DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
    edges = []
    for row in rows:
        item = dict(row)
        item["style"] = _loads(item.pop("style_json", None), {})
        item["evidence"] = _loads(item.pop("evidence_json", None), {})
        edges.append(item)
    return {
        "schema_version": SCHEMA_VERSION,
        "ready": True,
        "edges": edges,
        "total_matches": len(edges),
        "limit": min(int(limit), 100000),
        "offset": max(0, int(offset)),
        "elapsed_ms": _elapsed_ms(start),
    }
