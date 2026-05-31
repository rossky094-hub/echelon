"""Section evidence atomization and exact atom search.

This step sits between `paper_sections` and downstream reasoning.  It creates
span-bound, provenance-carrying evidence atoms that can be searched exactly and
later consumed by Step5c/Step13.  GNN/VGAE must not create these atoms; graph
models may only rank or expand already-materialized evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN
from echelon.v14b.evidence_contracts import (
    SECTION_PARSER_CONTRACT_VERSION,
    is_decision_section,
    normalize_section_key,
    section_provenance_strength,
)
from echelon.v14b.utils import add_common_args, setup_logging


ATOM_TYPES = (
    "constraint",
    "failure_mechanism",
    "attempted_path",
    "local_fix",
    "new_constraint",
    "metric_result",
    "validation_setup",
    "cost_or_scaling_signal",
)

TYPE_PATTERNS: dict[str, re.Pattern[str]] = {
    "constraint": re.compile(
        r"\b(limit(?:ation)?s?|challenge[sd]?|bottleneck|constraint|"
        r"trade[- ]?off|requires?|difficult|lack|insufficient|not yet)\b",
        re.I,
    ),
    "failure_mechanism": re.compile(
        r"\b(fail(?:ed|ure|s)?|loss|noise|instabil(?:ity|e)|defect|"
        r"degrad(?:e|es|ation)|crosstalk|thermal|fabrication error|mismatch)\b",
        re.I,
    ),
    "attempted_path": re.compile(
        r"\b(we (?:use|used|propose|proposed|employ|employed)|approach|method|"
        r"design|architecture|fabricat(?:e|ed|ion)|optimi[sz](?:e|ed|ation))\b",
        re.I,
    ),
    "local_fix": re.compile(
        r"\b(overcome|resolve|mitigate|address|improv(?:e|ed|es|ement)|"
        r"enable(?:d|s)?|achiev(?:e|ed|es)|demonstrat(?:e|ed|es))\b",
        re.I,
    ),
    "new_constraint": re.compile(
        r"\b(however|nevertheless|still|remain(?:s|ing)?|future work|"
        r"further work|open question|not fully|yet to)\b",
        re.I,
    ),
    "metric_result": re.compile(
        r"(\b\d+(?:\.\d+)?\s?(?:%|dB|GHz|MHz|THz|nm|um|K|mW|W|"
        r"ns|ps|fs)\b|\bQ[- ]?factor\b|\befficien(?:cy|t)\b)",
        re.I,
    ),
    "validation_setup": re.compile(
        r"\b(experiment(?:al)?|measurement|measured|simulation|simulated|"
        r"benchmark|validation|setup|prototype|testbed)\b",
        re.I,
    ),
    "cost_or_scaling_signal": re.compile(
        r"\b(cost|expensive|low[- ]?cost|scal(?:e|ing|able|ability)|"
        r"yield|manufactur(?:e|ing)|throughput|mass production)\b",
        re.I,
    ),
}

SECTION_TYPE_BIAS: dict[str, str] = {
    "limitations": "constraint",
    "limitation": "constraint",
    "error_analysis": "failure_mechanism",
    "ablation": "failure_mechanism",
    "method": "attempted_path",
    "methods": "attempted_path",
    "experiments": "validation_setup",
    "results": "metric_result",
    "future_work": "new_constraint",
    "conclusion": "new_constraint",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _loads(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return default


def ensure_section_atoms_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS section_atoms (
            atom_id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            section_name TEXT NOT NULL,
            section_key TEXT NOT NULL,
            atom_index INTEGER NOT NULL,
            atom_type TEXT NOT NULL,
            atom_text TEXT NOT NULL,
            title TEXT,
            page_start INTEGER,
            page_end INTEGER,
            source_url TEXT,
            source_storage_uri TEXT,
            parser_contract_version TEXT,
            source_delivery TEXT,
            extractor_method TEXT NOT NULL,
            evidence_grade TEXT NOT NULL,
            claim_scope TEXT NOT NULL,
            uncertainty_reasons_json TEXT NOT NULL,
            features_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_section_atoms_paper ON section_atoms(paper_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_section_atoms_type ON section_atoms(atom_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_section_atoms_section ON section_atoms(section_key)")
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS section_atoms_fts USING fts5(
                atom_id UNINDEXED,
                paper_id UNINDEXED,
                section_name,
                atom_type,
                title,
                atom_text
            )
            """
        )
    except sqlite3.OperationalError:
        pass
    conn.commit()


