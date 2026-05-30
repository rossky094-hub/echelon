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
from echelon.v14b.evidence_grade import claim_scope_policy, uncertainty_reasons
from echelon.v14b.topic_readiness import build_topic_readiness_preflight

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


def _future_candidate_evidence_text(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("VGAE pred:", "GNN/VGAE candidate edge:")
        .replace("confidence=", "candidate_score=")
    )


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


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


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
    "limitation",
    "limitations",
    "discussion",
    "conclusion",
    "conclusions",
    "future_work",
    "future_directions",
    "results",
    "error_analysis",
    "ablation",
    "method",
    "methods",
    "experiments",
}

STRONG_SECTION_STRATEGIES = {
    "explicit_heading",
    "heading_continuation",
    "embedded_heading",
}

MODERATE_SECTION_STRATEGIES = {
    "inline_heading",
}


def _normalize_section_key(raw: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(raw or "").strip().lower())


def _is_decision_section(raw: Any) -> bool:
    return _normalize_section_key(raw) in DECISION_SECTION_NAMES


def _section_provenance_strength(section: dict[str, Any]) -> str:
    strategies = {
        str(v).strip()
        for v in (section.get("extraction_strategies") or [])
        if str(v or "").strip()
    }
    if strategies & STRONG_SECTION_STRATEGIES:
        return "strong"
    if strategies & MODERATE_SECTION_STRATEGIES:
        return "moderate"
    grade = str(section.get("evidence_grade") or "")
    if grade in {"section_explicit_heading", "section_embedded_heading"}:
        return "strong"
    if grade == "section_inline_heading":
        return "moderate"
    return "weak"


def _paper_has_primary_evidence(paper: dict[str, Any]) -> bool:
    return bool((paper.get("content_availability") or {}).get("has_primary_evidence_sections"))


def _paper_has_traced_primary_evidence(paper: dict[str, Any]) -> bool:
    availability = paper.get("content_availability") or {}
    if "has_strong_or_moderate_primary_evidence_sections" in availability:
        return bool(availability.get("has_strong_or_moderate_primary_evidence_sections"))
    provenance = availability.get("primary_section_provenance")
    if isinstance(provenance, dict):
        return int(provenance.get("strong") or 0) + int(provenance.get("moderate") or 0) > 0
    return bool(availability.get("has_primary_evidence_sections"))


def _paper_has_access(paper: dict[str, Any]) -> bool:
    return bool(paper.get("access_links") or [])


def _section_evidence_contract(
    section_name: Any,
    meta: dict[str, Any] | None,
    pages: list[Any] | None = None,
) -> dict[str, Any]:
    """Expose section extraction provenance as a user-facing evidence contract."""
    meta = meta if isinstance(meta, dict) else {}
    raw_strategies = meta.get("extraction_strategies") or []
    if isinstance(raw_strategies, str):
        strategies = [raw_strategies]
    else:
        strategies = [str(v) for v in raw_strategies if str(v or "").strip()]
    strategy_set = set(strategies)
    is_decision_section = _is_decision_section(section_name)

    if "explicit_heading" in strategy_set or "heading_continuation" in strategy_set:
        evidence_grade = "section_explicit_heading"
        claim_scope = "section_level_evidence"
    elif "embedded_heading" in strategy_set:
        evidence_grade = "section_embedded_heading"
        claim_scope = "section_level_evidence_with_block_boundary_uncertainty"
    elif "loose_inline_heading" in strategy_set:
        evidence_grade = "section_loose_inline_heading"
        claim_scope = "supporting_section_evidence_with_heading_uncertainty"
    elif "inline_heading" in strategy_set:
        evidence_grade = "section_inline_heading"
        claim_scope = "section_level_evidence_with_layout_uncertainty"
    elif "parser_hint" in strategy_set:
        evidence_grade = "section_parser_hint"
        claim_scope = "supporting_section_evidence"
    else:
        evidence_grade = "section_legacy_unknown_strategy"
        claim_scope = "supporting_context_only"

    reasons: list[str] = []
    if not is_decision_section:
        reasons.append("section is not one of the primary decision-evidence sections")
    if not strategies:
        reasons.append("section extraction strategy unavailable; treat as weak provenance")
    if not pages:
        reasons.append("page-level provenance unavailable")
    if evidence_grade in {
        "section_embedded_heading",
        "section_loose_inline_heading",
        "section_inline_heading",
        "section_parser_hint",
    }:
        reasons.append("section boundary may be less reliable than an explicit heading")

    return {
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade,
        "uncertainty_reasons": reasons,
        "extraction_strategies": strategies,
        "required_evidence": [
            "explicit section heading",
            "page-level provenance",
            "paper-level access link",
        ],
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
        pages = _loads(row["section_pages_json"], [])
        meta = _loads(row["section_meta_json"], {})
        evidence_contract = _section_evidence_contract(row["section_name"], meta, pages)
        section = {
            "section_name": row["section_name"],
            "section_type": row["section_name"],
            "section_text": text[:2800],
            "text": text[:2800],
            "source_type": row["source_type"],
            "parser_name": row["parser_name"],
            "source_url": row["source_url"],
            "pages": pages,
            "meta": meta,
            **evidence_contract,
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
    resolution_cols = (
        "0 AS n_resolutions, NULL AS first_resolution_year, "
        "NULL AS max_resolution_confidence, NULL AS resolver_paper_id, "
        "NULL AS resolution_evidence_text"
    )
    resolution_join = ""
    if _table_exists(conn, "limitation_resolutions"):
        resolution_cols = (
            "COALESCE(r.n_resolutions, 0) AS n_resolutions, "
            "r.first_resolution_year AS first_resolution_year, "
            "r.max_resolution_confidence AS max_resolution_confidence, "
            "r.resolver_paper_id AS resolver_paper_id, "
            "r.resolution_evidence_text AS resolution_evidence_text"
        )
        resolution_join = """
            LEFT JOIN (
                SELECT atom_id,
                       COUNT(*) AS n_resolutions,
                       MIN(COALESCE(resolution_year, 9999)) AS first_resolution_year,
                       MAX(confidence) AS max_resolution_confidence,
                       MIN(resolver_paper_id) AS resolver_paper_id,
                       MAX(evidence_text) AS resolution_evidence_text
                FROM limitation_resolutions
                WHERE COALESCE(confidence, 0) >= 0.6
                GROUP BY atom_id
            ) r ON r.atom_id = a.atom_id
        """
    try:
        rows = conn.execute(
            f"""
            SELECT a.atom_id, a.paper_id, a.description, a.keyword, a.severity, a.evidence_source,
                   a.evidence_quality, a.evidence_weight, a.source_section_name,
                   a.extractor_method, {resolution_cols}
            FROM limitation_atoms a
            {resolution_join}
            WHERE a.paper_id IN ({placeholders})
            ORDER BY COALESCE(a.evidence_weight, 0) DESC, a.atom_id DESC
            """,
            paper_ids,
        ).fetchall()
    except sqlite3.Error:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["paper_id"]), []).append(
            {
                "atom_id": row["atom_id"],
                "description": row["description"],
                "keyword": row["keyword"],
                "severity": row["severity"],
                "evidence_source": row["evidence_source"],
                "evidence_quality": row["evidence_quality"],
                "evidence_weight": row["evidence_weight"],
                "source_section_name": row["source_section_name"],
                "extractor_method": row["extractor_method"],
                "is_resolved": 1 if int(row["n_resolutions"] or 0) > 0 else 0,
                "n_resolutions": int(row["n_resolutions"] or 0),
                "resolved_year": (
                    None
                    if row["first_resolution_year"] in (None, 9999)
                    else int(row["first_resolution_year"])
                ),
                "resolution_confidence": row["max_resolution_confidence"],
                "resolver_paper_id": row["resolver_paper_id"],
                "resolution_evidence_text": row["resolution_evidence_text"],
            }
        )
    return out


