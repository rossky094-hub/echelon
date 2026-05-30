"""Audit and prepare high-value section-ingest queues.

The section crawler is not just a PDF downloader.  It is the evidence supply
chain for Step5c limitation extraction, Step13 Claim Cards, Topic Lens, and the
R&D Radar.  This audit makes the queue accountable: it records which high-value
papers are covered by the current top-N budget, which already have primary
section evidence, and which papers should be sent into the next delta ingest.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, DB_V14
from echelon.v14b.evidence_contracts import section_provenance_strength
from echelon.v14b.product_baseline import PRODUCT_BASELINE_TOPICS
from echelon.v14b.step5s_section_ingest import (
    PRIMARY_SECTION_NAMES,
    SECTION_PARSER_CONTRACT_VERSION,
    _arxiv_pdf_url,
    _select_candidate_ids,
)
from echelon.v14b.utils import add_common_args, setup_logging

logger = logging.getLogger("echelon.v14b.step5s_section_queue_audit")

DEFAULT_SECTION_AUDIT_TOPICS = PRODUCT_BASELINE_TOPICS


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _loads(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _ensure_audit_tables(conn_v14: sqlite3.Connection) -> None:
    conn_v14.executescript(
        """
        CREATE TABLE IF NOT EXISTS section_priority_papers (
            paper_id TEXT PRIMARY KEY,
            priority_score REAL NOT NULL DEFAULT 0,
            reasons_json TEXT NOT NULL,
            in_top_n INTEGER NOT NULL DEFAULT 0,
            has_any_section INTEGER NOT NULL DEFAULT 0,
            has_primary_section INTEGER NOT NULL DEFAULT 0,
            has_current_primary_section INTEGER NOT NULL DEFAULT 0,
            has_decision_grade_primary_section INTEGER NOT NULL DEFAULT 0,
            eligible_pdf INTEGER NOT NULL DEFAULT 0,
            last_attempt_outcome TEXT,
            last_attempt_ts TEXT,
            retry_class TEXT,
            retry_priority REAL NOT NULL DEFAULT 0,
            access_strategy TEXT,
            section_contract_status TEXT,
            title TEXT,
            publication_year INTEGER,
            source_url TEXT,
            audit_ts TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS section_priority_summary (
            audit_ts TEXT NOT NULL,
            category TEXT NOT NULL,
            total INTEGER NOT NULL,
            in_top_n INTEGER NOT NULL,
            any_section INTEGER NOT NULL,
            primary_section INTEGER NOT NULL,
            current_primary_section INTEGER NOT NULL DEFAULT 0,
            decision_grade_primary_section INTEGER NOT NULL DEFAULT 0,
            eligible_pdf INTEGER NOT NULL,
            coverage_json TEXT NOT NULL,
            PRIMARY KEY (audit_ts, category)
        );
        CREATE INDEX IF NOT EXISTS idx_section_priority_score
            ON section_priority_papers(priority_score DESC);
        CREATE INDEX IF NOT EXISTS idx_section_priority_primary
            ON section_priority_papers(has_primary_section, priority_score DESC);
        """
    )
    cols = _cols(conn_v14, "section_priority_papers")
    for col, ddl in {
        "last_attempt_outcome": "ALTER TABLE section_priority_papers ADD COLUMN last_attempt_outcome TEXT",
        "last_attempt_ts": "ALTER TABLE section_priority_papers ADD COLUMN last_attempt_ts TEXT",
        "retry_class": "ALTER TABLE section_priority_papers ADD COLUMN retry_class TEXT",
        "retry_priority": "ALTER TABLE section_priority_papers ADD COLUMN retry_priority REAL NOT NULL DEFAULT 0",
        "access_strategy": "ALTER TABLE section_priority_papers ADD COLUMN access_strategy TEXT",
        "has_current_primary_section": "ALTER TABLE section_priority_papers ADD COLUMN has_current_primary_section INTEGER NOT NULL DEFAULT 0",
        "has_decision_grade_primary_section": "ALTER TABLE section_priority_papers ADD COLUMN has_decision_grade_primary_section INTEGER NOT NULL DEFAULT 0",
        "section_contract_status": "ALTER TABLE section_priority_papers ADD COLUMN section_contract_status TEXT",
    }.items():
        if col not in cols:
            conn_v14.execute(ddl)
    summary_cols = _cols(conn_v14, "section_priority_summary")
    if "current_primary_section" not in summary_cols:
        conn_v14.execute(
            "ALTER TABLE section_priority_summary "
            "ADD COLUMN current_primary_section INTEGER NOT NULL DEFAULT 0"
        )
        for row in conn_v14.execute(
            """
            SELECT audit_ts, category, total, coverage_json
            FROM section_priority_summary
            """
        ).fetchall():
            payload = _loads(row["coverage_json"], {})
            try:
                rate = float(payload.get("current_primary_section_rate") or 0.0)
                total = int(row["total"] or 0)
                current_n = int(round(rate * total))
            except (TypeError, ValueError):
                current_n = 0
                total = int(row["total"] or 0)
            conn_v14.execute(
                """
                UPDATE section_priority_summary
                SET current_primary_section = ?
                WHERE audit_ts = ? AND category = ?
                """,
                (max(0, min(total, current_n)), row["audit_ts"], row["category"]),
            )
    if "decision_grade_primary_section" not in summary_cols:
        conn_v14.execute(
            "ALTER TABLE section_priority_summary "
            "ADD COLUMN decision_grade_primary_section INTEGER NOT NULL DEFAULT 0"
        )


def _add(
    reasons: dict[str, set[str]],
    scores: Counter[str],
    categories: dict[str, set[str]],
    paper_id: Any,
    category: str,
    weight: float,
    reason: str | None = None,
) -> None:
    if paper_id is None:
        return
    pid = str(paper_id).strip()
    if not pid:
        return
    reasons[pid].add(category)
    if reason and reason != category:
        reasons[pid].add(reason)
    scores[pid] += float(weight)
    categories[category].add(pid)


def _split_paper_ids(raw: Any) -> list[str]:
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        vals = raw
    else:
        vals = str(raw).replace("|", ";").replace(",", ";").split(";")
    out: list[str] = []
    seen: set[str] = set()
    for val in vals:
        pid = str(val).strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
    return out


def _load_topic_evidence_gap_rows(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            rows.append(dict(row))
    return rows


def _gap_category(gap_type: str) -> str:
    if "bottleneck" in gap_type:
        return "topic_gap_bottleneck_evidence"
    if "turning" in gap_type:
        return "topic_gap_key_turning_section"
    if "claim_card" in gap_type:
        return "topic_gap_claim_card_inputs"
    return "topic_evidence_gap"


def apply_topic_evidence_gap_queue(
    reasons: dict[str, set[str]],
    scores: Counter[str],
    categories: dict[str, set[str]],
    *,
    gap_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge multi-topic regression gaps into the section evidence budget.

    The regression gate should not merely fail; it should feed the next section
    ingest batch with the exact papers whose missing sections block useful
    Topic Dossiers and Claim Cards.
    """
    paper_ids: set[str] = set()
    rows_without_ids = 0
    category_counts: Counter[str] = Counter()
    for row in gap_rows:
        gap_type = str(row.get("gap_type") or "topic_evidence_gap")
        category = _gap_category(gap_type)
        pids = _split_paper_ids(row.get("candidate_paper_ids"))
        if not pids:
            rows_without_ids += 1
            continue
        try:
            priority = float(row.get("priority") or 80.0)
        except (TypeError, ValueError):
            priority = 80.0
        topic = str(row.get("topic") or "topic").strip()
        bottleneck = str(row.get("bottleneck") or "").strip()
        for pid in pids:
            paper_ids.add(pid)
            category_counts[category] += 1
            reason = f"topic_gap:{topic}:{gap_type}"
            if bottleneck:
                reason += f":{bottleneck}"
            _add(reasons, scores, categories, pid, category, max(priority, 80.0) + 120.0, reason)
            _add(reasons, scores, categories, pid, f"topic:{topic}", 25.0, reason)
    return {
        "gap_rows": len(gap_rows),
        "gap_rows_without_candidate_papers": rows_without_ids,
        "gap_paper_ids": len(paper_ids),
        "gap_category_counts": dict(category_counts),
    }


def collect_priority_sets(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    *,
    topic_terms: list[str],
    topic_limit: int,
    top_n: int,
) -> tuple[dict[str, set[str]], Counter[str], dict[str, set[str]], list[str]]:
    reasons: dict[str, set[str]] = defaultdict(set)
    scores: Counter[str] = Counter()
    categories: dict[str, set[str]] = defaultdict(set)

    if _table_exists(conn_v14, "predicted_future_edges"):
        cols = _cols(conn_v14, "predicted_future_edges")
        conf_terms = [
            col for col in ("prediction_confidence", "calibrated_prob", "predicted_prob")
            if col in cols
        ]
        conf_expr = f"COALESCE({', '.join(conf_terms)}, 0)" if conf_terms else "0"
        for row in conn_v14.execute(
            f"""
            SELECT src_paper_id, dst_paper_id, {conf_expr} AS confidence
            FROM predicted_future_edges
            ORDER BY {conf_expr} DESC
            LIMIT ?
            """,
            (max(top_n, 2000),),
        ).fetchall():
            _add(reasons, scores, categories, row[0], "future_endpoint", 8.0, "future edge source")
            _add(reasons, scores, categories, row[1], "future_endpoint", 8.0, "future edge target")
            if float(row[2] or 0) < 0.7:
                _add(reasons, scores, categories, row[0], "active_learning_uncertain_future", 3.0)
                _add(reasons, scores, categories, row[1], "active_learning_uncertain_future", 3.0)

    if _table_exists(conn_v14, "limitation_atoms"):
        cols = _cols(conn_v14, "limitation_atoms")
        severity_expr = (
            "CASE COALESCE(severity, 'medium') WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END"
            if "severity" in cols
            else "1"
        )
        weight_expr = "COALESCE(evidence_weight, 0)" if "evidence_weight" in cols else "0"
        for row in conn_v14.execute(
            f"""
            SELECT paper_id
            FROM limitation_atoms
            ORDER BY {severity_expr} DESC, {weight_expr} DESC, paper_id
            LIMIT ?
            """,
            (max(top_n, 3000),),
        ).fetchall():
            _add(reasons, scores, categories, row[0], "limitation_evidence", 7.0)

    if _table_exists(conn_v14, "limitation_resolutions"):
        for row in conn_v14.execute(
            """
            SELECT resolver_paper_id
            FROM limitation_resolutions
            ORDER BY COALESCE(confidence, 0) DESC, resolver_paper_id
            LIMIT ?
            """,
            (max(top_n, 2000),),
        ).fetchall():
            _add(reasons, scores, categories, row[0], "resolution_evidence", 6.0)

    if _table_exists(conn_v14, "main_path_edges"):
        cols = _cols(conn_v14, "main_path_edges")
        src = "source_paper_id" if "source_paper_id" in cols else "citing_id"
        dst = "target_paper_id" if "target_paper_id" in cols else "cited_id"
        weight = "COALESCE(main_path_weight, spc, 0)" if "main_path_weight" in cols else "COALESCE(spc, 0)"
        for row in conn_v14.execute(
            f"""
            SELECT {src}, {dst}
            FROM main_path_edges
            WHERE COALESCE(is_main_path, 0) = 1
            ORDER BY {weight} DESC
            LIMIT ?
            """,
            (max(top_n, 3000),),
        ).fetchall():
            _add(reasons, scores, categories, row[0], "main_path_node", 9.0)
            _add(reasons, scores, categories, row[1], "main_path_node", 9.0)

    if _table_exists(conn_v14, "branch_lineages"):
        cols = _cols(conn_v14, "branch_lineages")
        evidence_col = "split_evidence_json" if "split_evidence_json" in cols else "why_json"
        conf_col = "split_confidence" if "split_confidence" in cols else "strength"
        for row in conn_v14.execute(
            f"""
            SELECT {evidence_col}, COALESCE({conf_col}, 0) AS conf
            FROM branch_lineages
            ORDER BY COALESCE({conf_col}, 0) DESC
            LIMIT ?
            """,
            (max(top_n, 6000),),
        ).fetchall():
            payload = _loads(row[0], {})
            driver_papers = []
            if isinstance(payload, dict):
                driver_papers.extend(payload.get("driver_papers") or [])
                for key in ("papers", "evidence_papers", "turning_papers"):
                    driver_papers.extend(payload.get(key) or [])
            for pid in driver_papers:
                _add(reasons, scores, categories, pid, "branch_split_driver", 8.0)

    if _table_exists(conn_v14, "subgraph_nodes"):
        for row in conn_v14.execute(
            """
            SELECT paper_id
            FROM subgraph_nodes
            WHERE COALESCE(is_keystone, 0) = 1
               OR COALESCE(keystone_score_v14, 0) >= 0.75
            ORDER BY COALESCE(keystone_score_v14, 0) DESC
            LIMIT ?
            """,
            (max(top_n, 5000),),
        ).fetchall():
            _add(reasons, scores, categories, row[0], "top_keystone", 7.0)

    if _table_exists(conn_v14, "visual_nodes"):
        for row in conn_v14.execute(
            """
            SELECT paper_id
            FROM visual_nodes
            ORDER BY COALESCE(uncertainty_score, 0) DESC, COALESCE(node_size, 0) DESC
            LIMIT ?
            """,
            (min(max(top_n // 4, 1000), 5000),),
        ).fetchall():
            _add(reasons, scores, categories, row[0], "active_learning_uncertainty_hotspot", 2.5)

    if _table_exists(conn_v14, "visual_clusters") and _table_exists(conn_v14, "visual_nodes"):
        for row in conn_v14.execute(
            """
            SELECT paper_id FROM (
                SELECT v.paper_id, v.cluster_id, v.node_size,
                       ROW_NUMBER() OVER (
                           PARTITION BY v.cluster_id
                           ORDER BY COALESCE(v.node_size, 0) DESC, v.paper_id
                       ) AS rn
                FROM visual_nodes v
            )
            WHERE rn <= 3
            LIMIT ?
            """,
            (max(top_n, 6000),),
        ).fetchall():
            _add(reasons, scores, categories, row[0], "cluster_representative", 3.0)

    for topic in topic_terms:
        q = f"%{topic.lower()}%"
        for row in conn_main.execute(
            """
            SELECT id
            FROM papers
            WHERE lower(COALESCE(title, '') || ' ' || COALESCE(abstract, '')) LIKE ?
            ORDER BY COALESCE(cited_by_count, 0) DESC, publication_date DESC
            LIMIT ?
            """,
            (q, topic_limit),
        ).fetchall():
            _add(reasons, scores, categories, row[0], f"topic:{topic}", 5.0)

    candidate_ids = _select_candidate_ids(conn_v14, top_n)
    return reasons, scores, categories, candidate_ids


def _section_status(conn_main: sqlite3.Connection) -> tuple[set[str], set[str], set[str], set[str]]:
    if not _table_exists(conn_main, "paper_sections"):
        return set(), set(), set(), set()
    any_rows = conn_main.execute("SELECT DISTINCT paper_id FROM paper_sections").fetchall()
    any_section = {str(r[0]) for r in any_rows}
    ph = ",".join("?" for _ in PRIMARY_SECTION_NAMES)
    primary_rows = conn_main.execute(
        f"""
        SELECT DISTINCT paper_id
        FROM paper_sections
        WHERE section_name IN ({ph})
          AND length(trim(section_text)) >= 80
        """,
        PRIMARY_SECTION_NAMES,
    ).fetchall()
    primary_section = {str(r[0]) for r in primary_rows}
    current_primary_section: set[str] = set()
    decision_grade_primary_section: set[str] = set()
    if "section_meta_json" in _cols(conn_main, "paper_sections"):
        current_rows = conn_main.execute(
            f"""
            SELECT paper_id, section_name, section_meta_json
            FROM paper_sections
            WHERE section_name IN ({ph})
              AND section_text IS NOT NULL
              AND length(trim(section_text)) >= 80
            """,
            PRIMARY_SECTION_NAMES,
        ).fetchall()
        for row in current_rows:
            meta = _loads(row["section_meta_json"], {})
            if meta.get("parser_contract_version") != SECTION_PARSER_CONTRACT_VERSION:
                continue
            paper_id = str(row["paper_id"])
            current_primary_section.add(paper_id)
            strength = section_provenance_strength(
                {
                    "section_name": row["section_name"],
                    "extraction_strategies": meta.get("extraction_strategies"),
                    "evidence_grade": meta.get("evidence_grade"),
                    "parser_contract_version": meta.get("parser_contract_version"),
                }
            )
            if strength in {"strong", "moderate"}:
                decision_grade_primary_section.add(paper_id)
    return any_section, primary_section, current_primary_section, decision_grade_primary_section


def _latest_attempts(conn_main: sqlite3.Connection, paper_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not paper_ids or not _table_exists(conn_main, "section_ingest_attempts"):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(paper_ids), 800):
        chunk = paper_ids[i:i + 800]
        ph = ",".join("?" for _ in chunk)
        rows = conn_main.execute(
            f"""
            SELECT paper_id, attempt_ts, outcome, source_url, detail,
                   inserted_sections, primary_sections
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY paper_id
                           ORDER BY attempt_ts DESC, attempt_id DESC
                       ) AS rn
                FROM section_ingest_attempts
                WHERE paper_id IN ({ph})
            )
            WHERE rn = 1
            """,
            chunk,
        ).fetchall()
        for row in rows:
            out[str(row["paper_id"])] = dict(row)
    return out


def _retry_class_and_strategy(
    *,
    outcome: str,
    eligible_pdf: bool,
    has_primary: bool,
    has_current_primary: bool,
    has_decision_grade_primary: bool,
) -> tuple[str, float, str]:
    if has_decision_grade_primary:
        return "covered", 0.0, "decision_grade_section_ready"
    if has_current_primary:
        return "weak_current_contract", 3.0, "manual/alternate parser review before evidence promotion"
    if has_primary or outcome == "success_primary":
        if eligible_pdf:
            return "stale_parser_contract", 6.0, "reparse with current parser contract before evidence promotion"
        return "stale_parser_contract", 3.0, "recover PDF/source URL, then reparse with current parser contract"
    if outcome == "success_secondary_only":
        return "partial_section", 2.0, "keep as weak evidence; retry if paper is decision-critical"
    if outcome in {"pdf_download_failed", "parse_timeout", "parser_exception"}:
        return "retryable_pdf_failure", 4.0, "retry with conservative timeout or alternate open-access URL"
    if outcome == "parse_no_blocks":
        return "parser_failure", 3.5, "retry with alternate parser or mark as external-access evidence gap"
    if outcome == "no_target_sections":
        return "no_target_sections", 1.0, "do not treat as strong bottleneck evidence; use abstract/metadata only with weak scope"
    if outcome == "no_pdf_url":
        return "needs_access_link", 2.5, "synthesize DOI/S2/OpenAlex/arXiv links and try Semantic Scholar/OpenAlex OA metadata"
    if eligible_pdf:
        return "not_attempted_pdf_available", 5.0, "high-priority delta ingest candidate"
    return "not_attempted_no_pdf", 1.5, "needs external access link or OA metadata backfill"


def _paper_metadata(conn_main: sqlite3.Connection, paper_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not paper_ids:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(paper_ids), 900):
        chunk = paper_ids[i:i + 900]
        ph = ",".join("?" for _ in chunk)
        for row in conn_main.execute(
            f"""
            SELECT id, title, publication_year, publication_date, arxiv_id, doi, s2_paper_id,
                   openalex_id, cited_by_count
            FROM papers
            WHERE id IN ({ph})
            """,
            chunk,
        ).fetchall():
            meta = dict(row)
            meta["source_url"] = _arxiv_pdf_url(meta.get("arxiv_id"), meta.get("doi")) or ""
            out[str(row["id"])] = meta
    return out


def _section_contract_status(
    *,
    has_primary: bool,
    has_current_primary: bool,
    has_decision_grade_primary: bool,
) -> str:
    if has_decision_grade_primary:
        return "decision_grade_current_contract"
    if has_current_primary:
        return "current_contract_weak"
    if has_primary:
        return "stale_or_missing_parser_contract"
    return "missing_primary_section"


def run_section_queue_audit(
    *,
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    top_n: int = 12000,
    out_dir: Path = Path("reports/v14b_pilot"),
    data_dir: Path = Path("data/v14b"),
    topic_terms: list[str] | None = None,
    topic_limit: int = 500,
    topic_evidence_gap_queue: Path | None = Path("reports/v14b_pilot/multi_topic_evidence_gap_queue.csv"),
) -> dict[str, Any]:
    topic_terms = topic_terms or list(DEFAULT_SECTION_AUDIT_TOPICS)
    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    conn_v14 = sqlite3.connect(str(db_v14))
    conn_v14.row_factory = sqlite3.Row
    _ensure_audit_tables(conn_v14)

    reasons, scores, categories, candidate_ids = collect_priority_sets(
        conn_main,
        conn_v14,
        topic_terms=topic_terms,
        topic_limit=topic_limit,
        top_n=top_n,
    )
    gap_rows = _load_topic_evidence_gap_rows(topic_evidence_gap_queue)
    gap_summary = apply_topic_evidence_gap_queue(
        reasons,
        scores,
        categories,
        gap_rows=gap_rows,
    )
    candidate_set = set(candidate_ids)
    any_section, primary_section, current_primary_section, decision_grade_primary_section = _section_status(conn_main)
    all_ids = sorted(reasons.keys(), key=lambda pid: (-scores[pid], pid))
    meta = _paper_metadata(conn_main, all_ids)
    attempts = _latest_attempts(conn_main, all_ids)
    audit_ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    rows = []
    for pid in all_ids:
        m = meta.get(pid, {})
        eligible = bool(m.get("source_url"))
        attempt = attempts.get(pid, {})
        retry_class, retry_boost, access_strategy = _retry_class_and_strategy(
            outcome=str(attempt.get("outcome") or ""),
            eligible_pdf=eligible,
            has_primary=pid in primary_section,
            has_current_primary=pid in current_primary_section,
            has_decision_grade_primary=pid in decision_grade_primary_section,
        )
        section_contract_status = _section_contract_status(
            has_primary=pid in primary_section,
            has_current_primary=pid in current_primary_section,
            has_decision_grade_primary=pid in decision_grade_primary_section,
        )
        rows.append(
            {
                "paper_id": pid,
                "priority_score": round(float(scores[pid]) + retry_boost, 4),
                "reasons": sorted(reasons[pid]),
                "in_top_n": pid in candidate_set,
                "has_any_section": pid in any_section,
                "has_primary_section": pid in primary_section,
                "has_current_primary_section": pid in current_primary_section,
                "has_decision_grade_primary_section": pid in decision_grade_primary_section,
                "eligible_pdf": eligible,
                "last_attempt_outcome": attempt.get("outcome") or "",
                "last_attempt_ts": attempt.get("attempt_ts") or "",
                "retry_class": retry_class,
                "retry_priority": retry_boost,
                "access_strategy": access_strategy,
                "section_contract_status": section_contract_status,
                "title": m.get("title") or "",
                "publication_year": m.get("publication_year") or (str(m.get("publication_date") or "")[:4] or None),
                "source_url": m.get("source_url") or "",
                "doi": m.get("doi") or "",
                "arxiv_id": m.get("arxiv_id") or "",
                "openalex_id": m.get("openalex_id") or "",
                "s2_paper_id": m.get("s2_paper_id") or "",
            }
        )

    conn_v14.execute("DELETE FROM section_priority_papers")
    conn_v14.executemany(
        """
        INSERT OR REPLACE INTO section_priority_papers
            (paper_id, priority_score, reasons_json, in_top_n, has_any_section,
             has_primary_section, has_current_primary_section, has_decision_grade_primary_section, eligible_pdf,
             last_attempt_outcome, last_attempt_ts, retry_class, retry_priority,
             access_strategy, section_contract_status, title, publication_year,
             source_url, audit_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["paper_id"],
                r["priority_score"],
                json.dumps(r["reasons"], ensure_ascii=False),
                int(r["in_top_n"]),
                int(r["has_any_section"]),
                int(r["has_primary_section"]),
                int(r["has_current_primary_section"]),
                int(r["has_decision_grade_primary_section"]),
                int(r["eligible_pdf"]),
                r["last_attempt_outcome"],
                r["last_attempt_ts"],
                r["retry_class"],
                r["retry_priority"],
                r["access_strategy"],
                r["section_contract_status"],
                r["title"],
                int(r["publication_year"]) if str(r["publication_year"] or "").isdigit() else None,
                r["source_url"],
                audit_ts,
            )
            for r in rows
        ],
    )

    summary_rows = []
    for category, ids in sorted(categories.items()):
        ids_set = set(ids)
        total = len(ids_set)
        in_top = len(ids_set & candidate_set)
        any_n = len(ids_set & any_section)
        primary_n = len(ids_set & primary_section)
        current_primary_n = len(ids_set & current_primary_section)
        decision_grade_primary_n = len(ids_set & decision_grade_primary_section)
        eligible_n = sum(1 for pid in ids_set if meta.get(pid, {}).get("source_url"))
        payload = {
            "in_top_n_rate": in_top / max(1, total),
            "primary_section_rate": primary_n / max(1, total),
            "current_primary_section_rate": current_primary_n / max(1, total),
            "decision_grade_primary_section_rate": decision_grade_primary_n / max(1, total),
            "eligible_pdf_rate": eligible_n / max(1, total),
        }
        summary_rows.append(
            {
                "category": category,
                "total": total,
                "in_top_n": in_top,
                "any_section": any_n,
                "primary_section": primary_n,
                "current_primary_section": current_primary_n,
                "decision_grade_primary_section": decision_grade_primary_n,
                "eligible_pdf": eligible_n,
                "coverage": payload,
            }
        )
        conn_v14.execute(
            """
            INSERT OR REPLACE INTO section_priority_summary
                (audit_ts, category, total, in_top_n, any_section, primary_section,
                 current_primary_section, decision_grade_primary_section, eligible_pdf, coverage_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_ts,
                category,
                total,
                in_top,
                any_n,
                primary_n,
                current_primary_n,
                decision_grade_primary_n,
                eligible_n,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
    conn_v14.commit()

    def is_topic_gap_row(row: dict[str, Any]) -> bool:
        return any(str(reason).startswith("topic_gap") for reason in (row.get("reasons") or []))

    delta_rows = [
        r for r in rows
        if not r["has_decision_grade_primary_section"]
        and r["retry_class"] != "covered"
        and (
            r["retry_class"] != "no_target_sections"
            or is_topic_gap_row(r)
        )
        and (
            r["eligible_pdf"]
            or r["retry_class"] in {
                "needs_access_link",
                "retryable_pdf_failure",
                "parser_failure",
                "no_target_sections",
                "stale_parser_contract",
                "weak_current_contract",
            }
        )
    ]
    delta_rows = sorted(delta_rows, key=lambda r: (-float(r["priority_score"]), r["retry_class"], r["paper_id"]))
    topic_gap_rows = [r for r in delta_rows if is_topic_gap_row(r)]
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "section_high_value_queue_audit.json"
    md_path = out_dir / "section_high_value_queue_audit.md"
    csv_path = data_dir / "section_delta_queue.csv"
    topic_gap_csv_path = data_dir / "topic_evidence_gap_delta_queue.csv"

    result = {
        "audit_ts": audit_ts,
        "top_n": top_n,
        "topic_terms": topic_terms,
        "topic_evidence_gap_queue": str(topic_evidence_gap_queue) if topic_evidence_gap_queue else "",
        "topic_evidence_gap_summary": gap_summary,
        "high_value_papers": len(rows),
        "candidate_top_n": len(candidate_set),
        "primary_section_papers": len(primary_section),
        "current_contract_primary_section_papers": len(current_primary_section),
        "decision_grade_primary_section_papers": len(decision_grade_primary_section),
        "weak_current_contract_primary_section_papers": len(current_primary_section - decision_grade_primary_section),
        "stale_primary_section_papers": len(primary_section - current_primary_section),
        "delta_queue": len(delta_rows),
        "topic_gap_delta_queue": len(topic_gap_rows),
        "retry_class_counts": dict(Counter(str(r["retry_class"]) for r in rows)),
        "summary": summary_rows,
        "top_delta": delta_rows[:200],
        "top_topic_gap_delta": topic_gap_rows[:200],
        "outputs": {
            "json": str(json_path),
            "markdown": str(md_path),
            "csv": str(csv_path),
            "topic_gap_csv": str(topic_gap_csv_path),
        },
    }
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    fieldnames = [
        "paper_id", "priority_score", "reasons", "in_top_n", "has_any_section",
        "has_primary_section", "has_current_primary_section", "has_decision_grade_primary_section",
        "section_contract_status",
        "eligible_pdf", "last_attempt_outcome", "last_attempt_ts", "retry_class",
        "retry_priority", "access_strategy", "publication_year", "title", "source_url",
        "doi", "arxiv_id", "openalex_id", "s2_paper_id",
    ]

    def write_delta_csv(path: Path, selected_rows: list[dict[str, Any]]) -> None:
        def clean_cell(value: Any) -> Any:
            if isinstance(value, str):
                return " ".join(value.split())
            return value

        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for r in selected_rows:
                row = dict(r)
                row["reasons"] = "|".join(row["reasons"])
                row = {key: clean_cell(row.get(key, "")) for key in fieldnames}
                writer.writerow(row)

    write_delta_csv(csv_path, delta_rows)
    write_delta_csv(topic_gap_csv_path, topic_gap_rows)
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        # Keep a small readback so tests and operators fail early on broken CSV
        # serialization instead of discovering it inside the long-running ingest.
        next(csv.DictReader(f), None)

    lines = [
        "# V14B Section High-Value Queue Audit",
        "",
        f"- audit_ts: `{audit_ts}`",
        f"- current top_n budget: `{top_n}`",
        f"- high-value papers considered: `{len(rows):,}`",
        f"- primary section papers: `{len(primary_section):,}`; "
        f"current parser-contract primary: `{len(current_primary_section):,}`; "
        f"decision-grade primary: `{len(decision_grade_primary_section):,}`",
        f"- next delta queue needing primary section/action: `{len(delta_rows):,}`",
        f"- multi-topic evidence-gap rows merged: `{gap_summary['gap_rows']:,}` "
        f"({gap_summary['gap_paper_ids']:,} papers)",
        f"- topic evidence-gap delta queue: `{len(topic_gap_rows):,}` papers",
        "",
        "## Failure / Retry Classes",
        "",
        "| retry_class | count |",
        "|---|---:|",
    ]
    retry_counts = Counter(str(r["retry_class"]) for r in rows)
    for cls, count in retry_counts.most_common():
        lines.append(f"| {cls} | {count:,} |")
    lines.extend([
        "",
        "## Category Coverage",
        "",
        "| category | total | in topN | any section | primary section | current parser primary | decision-grade primary | eligible PDF |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for s in summary_rows:
        lines.append(
            f"| {s['category']} | {s['total']:,} | {s['in_top_n']:,} | "
            f"{s['any_section']:,} | {s['primary_section']:,} | "
            f"{s['current_primary_section']:,} | {s['decision_grade_primary_section']:,} | "
            f"{s['eligible_pdf']:,} |"
        )
    lines.extend(
        [
            "",
            "## Why This Matters",
            "",
            "This queue is the evidence budget for limitation extraction, bottleneck lineage, "
            "Claim Cards, Topic Lens, and the R&D Radar. Papers missing primary section "
            "evidence cannot support high-confidence claims even if they are important graph nodes.",
            "",
            "Multi-topic regression gaps are merged into this budget so failed Topic Dossiers "
            "become targeted section evidence work instead of passive report failures.",
            "",
            f"Delta queue CSV: `{csv_path}`",
            f"Topic evidence-gap delta CSV: `{topic_gap_csv_path}`",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    conn_main.close()
    conn_v14.close()
    logger.info(
        "section queue audit done: high_value=%s delta=%s topic_gap_delta=%s outputs=%s",
        result["high_value_papers"],
        result["delta_queue"],
        result["topic_gap_delta_queue"],
        result["outputs"],
    )
    return result


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step5s_section_queue_audit",
        description="Audit high-value section-ingest coverage and emit delta queue.",
    )
    add_common_args(parser)
    parser.add_argument("--top-n", type=int, default=12000)
    parser.add_argument("--out-dir", default="reports/v14b_pilot")
    parser.add_argument("--data-dir", default="data/v14b")
    parser.add_argument("--topic", action="append", default=None)
    parser.add_argument("--topic-limit", type=int, default=500)
    parser.add_argument(
        "--topic-evidence-gap-queue",
        default="reports/v14b_pilot/multi_topic_evidence_gap_queue.csv",
        help="CSV emitted by topic_regression; merged into section delta priorities when present.",
    )
    args = parser.parse_args(argv)
    setup_logging("step5s_section_queue_audit", level=getattr(logging, args.log_level))
    run_section_queue_audit(
        db_main=Path(args.db) if args.db else DB_MAIN,
        db_v14=Path(args.db_v14) if args.db_v14 else DB_V14,
        top_n=args.top_n,
        out_dir=Path(args.out_dir),
        data_dir=Path(args.data_dir),
        topic_terms=args.topic or list(DEFAULT_SECTION_AUDIT_TOPICS),
        topic_limit=args.topic_limit,
        topic_evidence_gap_queue=Path(args.topic_evidence_gap_queue) if args.topic_evidence_gap_queue else None,
    )


if __name__ == "__main__":
    main()