def _sentence_chunks(text: str, *, min_chars: int = 80, max_chars: int = 700) -> list[str]:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return []
    pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", clean) if p.strip()]
    if not pieces:
        pieces = [clean]
    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        if len(piece) > max_chars:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            for start in range(0, len(piece), max_chars):
                part = piece[start : start + max_chars].strip()
                if len(part) >= min_chars:
                    chunks.append(part)
            continue
        candidate = f"{buf} {piece}".strip() if buf else piece
        if len(candidate) > max_chars and buf:
            if len(buf) >= min_chars:
                chunks.append(buf.strip())
            buf = piece
        else:
            buf = candidate
        if len(buf) >= min_chars and (buf.endswith((".", "!", "?")) or len(buf) >= max_chars * 0.75):
            chunks.append(buf.strip())
            buf = ""
    if buf:
        if chunks and len(buf) < min_chars:
            chunks[-1] = f"{chunks[-1]} {buf}".strip()[:max_chars]
        elif len(buf) >= min_chars:
            chunks.append(buf.strip())
    return chunks


def classify_atom_type(text: str, section_name: str = "") -> tuple[str, dict[str, bool]]:
    section_key = normalize_section_key(section_name)
    features = {name: bool(pattern.search(text or "")) for name, pattern in TYPE_PATTERNS.items()}
    for atom_type in ATOM_TYPES:
        if features.get(atom_type):
            return atom_type, features
    return SECTION_TYPE_BIAS.get(section_key, "constraint"), features


def _section_evidence_grade(section: dict[str, Any], meta: dict[str, Any]) -> tuple[str, list[str]]:
    reasons = ["section atom is retrieval evidence, not a standalone conclusion"]
    current_contract = meta.get("parser_contract_version") == SECTION_PARSER_CONTRACT_VERSION
    strength = section_provenance_strength(
        {
            "section_name": section.get("section_name"),
            "extraction_strategies": meta.get("extraction_strategies") or [],
            "parser_contract_version": meta.get("parser_contract_version"),
        }
    )
    if not is_decision_section(section.get("section_name")):
        reasons.append("section is not a primary decision section")
    if not current_contract:
        reasons.append("section parser contract is legacy or unknown")
    if strength == "weak":
        reasons.append("section extraction provenance is weak")
    reasons.append("atom type is deterministic heuristic classification")
    if current_contract and strength in {"strong", "moderate"} and is_decision_section(section.get("section_name")):
        return "section_atom_decision_grade", reasons
    if strength in {"strong", "moderate"}:
        return "section_atom_traced", reasons
    return "section_atom_weak", reasons


def _atom_id(paper_id: str, section_key: str, atom_index: int, atom_text: str) -> str:
    digest = hashlib.sha1(f"{paper_id}|{section_key}|{atom_index}|{atom_text}".encode("utf-8")).hexdigest()[:20]
    return f"sa_{digest}"


def extract_section_atoms_from_row(row: sqlite3.Row | dict[str, Any], *, max_atoms_per_section: int = 12) -> list[dict[str, Any]]:
    section = dict(row)
    meta = _loads(section.get("section_meta_json"), {})
    pages = _loads(section.get("section_pages_json"), [])
    page_values = [int(p) for p in pages if isinstance(p, (int, float)) and int(p) > 0]
    section_name = str(section.get("section_name") or "")
    section_key = normalize_section_key(section_name)
    evidence_grade, reasons = _section_evidence_grade(section, meta)
    chunks = _sentence_chunks(str(section.get("section_text") or ""))[:max_atoms_per_section]
    atoms: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks):
        atom_type, features = classify_atom_type(chunk, section_name)
        atoms.append(
            {
                "atom_id": _atom_id(str(section.get("paper_id") or ""), section_key, idx, chunk),
                "paper_id": str(section.get("paper_id") or ""),
                "section_name": section_name,
                "section_key": section_key,
                "atom_index": idx,
                "atom_type": atom_type,
                "atom_text": chunk,
                "title": str(section.get("title") or ""),
                "page_start": min(page_values) if page_values else None,
                "page_end": max(page_values) if page_values else None,
                "source_url": section.get("source_url") or "",
                "source_storage_uri": meta.get("source_storage_uri") or "",
                "parser_contract_version": meta.get("parser_contract_version") or "legacy_unknown_contract",
                "source_delivery": meta.get("source_delivery") or "",
                "extractor_method": "deterministic_section_atomizer_v1",
                "evidence_grade": evidence_grade,
                "claim_scope": "retrieval_context_only",
                "uncertainty_reasons_json": json.dumps(reasons, ensure_ascii=False),
                "features_json": json.dumps(features, ensure_ascii=False, sort_keys=True),
                "created_at": utc_now(),
            }
        )
    return atoms