def _load_context_limitations(
    conn: sqlite3.Connection,
    *,
    topic: str,
    paper_ids: list[str],
    cluster_ids: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Find section-level bottleneck evidence in the topic's graph context.

    Direct result papers are preferred.  Cluster-context rows are useful but
    intentionally labeled as contextual so the UI does not overclaim them.
    """
    if not _table_exists(conn, "limitation_atoms"):
        return []
    terms = _topic_bottleneck_terms(topic)[:36]
    topic_tokens = [
        t for t in _token_set(topic)
        if t not in TOPIC_STOPWORDS and len(t) >= 4
    ][:8]
    if not terms and not topic_tokens:
        return []

    clauses: list[str] = []
    params: list[Any] = []
    direct_ids = list(dict.fromkeys(str(pid) for pid in paper_ids if pid))[:500]
    context_clusters = list(dict.fromkeys(str(cid) for cid in cluster_ids if cid))[:12]
    if direct_ids:
        ph = ",".join("?" for _ in direct_ids)
        clauses.append(f"a.paper_id IN ({ph})")
        params.extend(direct_ids)
    if context_clusters:
        ph = ",".join("?" for _ in context_clusters)
        clauses.append(f"n.cluster_id IN ({ph})")
        params.extend(context_clusters)

    text_expr = (
        "lower(coalesce(a.keyword,'') || ' ' || coalesce(a.description,'') || ' ' || "
        "coalesce(d.metadata_json,'') || ' ' || coalesce(d.abstract,''))"
    )
    topic_like_clauses = []
    for token in topic_tokens:
        topic_like_clauses.append(f"{text_expr} LIKE ?")
        params.append(f"%{token}%")
    if topic_like_clauses:
        clauses.append("(" + " OR ".join(topic_like_clauses) + ")")
    if not clauses:
        return []

    bottleneck_clauses = []
    for term in terms[:36]:
        bottleneck_clauses.append(f"{text_expr} LIKE ?")
        params.append(f"%{term}%")
    if not bottleneck_clauses:
        return []

    resolution_cols = (
        "0 AS n_resolutions, NULL AS first_resolution_year, "
        "NULL AS max_resolution_confidence, NULL AS resolver_paper_id, "
        "NULL AS resolution_evidence_text"
    )
    resolution_join = ""
    if _table_exists(conn, "limitation_resolutions"):
        resolution_cols = (
            "COALESCE(r.n_resolutions, 0) AS n_resolutions, "
            "r.first_resolution_year AS first_resolution_year, "
            "r.max_resolution_confidence AS max_resolution_confidence, "
            "r.resolver_paper_id AS resolver_paper_id, "
            "r.resolution_evidence_text AS resolution_evidence_text"
        )
        resolution_join = """
            LEFT JOIN (
                SELECT atom_id,
                       COUNT(*) AS n_resolutions,
                       MIN(COALESCE(resolution_year, 9999)) AS first_resolution_year,
                       MAX(confidence) AS max_resolution_confidence,
                       MIN(resolver_paper_id) AS resolver_paper_id,
                       MAX(evidence_text) AS resolution_evidence_text
                FROM limitation_resolutions
                WHERE COALESCE(confidence, 0) >= 0.6
                GROUP BY atom_id
            ) r ON r.atom_id = a.atom_id
        """

    params.append(limit)
    try:
        rows = conn.execute(
            f"""
            SELECT a.atom_id, a.paper_id, a.description, a.keyword, a.severity,
                   a.evidence_source, a.evidence_quality, a.evidence_weight,
                   a.source_section_name, a.extractor_method,
                   {resolution_cols},
                   n.cluster_id, n.branch_id, d.metadata_json
            FROM limitation_atoms a
            {resolution_join}
            LEFT JOIN visual_nodes n ON n.paper_id = a.paper_id
            LEFT JOIN visual_paper_details d ON d.paper_id = a.paper_id
            WHERE ({' OR '.join(clauses)})
              AND ({' OR '.join(bottleneck_clauses)})
            ORDER BY
              CASE WHEN a.paper_id IN ({','.join('?' for _ in direct_ids) if direct_ids else "NULL"}) THEN 1 ELSE 0 END DESC,
              COALESCE(a.evidence_weight, 0) DESC,
              a.atom_id DESC
            LIMIT ?
            """,
            [
                *params[:-1],
                *direct_ids,
                params[-1],
            ],
        ).fetchall()
    except sqlite3.Error:
        return []

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    direct = set(direct_ids)
    for row in rows:
        pid = str(row["paper_id"])
        key = (pid, str(row["keyword"] or ""), str(row["description"] or "")[:160])
        if key in seen:
            continue
        seen.add(key)
        metadata = _loads(row["metadata_json"], {})
        relationship_scope = "direct_paper_match" if pid in direct else "cluster_branch_context"
        out.append(
            {
                "atom_id": row["atom_id"],
                "paper_id": pid,
                "title": metadata.get("title") or pid,
                "branch_id": row["branch_id"],
                "cluster_id": row["cluster_id"],
                "keyword": row["keyword"],
                "description": row["description"],
                "severity": row["severity"],
                "evidence_source": row["evidence_source"],
                "evidence_quality": row["evidence_quality"],
                "evidence_weight": row["evidence_weight"],
                "source_section_name": row["source_section_name"],
                "extractor_method": row["extractor_method"],
                "relationship_scope": relationship_scope,
                "is_resolved": 1 if int(row["n_resolutions"] or 0) > 0 else 0,
                "n_resolutions": int(row["n_resolutions"] or 0),
                "resolved_year": (
                    None
                    if row["first_resolution_year"] in (None, 9999)
                    else int(row["first_resolution_year"])
                ),
                "resolution_confidence": row["max_resolution_confidence"],
                "resolver_paper_id": row["resolver_paper_id"],
                "resolution_evidence_text": row["resolution_evidence_text"],
            }
        )
        if len(out) >= limit:
            break
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
        _normalize_section_key(s.get("section_name") or s.get("section_type"))
        for s in sections
        if _normalize_section_key(s.get("section_name") or s.get("section_type"))
    }
    decision_sections = [
        s
        for s in sections
        if _is_decision_section(s.get("section_name") or s.get("section_type"))
    ]
    provenance_counts = Counter(_section_provenance_strength(s) for s in decision_sections)
    primary_section_provenance = {
        "strong": int(provenance_counts.get("strong", 0)),
        "moderate": int(provenance_counts.get("moderate", 0)),
        "weak": int(provenance_counts.get("weak", 0)),
        "total": len(decision_sections),
        "section_names": sorted(
            {
                _normalize_section_key(s.get("section_name") or s.get("section_type"))
                for s in decision_sections
            }
        ),
    }
    strong_or_moderate_sections = (
        primary_section_provenance["strong"] + primary_section_provenance["moderate"]
    )
    links = access.get("external_links") or _external_links_from_ids(ids, sections)
    local_content = dict(access.get("local_content") or {})
    local_content.update(
        {
            "sections": sections[:10],
            "decision_evidence_sections": decision_sections[:10],
            "section_names": sorted(section_names),
            "primary_section_provenance": primary_section_provenance,
            "limitation_atoms": len(limitations or []),
            "claim_cards": len(claim_cards or []),
        }
    )
    availability = dict(access.get("content_availability") or {})
    availability.update(
        {
            "has_local_sections": bool(sections),
            "has_primary_evidence_sections": bool(decision_sections),
            "has_strong_or_moderate_primary_evidence_sections": bool(strong_or_moderate_sections),
            "primary_section_evidence_grade": (
                "strong_or_moderate"
                if strong_or_moderate_sections
                else ("weak" if decision_sections else "none")
            ),
            "primary_section_provenance": primary_section_provenance,
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
        limitations = _attach_limitation_contracts(
            limitations if isinstance(limitations, list) else [],
            paper_id=pid,
        )
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
        item = {
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
        item.update(_paper_hit_contract(item))
        out.append(item)
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
    frontfill = _frontfill_status(conn)
    combo_uncertainty = []
    if float(frontfill.get("linked_ref_rate") or 0.0) < 0.30:
        combo_uncertainty.append("linked refs below 30%; main/citation lineage is incomplete")
    if float(frontfill.get("primary_section_rate") or 0.0) < 0.10:
        combo_uncertainty.append("section evidence below decision-grade target; bottleneck claims must remain exploratory")
    if float(frontfill.get("openalex_w_rate") or 0.0) < 0.70:
        combo_uncertainty.append("OpenAlex coverage below cross-field target; field/topic interpretation needs uncertainty")
    if not (future_directions and claim_cards):
        combo_uncertainty.append("Step6/Step13 fused Claim Cards are not fully materialized for decision-grade Radar")

    def layer_combo(
        *,
        layers: list[str],
        label: str,
        question: str,
        relationship: str,
        display: str,
        decision_use: str,
        can_explain: list[str],
        cannot_explain: list[str],
        required_evidence: list[str],
        claim_scope: str,
        evidence_grade: str,
        uncertainty_reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "layers": layers,
            "label": label,
            "question": question,
            "relationship": relationship,
            "display": display,
            "decision_use": decision_use,
            "can_explain": can_explain,
            "cannot_explain": cannot_explain,
            "required_evidence": required_evidence,
            "claim_scope": claim_scope,
            "evidence_grade": evidence_grade,
            "uncertainty_reasons": sorted(set([*(uncertainty_reasons or []), *combo_uncertainty])),
        }

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
                "algorithm": "Step5b calibrated future candidate generator + Step6/Step13 fusion when available",
                "relationship": "candidate future-growth links from older enabling papers/bottlenecks toward newer candidate directions",
                "display": "purple dashed arcs; treat as score-ranked hypotheses with calibration status",
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
                    "combines main-path support, calibrated future-candidate score, unresolved bottlenecks, section evidence, "
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
        "frontfill_status": frontfill,
        "model_components": {
            "gnn_future_growth": {
                "name": "Step5b GNN/VGAE future candidate generator",
                "algorithm": "2-layer GCN encoder -> variational latent paper embeddings -> dot-product decoder -> calibrated candidate score",
                "source": "echelon/v14b/step5b_vgae.py",
                "role": (
                    "This is the project GNN. It proposes future candidate edges, but the product should only "
                    "treat them as high-value directions after Step6 fusion and Step13 Claim Cards add evidence."
                ),
            }
        },
        "layer_combinations": [
            layer_combo(
                layers=["main_path"],
                label="Historical trunk",
                question="哪些论文真正承接了最多演化流量？",
                relationship="Main Path isolates the high-throughput citation backbone.",
                display="Only black trunk edges are emphasized; this is the cleanest view of lineage, not topic breadth.",
                decision_use="Use for key turning papers and historical dependency, not for future candidate validation.",
                can_explain=["historical dependency backbone", "candidate key turning papers", "where to audit local citation support"],
                cannot_explain=["topic community breadth", "unresolved bottlenecks", "future R&D direction value"],
                required_evidence=["linked citation refs", "SCC-condensed DAG audit", "main_path edge weights"],
                claim_scope="lineage_candidate_until_linked_refs_target",
                evidence_grade="citation_backbone_partial",
            ),
            layer_combo(
                layers=["main_path", "topic"],
                label="Trunk plus branch communities",
                question="主干周围为什么形成这些主题团？",
                relationship="Main gives temporal flow; co-citation reveals intellectual neighborhoods around the trunk.",
                display="Black trunk plus blue-green community edges; best default for explaining why the field branched.",
                decision_use="Use for Topic Dossier branch naming and driver-paper review.",
                can_explain=["which communities orbit the historical trunk", "candidate branch neighborhoods", "where branch labels should be audited"],
                cannot_explain=["causal split reason without section bottlenecks", "investment-ready future direction"],
                required_evidence=["main_path edges", "co-citation/topic edges", "branch driver papers"],
                claim_scope="branch_context_candidate",
                evidence_grade="graph_structure_plus_topic_affinity",
            ),
            layer_combo(
                layers=["main_path", "citation"],
                label="Trunk plus real citation support",
                question="主干链条有哪些真实局部引用支撑？",
                relationship="SPC trunk is checked against ID-relinked local citation edges.",
                display="Black trunk with thin grey supporting citations.",
                decision_use="Use to audit whether a claimed turning paper is structurally supported.",
                can_explain=["local support around trunk edges", "whether a turning paper is connected inside the corpus"],
                cannot_explain=["semantic similarity", "whether a cited limitation is solved"],
                required_evidence=["provider ID repair", "reference relinking", "main_path_edge_audit"],
                claim_scope="citation_support_audit",
                evidence_grade="linked_refs_dependent",
            ),
            layer_combo(
                layers=["topic", "semantic"],
                label="Topic neighborhood search",
                question="这个 topic 附近还有哪些相似论文和主题块？",
                relationship="Co-citation captures shared citation context; semantic kNN captures text/section similarity.",
                display="Community edges plus similarity edges; good for related-work discovery.",
                decision_use="Use for Sci-Bot style retrieval, not as causal evolution evidence.",
                can_explain=["nearby papers to read", "retrieval expansion", "topic neighborhood boundaries"],
                cannot_explain=["historical causality", "branch parentage", "future direction validity"],
                required_evidence=["paper embeddings", "co-citation/reference neighborhoods", "search index"],
                claim_scope="retrieval_context_only",
                evidence_grade="semantic_topic_context",
            ),
            layer_combo(
                layers=["main_path", "topic", "bottleneck"],
                label="Why branches split",
                question="哪个卡点或使能条件导致分支裂变？",
                relationship="Main path and co-citation identify lineage/branch; bottleneck markers explain the constraint pressure.",
                display="Trunk and branches with red/orange bottleneck nodes.",
                decision_use="Use for Branch Dossier and Bottleneck Lineage review.",
                can_explain=["candidate split pressure", "branch driver papers tied to constraints", "which bottlenecks recur around a branch"],
                cannot_explain=["validated parent-child branch split without branch_lineage evidence", "resolved bottleneck status without resolution evidence"],
                required_evidence=["branch_lineages", "section-level limitation atoms", "driver papers", "bottleneck lineage triples"],
                claim_scope="branch_split_hypothesis_until_lineage_verified",
                evidence_grade="section_bottleneck_when_available",
            ),
            layer_combo(
                layers=["future", "bottleneck"],
                label="Bottleneck-driven future candidates",
                question="哪些未来候选是由未解卡点驱动的？",
                relationship="GNN/VGAE proposes future candidate links; bottleneck evidence tests whether they address real constraints.",
                display="Purple dashed candidates with red/orange bottleneck evidence.",
                decision_use="Use as candidate pool only; it cannot become Radar without Claim Cards.",
                can_explain=["which candidate links overlap unresolved constraints", "where to build a Claim Card next"],
                cannot_explain=["that a direction is investable", "that a bottleneck will be solved"],
                required_evidence=["calibrated future candidates", "unresolved limitation atoms", "Step6 fusion evidence"],
                claim_scope="candidate_pool_only",
                evidence_grade="calibrated_graph_plus_bottleneck_candidate",
            ),
            layer_combo(
                layers=["future", "bottleneck", "uncertainty"],
                label="R&D hypothesis audit",
                question="哪些方向值得验证，哪些证据太薄？",
                relationship="Future candidates are filtered by unresolved bottlenecks and penalized by coverage/calibration uncertainty.",
                display="Purple future arcs, bottleneck markers, and amber uncertainty warnings.",
                decision_use="Use before writing a validation experiment or investment memo.",
                can_explain=["which hypotheses deserve evidence gathering", "where uncertainty blocks promotion", "what to prioritize for section/OpenAlex frontfill"],
                cannot_explain=["decision-grade direction value without a complete Claim Card", "commercial relevance without explicit scoring"],
                required_evidence=["VGAE calibration", "section-level bottlenecks", "uncertainty audit", "Claim Card gates"],
                claim_scope="hypothesis_audit_only",
                evidence_grade="uncertainty_aware_candidate",
            ),
            layer_combo(
                layers=["future", "bottleneck", "uncertainty", "fusion_value"],
                label="Claim Card decision overlay",
                question="哪些候选已经形成可审计 Claim Card，哪些仍只能待验证？",
                relationship="Fusion value is Step6/Step13 evidence synthesis over future candidates, unresolved bottlenecks, uncertainty, and Claim Card completeness.",
                display="Radar/Claim Card overlay plus future/bottleneck/uncertainty context.",
                decision_use="Use to separate Radar-promoted Claim Cards from candidate-pool hypotheses.",
                can_explain=["which candidates have complete Claim Cards", "why incomplete candidates stay out of Radar", "which evidence gate blocks promotion"],
                cannot_explain=["raw GNN edges as conclusions", "high-confidence priority when Claim Card gates fail"],
                required_evidence=["Step6 fusion", "Step13 Claim Cards", "VGAE calibration", "section-level bottlenecks", "uncertainty audit"],
                claim_scope="radar_promotion_audit",
                evidence_grade="claim_card_fusion_contract",
            ),
            layer_combo(
                layers=["main_path", "topic", "future", "bottleneck", "uncertainty", "fusion_value"],
                label="Full decision context",
                question="这个 topic 为什么长成这样，未来哪里可能长，可信度如何？",
                relationship="Combines lineage, branch neighborhood, candidate generation, constraints, evidence risk, and Step6/Step13 fusion value.",
                display="Dense decision overlay; zoom/filter before reading individual edges.",
                decision_use="Use for executive review after reading the Topic Dossier.",
                can_explain=["full evidence context behind a Topic Dossier", "why a candidate is still exploratory", "which evidence gaps block Radar"],
                cannot_explain=["a final scientific claim by itself", "high-confidence R&D priority without complete Claim Cards"],
                required_evidence=["all graph layers", "Step6 fusion", "Step13 Claim Cards", "value-delivery audit"],
                claim_scope="decision_context_not_decision",
                evidence_grade="multi_layer_evidence_context",
            ),
        ],
        "fusion_status": (
            "materialized"
            if future_directions and claim_cards
            else "graph_edges_only_until_step6_step13_rerun"
        ),
    }


def _frontfill_status(conn_v14: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Expose evidence-readiness as product state, not hidden ops trivia."""
    status: dict[str, Any] = {
        "available": False,
        "papers": 0,
        "refs": 0,
        "linked_refs": 0,
        "linked_ref_rate": 0.0,
        "openalex_w": 0,
        "openalex_w_rate": 0.0,
        "primary_field": 0,
        "primary_field_rate": 0.0,
        "section_rows": 0,
        "section_papers": 0,
        "primary_section_papers": 0,
        "primary_section_rate": 0.0,
        "high_value_delta_queue": None,
        "interpretation": "frontfill metrics unavailable",
    }
    conn_main = _connect_main()
    if conn_main is None:
        return status
    try:
        papers = int(conn_main.execute("SELECT COUNT(*) FROM papers").fetchone()[0] or 0)
        openalex_w = int(
            conn_main.execute(
                """
                SELECT COUNT(*) FROM papers
                WHERE openalex_id LIKE 'W%'
                   OR openalex_id LIKE 'https://openalex.org/W%'
                """
            ).fetchone()[0] or 0
        )
        primary_field = int(
            conn_main.execute(
                """
                SELECT COUNT(*) FROM papers
                WHERE primary_field_id IS NOT NULL AND primary_field_id <> ''
                """
            ).fetchone()[0] or 0
        )
        section_rows = section_papers = primary_section_papers = 0
        refs = linked_refs = 0
        if _table_exists(conn_main, "paper_references"):
            refs = int(conn_main.execute("SELECT COUNT(*) FROM paper_references").fetchone()[0] or 0)
            ref_cols = {row[1] for row in conn_main.execute("PRAGMA table_info(paper_references)").fetchall()}
            if "cited_paper_id_internal" in ref_cols:
                linked_refs = int(
                    conn_main.execute(
                        """
                        SELECT COUNT(*)
                        FROM paper_references
                        WHERE cited_paper_id_internal IS NOT NULL
                          AND cited_paper_id_internal <> ''
                        """
                    ).fetchone()[0]
                    or 0
                )
            elif "cited_paper_id" in ref_cols:
                linked_refs = int(
                    conn_main.execute(
                        """
                        SELECT COUNT(*)
                        FROM paper_references
                        WHERE cited_paper_id IS NOT NULL
                          AND cited_paper_id <> ''
                        """
                    ).fetchone()[0]
                    or 0
                )
        if _table_exists(conn_main, "paper_sections"):
            section_rows = int(conn_main.execute("SELECT COUNT(*) FROM paper_sections").fetchone()[0] or 0)
            section_papers = int(
                conn_main.execute("SELECT COUNT(DISTINCT paper_id) FROM paper_sections").fetchone()[0] or 0
            )
            primary_section_papers = int(
                conn_main.execute(
                    """
                    SELECT COUNT(DISTINCT paper_id)
                    FROM paper_sections
                    WHERE lower(section_name) IN (
                        'limitation','limitations','discussion','conclusion','conclusions',
                        'future_work','future work','future directions','results','error_analysis',
                        'ablation','method','methods','experiments'
                    )
                      AND length(trim(section_text)) >= 80
                    """
                ).fetchone()[0] or 0
            )
        status.update(
            {
                "available": True,
                "papers": papers,
                "refs": refs,
                "linked_refs": linked_refs,
                "linked_ref_rate": linked_refs / max(1, refs),
                "openalex_w": openalex_w,
                "openalex_w_rate": openalex_w / max(1, papers),
                "primary_field": primary_field,
                "primary_field_rate": primary_field / max(1, papers),
                "section_rows": section_rows,
                "section_papers": section_papers,
                "primary_section_papers": primary_section_papers,
                "primary_section_rate": primary_section_papers / max(1, papers),
            }
        )
    finally:
        conn_main.close()
    if conn_v14 is not None and _table_exists(conn_v14, "section_priority_papers"):
        try:
            row = conn_v14.execute(
                """
                SELECT COUNT(*) AS n,
                       SUM(CASE WHEN has_primary_section = 0 AND eligible_pdf = 1 THEN 1 ELSE 0 END) AS delta_n,
                       SUM(CASE WHEN in_top_n = 1 THEN 1 ELSE 0 END) AS in_top_n
                FROM section_priority_papers
                """
            ).fetchone()
            if row:
                status["high_value_delta_queue"] = {
                    "high_value_papers": int(row["n"] or 0),
                    "missing_primary_with_pdf": int(row["delta_n"] or 0),
                    "in_current_top_n": int(row["in_top_n"] or 0),
                }
        except sqlite3.Error:
            pass
    if status["primary_section_papers"] < 5000:
        label = "section evidence is still too thin for high-confidence Claim Cards"
    elif status["openalex_w_rate"] < 0.7:
        label = "OpenAlex coverage still limits cross-field interpretation"
    else:
        label = "frontfill is approaching product-chain readiness"
    status["interpretation"] = label
    return status


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

METASURFACE_HOLOGRAPHY_BRANCH_FACETS = [
    {
        "name": "High-efficiency visible holography",
        "priority": 10,
        "keywords": ["efficiency", "efficient", "visible", "highest efficiency", "dielectric", "amplitude", "phase"],
        "why": "This branch asks whether holographic metasurfaces can move beyond image formation demos into high-throughput visible devices.",
        "bottleneck": "diffraction efficiency, optical loss, and phase/amplitude control under visible-wavelength constraints",
        "enabler": "dielectric meta-atoms, full amplitude-phase control, and printable or resin-embedded fabrication routes",
    },
    {
        "name": "Large field-of-view holography",
        "priority": 20,
        "keywords": ["wide-angle", "field of view", "fov", "angular", "off-axis", "large field", "3d"],
        "why": "Holography branches when narrow viewing windows and off-axis aberrations limit display or imaging utility.",
        "bottleneck": "field-of-view, angular bandwidth, and speckle/noise trade-offs",
        "enabler": "vectorial wavefront control, angular-momentum design, and multi-plane holographic encoding",
    },
    {
        "name": "Multiplexed and dynamic holography",
        "priority": 30,
        "keywords": ["multiplex", "multiplexed", "dynamic", "reconfigurable", "polarization", "wavelength", "spin", "channel", "encrypted"],
        "why": "Static single-channel holograms split into multiplexed/dynamic work when systems need several images, states, or security channels.",
        "bottleneck": "channel crosstalk, refreshability, polarization leakage, and information capacity",
        "enabler": "polarization/wavelength/OAM multiplexing, phase correlation design, and active or multi-layer metasurfaces",
    },
    {
        "name": "Fabrication-tolerant metasurface design",
        "priority": 40,
        "keywords": ["fabrication", "tolerant", "tolerance", "printing", "print", "resin", "inverse design", "end-to-end", "deep-learning"],
        "why": "The branch appears when ideal metasurface holograms fail to survive process error, scale-up, or fabrication-aware deployment.",
        "bottleneck": "fabrication tolerance, process repeatability, and inverse-design-to-fabrication transfer",
        "enabler": "end-to-end optimization, fabrication-aware inverse design, and one-step nanoparticle/resin printing",
    },
]

PHOTONIC_CRYSTAL_CAVITY_BRANCH_FACETS = [
    {
        "name": "High-Q nanocavities",
        "priority": 10,
        "keywords": ["high-q", "high q", "quality factor", "q-factor", "nanocavity", "nanocavities", "mode volume", "bic"],
        "why": "Photonic-crystal cavity work starts from pushing Q/V and confinement because those set the strength of light-matter interaction.",
        "bottleneck": "quality factor, mode volume, radiation loss, and fabrication disorder",
        "enabler": "band-gap engineering, nanobeam/L3 designs, topology/BIC concepts, and local tuning",
    },
    {
        "name": "Cavity quantum electrodynamics",
        "priority": 20,
        "keywords": ["qed", "quantum dot", "single quantum", "purcell", "strongly coupled", "strong coupling", "rabi", "emitter"],
        "why": "A distinct branch forms when cavities become platforms for quantum emitters, Purcell enhancement, and strong-coupling experiments.",
        "bottleneck": "emitter-cavity detuning, linewidth, mode volume, and deterministic placement",
        "enabler": "quantum dots/color centers, strain/photochromic tuning, and cavity-waveguide architectures",
    },
    {
        "name": "On-chip coupling and integration",
        "priority": 30,
        "keywords": ["waveguide", "coupled", "coupling", "integrated", "on-chip", "readout", "interface", "fiber"],
        "why": "The cavity branch becomes system-relevant when energy must be coupled into waveguides, fibers, or chip-scale readout paths.",
        "bottleneck": "coupling loss, alignment, packaging, and interface stability",
        "enabler": "waveguide-coupled cavities, fiber tapers, deterministic interfaces, and integrated tuning",
    },
    {
        "name": "Tunable and nonlinear cavity devices",
        "priority": 40,
        "keywords": ["tuning", "tunable", "nonlinear", "slow-light", "electrical", "strain", "photochromic", "graphene"],
        "why": "Tunable/nonlinear devices split from static cavities when applications require active control, switching, or enhanced nonlinear response.",
        "bottleneck": "thermal stability, tuning range, nonlinear loss, and device repeatability",
        "enabler": "strain/electrical/photochromic tuning, graphene control, and coupled-cavity arrays",
    },
]

QUANTUM_LIGHT_SOURCE_BRANCH_FACETS = [
    {
        "name": "Single-photon emitters",
        "priority": 10,
        "keywords": ["single-photon", "single photon", "emitter", "quantum dot", "color center", "heralded", "deterministic"],
        "why": "Quantum light-source work splits into emitter-based sources when deterministic single photons and local integration become central.",
        "bottleneck": "brightness, purity, indistinguishability, collection efficiency, and deterministic placement",
        "enabler": "quantum dots, color centers, 2D emitters, resonant cavities, and deterministic coupling",
    },
    {
        "name": "Entangled photon-pair sources",
        "priority": 20,
        "keywords": ["entangled", "photon pair", "biphoton", "spdc", "sagnac", "parametric", "squeezed", "coincidence"],
        "why": "Pair-source work forms a branch because networking and quantum information often need entanglement rate and pair quality, not just single photons.",
        "bottleneck": "pair rate, noise, spectral purity, indistinguishability, and source stability",
        "enabler": "SPDC/SFWM platforms, Sagnac loops, microresonators, and engineered nonlinear materials",
    },
    {
        "name": "Integrated quantum photonics",
        "priority": 30,
        "keywords": ["integrated", "on-chip", "photonic", "waveguide", "micro-ring", "microring", "silicon", "lithium niobate", "platform"],
        "why": "A system branch appears when quantum-light generation must be packaged into scalable photonic circuits.",
        "bottleneck": "propagation/coupling loss, chip-scale scalability, thermal drift, and packaging",
        "enabler": "silicon, SiN, lithium-niobate, van-der-Waals, and heterogeneous integrated photonic platforms",
    },
    {
        "name": "Deterministic coupling and collection",
        "priority": 40,
        "keywords": ["collection", "coupling", "fiber", "interface", "brightness", "extraction", "deterministic", "antenna"],
        "why": "This branch grows when a source exists but practical use is limited by collecting photons into the right spatial/spectral channel.",
        "bottleneck": "collection efficiency, fiber/chip coupling, spectral matching, and alignment robustness",
        "enabler": "nanocavities, antennas, waveguide interfaces, and packaged collection optics",
    },
]

BOTTLENECK_FACETS = [
    ("coupling loss", ["coupling loss", "coupling losses", "fiber-chip", "interface loss", "extraction", "escape efficiency"]),
    ("fabrication tolerance", ["fabrication tolerance", "fabrication disorder", "process variation", "disorder", "tolerance", "repeatability"]),
    ("quality factor and mode volume", ["quality factor", "q-factor", "high-q", "mode volume", "radiative loss"]),
    ("brightness and indistinguishability", ["brightness", "indistinguishability", "purity", "pair rate", "single photon"]),
    ("speckle and holographic noise", ["speckle", "holographic noise", "coherence noise", "ghost", "contrast"]),
    ("channel crosstalk", ["crosstalk", "cross-talk", "channel leakage", "polarization leakage", "multiplex leakage"]),
    ("efficiency", ["efficiency", "throughput", "loss", "collection", "transmission"]),
    ("chromatic aberration", ["chromatic", "dispersion", "achromatic", "broadband", "wavelength"]),
    ("field of view and angular aberration", ["field of view", "fov", "angular", "off-axis", "aberration", "wide-angle"]),
    ("manufacturing consistency", ["manufacturing", "fabrication", "scalable", "scalability", "large-area", "uniformity", "yield", "printing", "lithography"]),
    ("system integration", ["integration", "integrated", "on-chip", "packaging", "alignment", "coupling"]),
    ("cost and reliability", ["cost", "low-cost", "reliability", "robust", "mass", "commercial"]),
]

TOPIC_BOTTLENECK_TERMS = {
    "metasurface_holography": [
        "efficiency", "speckle", "field of view", "fov", "crosstalk", "fabrication tolerance",
        "holography", "multiplex", "wide-angle",
    ],
    "photonic_crystal_cavity": [
        "quality factor", "q-factor", "mode volume", "coupling loss", "fabrication disorder",
        "thermal", "photonic crystal", "cavity", "nanocavity",
    ],
    "quantum_light_source": [
        "brightness", "indistinguishability", "collection", "collection efficiency", "scalability",
        "integration", "single photon", "photon pair", "quantum source",
    ],
    "metalens": [
        "efficiency", "chromatic", "field of view", "fov", "manufacturing", "integration", "cost",
        "metalens", "metasurface",
    ],
}

TOPIC_RELEVANCE_PROFILES = {
    "metasurface_holography": {
        "strong": ["metasurface holography", "meta-holography", "holographic metasurface", "metasurface hologram"],
        "medium": ["holography", "holographic", "hologram", "metahologram", "meta hologram"],
        "weak": ["metasurface", "multiplexed", "speckle", "field of view", "crosstalk"],
    },
    "photonic_crystal_cavity": {
        "strong": ["photonic crystal cavity", "photonic-crystal cavity", "photonic crystal nanocavity"],
        "medium": ["nanocavity", "nanocavities", "high-q", "q-factor", "quality factor", "mode volume"],
        "weak": ["cavity", "purcell", "strong coupling", "waveguide-coupled"],
    },
    "quantum_light_source": {
        "strong": ["quantum light source", "single-photon source", "single photon source", "photon-pair source"],
        "medium": ["single photon", "single-photon", "photon pair", "entangled photon", "quantum emitter", "emitter"],
        "weak": ["brightness", "indistinguishability", "collection efficiency", "heralded", "spdc"],
    },
    "metalens": {
        "strong": ["metalens", "meta-lens", "metalenses"],
        "medium": ["achromatic lens", "flat lens", "metasurface lens", "metaoptic lens", "meta-optic lens"],
        "weak": ["high-na", "numerical aperture", "field of view", "large-area", "inverse design"],
    },
}


def _topic_branch_facets(topic: str) -> list[dict[str, Any]]:
    text = topic.lower()
    if "holograph" in text and ("metasurface" in text or "meta-optic" in text or "meta optic" in text):
        return METASURFACE_HOLOGRAPHY_BRANCH_FACETS
    if "photonic crystal" in text and "cavit" in text:
        return PHOTONIC_CRYSTAL_CAVITY_BRANCH_FACETS
    if "quantum" in text and ("light source" in text or "photon source" in text or "single photon" in text):
        return QUANTUM_LIGHT_SOURCE_BRANCH_FACETS
    if "metalens" in text or "meta-lens" in text:
        return METALENS_BRANCH_FACETS
    return []


def _topic_bottleneck_terms(topic: str) -> list[str]:
    text = topic.lower()
    key = None
    if "holograph" in text and ("metasurface" in text or "meta-optic" in text or "meta optic" in text):
        key = "metasurface_holography"
    elif "photonic crystal" in text and "cavit" in text:
        key = "photonic_crystal_cavity"
    elif "quantum" in text and ("light source" in text or "photon source" in text or "single photon" in text):
        key = "quantum_light_source"
    elif "metalens" in text or "meta-lens" in text:
        key = "metalens"
    terms = list(TOPIC_BOTTLENECK_TERMS.get(key or "", []))
    for label, facet_terms in BOTTLENECK_FACETS:
        terms.append(label)
        terms.extend(facet_terms[:3])
    # Keep this deterministic; the SQL caller will cap the list.
    return list(dict.fromkeys(t.lower() for t in terms if t))


def _topic_profile_key(topic: str) -> str | None:
    text = topic.lower()
    if "holograph" in text and ("metasurface" in text or "meta-optic" in text or "meta optic" in text):
        return "metasurface_holography"
    if "photonic crystal" in text and "cavit" in text:
        return "photonic_crystal_cavity"
    if "quantum" in text and ("light source" in text or "photon source" in text or "single photon" in text):
        return "quantum_light_source"
    if "metalens" in text or "meta-lens" in text:
        return "metalens"
    return None


def _paper_text(paper: dict[str, Any]) -> str:
    return " ".join(
        str(paper.get(k) or "")
        for k in ("title", "abstract", "cluster_label", "field", "subfield", "topic")
    ).lower()


def _facet_matches(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(k in lower for k in keywords)


def _topic_relevance_score(topic: str, paper: dict[str, Any]) -> tuple[int, list[str]]:
    text = _paper_text(paper)
    key = _topic_profile_key(topic)
    matched: list[str] = []
    score = 0
    if key:
        profile = TOPIC_RELEVANCE_PROFILES.get(key, {})
        for term in profile.get("strong", []):
            if term in text:
                score += 4
                matched.append(term)
        for term in profile.get("medium", []):
            if term in text:
                score += 2
                matched.append(term)
        for term in profile.get("weak", []):
            if term in text:
                score += 1
                matched.append(term)
        return score, matched

    tokens = _token_set(topic)
    for token in tokens:
        if token in text:
            score += 1
            matched.append(token)
    return score, matched


def _split_topic_turning_papers(
    topic: str,
    papers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    topic_specific: list[dict[str, Any]] = []
    broader_context: list[dict[str, Any]] = []
    for paper in papers:
        score, matched = _topic_relevance_score(topic, paper)
        item = dict(paper)
        reason = dict(item.get("reason") or {})
        reason["topic_relevance_score"] = score
        reason["topic_relevance_terms"] = matched[:8]
        has_primary_section = _paper_has_primary_evidence(item)
        has_traced_section = _paper_has_traced_primary_evidence(item)
        if score >= 2:
            reason["topic_relevance_scope"] = "topic_specific"
            item["reason"] = reason
            item["claim_scope"] = "topic_specific_turning_candidate"
            item["evidence_grade"] = (
                "section_backed_turning_candidate"
                if has_traced_section
                else "weak_section_turning_candidate"
                if has_primary_section
                else "metadata_turning_candidate"
            )
            item["uncertainty_reasons"] = [
                *(
                    []
                    if has_traced_section
                    else ["key turning paper has only weak section parser provenance"]
                    if has_primary_section
                    else ["key turning paper lacks local primary section evidence"]
                ),
                "main-path relevance is topic-filtered but remains uncertainty-labeled until linked refs reach target",
            ]
            topic_specific.append(item)
        else:
            reason["topic_relevance_scope"] = "broader_field_context"
            reason["why"] = (
                "This paper lies on a nearby field-level main path but lacks enough topic-specific "
                "text evidence to be treated as a key turning paper for this query."
            )
            item["reason"] = reason
            item["claim_scope"] = "broader_context_not_topic_turning_paper"
            item["evidence_grade"] = "metadata_broader_context"
            item["uncertainty_reasons"] = [
                "topic relevance score is below the key-turning threshold",
                "show as broader field context, not as this topic's turning paper",
            ]
            broader_context.append(item)
    topic_specific.sort(
        key=lambda p: (
            int((p.get("reason") or {}).get("topic_relevance_score") or 0),
            float(p.get("score") or 0.0),
        ),
        reverse=True,
    )
    return topic_specific, broader_context


def _topic_driver_fallback_papers(
    topic: str,
    hits: list[dict[str, Any]],
    *,
    existing_ids: set[str],
    per_facet: int = 2,
    limit: int = 16,
) -> list[dict[str, Any]]:
    """Use topic-facet driver papers when the global main path is too broad.

    This keeps the Topic Dossier honest: a field-level main-path paper is not
    promoted as a topic turning paper, but strongly matching branch drivers can
    still seed a useful, clickable history path.
    """
    out: list[dict[str, Any]] = []
    seen = set(existing_ids)
    for facet in _topic_branch_facets(topic):
        matched = [
            h for h in hits
            if h.get("paper_id")
            and h.get("paper_id") not in seen
            and _facet_matches(_paper_text(h), facet.get("keywords") or [])
        ]
        matched.sort(key=lambda h: (int(h.get("year") or 9999), -(float(h.get("score") or 0.0))))
        for paper in matched[:per_facet]:
            item = dict(paper)
            score, terms = _topic_relevance_score(topic, item)
            if score <= 0:
                continue
            reason = dict(item.get("reason") or {})
            reason.update(
                {
                    "why": "This paper is a topic-specific branch driver used because the global main path is too broad for this query.",
                    "role": "topic branch driver / turning fallback",
                    "topic_relevance_scope": "topic_branch_driver_fallback",
                    "topic_relevance_score": score,
                    "topic_relevance_terms": terms[:8],
                    "facet": facet.get("name"),
                }
            )
            item["reason"] = reason
            has_primary_section = _paper_has_primary_evidence(item)
            has_traced_section = _paper_has_traced_primary_evidence(item)
            item["claim_scope"] = "topic_branch_driver_turning_fallback"
            item["evidence_grade"] = (
                "section_backed_turning_candidate"
                if has_traced_section
                else "weak_section_turning_candidate"
                if has_primary_section
                else "metadata_turning_candidate"
            )
            item["uncertainty_reasons"] = [
                "used as topic-specific fallback because global main path is broader than the query",
                *(
                    []
                    if has_traced_section
                    else ["fallback driver has only weak section parser provenance"]
                    if has_primary_section
                    else ["fallback driver lacks local primary section evidence"]
                ),
            ]
            out.append(item)
            seen.add(str(item.get("paper_id")))
            if len(out) >= limit:
                return out
    return out


def _paper_ref(paper: dict[str, Any], why: str | None = None) -> dict[str, Any]:
    return {
        "paper_id": paper.get("paper_id"),
        "title": paper.get("title"),
        "year": paper.get("year"),
        "cluster_id": paper.get("cluster_id"),
        "branch_id": paper.get("branch_id"),
        "cluster_label": paper.get("cluster_label"),
        "access_links": paper.get("access_links") or [],
        "claim_scope": paper.get("claim_scope"),
        "evidence_grade": paper.get("evidence_grade"),
        "uncertainty_reasons": paper.get("uncertainty_reasons") or [],
        "content_availability": paper.get("content_availability") or {},
        "why": why,
    }


def _paper_evidence_object(
    paper: dict[str, Any] | None,
    *,
    role: str,
    source: str,
    why: str | None = None,
) -> dict[str, Any] | None:
    if not paper or not paper.get("paper_id"):
        return None
    return {
        "type": "paper",
        "role": role,
        "source": source,
        "paper_id": paper.get("paper_id"),
        "title": paper.get("title"),
        "year": paper.get("year"),
        "cluster_id": paper.get("cluster_id"),
        "branch_id": paper.get("branch_id"),
        "label": paper.get("title") or paper.get("paper_id"),
        "why": why or paper.get("why") or (paper.get("reason") or {}).get("why"),
        "access_links": paper.get("access_links") or [],
        "content_availability": paper.get("content_availability") or {},
        "click_target": {"kind": "paper", "id": paper.get("paper_id")},
    }


def _paper_hit_contract(paper: dict[str, Any]) -> dict[str, Any]:
    reason = paper.get("reason") if isinstance(paper.get("reason"), dict) else {}
    visual = paper.get("visual") if isinstance(paper.get("visual"), dict) else {}
    visual_role = str(visual.get("role") or paper.get("visual_role") or reason.get("role") or "paper")
    layer = str(reason.get("layer") or reason.get("edge_type") or "")
    has_traced_section = _paper_has_traced_primary_evidence(paper)
    has_primary_section = _paper_has_primary_evidence(paper)

    if visual_role == "future_anchor":
        claim_scope = "candidate_pool_only"
        evidence_grade = "graph_future_anchor_context"
    elif visual_role == "limitation_bottleneck" or (paper.get("limitations") or []):
        claim_scope = "bottleneck_context_only"
        evidence_grade = (
            "section_bottleneck_context"
            if has_traced_section
            else "weak_bottleneck_context"
            if has_primary_section
            else "metadata_bottleneck_context"
        )
    elif bool(reason.get("is_main_path")) or visual_role == "main_path" or layer == "main_path":
        claim_scope = "main_path_context_only"
        evidence_grade = (
            "section_backed_main_path_context"
            if has_traced_section
            else "graph_main_path_context"
        )
    elif layer == "citation":
        claim_scope = "citation_context_only"
        evidence_grade = "local_citation_edge_context"
    else:
        claim_scope = "retrieval_context_only"
        evidence_grade = "metadata_search_context"

    uncertainty = [
        "paper search/list hit is retrieval context, not a standalone Topic Dossier conclusion",
    ]
    if not has_traced_section:
        uncertainty.append("paper hit lacks strong/moderate local primary section evidence in this list view")
    if layer in {"citation", "main_path"}:
        uncertainty.append("linked edge context must be opened and audited before using this paper as citation evidence")
    if claim_scope == "candidate_pool_only":
        uncertainty.append("future-anchor paper remains candidate-pool context until Step6 fusion and a complete Claim Card")

    evidence_object = _paper_evidence_object(
        paper,
        role="visual_search_hit",
        source="visual_search_or_topic_list",
        why=reason.get("why") or reason.get("role") or reason.get("layer") or "retrieved visual paper hit",
    )
    if evidence_object:
        evidence_object.update(
            {
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
            }
        )
    return {
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade,
        "uncertainty_reasons": sorted(set(uncertainty)),
        "required_evidence": [
            "Topic Dossier synthesis before treating this list hit as a topic conclusion",
            "paper detail with local primary section evidence",
            "linked citation or branch lineage evidence when used for historical claims",
            "complete Step13 Claim Card before promotion to Radar",
        ],
        "evidence_objects": _compact_evidence_objects([evidence_object], limit=3),
    }


def _limitation_evidence_object(limitation: dict[str, Any] | None, *, source: str) -> dict[str, Any] | None:
    if not limitation:
        return None
    paper_id = limitation.get("paper_id")
    return {
        "type": "limitation_atom",
        "role": "bottleneck_evidence",
        "source": source,
        "paper_id": paper_id,
        "label": limitation.get("keyword") or "limitation",
        "description": limitation.get("description"),
        "evidence_quality": limitation.get("evidence_quality"),
        "relationship_scope": limitation.get("relationship_scope"),
        "source_section_name": limitation.get("source_section_name"),
        "atom_id": limitation.get("atom_id"),
        "is_resolved": int(bool(_limitation_is_resolved(limitation))),
        "n_resolutions": limitation.get("n_resolutions"),
        "click_target": {"kind": "paper", "id": paper_id} if paper_id else None,
    }


def _limitation_is_resolved(limitation: dict[str, Any] | None) -> bool:
    if not limitation:
        return False
    if int(limitation.get("n_resolutions") or 0) > 0:
        return True
    value = limitation.get("is_resolved")
    if isinstance(value, bool):
        return value
    if str(value).strip().lower() in {"1", "true", "yes", "resolved"}:
        return True
    try:
        confidence = float(limitation.get("resolution_confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return bool(limitation.get("resolver_paper_id") and confidence >= 0.6)


def _limitation_resolution_evidence_object(
    limitation: dict[str, Any] | None,
    *,
    source: str,
) -> dict[str, Any] | None:
    if not _limitation_is_resolved(limitation):
        return None
    resolver_id = limitation.get("resolver_paper_id")
    paper_id = limitation.get("paper_id")
    return {
        "type": "limitation_resolution",
        "role": "partial_resolution_evidence",
        "source": source,
        "atom_id": limitation.get("atom_id"),
        "paper_id": paper_id,
        "resolver_paper_id": resolver_id,
        "label": limitation.get("keyword") or "resolution evidence",
        "description": limitation.get("resolution_evidence_text") or limitation.get("description"),
        "resolution_year": limitation.get("resolved_year"),
        "resolution_confidence": limitation.get("resolution_confidence"),
        "n_resolutions": limitation.get("n_resolutions"),
        "click_target": {"kind": "paper", "id": resolver_id or paper_id} if (resolver_id or paper_id) else None,
    }


def _limitation_atom_contract(limitation: dict[str, Any] | None) -> dict[str, Any]:
    limitation = limitation if isinstance(limitation, dict) else {}
    evidence_quality = str(limitation.get("evidence_quality") or "").strip().lower()
    evidence_source = str(limitation.get("evidence_source") or "").strip().lower()
    extractor_method = str(limitation.get("extractor_method") or "").strip().lower()
    section_name = str(limitation.get("source_section_name") or limitation.get("section_name") or "").strip()
    has_section_evidence = (
        evidence_quality in {"section_level", "section_explicit_heading", "section_embedded_heading", "section_inline_heading"}
        or evidence_source == "structured_sections"
        or _is_decision_section(section_name)
    )
    is_llm = extractor_method.startswith("llm")
    is_resolved = _limitation_is_resolved(limitation)

    if is_resolved:
        claim_scope = "partial_resolution_context_only"
        evidence_grade = "section_resolution_context" if has_section_evidence else "weak_resolution_context"
    elif has_section_evidence:
        claim_scope = "bottleneck_context_only"
        evidence_grade = "section_limitation_context"
    elif is_llm:
        claim_scope = "weak_bottleneck_hypothesis"
        evidence_grade = "llm_weak_limitation_label"
    else:
        claim_scope = "weak_bottleneck_hypothesis"
        evidence_grade = "metadata_or_abstract_limitation_context"

    uncertainty = [
        "limitation atom is bottleneck context, not a standalone high-confidence claim",
    ]
    if not has_section_evidence:
        uncertainty.append("limitation lacks structured local section evidence in a decision section")
    if is_llm:
        uncertainty.append("LLM-extracted limitation labels remain weak unless anchored to structured section evidence")
    if is_resolved:
        uncertainty.append("resolution evidence suggests partial progress; current applicability still needs validation")
    try:
        evidence_weight = float(limitation.get("evidence_weight") or 0.0)
    except (TypeError, ValueError):
        evidence_weight = 0.0
    if evidence_weight and evidence_weight < 0.6:
        uncertainty.append("limitation evidence weight is below strong-evidence threshold")

    evidence_object = _limitation_evidence_object(limitation, source="visual_paper_detail")
    if evidence_object:
        evidence_object.update(
            {
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
            }
        )
    resolution_object = _limitation_resolution_evidence_object(limitation, source="visual_paper_detail")
    if resolution_object:
        resolution_object.update(
            {
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
            }
        )
    return {
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade,
        "uncertainty_reasons": sorted(set(uncertainty)),
        "required_evidence": [
            "structured limitation/discussion/results/methods section evidence",
            "typed bottleneck lineage chain: constraint -> failure mechanism -> attempted path -> local fix -> new constraint",
            "resolution evidence from later papers before marking the bottleneck as solved",
            "complete Step13 Claim Card before using this limitation for R&D Radar promotion",
        ],
        "evidence_objects": _compact_evidence_objects([evidence_object, resolution_object], limit=4),
    }


def _attach_limitation_contracts(
    limitations: list[Any],
    *,
    paper_id: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in limitations:
        item = dict(raw) if isinstance(raw, dict) else {"description": str(raw)}
        if paper_id and not item.get("paper_id"):
            item["paper_id"] = paper_id
        item.update(_limitation_atom_contract(item))
        out.append(item)
    return out


def _lineage_triple_evidence_object(triple: dict[str, Any] | None, *, source: str) -> dict[str, Any] | None:
    if not triple:
        return None
    paper_id = triple.get("paper_id")
    source_stage = triple.get("source_stage") or "constraint"
    target_stage = triple.get("target_stage") or "failure_mechanism"
    label = f"{source_stage} -> {target_stage}"
    return {
        "type": "bottleneck_lineage_triple",
        "role": "typed_bottleneck_lineage",
        "source": source,
        "id": triple.get("triple_id"),
        "paper_id": paper_id,
        "resolver_paper_id": triple.get("resolver_paper_id"),
        "label": label,
        "description": triple.get("target_text") or triple.get("source_text"),
        "relation_type": triple.get("relation_type"),
        "event_year": triple.get("event_year"),
        "evidence_section": triple.get("evidence_section"),
        "evidence_page": triple.get("evidence_page"),
        "evidence_quality": triple.get("evidence_quality"),
        "evidence_weight": triple.get("evidence_weight"),
        "lineage_chain": {
            "source_stage": source_stage,
            "target_stage": target_stage,
            "source_text": triple.get("source_text"),
            "target_text": triple.get("target_text"),
        },
        "click_target": {"kind": "paper", "id": paper_id} if paper_id else None,
    }


def _edge_evidence_object(edge: dict[str, Any] | None, *, edge_type: str, source: str) -> dict[str, Any] | None:
    if not edge:
        return None
    source_id = edge.get("source_paper_id")
    target_id = edge.get("target_paper_id")
    if not source_id and not target_id:
        return None
    return {
        "type": edge_type,
        "role": edge_type,
        "source": source,
        "edge_id": edge.get("edge_id"),
        "source_paper_id": source_id,
        "target_paper_id": target_id,
        "weight": edge.get("weight"),
        "confidence": edge.get("confidence"),
        "label": f"{source_id or '?'} -> {target_id or '?'}",
        "relationship_scope": (edge.get("evidence") or {}).get("relationship_scope"),
        "click_target": {"kind": "edge", "id": edge.get("edge_id") or f"{source_id}->{target_id}"},
    }


def _future_edge_calibration_status(edge: dict[str, Any] | None) -> str:
    evidence = (edge or {}).get("evidence") or {}
    status = evidence.get("calibration_status") or evidence.get("lifecycle_calibration_status")
    if status:
        return str(status)
    if evidence.get("calibration_label") or evidence.get("calibration_method") or evidence.get("calibrated_prob") is not None:
        return "edge_calibrated_run_audit_unknown"
    return "not_calibrated"


def _future_edge_has_run_calibration(edge: dict[str, Any] | None) -> bool:
    return _future_edge_calibration_status(edge) == "calibrated_with_run_audit"


def _future_edge_evidence_grade(edge: dict[str, Any] | None) -> str:
    if _future_edge_has_run_calibration(edge):
        return "calibrated_candidate_generator"
    if edge:
        return "uncalibrated_candidate_generator"
    return "future_candidate_generation_gap"


def _future_edge_claim_contract(edge: dict[str, Any] | None) -> dict[str, Any]:
    calibration_status = _future_edge_calibration_status(edge)
    evidence_grade = _future_edge_evidence_grade(edge)
    evidence = (edge or {}).get("evidence") or {}
    uncertainty = [
        "GNN/VGAE is a future candidate generator, not a conclusion generator",
        "future edge cannot be promoted without Step6 fusion and a complete Step13 Claim Card",
        *(
            []
            if calibration_status == "calibrated_with_run_audit"
            else [calibration_status.replace("_", " ")]
        ),
        *list(evidence.get("uncertainty_reasons") or []),
    ]
    return {
        "claim_scope": "candidate_pool_only",
        "evidence_grade": evidence_grade,
        "uncertainty_reasons": sorted(set(uncertainty)),
        "required_evidence": [
            "rolling held-out-year calibration audit",
            "Step6 fusion evidence",
            "Step13 five-question Claim Card",
            "section-level bottleneck evidence",
        ],
        "calibration_status": calibration_status,
        "evidence_objects": _compact_evidence_objects(
            [_edge_evidence_object(edge, edge_type="future_candidate", source="Step5b VGAE")],
            limit=4,
        ),
    }


def _apply_future_edge_contracts(future_growth: list[dict[str, Any]]) -> None:
    for edge in future_growth:
        contract = _future_edge_claim_contract(edge)
        edge.setdefault("claim_scope", contract["claim_scope"])
        edge.setdefault("evidence_grade", contract["evidence_grade"])
        edge.setdefault("uncertainty_reasons", contract["uncertainty_reasons"])
        edge.setdefault("required_evidence", contract["required_evidence"])
        edge.setdefault("calibration_status", contract["calibration_status"])
        edge.setdefault("evidence_objects", contract["evidence_objects"])


def _format_minimal_validation_experiment(experiment: dict[str, Any] | None) -> str | None:
    if not isinstance(experiment, dict) or not experiment:
        return None
    pieces = []
    if experiment.get("experiment"):
        pieces.append(str(experiment.get("experiment")))
    if experiment.get("cost_level") or experiment.get("cycle_weeks"):
        pieces.append(
            "cost={cost}; cycle={cycle} weeks".format(
                cost=experiment.get("cost_level") or "unknown",
                cycle=experiment.get("cycle_weeks") or "unknown",
            )
        )
    success = experiment.get("success_criteria") or []
    if isinstance(success, str):
        success = [success]
    falsification = experiment.get("falsification_conditions") or []
    if isinstance(falsification, str):
        falsification = [falsification]
    if success:
        pieces.append("success: " + "; ".join(str(x) for x in success[:2] if x))
    if falsification:
        pieces.append("falsify: " + "; ".join(str(x) for x in falsification[:2] if x))
    return " | ".join(pieces) if pieces else None


def _claim_card_evidence_objects(item: dict[str, Any]) -> list[dict[str, Any]]:
    card = item.get("claim_card") or {}
    if not isinstance(card, dict):
        card = {}
    experiment = card.get("minimal_validation_experiment") or {}
    objects: list[dict[str, Any] | None] = [
        {
            "type": "claim_card",
            "role": "five_question_contract",
            "source": "Step13 Claim Card",
            "id": card.get("claim_card_id") or item.get("direction_id"),
            "label": item.get("direction_name") or item.get("title") or item.get("direction_id"),
            "claim_scope": item.get("claim_scope"),
            "evidence_grade": item.get("evidence_grade") or item.get("evidence_tier"),
            "five_question_complete": bool(card.get("five_question_complete")),
            "high_confidence_eligible": bool(card.get("high_confidence_eligible")),
            "description": "Step13 five-question Claim Card; Radar promotion still depends on high-confidence gates.",
        },
        {
            "type": "minimal_validation_experiment",
            "role": "falsifiable_validation",
            "source": "Step13 Claim Card",
            "id": card.get("claim_card_id") or item.get("direction_id"),
            "label": (experiment or {}).get("experiment") or "minimal validation experiment",
            "description": _format_minimal_validation_experiment(experiment),
            "claim_scope": item.get("claim_scope"),
            "evidence_grade": item.get("evidence_grade") or item.get("evidence_tier"),
        } if experiment else None,
    ]
    root = card.get("root_constraint") or {}
    if isinstance(root, dict) and root:
        objects.append(
            {
                "type": "claim_card_root_constraint",
                "role": "root_constraint",
                "source": "Step13 Claim Card",
                "id": root.get("principle_id") or card.get("claim_card_id"),
                "label": root.get("type") or "root constraint",
                "description": root.get("constraint"),
                "claim_scope": item.get("claim_scope"),
                "evidence_grade": item.get("evidence_grade") or item.get("evidence_tier"),
            }
        )
    for attempt in (card.get("attempts_last_10y") or [])[:4]:
        if not isinstance(attempt, dict):
            continue
        objects.append(
            {
                "type": "claim_card_attempt",
                "role": "past_attempt_failure",
                "source": "Step13 Claim Card",
                "paper_id": attempt.get("paper_id"),
                "label": attempt.get("attempt_path") or attempt.get("keyword") or "past attempt",
                "description": attempt.get("why_failed"),
                "event_year": attempt.get("year"),
                "evidence_quality": attempt.get("evidence_quality"),
                "section_provenance_strength": attempt.get("section_provenance_strength"),
                "click_target": {"kind": "paper", "id": attempt.get("paper_id")} if attempt.get("paper_id") else None,
            }
        )
    unresolved = card.get("unresolved_bottleneck") or {}
    for bottleneck in (unresolved.get("items") if isinstance(unresolved, dict) else []) or []:
        if not isinstance(bottleneck, dict):
            continue
        objects.append(
            {
                "type": "claim_card_unresolved_bottleneck",
                "role": "open_bottleneck",
                "source": "Step13 Claim Card",
                "paper_id": bottleneck.get("paper_id"),
                "label": bottleneck.get("keyword") or "unresolved bottleneck",
                "description": bottleneck.get("description"),
                "evidence_quality": bottleneck.get("evidence_quality"),
                "section_provenance_strength": bottleneck.get("section_provenance_strength"),
                "click_target": {"kind": "paper", "id": bottleneck.get("paper_id")} if bottleneck.get("paper_id") else None,
            }
        )
    return _compact_evidence_objects(objects, limit=12)


def _compact_evidence_objects(objects: list[dict[str, Any] | None], *, limit: int = 12) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for obj in objects:
        if not obj:
            continue
        key = (obj.get("type"), obj.get("paper_id") or obj.get("edge_id"), obj.get("label"))
        if key in seen:
            continue
        seen.add(key)
        out.append(obj)
        if len(out) >= limit:
            break
    return out


def _evidence_contract_for_five_questions(
    questions: list[dict[str, Any]],
    *,
    topic_dossier: dict[str, Any],
    turning_hits: list[dict[str, Any]],
    unresolved_limitations: list[dict[str, Any]],
    future_growth: list[dict[str, Any]],
    top_claim_card: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Attach evidence contracts to each user-facing first-principles answer.

    The five questions are the highest-level research brief shown in Topic Lens.
    They must therefore inherit the same evidence discipline as Claim Cards:
    explain what evidence supports the sentence, where it is weak, and why it
    cannot be promoted to Radar without stronger section/Claim Card support.
    """
    dossier_scope = str(topic_dossier.get("claim_scope") or "candidate_pool_only")
    dossier_grade = str(topic_dossier.get("evidence_grade") or "metadata_only")
    base_uncertainty = list(topic_dossier.get("uncertainty_reasons") or [])
    branch_evidence = [
        obj
        for split in topic_dossier.get("branch_splits", [])[:5]
        for obj in (split.get("evidence_objects") or [])
    ]
    bottleneck_evidence = [
        obj
        for bottleneck in topic_dossier.get("hard_bottlenecks", [])[:5]
        for obj in (bottleneck.get("evidence_objects") or [])
    ]
    turning_evidence = [
        _paper_evidence_object(
            paper,
            role="key_turning_paper",
            source="topic_main_path",
            why=(paper.get("reason") or {}).get("why") if isinstance(paper, dict) else None,
        )
        for paper in turning_hits[:6]
    ]
    limitation_evidence = [
        _limitation_evidence_object(lim, source="limitation_atoms")
        for lim in unresolved_limitations[:8]
    ]
    future_evidence = [
        _edge_evidence_object(edge, edge_type="future_candidate", source="Step5b VGAE candidate generator")
        for edge in future_growth[:8]
    ]
    future_gap_evidence = _compact_evidence_objects(
        [*bottleneck_evidence[:5], *branch_evidence[:5], *turning_evidence[:5]],
        limit=8,
    )

    has_complete_card = bool(top_claim_card and top_claim_card.get("five_question_complete"))
    card_strength = (
        str(top_claim_card.get("evidence_strength_level") or "")
        if isinstance(top_claim_card, dict)
        else ""
    )
    has_calibrated_future = any(_future_edge_has_run_calibration(edge) for edge in future_growth)
    future_calibration_gap = bool(future_growth) and not has_calibrated_future

    specs = [
        {
            "claim_scope": dossier_scope,
            "evidence_grade": "branch_evidence_context" if branch_evidence else dossier_grade,
            "required_evidence": ["branch split evidence", "driver papers", "topic-matched paper sections"],
            "objects": branch_evidence,
            "extra_uncertainty": ["branch claims remain weak unless lineage_status is evidence_backed_split"],
        },
        {
            "claim_scope": dossier_scope,
            "evidence_grade": "section_bottleneck_context" if bottleneck_evidence else dossier_grade,
            "required_evidence": ["section-level bottleneck atoms", "first-principles principle mapping"],
            "objects": bottleneck_evidence or limitation_evidence,
            "extra_uncertainty": ["root-constraint labels are evidence-linked hypotheses, not LLM-free causal proof"],
        },
        {
            "claim_scope": "topic_specific_turning_candidate",
            "evidence_grade": (
                "section_backed_turning_context"
                if any(_paper_has_traced_primary_evidence(p) for p in turning_hits)
                else "weak_section_turning_context"
                if any(_paper_has_primary_evidence(p) for p in turning_hits)
                else "metadata_turning_candidate"
            ),
            "required_evidence": ["topic-specific turning papers", "main-path weights", "linked citation support"],
            "objects": turning_evidence,
            "extra_uncertainty": ["linked refs below target can distort main-path turning-paper rank"],
        },
        {
            "claim_scope": "exploratory_bottleneck_claim",
            "evidence_grade": (
                "section_level_bottleneck_evidence"
                if any(str(lim.get("evidence_quality") or "").lower() == "section_level" for lim in unresolved_limitations)
                else "metadata_or_abstract_bottleneck"
            ),
            "required_evidence": ["limitation/discussion/conclusion/results/method/experiment sections", "resolution evidence"],
            "objects": limitation_evidence,
            "extra_uncertainty": ["unresolved does not mean impossible; it means no matching resolution evidence is linked yet"],
        },
        {
            "claim_scope": (
                "exploratory_with_claim_card"
                if has_complete_card
                else "candidate_pool_only"
            ),
            "evidence_grade": (
                f"claim_card_{card_strength}" if has_complete_card and card_strength else
                "calibrated_candidate_generator" if has_calibrated_future else
                "uncalibrated_candidate_generator" if future_evidence else
                "future_candidate_generation_gap"
            ),
            "required_evidence": [
                "rolling held-out-year calibration",
                "Step6 fusion",
                "complete Step13 Claim Card",
                "topic-matched future candidate endpoints",
            ],
            "objects": future_evidence or future_gap_evidence,
            "extra_uncertainty": (
                [] if has_complete_card else [
                    "future candidates are not Radar directions until Step6/Step13 Claim Card gates pass",
                    (
                        "future candidate edges lack rolling held-out-year run-level calibration"
                    ) if future_calibration_gap else "",
                    (
                        "no calibrated future candidate matched this topic; use branch/bottleneck evidence "
                        "as the next frontfill and backtest target"
                    ) if not future_evidence else "",
                ]
            ),
        },
    ]

    out: list[dict[str, Any]] = []
    for idx, question in enumerate(questions):
        spec = specs[min(idx, len(specs) - 1)]
        evidence_objects = _compact_evidence_objects(spec.get("objects") or [], limit=8)
        uncertainty = sorted(
            {
                item for item in [*base_uncertainty, *list(spec.get("extra_uncertainty") or [])]
                if item
            }
        )
        item = dict(question)
        item.update(
            {
                "claim_scope": spec["claim_scope"],
                "evidence_grade": spec["evidence_grade"] if evidence_objects else "insufficient",
                "uncertainty_reasons": uncertainty,
                "required_evidence": spec["required_evidence"],
                "evidence_objects": evidence_objects,
            }
        )
        out.append(item)
    return out


def _build_topic_branch_splits(
    topic: str,
    hits: list[dict[str, Any]],
    turning_hits: list[dict[str, Any]],
    branch_dossiers: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    facets = _topic_branch_facets(topic)
    source_papers = hits[:200]
    turning_by_id = {p.get("paper_id"): p for p in turning_hits}
    branch_contract_by_id = {
        str(b.get("branch_id")): b
        for b in (branch_dossiers or [])
        if isinstance(b, dict) and b.get("branch_id")
    }
    branch_contract_by_cluster = {
        str(b.get("cluster_id")): b
        for b in (branch_dossiers or [])
        if isinstance(b, dict) and b.get("cluster_id")
    }
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
        branch_ids = Counter(
            str(p.get("branch_id")) for p in matched if p.get("branch_id")
        )
        cluster_ids = Counter(
            str(p.get("cluster_id")) for p in matched if p.get("cluster_id")
        )
        dominant_branch_id = branch_ids.most_common(1)[0][0] if branch_ids else None
        dominant_cluster_id = cluster_ids.most_common(1)[0][0] if cluster_ids else None
        primary_section_evidence = sum(
            1
            for p in evidence
            if _paper_has_traced_primary_evidence(p)
        )
        evidence_objects = _compact_evidence_objects(
            [
                _paper_evidence_object(
                    p,
                    role="branch_driver",
                    source="topic_branch_facet",
                    why="turning/main-path evidence" if p.get("paper_id") in turning_by_id else "topic evidence",
                )
                for p in evidence
            ]
        )
        lineage = branch_contract_by_id.get(str(dominant_branch_id)) or branch_contract_by_cluster.get(str(dominant_cluster_id)) or {}
        lineage_status = str(lineage.get("lineage_status") or "weak_split_candidate")
        claim_scope = (
            str(lineage.get("claim_scope") or "weak_branch_split_candidate")
            if lineage
            else "topic_facet_with_driver_papers"
        )
        evidence_grade = (
            str(lineage.get("evidence_grade") or "graph_weak_branch_split")
            if lineage
            else (
                "section_backed_topic_branch_candidate"
                if primary_section_evidence
                else "metadata_topic_branch_candidate"
            )
        )
        uncertainty = [
            *(
                list(lineage.get("uncertainty_reasons") or [])
                if lineage
                else [
                    "branch matched by topic-specific facet and driver papers; branch_lineages parent evidence is not yet attached to this dossier item"
                ]
            ),
            *(
                []
                if primary_section_evidence
                else ["driver papers lack local primary section evidence in this card"]
            ),
        ]
        lineage_evidence_objects = [
            obj
            for obj in (lineage.get("evidence_objects") or [])
            if isinstance(obj, dict) and obj.get("type") == "branch_lineage"
        ]
        splits.append(
            {
                "name": facet["name"],
                "priority": facet.get("priority", 999),
                "paper_count": len(matched),
                "why_appeared": facet["why"],
                "historical_bottleneck": facet["bottleneck"],
                "enabling_condition": facet["enabler"],
                "first_seen_year": min((int(p.get("year")) for p in matched if p.get("year")), default=None),
                "dominant_branch_id": dominant_branch_id,
                "dominant_cluster_id": dominant_cluster_id,
                "parent_branch_id": lineage.get("parent_branch_id"),
                "split_year": lineage.get("split_year"),
                "split_confidence": lineage.get("split_confidence"),
                "lineage_status": lineage_status,
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
                "uncertainty_reasons": sorted(set(uncertainty)),
                "required_evidence": lineage.get("required_evidence") or [
                    "parent_branch_id with time-forward citation support",
                    "driver papers with local primary section evidence",
                    "constraint shift tied to limitation/discussion/conclusion/results sections",
                ],
                "split_reason": lineage.get("split_reason"),
                "constraint_shift": lineage.get("constraint_shift"),
                "driver_papers": [
                    _paper_ref(p, "turning/main-path evidence" if p.get("paper_id") in turning_by_id else "topic evidence")
                    for p in evidence
                ],
                "evidence_objects": _compact_evidence_objects([*lineage_evidence_objects, *evidence_objects]),
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
                "dominant_branch_id": branch_hits[0].get("branch_id") if branch_hits else None,
                "dominant_cluster_id": branch_hits[0].get("cluster_id") if branch_hits else None,
                "parent_branch_id": None,
                "lineage_status": "layout_cluster_only",
                "claim_scope": "exploratory_layout_cluster",
                "evidence_grade": "layout_cluster_only",
                "uncertainty_reasons": [
                    "no topic-specific branch facet or branch-lineage evidence matched this item",
                    "this may be useful for navigation but must not be narrated as scientific branch evolution",
                ],
                "driver_papers": [_paper_ref(p, "representative topic evidence") for p in branch_hits[:3]],
                "evidence_objects": _compact_evidence_objects(
                    [
                        _paper_evidence_object(
                            p,
                            role="branch_representative",
                            source="cluster_topic_concentration",
                            why="representative topic evidence",
                        )
                        for p in branch_hits[:3]
                    ]
                ),
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
        resolved_rows = [r for r in rows if _limitation_is_resolved(r)]
        unresolved_rows = [r for r in rows if not _limitation_is_resolved(r)]
        resolved_count = len(resolved_rows)
        unresolved_count = len(unresolved_rows)
        section_level_count = sum(
            1 for r in rows
            if str(r.get("evidence_quality") or "").lower() in {"section_level", "section"}
        )
        direct_count = sum(
            1 for r in rows
            if str(r.get("relationship_scope") or "direct_paper_match") == "direct_paper_match"
        )
        evidence_grade = (
            "section_backed_partial_resolution_candidate"
            if resolved_count and section_level_count
            else (
                "metadata_partial_resolution_candidate"
                if resolved_count
                else (
                    "section_backed_bottleneck_candidate"
                    if section_level_count
                    else "metadata_or_abstract_bottleneck_candidate"
                )
            )
        )
        claim_scope = (
            "topic_bottleneck_with_partial_resolution_evidence"
            if resolved_count
            else (
                "topic_bottleneck_candidate"
                if section_level_count
                else "weak_bottleneck_hypothesis"
            )
        )
        resolution_status = (
            "partially_addressed_but_still_open"
            if resolved_count and unresolved_count
            else (
                "resolved_evidence_observed_verify_generalization"
                if resolved_count
                else "open_no_resolution_evidence"
            )
        )
        uncertainty = [
            *(
                []
                if section_level_count
                else ["bottleneck is not backed by local primary section evidence"]
            ),
            *(
                []
                if direct_count
                else ["bottleneck evidence is cluster/branch context, not a direct topic-paper match"]
            ),
            *(
                ["no Step5c limitation_resolutions evidence is linked to this bottleneck yet"]
                if not resolved_count
                else []
            ),
            *(
                ["partial resolution evidence exists, but unresolved atoms remain open"]
                if resolved_count and unresolved_count
                else []
            ),
            *(
                ["resolution evidence exists; verify it generalizes across branches before treating the bottleneck as solved"]
                if resolved_count and not unresolved_count
                else []
            ),
        ]
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
                "status": resolution_status,
                "resolution_status": resolution_status,
                "evidence_count": len(rows),
                "resolved_evidence_count": resolved_count,
                "unresolved_evidence_count": unresolved_count,
                "evidence_quality": rows[0].get("evidence_quality") or "unknown",
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
                "uncertainty_reasons": sorted(set(uncertainty)),
                "direct_evidence_count": direct_count,
                "section_level_evidence_count": section_level_count,
                "why_it_matters": (
                    f"{label} recurs in the topic evidence with {unresolved_count} open atom(s) and "
                    f"{resolved_count} Step5c resolution atom(s). Treat it as solved only when resolution "
                    "evidence is section-backed and no topic-relevant open atoms remain."
                ),
                "evidence_papers": papers[:5],
                "resolution_evidence": [
                    {
                        "atom_id": r.get("atom_id"),
                        "paper_id": r.get("paper_id"),
                        "resolver_paper_id": r.get("resolver_paper_id"),
                        "resolution_year": r.get("resolved_year"),
                        "resolution_confidence": r.get("resolution_confidence"),
                        "evidence_text": r.get("resolution_evidence_text"),
                    }
                    for r in resolved_rows[:5]
                ],
                "sample_evidence": [
                    {
                        "atom_id": r.get("atom_id"),
                        "paper_id": r.get("paper_id"),
                        "description": r.get("description"),
                        "keyword": r.get("keyword"),
                        "evidence_quality": r.get("evidence_quality"),
                        "is_resolved": int(bool(_limitation_is_resolved(r))),
                        "n_resolutions": int(r.get("n_resolutions") or 0),
                    }
                    for r in rows[:4]
            ],
            "evidence_objects": _compact_evidence_objects(
                [
                    *[
                        _paper_evidence_object(
                            by_id.get(lim.get("paper_id")) or {"paper_id": lim.get("paper_id"), "title": lim.get("title")},
                            role="bottleneck_paper",
                            source="limitation_atoms",
                            why=f"limitation evidence: {lim.get('keyword') or label}",
                        )
                        for lim in rows[:5]
                    ],
                    *[_limitation_evidence_object(lim, source="limitation_atoms") for lim in rows[:5]],
                    *[
                        _limitation_resolution_evidence_object(lim, source="limitation_resolutions")
                        for lim in resolved_rows[:5]
                    ],
                ],
                limit=10,
            ),
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
                "evidence_grade": item.get("evidence_grade") or (
                    "complete_claim_card"
                    if item.get("claim_card", {}).get("five_question_complete")
                    else "incomplete_claim_card"
                ),
                "uncertainty_reasons": [
                    *(
                        []
                        if item.get("eligible")
                        else ["Claim Card exists but high-confidence gates are not fully passed"]
                    ),
                    *list(item.get("missing_high_confidence_gates") or []),
                ],
                "why_worth_testing": item.get("plain_language"),
                "why_not_ready": None if item.get("eligible") else "Claim Card exists but high-confidence gates are not fully passed.",
                "minimal_validation_experiment": item.get("minimal_validation_experiment")
                or _format_minimal_validation_experiment(
                    (item.get("claim_card") or {}).get("minimal_validation_experiment")
                ),
                "can_explain": [
                    "what the complete five-question Claim Card proposes to validate",
                    "which evidence objects and papers support the validation plan",
                    "which high-confidence gates still block promotion",
                ],
                "cannot_explain": [
                    "high-confidence status when section/calibration gates fail",
                    "successful validation before the minimal experiment is run",
                    "raw GNN edge conclusions",
                ],
                "required_evidence": item.get("required_evidence") or [
                    "complete five-question Step13 Claim Card",
                    "strong/moderate section evidence for unresolved bottleneck claims",
                    "rolling held-out-year calibration audit",
                    "minimal validation experiment result with falsification check",
                ],
                "evidence_papers": item.get("evidence_papers") or [],
                "source": "Step6/Step13 Claim Card",
                "evidence_objects": item.get("evidence_objects") or _claim_card_evidence_objects(item),
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
                "evidence_grade": (
                    "section_backed_validation_candidate"
                    if str(bottleneck.get("evidence_grade") or "").startswith("section_backed")
                    and str(branch.get("evidence_grade") or "").startswith("section_backed")
                    else "weak_validation_candidate"
                ),
                "uncertainty_reasons": sorted(
                    set(
                        [
                            "No complete Step13 five-question Claim Card yet",
                            "validation direction is assembled from branch and bottleneck evidence, not promoted Radar evidence",
                            *list(branch.get("uncertainty_reasons") or []),
                            *list(bottleneck.get("uncertainty_reasons") or []),
                        ]
                    )
                ),
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
                "can_explain": [
                    "which branch and bottleneck should be tested together",
                    "why the topic has a plausible 6-18 month validation target",
                    "which evidence objects should be read before experiment design",
                ],
                "cannot_explain": [
                    "that the direction is ready for Radar",
                    "that the named bottleneck is solved",
                    "commercial or investment priority without a complete Claim Card",
                ],
                "required_evidence": [
                    "complete Step13 five-question Claim Card",
                    "section-level bottleneck and resolution evidence",
                    "calibrated future candidate or explicit non-GNN rationale",
                    "minimal validation experiment with success and falsification criteria",
                ],
                "evidence_papers": (branch.get("driver_papers") or [])[:3] + (bottleneck.get("evidence_papers") or [])[:2],
                "source": "topic branch + limitation evidence",
                "evidence_objects": _compact_evidence_objects(
                    [
                        *[
                            _paper_evidence_object(
                                p,
                                role="validation_branch_driver",
                                source="topic_branch",
                                why=p.get("why") if isinstance(p, dict) else None,
                            )
                            for p in (branch.get("driver_papers") or [])[:3]
                        ],
                        *[
                            _paper_evidence_object(
                                p,
                                role="validation_bottleneck_evidence",
                                source="bottleneck_dossier",
                                why=p.get("why") if isinstance(p, dict) else None,
                            )
                            for p in (bottleneck.get("evidence_papers") or [])[:2]
                        ],
                        *((bottleneck.get("evidence_objects") or [])[:4] if isinstance(bottleneck, dict) else []),
                    ],
                    limit=10,
                ),
            }
        )
    if not directions and future_growth:
        for edge in future_growth[:5]:
            calibration_status = _future_edge_calibration_status(edge)
            evidence_grade = _future_edge_evidence_grade(edge)
            directions.append(
                {
                    "name": f"Audit future candidate: {edge.get('source_paper_id')} -> {edge.get('target_paper_id')}",
                    "claim_scope": "candidate_pool_only",
                    "evidence_strength": evidence_grade,
                    "evidence_grade": evidence_grade,
                    "uncertainty_reasons": [
                        "GNN/VGAE is a candidate generator, not a conclusion generator",
                        "missing Step6 fusion evidence",
                        "missing Step13 five-question Claim Card",
                        *(
                            []
                            if calibration_status == "calibrated_with_run_audit"
                            else [calibration_status.replace("_", " ")]
                        ),
                    ],
                    "why_worth_testing": "Step5b/GNN suggests a possible growth link; use it for candidate generation only.",
                    "why_not_ready": "Missing Step6 fusion and Step13 Claim Card.",
                    "minimal_validation_experiment": "Read both endpoint papers, map the shared bottleneck, then design a falsifiable experiment.",
                    "can_explain": [
                        "which GNN/VGAE endpoint pair to inspect next",
                        "where to look for shared bottleneck evidence",
                        "candidate-pool prioritization for Step6/Step13 evidence gathering",
                    ],
                    "cannot_explain": [
                        "that the candidate link will become a validated future outcome",
                        "that the direction is valid or investable",
                        "Radar promotion without a complete Claim Card",
                    ],
                    "required_evidence": [
                        "rolling held-out-year calibration audit",
                        "Step6 fusion evidence",
                        "Step13 five-question Claim Card",
                        "section-level bottleneck evidence",
                    ],
                    "evidence_papers": [
                        _paper_ref(edge.get("source_paper") or {"paper_id": edge.get("source_paper_id")}, "future edge source"),
                        _paper_ref(edge.get("target_paper") or {"paper_id": edge.get("target_paper_id")}, "future edge target"),
                    ],
                    "source": "Step5b GNN candidate",
                    "evidence_objects": _compact_evidence_objects(
                        [
                            _edge_evidence_object(edge, edge_type="future_candidate", source="Step5b VGAE"),
                            _paper_evidence_object(
                                edge.get("source_paper") or {"paper_id": edge.get("source_paper_id")},
                                role="future_source",
                                source="Step5b VGAE",
                                why="future edge source",
                            ),
                            _paper_evidence_object(
                                edge.get("target_paper") or {"paper_id": edge.get("target_paper_id")},
                                role="future_target",
                                source="Step5b VGAE",
                                why="future edge target",
                            ),
                        ],
                        limit=8,
                    ),
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


def _lineage_status(split_evidence: dict[str, Any], split_confidence: Any) -> str:
    if not isinstance(split_evidence, dict):
        split_evidence = {}
    explicit = str(split_evidence.get("lineage_status") or "").strip()
    if explicit:
        return explicit
    support = int(split_evidence.get("parent_citation_support") or 0)
    try:
        conf = float(split_confidence or split_evidence.get("parent_support_ratio") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    if support >= 8 and conf >= 0.30:
        return "evidence_backed_split"
    if support >= 3:
        return "weak_split_candidate"
    return "layout_cluster_only"


def _split_reason(branch_id: str, parent_branch_id: Any, split_evidence: dict[str, Any]) -> str:
    if not isinstance(split_evidence, dict):
        split_evidence = {}
    explicit = str(split_evidence.get("split_reason") or "").strip()
    if explicit:
        return explicit
    support = int(split_evidence.get("parent_citation_support") or 0)
    ratio = float(split_evidence.get("parent_support_ratio") or 0.0)
    if parent_branch_id:
        return (
            f"Parent branch {parent_branch_id} is selected by {support} time-forward "
            f"cross-cluster citation flows into {branch_id}; support ratio={ratio:.2f}."
        )
    return "No reliable parent branch was found; this is treated as a root or layout-only cluster."


def _branch_lineage_contract(item: dict[str, Any], lineage_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(lineage_payload, dict):
        lineage_payload = {}
    lineage_status = _lineage_status(lineage_payload, item.get("split_confidence"))
    support = int(lineage_payload.get("parent_citation_support") or 0)
    if lineage_status == "evidence_backed_split":
        claim_scope = "evidence_backed_branch_split_candidate"
        evidence_grade = "graph_backed_branch_split"
    elif lineage_status == "weak_split_candidate":
        claim_scope = "weak_branch_split_candidate"
        evidence_grade = "graph_weak_branch_split"
    else:
        claim_scope = "layout_cluster_navigation_only"
        evidence_grade = "layout_cluster_only"
    uncertainty = [
        *(
            []
            if lineage_status == "evidence_backed_split"
            else ["branch split is not strongly backed by parent-child lineage evidence"]
        ),
        "cluster-panel lineage is graph-level context until driver papers have local primary section evidence",
        *(
            ["layout clusters are navigation aids and must not be narrated as causal scientific evolution"]
            if lineage_status == "layout_cluster_only"
            else []
        ),
    ]
    return {
        "lineage_status": lineage_status,
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade,
        "uncertainty_reasons": sorted(set(uncertainty)),
        "required_evidence": [
            "parent_branch_id with time-forward citation support",
            "driver papers with local primary section evidence",
            "constraint shift tied to limitation/discussion/conclusion/results sections",
            "branch split support score and audit trail",
        ],
        "evidence_objects": _compact_evidence_objects(
            [
                {
                    "type": "branch_lineage",
                    "role": "cluster_panel_branch_lineage",
                    "source": "branch_lineages",
                    "id": f"branch_lineage:{item.get('branch_id') or ''}",
                    "label": f"{item.get('parent_branch_id') or 'root'} -> {item.get('branch_id') or '-'}",
                    "relationship": "split_evidence",
                    "lineage_status": lineage_status,
                    "support_score": item.get("split_confidence"),
                    "description": item.get("split_reason"),
                    "claim_scope": claim_scope,
                    "evidence_grade": evidence_grade,
                    "support_count": support,
                }
            ],
            limit=4,
        ),
    }


def _story_focus_paper_object(paper: Any) -> dict[str, Any] | None:
    if isinstance(paper, dict):
        pid = paper.get("paper_id") or paper.get("id")
        data = {
            "paper_id": pid,
            "title": paper.get("title"),
            "year": paper.get("year"),
            "cluster_id": paper.get("cluster_id"),
            "branch_id": paper.get("branch_id"),
        }
    else:
        data = {"paper_id": str(paper) if paper else None}
    return _paper_evidence_object(
        data,
        role="story_focus_paper",
        source="visual_story_steps",
        why="paper used to anchor this Story Mode time slice",
    )


def _story_step_contract(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    step_id = str(item.get("story_step_id") or "")
    is_future = step_id.endswith(":future") or "future" in step_id or "predicted_future_edges" in str(evidence.get("source") or "")
    if is_future:
        claim_scope = "candidate_pool_only"
        evidence_grade = "future_candidate_story_context"
        required_evidence = [
            "rolling held-out-year calibration audit",
            "Step6 fusion evidence",
            "complete Step13 Claim Card",
            "section-level bottleneck evidence",
        ]
        uncertainty = [
            "Story Mode future slice is a candidate-generation view, not a conclusion",
            "future candidates cannot enter Radar without complete Claim Cards",
        ]
    else:
        claim_scope = "timeline_context_only"
        evidence_grade = "metadata_cluster_timeline_context"
        required_evidence = [
            "linked citation/main-path support",
            "branch_lineages evidence for parent-child splits",
            "representative papers with local primary section evidence",
            "bottleneck or Claim Card evidence before decision claims",
        ]
        uncertainty = [
            "Story Mode is explanatory timeline context, not decision-grade evidence",
            "cluster activity does not prove causal branch evolution without branch lineage evidence",
        ]
    focus_papers = item.get("focus_papers") if isinstance(item.get("focus_papers"), list) else []
    if not focus_papers:
        uncertainty.append("story step has no focus papers attached")
    story_object = {
        "type": "visual_story_step",
        "role": "story_timeline_context",
        "source": "visual_story_steps",
        "id": step_id,
        "label": item.get("title") or step_id,
        "relationship": "timeline_slice",
        "description": item.get("narrative"),
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade,
        "focus_cluster_id": item.get("focus_cluster_id"),
        "year_start": item.get("year_start"),
        "year_end": item.get("year_end"),
        "click_target": {"kind": "story_step", "id": step_id},
    }
    evidence_objects = _compact_evidence_objects(
        [
            story_object,
            *[_story_focus_paper_object(p) for p in focus_papers[:5]],
        ],
        limit=8,
    )
    return {
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade,
        "uncertainty_reasons": sorted(set(uncertainty)),
        "required_evidence": required_evidence,
        "evidence_objects": evidence_objects,
    }


def _paper_role_contract(
    paper: dict[str, Any],
    edges: list[dict[str, Any]],
    *,
    visual_role: str,
    why_parts: list[str],
) -> dict[str, Any]:
    layer_keys = {
        "main_path" if edge.get("is_main_path") else str(edge.get("layer") or edge.get("edge_type") or "edge")
        for edge in edges
    }
    has_traced_section = _paper_has_traced_primary_evidence(paper)
    has_primary_section = _paper_has_primary_evidence(paper)
    if "future" in layer_keys or visual_role == "future_anchor":
        claim_scope = "candidate_pool_only"
        evidence_grade = (
            "section_context_future_endpoint"
            if has_traced_section
            else "graph_future_endpoint_context"
        )
    elif visual_role == "limitation_bottleneck" or (paper.get("limitations") or []):
        claim_scope = "bottleneck_context_only"
        evidence_grade = (
            "section_bottleneck_context"
            if has_traced_section
            else "weak_bottleneck_context"
            if has_primary_section
            else "metadata_bottleneck_context"
        )
    elif "main_path" in layer_keys:
        claim_scope = "main_path_context_only"
        evidence_grade = (
            "section_backed_main_path_context"
            if has_traced_section
            else "graph_main_path_context"
        )
    else:
        claim_scope = "retrieval_context_only"
        evidence_grade = "metadata_search_context"
    uncertainty = [
        "paper detail explains why the item is shown; it is not a standalone scientific conclusion",
        *(
            []
            if has_traced_section
            else ["paper lacks strong/moderate local primary section evidence in this detail view"]
        ),
        *(
            ["future endpoint evidence cannot enter Radar without Step6 fusion and a complete Claim Card"]
            if claim_scope == "candidate_pool_only"
            else []
        ),
    ]
    required_evidence = [
        "local primary section evidence with strong/moderate parser provenance",
        "linked citation context when used for main-path claims",
        "branch/bottleneck lineage evidence before narrating causal evolution",
        "complete Step13 Claim Card before promotion to Radar",
    ]
    evidence_objects = _compact_evidence_objects(
        [
            _paper_evidence_object(
                paper,
                role="selected_paper_detail",
                source="visual_paper_detail",
                why="; ".join(why_parts[:3]) if why_parts else "selected from visual graph",
            ),
            *[
                _edge_evidence_object(
                    edge,
                    edge_type="main_path_edge" if edge.get("is_main_path") else str(edge.get("layer") or edge.get("edge_type") or "edge"),
                    source="visual_paper_detail",
                )
                for edge in edges[:5]
            ],
        ],
        limit=8,
    )
    return {
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade,
        "uncertainty_reasons": sorted(set(uncertainty)),
        "required_evidence": required_evidence,
        "evidence_objects": evidence_objects,
    }


def _visual_node_role_contract(node: dict[str, Any]) -> dict[str, Any]:
    visual_role = str(node.get("visual_role") or node.get("role") or "paper")
    flags = node.get("flags")
    if not isinstance(flags, dict):
        flags = _loads(node.get("flags_json"), {})
    try:
        uncertainty_score = float(node.get("uncertainty_score") or 0.0)
    except (TypeError, ValueError):
        uncertainty_score = 0.0

    if visual_role == "future_anchor" or flags.get("is_future_anchor"):
        claim_scope = "candidate_pool_only"
        evidence_grade = "graph_future_anchor_context"
    elif visual_role == "limitation_bottleneck" or flags.get("has_unresolved_limitation"):
        claim_scope = "bottleneck_context_only"
        evidence_grade = "graph_bottleneck_node_context"
    elif visual_role == "main_path" or flags.get("is_main_path"):
        claim_scope = "main_path_context_only"
        evidence_grade = "graph_main_path_node_context"
    else:
        claim_scope = "retrieval_context_only"
        evidence_grade = "graph_node_role_context"

    uncertainty = [
        "visual node role is navigation context, not a standalone scientific conclusion",
        "node hover does not include local section evidence; open paper detail or Claim Card before using it as evidence",
    ]
    if uncertainty_score >= 0.5:
        uncertainty.append("visual embedding uncertainty score is elevated")
    if claim_scope == "candidate_pool_only":
        uncertainty.append("future anchors remain candidate-pool context until Step6 fusion and a complete Claim Card")

    evidence_object = {
        "type": "visual_node_role",
        "role": "graph_node_context",
        "source": "visual_nodes",
        "paper_id": node.get("paper_id"),
        "label": node.get("title") or node.get("paper_id"),
        "year": node.get("year") or node.get("publication_year"),
        "visual_role": visual_role,
        "cluster_id": node.get("cluster_id"),
        "branch_id": node.get("branch_id"),
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade,
        "uncertainty_score": uncertainty_score,
        "flags": flags,
        "click_target": {"kind": "paper", "id": node.get("paper_id")} if node.get("paper_id") else None,
    }
    return {
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade,
        "uncertainty_reasons": sorted(set(uncertainty)),
        "required_evidence": [
            "paper detail with local primary section evidence",
            "linked citation context when used for main-path claims",
            "branch/bottleneck lineage evidence before narrating causal evolution",
            "complete Step13 Claim Card before promotion to Radar",
        ],
        "evidence_objects": _compact_evidence_objects([evidence_object], limit=3),
    }


def _visual_edge_contract(edge: dict[str, Any], frontfill: dict[str, Any] | None = None) -> dict[str, Any]:
    layer_key = (
        "main_path"
        if edge.get("is_main_path") or edge.get("edge_type") == "main_path"
        else str(edge.get("layer") or edge.get("edge_type") or "edge")
    )
    evidence = edge.get("evidence") if isinstance(edge.get("evidence"), dict) else {}
    frontfill = frontfill if isinstance(frontfill, dict) else {}
    linked_ref_rate = float(frontfill.get("linked_ref_rate") or 0.0)

    if layer_key == "future" or edge.get("edge_type") == "future_growth":
        contract = _future_edge_claim_contract(edge)
        contract["evidence_objects"] = _compact_evidence_objects(
            [
                _edge_evidence_object(edge, edge_type="visual_edge", source="visual_edges"),
                *contract.get("evidence_objects", []),
            ],
            limit=5,
        )
        return contract
    if layer_key == "main_path":
        claim_scope = "main_path_context_only"
        evidence_grade = (
            "citation_backbone_partial_low_linked_refs"
            if linked_ref_rate < 0.30
            else "citation_backbone_context"
        )
        uncertainty = [
            "main-path visual edge is historical trunk context, not a standalone causal conclusion",
        ]
    elif layer_key == "citation":
        claim_scope = "citation_context_only"
        evidence_grade = "local_citation_edge_context"
        uncertainty = ["citation visual edge needs ID-relinked reference support before causal interpretation"]
    elif layer_key == "topic":
        claim_scope = "community_context_only"
        evidence_grade = "co_citation_context"
        uncertainty = ["topic/co-citation edge indicates shared community context, not direct influence"]
    elif layer_key == "semantic":
        claim_scope = "retrieval_context_only"
        evidence_grade = "embedding_similarity_context"
        uncertainty = ["semantic edge is a retrieval expansion aid, not historical evidence"]
    elif layer_key == "bottleneck":
        claim_scope = "bottleneck_context_only"
        evidence_grade = "graph_bottleneck_edge_context"
        uncertainty = ["bottleneck edge requires section-level limitation/resolution evidence before decision use"]
    else:
        claim_scope = "graph_edge_context_only"
        evidence_grade = "visual_edge_context"
        uncertainty = ["visual edge is graph context and needs paper-level evidence before decision use"]

    if linked_ref_rate < 0.30 and layer_key in {"main_path", "citation"}:
        uncertainty.append("linked refs below 30%; citation evolution is incomplete and must stay uncertainty-labeled")
    if not evidence:
        uncertainty.append("edge has no supporting evidence payload beyond visual graph metadata")

    evidence_object = _edge_evidence_object(edge, edge_type="visual_edge", source="visual_edges")
    if evidence_object:
        evidence_object.update(
            {
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
                "layer": layer_key,
                "relationship_scope": evidence.get("relationship_scope"),
            }
        )
    return {
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade,
        "uncertainty_reasons": sorted(set(uncertainty)),
        "required_evidence": [
            "ID-relinked local citation support for citation/main-path claims",
            "source and target paper detail evidence",
            "section-level evidence when the edge is used for bottleneck or Claim Card claims",
            "Step6 fusion and complete Step13 Claim Card before decision promotion",
        ],
        "evidence_objects": _compact_evidence_objects([evidence_object], limit=3),
    }


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
        branch_id = row.get("branch_id") or c.get("branch_id")
        split_confidence = row.get("split_confidence") if row.get("split_confidence") is not None else row.get("strength")
        lineage_payload = split_evidence or why
        lineage_status = _lineage_status(lineage_payload, split_confidence)
        driver_ids = []
        if isinstance(lineage_payload, dict):
            driver_ids = [str(x) for x in (lineage_payload.get("driver_papers") or []) if x]
        driver_papers = _hydrate_hits(conn, driver_ids[:5], scores={}) if driver_ids else []
        representative_evidence = driver_papers or rep_papers
        primary_driver_sections = sum(
            1
            for p in representative_evidence
            if _paper_has_traced_primary_evidence(p)
        )
        split_reason = _split_reason(str(branch_id or cid), row.get("parent_branch_id"), lineage_payload)
        constraint_shift = (
            lineage_payload.get("constraint_shift")
            if isinstance(lineage_payload, dict)
            else None
        ) or {
            "status": "inferred_from_terms_pending_section_evidence",
            "note": "Use top terms, driver papers, and section-level bottleneck evidence before treating this as a causal split.",
        }
        if lineage_status == "evidence_backed_split":
            claim_scope = "evidence_backed_branch_split_candidate"
            evidence_grade = (
                "section_backed_branch_split"
                if primary_driver_sections
                else "graph_backed_branch_split"
            )
        elif lineage_status == "weak_split_candidate":
            claim_scope = "weak_branch_split_candidate"
            evidence_grade = (
                "section_context_weak_branch_split"
                if primary_driver_sections
                else "graph_weak_branch_split"
            )
        else:
            claim_scope = "layout_cluster_navigation_only"
            evidence_grade = "layout_cluster_only"
        uncertainty = [
            *(
                []
                if lineage_status == "evidence_backed_split"
                else ["branch split is not strongly backed by parent-child lineage evidence"]
            ),
            *(
                []
                if primary_driver_sections
                else ["branch driver/representative papers lack local primary section evidence in this card"]
            ),
            *(
                ["layout clusters are navigation aids and must not be narrated as causal scientific evolution"]
                if lineage_status == "layout_cluster_only"
                else []
            ),
        ]
        required_evidence = [
            "parent_branch_id with time-forward citation support",
            "driver papers with local primary section evidence",
            "constraint shift tied to limitation/discussion/conclusion/results sections",
            "branch split support score and audit trail",
        ]
        branch_evidence_objects = [
            {
                "type": "branch_lineage",
                "role": "branch_split_evidence",
                "source": "branch_lineages",
                "id": f"branch_lineage:{branch_id or cid}",
                "label": f"{row.get('parent_branch_id') or 'root'} -> {branch_id or cid}",
                "relationship": "split_evidence",
                "lineage_status": lineage_status,
                "support_score": split_confidence,
                "description": split_reason,
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
            }
        ] + [
            _paper_evidence_object(
                p,
                role="branch_split_driver" if driver_papers else "branch_representative",
                source="branch_lineages" if driver_papers else "visual_cluster_representatives",
                why="branch split driver" if driver_papers else "branch representative while driver evidence is missing",
            )
            for p in representative_evidence[:3]
        ]
        dossiers.append(
            {
                "cluster_id": cid,
                "branch_id": branch_id,
                "label": _clean_branch_label(row.get("label"), cid),
                "topic_match_count": count,
                "topic_share": count / total,
                "global_paper_count": int(row.get("n_nodes") or 0),
                "year_range": [row.get("year_start"), row.get("year_end")],
                "parent_branch_id": row.get("parent_branch_id"),
                "split_year": row.get("split_year"),
                "split_confidence": split_confidence,
                "lineage_status": lineage_status,
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
                "uncertainty_reasons": sorted(set(uncertainty)),
                "required_evidence": required_evidence,
                "split_reason": split_reason,
                "constraint_shift": constraint_shift,
                "split_evidence": lineage_payload,
                "future_hint": future,
                "top_terms": [str(x) for x in (terms or [])[:8] if x],
                "representative_papers": rep_papers,
                "driver_papers": [_paper_ref(p, "branch split driver") for p in driver_papers],
                "evidence_objects": branch_evidence_objects,
                "interpretation": (
                    (
                        f"This branch is an evidence-backed split for the topic's {row.get('label') or cid} neighborhood. "
                        if lineage_status == "evidence_backed_split"
                        else f"This branch is a weak/layout-derived hypothesis for the topic's {row.get('label') or cid} neighborhood. "
                    )
                    + "Use driver papers and section bottleneck evidence before treating it as a real lineage split."
                ),
            }
        )
    return dossiers


def _build_bottleneck_lineage(
    principles: list[dict[str, Any]],
    history_events: list[dict[str, Any]],
    unresolved_limitations: list[dict[str, Any]],
    lineage_triples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    event_by_principle: dict[str, list[dict[str, Any]]] = {}
    for event in history_events:
        event_by_principle.setdefault(str(event.get("principle_id")), []).append(event)
    triples_by_principle: dict[str, list[dict[str, Any]]] = {}
    for triple in lineage_triples or []:
        triples_by_principle.setdefault(str(triple.get("principle_id")), []).append(triple)
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
        keyword_set = {x.lower() for x in keyword_list}
        matched_limitations = [
            x
            for x in unresolved_limitations
            if not keyword_set
            or str(x.get("keyword") or "").lower() in keyword_set
            or any(k and k in str(x.get("description") or "").lower() for k in keyword_set)
        ][:6]
        triples = sorted(
            triples_by_principle.get(pid, []),
            key=lambda x: (
                -(int(x.get("event_year") or 0)),
                int(x.get("edge_order") or 0),
            ),
        )[:10]
        has_section_triple = any(
            "section" in str(x.get("evidence_quality") or "").lower()
            for x in triples
        )
        has_section_limitation = any(
            "section" in str(x.get("evidence_quality") or "").lower()
            for x in matched_limitations
        )
        if has_section_triple:
            evidence_grade = "typed_section_lineage"
            claim_scope = "bottleneck_lineage_evidence"
        elif has_section_limitation:
            evidence_grade = "section_bottleneck_context"
            claim_scope = "exploratory_bottleneck_lineage"
        elif triples:
            evidence_grade = "typed_metadata_lineage"
            claim_scope = "exploratory_bottleneck_lineage"
        else:
            evidence_grade = "aggregate_bottleneck_history"
            claim_scope = "lineage_prior_until_typed_section_evidence"
        uncertainty = [
            "bottleneck lineage is evidence context; high-confidence direction claims still require Step6/Step13 Claim Card gates"
        ]
        if not triples:
            uncertainty.append("no typed constraint->failure->attempt lineage triples matched this principle")
        if not has_section_triple:
            uncertainty.append("lineage lacks section-level typed triples for this topic")
        if not matched_limitations:
            uncertainty.append("no topic-matched limitation atoms attached to this root constraint")
        required_evidence = [
            "typed triples from limitation/discussion/conclusion/results/method sections",
            "paper-level section evidence with page/section provenance",
            "resolved and unresolved atoms separated over time",
        ]
        typed_chain = [
            {
                "triple_id": t.get("triple_id"),
                "source_stage": t.get("source_stage"),
                "target_stage": t.get("target_stage"),
                "source_text": t.get("source_text"),
                "target_text": t.get("target_text"),
                "relation_type": t.get("relation_type"),
                "paper_id": t.get("paper_id"),
                "resolver_paper_id": t.get("resolver_paper_id"),
                "event_year": t.get("event_year"),
                "evidence_section": t.get("evidence_section"),
                "evidence_page": t.get("evidence_page"),
                "evidence_quality": t.get("evidence_quality"),
                "evidence_weight": t.get("evidence_weight"),
            }
            for t in triples[:5]
        ]
        evidence_objects = _compact_evidence_objects(
            [
                *[
                    _lineage_triple_evidence_object(t, source="bottleneck_lineage_graph")
                    for t in triples[:6]
                ],
                *[
                    _limitation_evidence_object(lim, source="topic_bottleneck_lineage")
                    for lim in matched_limitations[:4]
                ],
            ],
            limit=10,
        )
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
                "typed_chain": typed_chain,
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
                "can_explain": [
                    "which root constraint is linked to limitation atoms and typed lineage triples",
                    "how constraint/failure/attempt/fix stages appear in the available evidence",
                    "where to inspect section-level bottleneck evidence before Claim Card promotion",
                ],
                "cannot_explain": [
                    "a proven causal root-cause chain when section-level typed triples are missing",
                    "that a bottleneck is solved without linked resolution atoms",
                    "high-confidence R&D direction value without Step6/Step13 Claim Cards",
                ],
                "uncertainty_reasons": sorted(set(uncertainty)),
                "required_evidence": required_evidence,
                "evidence_objects": evidence_objects,
                "interpretation": (
                    "Root constraint lineage: opened/resolved backlog over time. "
                    "High backlog with weak section evidence remains exploratory; only typed section lineage "
                    "can support strong bottleneck-history claims."
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
    incomplete_cards: list[dict[str, Any]] = []
    for d in future_directions[:12]:
        card = d.get("claim_card") or {}
        quality_gate = card.get("quality_gate") or {}
        five_complete = bool(card.get("five_question_complete"))
        eligible = bool(card.get("high_confidence_eligible"))
        missing_gates = list(quality_gate.get("missing_gates") or [])
        missing_high_conf = list(quality_gate.get("missing_high_confidence_gates") or [])
        evidence_grade = str(
            card.get("evidence_grade")
            or d.get("evidence_grade")
            or d.get("evidence_tier")
            or card.get("evidence_strength_level")
            or (
                "complete_claim_card_pending_high_confidence_evidence"
                if five_complete
                else "incomplete_claim_card"
            )
        )
        uncertainty = [
            *list(d.get("uncertainty_reasons") or []),
            *list(card.get("uncertainty_reasons") or []),
            *[f"missing five-question gate: {gate}" for gate in missing_gates],
            *[f"missing high-confidence gate: {gate}" for gate in missing_high_conf],
        ]
        if five_complete and not eligible:
            uncertainty.append("complete Claim Card remains exploratory until high-confidence evidence gates pass")
        required_evidence = [
            "strong/moderate section evidence for unresolved bottleneck claims",
            "rolling held-out-year calibration audit for linked future candidates",
            "successful minimal validation experiment with explicit falsification conditions",
            "expert review before investment-grade interpretation",
            *[f"missing five-question gate: {gate}" for gate in missing_gates],
            *[f"missing high-confidence gate: {gate}" for gate in missing_high_conf],
        ]
        item = {
            "kind": "claim_card" if five_complete else "incomplete_claim_card",
            "title": d.get("direction_name") or d.get("direction_id"),
            "priority": d.get("confidence"),
            "technical_score": d.get("confidence"),
            "commercial_relevance": d.get("commercial_relevance"),
            "validation_cost": d.get("validation_cost"),
            "claim_scope": d.get("claim_scope") or ("radar_claim_card" if five_complete else "candidate_pool_only"),
            "evidence_grade": evidence_grade,
            "uncertainty_reasons": sorted(set(uncertainty)),
            "required_evidence": sorted(set(required_evidence)),
            "evidence_tier": d.get("evidence_tier"),
            "eligible": eligible,
            "claim_card": card,
            "missing_gates": missing_gates,
            "missing_high_confidence_gates": missing_high_conf,
            "plain_language": (
                "Decision-grade Claim Card is complete; read eligibility gates before treating it as high confidence."
                if five_complete
                else "Incomplete Claim Card: this direction remains in the candidate pool until all five questions are answered."
            ),
        }
        item["minimal_validation_experiment"] = _format_minimal_validation_experiment(
            card.get("minimal_validation_experiment")
        )
        item["evidence_objects"] = _claim_card_evidence_objects(item)
        item["evidence_papers"] = [
            {
                "paper_id": obj.get("paper_id"),
                "title": obj.get("label") or obj.get("paper_id"),
                "year": obj.get("event_year"),
                "why": obj.get("role"),
            }
            for obj in item["evidence_objects"]
            if obj.get("paper_id")
        ][:6]
        if five_complete:
            claim_cards.append(item)
        else:
            incomplete_cards.append(item)
    candidate_pool: list[dict[str, Any]] = []
    candidate_pool.extend(incomplete_cards)
    for e in future_growth[:20]:
        src = (e.get("source_paper") or {}).get("title") or e.get("source_paper_id")
        dst = (e.get("target_paper") or {}).get("title") or e.get("target_paper_id")
        conf = float(e.get("confidence") or e.get("weight") or 0.0)
        evidence = e.get("evidence") or {}
        lifecycle_missing = evidence.get("missing_gates") or []
        lifecycle_reason = evidence.get("candidate_pool_reason")
        calibration_status = _future_edge_calibration_status(e)
        evidence_grade = _future_edge_evidence_grade(e)
        calibration_uncertainty = [] if calibration_status == "calibrated_with_run_audit" else [
            calibration_status.replace("_", " ")
        ]
        candidate_pool.append(
            {
                "kind": "candidate_edge",
                "title": f"{src} -> {dst}",
                "priority": round(conf * 0.55, 4),
                "candidate_score": conf,
                "model_evidence": {
                    "generator": "Step5b GNN/VGAE future candidate generator",
                    "candidate_score": conf,
                    "calibrated_prob": evidence.get("calibrated_prob"),
                    "raw_candidate_score": evidence.get("raw_candidate_score") or evidence.get("raw_predicted_prob"),
                    "calibration_method": evidence.get("calibration_method"),
                    "calibration_support": evidence.get("calibration_support"),
                    "calibration_label": evidence.get("calibration_label"),
                    "calibration_status": evidence.get("calibration_status"),
                    "lifecycle_state": evidence.get("lifecycle_state"),
                    "candidate_pool_reason": lifecycle_reason,
                    "relationship_scope": evidence.get("relationship_scope"),
                    "confidence_semantics": evidence.get("confidence_semantics"),
                    "uncertainty_reasons": evidence.get("uncertainty_reasons") or [],
                },
                "commercial_relevance": None,
                "validation_cost": None,
                "claim_scope": "exploratory_candidate_pool",
                "evidence_grade": evidence_grade,
                "uncertainty_reasons": [
                    "raw GNN/VGAE edge is not a Radar direction",
                    *calibration_uncertainty,
                    *list(evidence.get("uncertainty_reasons") or []),
                ],
                "eligible": False,
                "source_paper": e.get("source_paper"),
                "target_paper": e.get("target_paper"),
                "evidence_papers": [
                    _paper_ref(e.get("source_paper") or {"paper_id": e.get("source_paper_id")}, "GNN candidate source"),
                    _paper_ref(e.get("target_paper") or {"paper_id": e.get("target_paper_id")}, "GNN candidate target"),
                ],
                "evidence_objects": e.get("evidence_objects")
                or _future_edge_claim_contract(e).get("evidence_objects")
                or [],
                "missing_gates": sorted(
                    set(
                        [
                            *(lifecycle_missing or [
                                "Step6 fusion evidence",
                                "Step13 five-question Claim Card",
                                "section-level bottleneck evidence",
                                "commercial relevance",
                                "minimal validation experiment",
                            ]),
                            *(
                                []
                                if calibration_status == "calibrated_with_run_audit"
                                else ["rolling held-out-year calibration audit"]
                            ),
                        ]
                    )
                ),
                "plain_language": (
                    "This is a GNN/VGAE future-growth candidate. It is useful for discovery, "
                    "but not yet a decision-grade R&D direction."
                ),
            }
        )
    items = claim_cards or [
        {
            "kind": "radar_empty_state",
            "title": "No complete Claim Cards yet",
            "claim_scope": "candidate_only",
            "evidence_grade": "no_complete_claim_card",
            "uncertainty_reasons": [
                "Radar main view is empty until Step6/Step13 produce complete five-question Claim Cards"
            ],
            "eligible": False,
            "plain_language": (
                "Radar is intentionally empty because this topic currently has future candidates but no complete "
                "Step6/Step13 five-question Claim Card. Review the candidate pool, then rerun fusion and "
                "first-principles history after section evidence is complete."
            ),
        }
    ]
    return {
        "summary": (
            "R&D Radar only promotes complete Step13 Claim Cards. High-confidence status additionally requires "
            "strong section evidence, calibrated future-growth backtest, and sufficient direction evidence score. "
            "GNN/VGAE candidate edges and incomplete cards stay in the candidate pool."
        ),
        "items": items,
        "claim_cards": claim_cards,
        "incomplete_claim_cards": incomplete_cards,
        "candidate_pool": candidate_pool,
        "claim_cards_ready": bool(claim_cards),
        "high_confidence_ready": any(item.get("eligible") for item in claim_cards),
    }


def _reading_path_item(
    *,
    mode: str,
    title: str,
    why: str,
    papers: list[dict[str, Any]],
    claim_scope: str,
    evidence_grade: str,
    uncertainty_reasons: list[str] | None = None,
    evidence_objects: list[dict[str, Any] | None] | None = None,
    required_evidence: list[str] | None = None,
    can_explain: list[str] | None = None,
    cannot_explain: list[str] | None = None,
) -> dict[str, Any] | None:
    papers = [p for p in papers if p and p.get("paper_id")]
    objects = _compact_evidence_objects(
        [
            *[
                _paper_evidence_object(
                    p,
                    role=f"reading_path_{mode}",
                    source="topic_dossier_reading_path",
                    why=why,
                )
                for p in papers
            ],
            *(evidence_objects or []),
        ],
        limit=10,
    )
    if not papers and not objects:
        return None
    has_primary = any(_paper_has_primary_evidence(p) for p in papers)
    has_traced_primary = any(_paper_has_traced_primary_evidence(p) for p in papers)
    uncertainty = list(uncertainty_reasons or [])
    if not has_primary:
        uncertainty.append("recommended papers lack local primary section evidence in this reading path item")
    elif not has_traced_primary:
        uncertainty.append("recommended papers have only weak section parser provenance in this reading path item")
    return {
        "mode": mode,
        "title": title,
        "why": why,
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade if objects else "insufficient",
        "can_explain": can_explain or [
            "why these papers are worth reading next",
            "what evidence object or graph context selected this step",
        ],
        "cannot_explain": cannot_explain or [
            "a standalone scientific conclusion",
            "Radar promotion without complete Step13 Claim Cards",
            "causal history without linked citation and section evidence",
        ],
        "uncertainty_reasons": sorted(set(uncertainty)),
        "required_evidence": required_evidence or [
            "clickable paper record",
            "local section evidence for strong interpretation",
            "linked graph/lineage evidence for causal claims",
        ],
        "papers": [_paper_ref(p, why) for p in papers[:6]],
        "evidence_objects": objects,
    }


def _build_reading_path(
    *,
    hits: list[dict[str, Any]],
    turning_hits: list[dict[str, Any]],
    branch_splits: list[dict[str, Any]],
    bottleneck_dossiers: list[dict[str, Any]],
    validation_directions: list[dict[str, Any]],
    future_growth: list[dict[str, Any]],
    rd_radar: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build an auditable reading path instead of a generic recommendation list.

    A useful Topic Dossier should tell a researcher what to read first and why.
    Each item is deliberately scoped: starter papers are not turning papers,
    GNN endpoints are not Radar directions, and bottleneck papers remain weak
    unless section evidence exists.
    """
    path: list[dict[str, Any]] = []
    starter = sorted(
        hits[:80],
        key=lambda p: (
            -float(p.get("score") or 0.0),
            0 if _paper_has_traced_primary_evidence(p) else 1,
            -(int(p.get("year") or 0)),
        ),
    )[:5]
    item = _reading_path_item(
        mode="starter",
        title="Start here: topic anchors",
        why="High topic match papers provide vocabulary and representative context before reading lineage claims.",
        papers=starter,
        claim_scope="retrieval_context_only",
        evidence_grade=(
            "section_backed_topic_anchor"
            if any(_paper_has_traced_primary_evidence(p) for p in starter)
            else "weak_section_topic_anchor"
            if any(_paper_has_primary_evidence(p) for p in starter)
            else "metadata_topic_anchor"
        ),
        uncertainty_reasons=[
            "starter papers are selected by topic relevance, not by proof of future direction",
        ],
        can_explain=["topic vocabulary", "representative starting context", "which papers to inspect before lineage claims"],
        cannot_explain=["key turning status", "branch causality", "future direction value"],
    )
    if item:
        path.append(item)

    item = _reading_path_item(
        mode="turning",
        title="Then read: key turning papers",
        why="These papers sit on topic-specific main-path context or validated turning fallback; read them to understand why the branch grew.",
        papers=turning_hits[:6],
        claim_scope="topic_specific_turning_candidate",
        evidence_grade=(
            "section_backed_turning_path"
            if any(_paper_has_traced_primary_evidence(p) for p in turning_hits[:6])
            else "weak_section_turning_path"
            if any(_paper_has_primary_evidence(p) for p in turning_hits[:6])
            else "metadata_turning_path"
        ),
        uncertainty_reasons=[
            "linked refs below target can distort main-path rank",
            "broader field context papers must not be narrated as topic-specific turning papers",
        ],
        required_evidence=["topic-specific text/facet match", "main-path context", "access link or local section evidence"],
        can_explain=["candidate turning-paper context", "where topic text overlaps main-path context", "which papers need citation audit"],
        cannot_explain=["complete historical causality while linked refs are below target", "bottleneck resolution", "Radar direction value"],
    )
    if item:
        path.append(item)

    branch_driver_papers: list[dict[str, Any]] = []
    branch_evidence: list[dict[str, Any] | None] = []
    for branch in branch_splits[:5]:
        branch_driver_papers.extend([p for p in (branch.get("driver_papers") or []) if isinstance(p, dict)])
        branch_evidence.extend(branch.get("evidence_objects") or [])
    item = _reading_path_item(
        mode="branch_driver",
        title="Map branches: driver papers",
        why="Driver papers explain which branch/facet the topic is using and whether the split is evidence-backed or only weak.",
        papers=branch_driver_papers[:8],
        claim_scope="branch_context_candidate",
        evidence_grade=(
            "section_backed_branch_driver_path"
            if any(_paper_has_traced_primary_evidence(p) for p in branch_driver_papers)
            else "weak_section_branch_driver_path"
            if any(_paper_has_primary_evidence(p) for p in branch_driver_papers)
            else "metadata_branch_driver_path"
        ),
        uncertainty_reasons=[
            "branch drivers do not prove parent-child lineage unless branch_lineages support is present",
        ],
        evidence_objects=branch_evidence[:8],
        required_evidence=["driver papers", "branch lineage status", "section-level constraint shift evidence"],
        can_explain=["candidate branch context", "which driver papers support a split hypothesis", "where branch-lineage evidence should be audited"],
        cannot_explain=["evidence-backed parent-child split without lineage support", "root constraint shift without section evidence", "investment-ready direction"],
    )
    if item:
        path.append(item)

    bottleneck_papers: list[dict[str, Any]] = []
    bottleneck_evidence: list[dict[str, Any] | None] = []
    for bottleneck in bottleneck_dossiers[:5]:
        bottleneck_papers.extend([p for p in (bottleneck.get("evidence_papers") or []) if isinstance(p, dict)])
        bottleneck_evidence.extend(bottleneck.get("evidence_objects") or [])
    item = _reading_path_item(
        mode="bottleneck",
        title="Audit bottlenecks: section evidence",
        why="These papers contain the limitation/discussion/results/method evidence that keeps the dossier from becoming generic trend prose.",
        papers=bottleneck_papers[:8],
        claim_scope="exploratory_bottleneck_claim",
        evidence_grade=(
            "section_backed_bottleneck_path"
            if any(str((obj or {}).get("evidence_quality") or "").lower().startswith("section") for obj in bottleneck_evidence)
            else "metadata_or_abstract_bottleneck_path"
        ),
        uncertainty_reasons=[
            "unresolved bottleneck claims remain weak until resolution evidence is linked",
        ],
        evidence_objects=bottleneck_evidence[:10],
        required_evidence=["limitation/discussion/conclusion/results sections", "resolution atoms", "paper access links"],
        can_explain=["which limitation atoms anchor the bottleneck", "where section evidence should be read", "which constraints still look unresolved"],
        cannot_explain=["that a bottleneck is solved without resolution atoms", "high-confidence Claim Card evidence before section provenance passes", "commercial priority"],
    )
    if item:
        path.append(item)

    if rd_radar.get("claim_cards"):
        card_papers: list[dict[str, Any]] = []
        card_evidence: list[dict[str, Any] | None] = []
        for card in rd_radar.get("claim_cards", [])[:3]:
            for paper in (card.get("evidence_papers") or []):
                if isinstance(paper, dict):
                    card_papers.append(paper)
            card_evidence.extend(card.get("evidence_objects") or [])
        item = _reading_path_item(
            mode="claim_card",
            title="Decision read: complete Claim Cards",
            why="Read these after branch and bottleneck evidence; they are the only candidates allowed into the Radar main view.",
            papers=card_papers,
            claim_scope="exploratory_with_claim_card",
            evidence_grade="complete_claim_card_path",
            uncertainty_reasons=[
                "complete Claim Card still needs high-confidence gates before being treated as validated",
            ],
            evidence_objects=card_evidence,
            required_evidence=["complete five-question card", "calibrated future candidate", "section bottleneck evidence"],
            can_explain=["which candidates have complete five-question cards", "which evidence objects support the card", "what minimal validation experiment to inspect"],
            cannot_explain=["high-confidence status when section/calibration gates fail", "successful validation before experiment results", "raw GNN edge conclusions"],
        )
    else:
        future_papers: list[dict[str, Any]] = []
        future_evidence: list[dict[str, Any] | None] = []
        for edge in future_growth[:5]:
            for key in ("source_paper", "target_paper"):
                paper = edge.get(key)
                if isinstance(paper, dict) and paper.get("paper_id"):
                    future_papers.append(paper)
            future_evidence.append(_edge_evidence_object(edge, edge_type="future_candidate", source="Step5b VGAE"))
        item = _reading_path_item(
            mode="future_candidate",
            title="Finally inspect: future candidate endpoints",
            why="These are GNN/VGAE candidate endpoints. They help find hypotheses, but cannot be treated as directions until Step6/Step13 creates a complete Claim Card.",
            papers=future_papers[:8],
            claim_scope="candidate_pool_only",
            evidence_grade="calibrated_candidate_endpoint_path",
            uncertainty_reasons=[
                "GNN/VGAE is a candidate generator, not a conclusion generator",
                "future endpoints are excluded from Radar until Claim Card gates pass",
            ],
            evidence_objects=future_evidence,
            required_evidence=["calibration audit", "Step6 fusion evidence", "complete Step13 Claim Card"],
            can_explain=["which future endpoints to inspect as hypotheses", "where Step6/Step13 should gather evidence next", "candidate-pool scope"],
            cannot_explain=["that the future direction is valid", "that the bottleneck will be solved", "Radar promotion without a complete Claim Card"],
        )
    if item:
        path.append(item)
    return path


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
        if _paper_has_primary_evidence(h)
    )
    traced_section_ready = sum(
        1 for h in hits
        if _paper_has_traced_primary_evidence(h)
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
    branch_splits = _build_topic_branch_splits(topic, hits, turning_hits, branch_dossiers)
    bottleneck_dossiers = _build_bottleneck_dossiers(unresolved_limitations, hits)
    validation_directions = _build_validation_directions(
        topic,
        branch_splits,
        bottleneck_dossiers,
        future_growth,
        rd_radar,
    )
    reading_path = _build_reading_path(
        hits=hits,
        turning_hits=turning_hits,
        branch_splits=branch_splits,
        bottleneck_dossiers=bottleneck_dossiers,
        validation_directions=validation_directions,
        future_growth=future_growth,
        rd_radar=rd_radar,
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
    evidence_objects = _compact_evidence_objects(
        [
            *[
                obj
                for branch in branch_splits[:6]
                for obj in (branch.get("evidence_objects") or [])
            ],
            *[
                obj
                for bottleneck in bottleneck_dossiers[:6]
                for obj in (bottleneck.get("evidence_objects") or [])
            ],
            *[
                obj
                for direction in validation_directions[:5]
                for obj in (direction.get("evidence_objects") or [])
            ],
            *[
                _paper_evidence_object(
                    paper,
                    role="key_turning_paper",
                    source="topic_main_path",
                    why=(paper.get("reason") or {}).get("why") if isinstance(paper, dict) else None,
                )
                for paper in turning_hits[:8]
            ],
            *[
                _edge_evidence_object(edge, edge_type="future_candidate", source="Step5b VGAE")
                for edge in future_growth[:8]
            ],
        ],
        limit=40,
    )
    frontfill = value_model.get("frontfill_status") or {}
    local_section_rate = section_ready / max(1, len(hits))
    traced_section_rate = traced_section_ready / max(1, len(hits))
    has_calibration = any(_future_edge_has_run_calibration(edge) for edge in future_growth)
    has_complete_claim_card = bool(rd_radar.get("claim_cards_ready"))
    if (
        branch_splits
        and bottleneck_dossiers
        and traced_section_ready >= 3
        and traced_section_rate >= 0.35
    ):
        evidence_grade = "moderate_section"
    elif evidence_objects and section_ready:
        evidence_grade = "metadata_only"
    elif evidence_objects:
        evidence_grade = "metadata_only"
    else:
        evidence_grade = "insufficient"
    dossier_claim_scope = claim_scope_policy(
        evidence_grade=evidence_grade,
        has_complete_claim_card=has_complete_claim_card,
        has_calibration=has_calibration,
        linked_ref_rate=float(frontfill.get("linked_ref_rate") or 0.0),
    )
    dossier_uncertainty = uncertainty_reasons(
        linked_ref_rate=float(frontfill.get("linked_ref_rate") or 0.0),
        primary_section_rate=float(frontfill.get("primary_section_rate") or 0.0),
        openalex_rate=float(frontfill.get("openalex_w_rate") or 0.0),
        has_calibration=has_calibration,
    )
    if local_section_rate < 0.35:
        dossier_uncertainty.append("topic-local section evidence below dossier-grade target")
    if section_ready and traced_section_ready < section_ready:
        dossier_uncertainty.append("some topic-local primary sections have weak parser provenance")
    if not branch_splits:
        dossier_uncertainty.append("no evidence-backed branch split available for this topic")
    if not bottleneck_dossiers:
        dossier_uncertainty.append("no section-linked bottleneck dossier available for this topic")
    if future_growth and not has_complete_claim_card:
        dossier_uncertainty.append("future candidates exist but no complete five-question Claim Card is available")
    insufficient_evidence = []
    if not branch_splits:
        insufficient_evidence.append(
            {
                "claim": "interpretable branch split",
                "reason": "no branch split matched the topic with driver-paper evidence",
                "needed": "branch lineage or representative cluster evidence",
            }
        )
    if not bottleneck_dossiers:
        insufficient_evidence.append(
            {
                "claim": "hard bottleneck dossier",
                "reason": "no unresolved limitation atoms matched this topic context",
                "needed": "section-level limitations/discussion/conclusion evidence",
            }
        )
    if future_growth and not rd_radar.get("claim_cards_ready"):
        insufficient_evidence.append(
            {
                "claim": "investable future direction",
                "reason": "future candidates exist but Step6/Step13 Claim Cards are not complete",
                "needed": "fusion evidence plus five-question Claim Cards",
            }
        )
    if section_ready == 0:
        insufficient_evidence.append(
            {
                "claim": "strong local evidence",
                "reason": "no primary section evidence was present in this topic result set",
                "needed": "paper_sections from limitations/discussion/conclusion/future_work/results/methods",
            }
        )
    elif traced_section_ready == 0:
        insufficient_evidence.append(
            {
                "claim": "strong local evidence",
                "reason": "primary section evidence exists, but parser provenance is weak",
                "needed": "explicit/embedded heading section evidence for key papers",
            }
        )
    if evidence_grade == "insufficient":
        headline = (
            f"{topic} does not yet have enough evidence-backed branch/bottleneck structure; "
            "treat this as a search dossier, not a scientific conclusion."
        )
        value_claim = (
            "The next value-creating action is to frontfill primary sections for the listed evidence gaps, "
            "then rerun Step5c/Step6/Step13 before making a direction claim."
        )
    elif dossier_claim_scope in {"candidate_pool_only", "insufficient_evidence"}:
        headline = (
            f"{topic} has a candidate evidence dossier around {branch_text}, but current evidence is not "
            "strong enough for Radar promotion."
        )
        value_claim = (
            f"The decision question is whether {topic} can keep verified performance under "
            f"{bottleneck_text or 'the current hard constraints'}; current claim scope is {dossier_claim_scope}."
        )
    else:
        headline = f"{topic} is best read as a {phase} topic organized around {branch_text}."
        value_claim = (
            f"The decision question is not whether {topic} exists, but whether it can keep verified performance "
            f"under {bottleneck_text or 'the current hard constraints'}."
        )
    return {
        "headline": headline,
        "value_claim": value_claim,
        "decision_summary": (
            "Start with the branch splits and hard bottlenecks below; every claim links back to papers or evidence objects. "
            f"Current radar status: {claim_status}."
        ),
        "stage": phase,
        "claim_scope": dossier_claim_scope,
        "evidence_grade": evidence_grade,
        "uncertainty_reasons": sorted(set(dossier_uncertainty)),
        "claim_policy": (
            "Topic Dossier text is capped by evidence_grade, Claim Card completeness, calibration, "
            "linked-ref coverage, and local section coverage. Weak dossiers remain candidate_pool_only."
        ),
        "branch_splits": branch_splits,
        "hard_bottlenecks": bottleneck_dossiers,
        "validation_directions": validation_directions,
        "reading_path": reading_path,
        "evidence_objects": evidence_objects,
        "insufficient_evidence": insufficient_evidence,
        "solved_vs_open": {
            "partially_addressed": [
                b["name"]
                for b in bottleneck_dossiers
                if int(b.get("resolved_evidence_count") or 0) > 0
            ],
            "resolution_evidence_counts": {
                b["name"]: {
                    "resolved": int(b.get("resolved_evidence_count") or 0),
                    "unresolved": int(b.get("unresolved_evidence_count") or 0),
                    "status": b.get("resolution_status"),
                }
                for b in bottleneck_dossiers[:8]
            },
            "still_open": [
                b["name"]
                for b in bottleneck_dossiers[:6]
                if int(b.get("unresolved_evidence_count") or 0) > 0
            ],
            "rule": (
                "A bottleneck is only treated as partially addressed when Step5c high-confidence "
                "limitation_resolutions evidence is linked; title words such as improve/mitigate do not close it. "
                "It remains open while any topic-relevant unresolved limitation atom remains."
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
            "strong_or_moderate_primary_section_coverage_in_results": traced_section_rate,
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
    history_main_path_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    main_path_contract = history_main_path_contract or _build_history_main_path_contract(
        main_path_edges=main_path_edges,
        key_turning_papers=turning_hits,
        broader_context_papers=[],
        value_model=value_model,
    )
    return {
        "summary": "Evidence Map is for auditing the dossier, not for making users infer value from raw nodes.",
        "main_path": {
            "meaning": value_model.get("layers", {}).get("main_path", {}).get("relationship"),
            "claim_scope": main_path_contract.get("claim_scope"),
            "evidence_grade": main_path_contract.get("evidence_grade"),
            "uncertainty_reasons": main_path_contract.get("uncertainty_reasons") or [],
            "required_evidence": main_path_contract.get("required_evidence") or [],
            "evidence_objects": main_path_contract.get("evidence_objects")
            or _main_path_evidence_objects(
                main_path_edges,
                claim_scope=main_path_contract.get("claim_scope"),
                evidence_grade=main_path_contract.get("evidence_grade"),
            ),
            "metrics": main_path_contract.get("metrics") or {},
            "relevance_policy": main_path_contract.get("relevance_policy"),
            "can_explain": [
                "topic-filtered historical trunk context",
                "candidate key turning papers with local edge support",
                "where citation relinking should be audited next",
            ],
            "cannot_explain": [
                "complete historical causality while linked refs are below target",
                "topic branch split reasons without section-level bottleneck evidence",
                "future direction value or Radar promotion",
            ],
            "edges": main_path_edges[:80],
            "key_turning_papers": turning_hits[:50],
        },
        "future_candidates": {
            "meaning": value_model.get("layers", {}).get("future", {}).get("relationship"),
            "claim_scope": "candidate_pool_only",
            "evidence_grade": (
                "calibrated_candidate_generator"
                if any(_future_edge_has_run_calibration(edge) for edge in future_growth)
                else ("uncalibrated_candidate_generator" if future_growth else "future_candidate_generation_gap")
            ),
            "uncertainty_reasons": sorted(
                {
                    reason
                    for edge in future_growth[:80]
                    for reason in (
                        edge.get("uncertainty_reasons")
                        or _future_edge_claim_contract(edge).get("uncertainty_reasons")
                        or []
                    )
                }
            ),
            "required_evidence": [
                "rolling held-out-year calibration audit",
                "Step6 fusion evidence",
                "Step13 five-question Claim Card",
                "section-level bottleneck evidence",
            ],
            "edges": [
                {
                    **edge,
                    **{
                        key: edge.get(key) or _future_edge_claim_contract(edge).get(key)
                        for key in (
                            "claim_scope",
                            "evidence_grade",
                            "uncertainty_reasons",
                            "required_evidence",
                            "calibration_status",
                            "evidence_objects",
                        )
                    },
                }
                for edge in future_growth[:80]
            ],
        },
        "branches": [
            {
                "cluster_id": b.get("cluster_id"),
                "branch_id": b.get("branch_id"),
                "label": b.get("label"),
                "topic_share": b.get("topic_share"),
                "split_confidence": b.get("split_confidence"),
                "parent_branch_id": b.get("parent_branch_id"),
                "lineage_status": b.get("lineage_status"),
                "claim_scope": b.get("claim_scope"),
                "evidence_grade": b.get("evidence_grade"),
                "uncertainty_reasons": b.get("uncertainty_reasons") or [],
                "required_evidence": b.get("required_evidence") or [],
                "evidence_objects": b.get("evidence_objects") or [],
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
                "can_explain": combo.get("can_explain") or [],
                "cannot_explain": combo.get("cannot_explain") or [],
                "required_evidence": combo.get("required_evidence") or [],
                "claim_scope": combo.get("claim_scope"),
                "evidence_grade": combo.get("evidence_grade"),
                "uncertainty_reasons": combo.get("uncertainty_reasons") or [],
            }
            for combo in value_model.get("layer_combinations", [])
        ],
    }


def _main_path_evidence_objects(
    main_path_edges: list[dict[str, Any]],
    *,
    limit: int = 8,
    claim_scope: str | None = None,
    evidence_grade: str | None = None,
) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for edge in main_path_edges[:limit]:
        edge_id = str(edge.get("edge_id") or "").strip()
        if not edge_id:
            continue
        objects.append(
            {
                "type": "main_path_edge",
                "edge_id": edge_id,
                "source_paper_id": edge.get("source_paper_id"),
                "target_paper_id": edge.get("target_paper_id"),
                "label": "main path citation edge",
                "source": "topic_history_main_path",
                "evidence_grade": edge.get("evidence_grade") or evidence_grade,
                "claim_scope": edge.get("claim_scope") or claim_scope,
                "description": edge.get("plain_language"),
            }
        )
    return objects


def _build_history_main_path_contract(
    *,
    main_path_edges: list[dict[str, Any]],
    key_turning_papers: list[dict[str, Any]],
    broader_context_papers: list[dict[str, Any]],
    value_model: dict[str, Any],
) -> dict[str, Any]:
    frontfill = value_model.get("frontfill_status") or {}
    linked_ref_rate = float(frontfill.get("linked_ref_rate") or 0.0)
    reasons: list[str] = []
    if linked_ref_rate < 0.30:
        reasons.append("linked refs below 30%; citation backbone is incomplete")
    if not main_path_edges:
        reasons.append("no topic main-path citation edges matched")
    if not key_turning_papers:
        reasons.append("no topic-specific key turning papers after relevance filtering")
    if broader_context_papers:
        reasons.append("broader field main-path anchors are separated from topic-specific turning papers")
    claim_scope = (
        "main_path_context_low_linked_refs"
        if linked_ref_rate < 0.30
        else "topic_main_path_context"
    )
    evidence_grade = (
        "citation_backbone_partial_low_linked_refs"
        if linked_ref_rate < 0.30
        else "linked_citation_backbone"
    )
    return {
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade,
        "uncertainty_reasons": sorted(set(reasons)),
        "required_evidence": [
            "linked citation references",
            "main_path edge weights",
            "topic-specific text or facet relevance for key turning papers",
            "provider ID repair and reference relinking",
        ],
        "evidence_objects": _main_path_evidence_objects(
            main_path_edges,
            claim_scope=claim_scope,
            evidence_grade=evidence_grade,
        ),
        "metrics": {
            "main_path_edges": len(main_path_edges),
            "key_turning_papers": len(key_turning_papers),
            "broader_context_papers": len(broader_context_papers),
            "linked_ref_rate": linked_ref_rate,
        },
        "relevance_policy": (
            "key_turning_papers require topic-specific text/facet evidence; broader_context_papers "
            "are field-level anchors and should not be narrated as topic turning papers."
        ),
    }


def _apply_history_main_path_contract(
    main_path_edges: list[dict[str, Any]],
    contract: dict[str, Any],
) -> None:
    for edge in main_path_edges:
        edge.setdefault("claim_scope", contract.get("claim_scope"))
        edge.setdefault("evidence_grade", contract.get("evidence_grade"))
        edge.setdefault("uncertainty_reasons", list(contract.get("uncertainty_reasons") or []))
        edge.setdefault("required_evidence", list(contract.get("required_evidence") or []))


def _build_topic_readiness_preflight(
    *,
    topic: str,
    topic_dossier: dict[str, Any],
    turning_hits: list[dict[str, Any]],
    future_growth: list[dict[str, Any]],
    rd_radar: dict[str, Any],
    first_principles_questions: list[dict[str, Any]],
    bottleneck_lineage: dict[str, Any],
) -> dict[str, Any]:
    return build_topic_readiness_preflight(
        topic=topic,
        topic_dossier=topic_dossier,
        turning_hits=turning_hits,
        future_growth=future_growth,
        rd_radar=rd_radar,
        first_principles_questions=first_principles_questions,
        bottleneck_lineage=bottleneck_lineage,
    )


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
        turning_hits, broader_turning_context = _split_topic_turning_papers(topic_text, turning_hits)
        min_topic_turning = min(8, max(4, int(top_k) // 10))
        if len(turning_hits) < min_topic_turning:
            fallback_turning = _topic_driver_fallback_papers(
                topic_text,
                hits,
                existing_ids={str(p.get("paper_id")) for p in turning_hits},
                limit=max(8, min_topic_turning * 2),
            )
            turning_hits = [*turning_hits, *fallback_turning]

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
            edge.setdefault("candidate_score", edge.get("confidence") or edge.get("weight"))
            calibration_status = _future_edge_calibration_status(edge)
            calibration_phrase = (
                "run-calibrated exploratory evidence"
                if calibration_status == "calibrated_with_run_audit"
                else f"uncalibrated candidate evidence ({calibration_status})"
            )
            edge["plain_language"] = (
                "Future-growth candidate: the generator scores the source-side idea/bottleneck "
                f"as a possible bridge to the target-side direction; treat as {calibration_phrase} "
                "until Step6/Step13 Claim Cards are materialized."
            )
        _apply_future_edge_contracts(future_growth)

        unresolved_limitations = []
        for h in hits:
            lims = h.get("limitations") or []
            if not isinstance(lims, list):
                continue
            for lim in lims[:3]:
                item = dict(lim) if isinstance(lim, dict) else {"description": str(lim)}
                item.setdefault("paper_id", h["paper_id"])
                item.setdefault("title", h.get("title"))
                item.setdefault("branch_id", h.get("branch_id"))
                item.setdefault("cluster_id", h.get("cluster_id"))
                item.setdefault("relationship_scope", "direct_paper_match")
                unresolved_limitations.append(item)
        context_limitations = _load_context_limitations(
            conn,
            topic=topic_text,
            paper_ids=context_seed_ids,
            cluster_ids=top_cluster_ids,
            limit=max(20, int(top_k)),
        )
        seen_limitations = {
            (
                str(x.get("paper_id") or ""),
                str(x.get("keyword") or ""),
                str(x.get("description") or "")[:160],
            )
            for x in unresolved_limitations
        }
        for lim in context_limitations:
            key = (
                str(lim.get("paper_id") or ""),
                str(lim.get("keyword") or ""),
                str(lim.get("description") or "")[:160],
            )
            if key not in seen_limitations:
                seen_limitations.add(key)
                unresolved_limitations.append(lim)
        unresolved_limitations = _attach_limitation_contracts(unresolved_limitations[: max(20, int(top_k))])

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
                item["vgae_evidence"] = _future_candidate_evidence_text(item.get("vgae_evidence"))
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
        lineage_triples = []
        if _table_exists(conn, "first_principles_principles"):
            rows = conn.execute(
                """
                SELECT principle_id, principle_name, root_cause, bottleneck_score,
                       unresolved_atoms, resolved_atoms, emergence_year, peak_backlog_year,
                       current_backlog, evidence_quality_json, top_keywords_json, top_branches_json,
                       top_papers_json,
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
        if _table_exists(conn, "bottleneck_lineage_triples") and principles:
            pids = [p.get("principle_id") for p in principles if p.get("principle_id")]
            ph = ",".join("?" for _ in pids)
            lineage_triples = [
                dict(r)
                for r in conn.execute(
                    f"""
                    SELECT triple_id, principle_id, direction_id, atom_id, edge_order,
                           source_stage, target_stage, source_text, target_text,
                           relation_type, paper_id, resolver_paper_id, event_year,
                           evidence_section, evidence_page, evidence_quality,
                           evidence_weight, metadata_json
                    FROM bottleneck_lineage_triples
                    WHERE principle_id IN ({ph})
                    ORDER BY event_year DESC, edge_order ASC
                    LIMIT 300
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
                    f"cycle_weeks={experiment.get('cycle_weeks', 'N/A')}; "
                    f"success={'; '.join(_text_list(experiment.get('success_criteria'))) or 'N/A'}; "
                    f"falsify={'; '.join(_text_list(experiment.get('falsification_conditions'))) or 'N/A'})"
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
                    "并用后续季度回测验证 candidate edges 是否获得真实证据支持。"
                ),
            },
        ]

    bottleneck_lineage = _build_bottleneck_lineage(
        principles,
        history_events,
        unresolved_limitations,
        lineage_triples,
    )
    rd_radar = _build_rd_radar(future_directions, future_growth)
    history_main_path_contract = _build_history_main_path_contract(
        main_path_edges=main_path_edges,
        key_turning_papers=turning_hits,
        broader_context_papers=broader_turning_context,
        value_model=value_model,
    )
    _apply_history_main_path_contract(main_path_edges, history_main_path_contract)
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
        history_main_path_contract=history_main_path_contract,
    )
    first_principles_five_questions = _evidence_contract_for_five_questions(
        first_principles_five_questions,
        topic_dossier=topic_dossier,
        turning_hits=turning_hits,
        unresolved_limitations=unresolved_limitations,
        future_growth=future_growth,
        top_claim_card=top_claim_card,
    )
    topic_readiness = _build_topic_readiness_preflight(
        topic=topic_text,
        topic_dossier=topic_dossier,
        turning_hits=turning_hits,
        future_growth=future_growth,
        rd_radar=rd_radar,
        first_principles_questions=first_principles_five_questions,
        bottleneck_lineage=bottleneck_lineage,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "ready": True,
        "topic": topic_text,
        "corpus_id": corpus_id,
        "topic_readiness": topic_readiness,
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
            "topic_specific_turning_papers": len(turning_hits),
            "broader_turning_context_papers": len(broader_turning_context),
            "note": (
                "Topic Lens expands from exact paper matches into dominant clusters/branches "
                "so mainstream directions can recover main-path and future-growth context. "
                "Broader-field main-path papers are separated from topic-specific turning papers."
            ),
        },
        "cluster_distribution": cluster_distribution,
        "history_main_path": {
            **history_main_path_contract,
            "edges": main_path_edges,
            "key_turning_papers": turning_hits[: max(10, min(int(top_k), 80))],
            "broader_context_papers": broader_turning_context[: max(10, min(int(top_k), 40))],
        },
        "unresolved_limitations": unresolved_limitations,
        "future_growth": {
            "candidate_edges": future_growth,
            "future_directions": future_directions,
            "claim_scope": "candidate_pool_only",
            "evidence_grade": (
                "calibrated_future_candidate_generator"
                if any(_future_edge_has_run_calibration(edge) for edge in future_growth)
                else ("future_candidate_generation_gap" if not future_growth else "uncalibrated_candidate_generator")
            ),
            "uncertainty_reasons": sorted(
                {
                    "future candidates are inspection targets, not Radar directions",
                    "Radar promotion requires Step6 fusion plus complete Step13 Claim Card",
                    *[
                        reason
                        for edge in future_growth[:80]
                        for reason in (
                            edge.get("uncertainty_reasons")
                            or _future_edge_claim_contract(edge).get("uncertainty_reasons")
                            or []
                        )
                    ],
                }
            ),
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
        frontfill = _frontfill_status(conn)
    return {
        "schema_version": SCHEMA_VERSION,
        "ready": ready,
        "missing_tables": missing,
        "counts": counts,
        "frontfill_status": frontfill,
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
        frontfill = _frontfill_status(conn)
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
        item.update(_visual_edge_contract(item, frontfill))
        edges.append(item)
    paper = hits[0]
    visual_role = (paper.get("visual") or {}).get("role") or paper.get("visual_role") or "paper"
    why_parts = []
    if layer_counts.get("main_path"):
        why_parts.append(f"main-path node: {layer_counts['main_path']} loaded trunk edges, cumulative weight {main_weight:.2f}")
    if layer_counts.get("future"):
        why_parts.append(f"future anchor/candidate endpoint: {layer_counts['future']} future edges, cumulative candidate score {future_weight:.2f}")
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
        **_paper_role_contract(paper, edges, visual_role=visual_role, why_parts=why_parts),
        "evidence_gap": (
            "section-level evidence with strong/moderate parser provenance available"
            if _paper_has_traced_primary_evidence(paper)
            else "local section evidence available but parser provenance is weak"
            if _paper_has_primary_evidence(paper)
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
            else "strength"
        )
        split_evidence_sql = (
            "split_evidence_json"
            if "split_evidence_json" in lineage_cols
            else "why_json"
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
        lineage_payload = item.get("split_evidence") or item.get("why") or {}
        item["lineage_status"] = _lineage_status(lineage_payload, item.get("split_confidence"))
        item["split_reason"] = _split_reason(str(item.get("branch_id") or ""), item.get("parent_branch_id"), lineage_payload)
        item.update(_branch_lineage_contract(item, lineage_payload))
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
        item.update(_story_step_contract(item))
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
        item = {
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
        item.update(_visual_node_role_contract(item))
        nodes.append(item)
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
        frontfill = _frontfill_status(conn)
    edges = []
    for row in rows:
        item = dict(row)
        item["style"] = _loads(item.pop("style_json", None), {})
        item["evidence"] = _loads(item.pop("evidence_json", None), {})
        item.update(_visual_edge_contract(item, frontfill))
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
