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
from pathlib import Path
from typing import Any

from echelon.schema.graph_visual_edit import GraphSearchQuery, GraphVisualEdit
from echelon.v14b.config import DB_V14

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


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_v14_path()), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'virtual table') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


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
            payload_json TEXT,
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
    conn.commit()


def submit_visual_edit(edit: GraphVisualEdit) -> dict:
    with _connect() as conn:
        ensure_edit_schema(conn)
        conn.execute(
            """
            INSERT OR IGNORE INTO graph_visual_edits
                (edit_id, target_type, target_id, action, payload_json, rationale,
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
            SELECT edit_id, target_type, target_id, action, payload_json, rationale,
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
    data["payload"] = _loads(data.pop("payload_json", None), {})
    data["schema_version"] = SCHEMA_VERSION
    return data


def get_visual_edit_history(expert_id: str, limit: int = 100) -> dict:
    with _connect() as conn:
        ensure_edit_schema(conn)
        rows = conn.execute(
            """
            SELECT edit_id, target_type, target_id, action, payload_json, rationale,
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
        item["payload"] = _loads(item.pop("payload_json", None), {})
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
    rows = conn.execute(
        f"""
        SELECT
            n.paper_id, n.cluster_id, n.branch_id, n.x, n.y, n.z,
            n.publication_year, n.node_size, n.color_hex, n.visual_role,
            n.uncertainty_score, n.flags_json,
            c.label AS cluster_label,
            d.ids_json, d.metadata_json, d.abstract, d.sections_json,
            d.limitations_json, d.recommendation_json
        FROM visual_nodes n
        LEFT JOIN visual_clusters c ON c.cluster_id = n.cluster_id
        LEFT JOIN visual_paper_details d ON d.paper_id = n.paper_id
        WHERE n.paper_id IN ({placeholders})
        """,
        unique_ids,
    ).fetchall()
    by_id = {str(row["paper_id"]): row for row in rows}
    out = []
    for pid in unique_ids:
        row = by_id.get(pid)
        if not row:
            continue
        metadata = _loads(row["metadata_json"], {})
        ids = _loads(row["ids_json"], {})
        flags = _loads(row["flags_json"], {})
        recommendations = _loads(row["recommendation_json"], {})
        limitations = _loads(row["limitations_json"], [])
        abstract = row["abstract"] or ""
        out.append(
            {
                "paper_id": pid,
                "title": metadata.get("title") or pid,
                "abstract": abstract[:1400],
                "year": metadata.get("year") or row["publication_year"],
                "cited_by_count": metadata.get("cited_by_count"),
                "ids": ids,
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
    for row in rows:
        item = dict(row)
        item["style"] = _loads(item.pop("style_json", None), {})
        item["evidence"] = _loads(item.pop("evidence_json", None), {})
        edges.append(item)
    return {
        "schema_version": SCHEMA_VERSION,
        "ready": True,
        "paper": hits[0],
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
        lineage_rows = conn.execute(
            """
            SELECT branch_id, parent_branch_id, split_year, strength,
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