def _insert_atoms(
    conn: sqlite3.Connection,
    atoms: list[dict[str, Any]],
    *,
    replace_fts_rows: bool = True,
) -> int:
    if not atoms:
        return 0
    rows = [
        (
            a["atom_id"],
            a["paper_id"],
            a["section_name"],
            a["section_key"],
            int(a["atom_index"]),
            a["atom_type"],
            a["atom_text"],
            a["title"],
            a["page_start"],
            a["page_end"],
            a["source_url"],
            a["source_storage_uri"],
            a["parser_contract_version"],
            a["source_delivery"],
            a["extractor_method"],
            a["evidence_grade"],
            a["claim_scope"],
            a["uncertainty_reasons_json"],
            a["features_json"],
            a["created_at"],
        )
        for a in atoms
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO section_atoms (
            atom_id, paper_id, section_name, section_key, atom_index, atom_type,
            atom_text, title, page_start, page_end, source_url, source_storage_uri,
            parser_contract_version, source_delivery, extractor_method, evidence_grade,
            claim_scope, uncertainty_reasons_json, features_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    if _table_exists(conn, "section_atoms_fts"):
        if replace_fts_rows:
            conn.execute(
                "CREATE TEMP TABLE IF NOT EXISTS section_atom_fts_refresh_ids (atom_id TEXT PRIMARY KEY)"
            )
            conn.execute("DELETE FROM section_atom_fts_refresh_ids")
            conn.executemany(
                "INSERT OR IGNORE INTO section_atom_fts_refresh_ids (atom_id) VALUES (?)",
                [(a["atom_id"],) for a in atoms],
            )
            conn.execute(
                """
                DELETE FROM section_atoms_fts
                WHERE atom_id IN (SELECT atom_id FROM section_atom_fts_refresh_ids)
                """
            )
        conn.executemany(
            """
            INSERT INTO section_atoms_fts
                (atom_id, paper_id, section_name, atom_type, title, atom_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    a["atom_id"],
                    a["paper_id"],
                    a["section_name"],
                    a["atom_type"],
                    a["title"],
                    a["atom_text"],
                )
                for a in atoms
            ],
        )
    return len(rows)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'virtual table') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def build_section_atoms(
    db_main: Path = DB_MAIN,
    *,
    limit: int | None = None,
    rebuild: bool = True,
    max_atoms_per_section: int = 12,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_main), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    ensure_section_atoms_schema(conn)
    if not _table_exists(conn, "paper_sections"):
        conn.close()
        return {
            "sections_processed": 0,
            "atoms_written": 0,
            "by_type": {},
            "by_evidence_grade": {},
            "fts_enabled": False,
            "status": "paper_sections_missing",
        }
    if rebuild:
        conn.execute("DELETE FROM section_atoms")
        if _table_exists(conn, "section_atoms_fts"):
            conn.execute("DELETE FROM section_atoms_fts")
        conn.commit()
    paper_columns = _columns(conn, "papers")
    section_columns = _columns(conn, "paper_sections")
    source_url = "s.source_url" if "source_url" in section_columns else "'' AS source_url"
    section_pages = "s.section_pages_json" if "section_pages_json" in section_columns else "'[]' AS section_pages_json"
    section_meta = "s.section_meta_json" if "section_meta_json" in section_columns else "'{}' AS section_meta_json"
    title_expr = "p.title" if {"id", "title"} <= paper_columns else "'' AS title"
    join_expr = "LEFT JOIN papers p ON p.id = s.paper_id" if {"id", "title"} <= paper_columns else ""
    sql = f"""
        SELECT s.paper_id, s.section_name, s.section_text, {source_url},
               {section_pages}, {section_meta}, {title_expr}
        FROM paper_sections s
        {join_expr}
        WHERE COALESCE(s.section_text, '') != ''
        ORDER BY s.paper_id, s.section_name
    """
    if limit is not None:
        sql += " LIMIT ?"
        rows = conn.execute(sql, (int(limit),)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    total = 0
    by_type: dict[str, int] = {}
    by_grade: dict[str, int] = {}
    pending: list[dict[str, Any]] = []
    for row in rows:
        atoms = extract_section_atoms_from_row(row, max_atoms_per_section=max_atoms_per_section)
        for atom in atoms:
            by_type[atom["atom_type"]] = by_type.get(atom["atom_type"], 0) + 1
            by_grade[atom["evidence_grade"]] = by_grade.get(atom["evidence_grade"], 0) + 1
        pending.extend(atoms)
        if len(pending) >= 1000:
            total += _insert_atoms(conn, pending, replace_fts_rows=not rebuild)
            pending = []
    if pending:
        total += _insert_atoms(conn, pending, replace_fts_rows=not rebuild)
    conn.commit()
    fts_enabled = _table_exists(conn, "section_atoms_fts")
    conn.close()
    return {
        "sections_processed": len(rows),
        "atoms_written": total,
        "by_type": by_type,
        "by_evidence_grade": by_grade,
        "fts_enabled": fts_enabled,
    }


def _fts_query(text: str) -> str:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", text or "")
    unique_tokens = list(dict.fromkeys(t for t in tokens if t.strip()))
    return " OR ".join(f'"{token}"' for token in unique_tokens[:16])


def search_section_atoms(
    conn: sqlite3.Connection,
    query_text: str,
    *,
    top_k: int = 20,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    filters = filters or {}
    ensure_section_atoms_schema(conn)
    where = []
    params: list[Any] = []
    if filters.get("paper_id"):
        where.append("a.paper_id = ?")
        params.append(str(filters["paper_id"]))
    if filters.get("atom_type"):
        where.append("a.atom_type = ?")
        params.append(str(filters["atom_type"]))
    if filters.get("section_name"):
        where.append("a.section_key = ?")
        params.append(normalize_section_key(filters["section_name"]))
    where_sql = " AND ".join(where)
    if _table_exists(conn, "section_atoms_fts") and query_text:
        q = _fts_query(query_text)
        if q:
            extra = f" AND {where_sql}" if where_sql else ""
            rows = conn.execute(
                f"""
                SELECT a.*, bm25(section_atoms_fts) AS rank_score
                FROM section_atoms_fts f
                JOIN section_atoms a ON a.atom_id = f.atom_id
                WHERE section_atoms_fts MATCH ?{extra}
                ORDER BY rank_score
                LIMIT ?
                """,
                (q, *params, int(top_k)),
            ).fetchall()
            return [_row_to_hit(row) for row in rows]
    pattern = f"%{query_text.lower()}%" if query_text else "%"
    extra = f" AND {where_sql}" if where_sql else ""
    rows = conn.execute(
        f"""
        SELECT a.*, 0.0 AS rank_score
        FROM section_atoms a
        WHERE lower(a.atom_text || ' ' || COALESCE(a.title, '')) LIKE ?{extra}
        ORDER BY a.evidence_grade ASC, a.paper_id, a.atom_index
        LIMIT ?
        """,
        (pattern, *params, int(top_k)),
    ).fetchall()
    return [_row_to_hit(row) for row in rows]


def _row_to_hit(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["uncertainty_reasons"] = _loads(item.pop("uncertainty_reasons_json", "[]"), [])
    item["features"] = _loads(item.pop("features_json", "{}"), {})
    item["search_semantics"] = "retrieval hit only; not a Topic Dossier or Claim Card conclusion"
    return item


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build searchable section evidence atoms from paper_sections.")
    add_common_args(parser)
    parser.add_argument("--max-atoms-per-section", type=int, default=12)
    parser.add_argument("--no-rebuild", action="store_true")
    parser.add_argument("--query", default=None, help="Optional smoke-test query after building atoms.")
    args = parser.parse_args(argv)
    setup_logging("section_atoms", level=getattr(logging, args.log_level))
    db_main = Path(args.db) if args.db else DB_MAIN
    stats = build_section_atoms(
        db_main,
        limit=args.limit,
        rebuild=not args.no_rebuild,
        max_atoms_per_section=args.max_atoms_per_section,
    )
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    if args.query:
        conn = sqlite3.connect(str(db_main))
        conn.row_factory = sqlite3.Row
        hits = search_section_atoms(conn, args.query, top_k=5)
        conn.close()
        print(json.dumps({"query": args.query, "hits": hits}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
