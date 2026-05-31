"""Step 5s: ingest section-level evidence for limitation tracking.

This step materializes `paper_sections` in the main library DB so Step5c can
read limitation/discussion/conclusion/future-work evidence from full text
instead of falling back to abstract-only extraction.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import signal
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from echelon.pdf.parser import parse_pdf_pages
from echelon.v14b.corpus_registry import create_temp_corpus_table, ensure_corpus_schema
from echelon.v14b.config import (
    DB_MAIN,
    DB_V14,
    LIMIT,
    LIMITATION_TOP_N,
    RAW_PDF_MANIFEST,
    RAW_PDF_MAX_BYTES,
    RAW_PDF_STORE_ROOT,
    SEMANTIC_SCHOLAR_API_KEY,
    SECTION_INGEST_CONCURRENCY,
    SECTION_INGEST_MAX_CHARS,
    SECTION_INGEST_MIN_CHARS,
    SECTION_INGEST_PREFER_LOCAL_RAW_PDF,
    SECTION_INGEST_REQUIRE_ARXIV,
    SECTION_INGEST_TIMEOUT_SEC,
    SECTION_INGEST_TOP_N,
)
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.evidence_contracts import (
    PRIMARY_SECTION_NAMES,
    SECTION_PARSER_CONTRACT_GUARDS,
    SECTION_PARSER_CONTRACT_VERSION,
    SECTION_PARSER_NAME,
)
from echelon.v14b.id_normalization import normalize_arxiv_id, normalize_doi, normalize_s2_paper_id
from echelon.v14b.utils import Checkpoint, add_common_args, make_progress, setup_logging

logger = logging.getLogger("echelon.v14b.step5s_section_ingest")

SECTION_PARSE_TIMEOUT_SEC = int(os.getenv("V14B_SECTION_PARSE_TIMEOUT_SEC", "180"))
SECTION_INGEST_TRUST_ENV = os.getenv("V14B_SECTION_INGEST_TRUST_ENV", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("limitations", re.compile(r"^\s*(section\s+)?(\d+(\.\d+)*|[ivx]+|[a-z])?[\).:\s-]*(limitation|limitations|open challenges?|challenges and limitations|limitations and future work)\s*[:.\-–—]*\s*$", re.I)),
    ("discussion", re.compile(r"^\s*(section\s+)?(\d+(\.\d+)*|[ivx]+|[a-z])?[\).:\s-]*(discussion|discussion and outlook|discussion and conclusions?|results and discussion)\s*[:.\-–—]*\s*$", re.I)),
    ("conclusion", re.compile(r"^\s*(section\s+)?(\d+(\.\d+)*|[ivx]+|[a-z])?[\).:\s-]*(conclusion|conclusions|concluding remarks?|summary|summary and conclusions?)\s*[:.\-–—]*\s*$", re.I)),
    ("future_work", re.compile(r"^\s*(section\s+)?(\d+(\.\d+)*|[ivx]+|[a-z])?[\).:\s-]*(future work|outlook|perspective|perspectives|summary and outlook|conclusions? and outlook)\s*[:.\-–—]*\s*$", re.I)),
    ("results", re.compile(r"^\s*(section\s+)?(\d+(\.\d+)*|[ivx]+|[a-z])?[\).:\s-]*(results?|evaluation|experimental results|results and discussion)\s*[:.\-–—]*\s*$", re.I)),
    ("error_analysis", re.compile(r"^\s*(section\s+)?(\d+(\.\d+)*|[ivx]+|[a-z])?[\).:\s-]*(error analysis|failure analysis|limitations and discussion|failure cases?)\s*[:.\-–—]*\s*$", re.I)),
    ("ablation", re.compile(r"^\s*(section\s+)?(\d+(\.\d+)*|[ivx]+|[a-z])?[\).:\s-]*ablation( study| analysis)?\s*[:.\-–—]*\s*$", re.I)),
    ("method", re.compile(r"^\s*(section\s+)?(\d+(\.\d+)*|[ivx]+|[a-z])?[\).:\s-]*(method|methods|methodology|approach|materials and methods|theoretical model|model and methods|device fabrication|fabrication and characterization)\s*[:.\-–—]*\s*$", re.I)),
    ("experiments", re.compile(r"^\s*(section\s+)?(\d+(\.\d+)*|[ivx]+|[a-z])?[\).:\s-]*(experiment|experiments|experimental setup|experimental methods|experiment setup|validation experiment)\s*[:.\-–—]*\s*$", re.I)),
]

INLINE_SECTION_PREFIXES: list[tuple[str, tuple[str, ...]]] = [
    ("limitations", ("challenges and limitations", "limitations and future work", "open challenges", "limitations", "limitation")),
    ("error_analysis", ("limitations and discussion", "failure analysis", "failure cases", "error analysis")),
    ("future_work", ("summary and outlook", "conclusions and outlook", "conclusion and outlook", "future work", "outlook", "perspectives", "perspective")),
    ("discussion", ("results and discussion", "discussion and conclusions", "discussion and conclusion", "discussion and outlook", "discussion")),
    ("conclusion", ("summary and conclusions", "summary and conclusion", "concluding remarks", "conclusions", "conclusion", "summary")),
    ("results", ("experimental results", "results and discussion", "evaluation", "results", "result")),
    ("ablation", ("ablation analysis", "ablation study", "ablation")),
    ("method", ("fabrication and characterization", "materials and methods", "methods and experiments", "model and methods", "theoretical model", "device fabrication", "methodology", "methods", "method", "approach")),
    ("experiments", ("methods and experiments", "experimental methods", "experimental setup", "experiment setup", "validation experiment", "experiments", "experiment")),
]

LOOSE_INLINE_HEADINGS = {
    "limitation",
    "limitations",
    "discussion",
    "conclusion",
    "conclusions",
    "concluding remarks",
    "summary",
    "method",
    "methods",
    "experiments",
    "experiment",
    "outlook",
}

AMBIGUOUS_FRAGMENT_HEADINGS = {
    "outlook",
    "perspective",
    "perspectives",
}

FALSE_INLINE_BODY_STARTS = {
    "show",
    "shows",
    "showed",
    "indicate",
    "indicates",
    "indicated",
    "suggest",
    "suggests",
    "suggested",
    "demonstrate",
    "demonstrates",
    "demonstrated",
    "reveal",
    "reveals",
    "revealed",
}

EMBEDDED_BOUNDARY_PHRASES: tuple[str, ...] = (
    "abstract",
    "introduction",
    "background",
    "related work",
    "theory",
    "design",
    "simulation",
    "references",
    "bibliography",
    "acknowledgements",
    "acknowledgments",
    "appendix",
    "supplementary",
    "supporting information",
)

STOP_SECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*(\d+(\.\d+)*|[ivx]+|[a-z])?[\).:\s-]*(references|bibliography|acknowledg(e)?ments?|appendix|supplementary|supporting information|data availability|code availability|author contributions?|conflicts? of interest)\s*[:.\-–—]*\s*$", re.I),
]

TERMINAL_SUMMARY_CUE_RE = re.compile(
    r"\b(in summary|in conclusion|to summarize|to conclude)\b\s*[,:\-–—]?\s+",
    re.I,
)
TERMINAL_SUMMARY_STOP_RE = re.compile(
    r"\b(references|bibliography|acknowledg(?:e)?ments?|appendix|supplementary|supporting information)\b",
    re.I,
)

TOC_DOT_LEADER_RE = re.compile(r"\.\s*(?:\.\s*){2,}\d{1,4}(?:\s|$)")
TOC_NUMBERED_ENTRY_RE = re.compile(
    r"^\s*(?:section\s+)?(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)?)\s+"
    r"[A-Z][A-Za-z0-9,&()/+'\-\s]{2,90}\s+\d{1,4}\s*$"
)

SECTION_INGEST_OUTCOMES = {
    "already_has_primary",
    "no_local_raw_pdf",
    "no_pdf_url",
    "pdf_download_failed",
    "parse_timeout",
    "parser_exception",
    "parse_no_blocks",
    "no_target_sections",
    "success_primary",
    "success_secondary_only",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_obj(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def ensure_sections_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_sections (
            paper_id TEXT NOT NULL,
            section_name TEXT NOT NULL,
            section_text TEXT NOT NULL,
            source_type TEXT,
            parser_name TEXT,
            source_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (paper_id, section_name)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_sections_paper ON paper_sections(paper_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_sections_name ON paper_sections(section_name)"
    )
    cols = {
        row[1] for row in conn.execute("PRAGMA table_info(paper_sections)").fetchall()
    }
    if "section_pages_json" not in cols:
        conn.execute("ALTER TABLE paper_sections ADD COLUMN section_pages_json TEXT")
    if "section_meta_json" not in cols:
        conn.execute("ALTER TABLE paper_sections ADD COLUMN section_meta_json TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS section_ingest_attempts (
            attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id TEXT NOT NULL,
            attempt_ts TEXT NOT NULL,
            run_id TEXT,
            outcome TEXT NOT NULL,
            source_url TEXT,
            detail TEXT,
            inserted_sections INTEGER NOT NULL DEFAULT 0,
            primary_sections INTEGER NOT NULL DEFAULT 0,
            candidate_file TEXT,
            parser_name TEXT,
            parser_contract_version TEXT,
            repair_contracts_json TEXT
        )
        """
    )
    attempt_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(section_ingest_attempts)").fetchall()
    }
    if "parser_name" not in attempt_cols:
        conn.execute("ALTER TABLE section_ingest_attempts ADD COLUMN parser_name TEXT")
    if "parser_contract_version" not in attempt_cols:
        conn.execute("ALTER TABLE section_ingest_attempts ADD COLUMN parser_contract_version TEXT")
    if "repair_contracts_json" not in attempt_cols:
        conn.execute("ALTER TABLE section_ingest_attempts ADD COLUMN repair_contracts_json TEXT")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_section_ingest_attempts_paper_ts
        ON section_ingest_attempts(paper_id, attempt_ts DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_section_ingest_attempts_outcome
        ON section_ingest_attempts(outcome, attempt_ts DESC)
        """
    )
    conn.commit()


def record_ingest_attempt(
    conn: sqlite3.Connection,
    *,
    paper_id: str,
    outcome: str,
    run_id: str,
    source_url: str = "",
    detail: str = "",
    inserted_sections: int = 0,
    primary_sections: int = 0,
    candidate_file: Path | None = None,
    repair_contracts: list[dict[str, Any]] | None = None,
) -> None:
    """Record why a high-value paper did or did not yield local section evidence."""
    if outcome not in SECTION_INGEST_OUTCOMES:
        outcome = "parse_no_blocks"
    repair_contracts_payload = _normalise_repair_contracts(repair_contracts)
    conn.execute(
        """
        INSERT INTO section_ingest_attempts
            (paper_id, attempt_ts, run_id, outcome, source_url, detail,
             inserted_sections, primary_sections, candidate_file, parser_name,
             parser_contract_version, repair_contracts_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            utc_now(),
            run_id,
            outcome,
            source_url,
            detail[:1000],
            int(inserted_sections or 0),
            int(primary_sections or 0),
            str(candidate_file) if candidate_file else None,
            SECTION_PARSER_NAME,
            SECTION_PARSER_CONTRACT_VERSION,
            (
                json.dumps(repair_contracts_payload, ensure_ascii=False, sort_keys=True)
                if repair_contracts_payload else None
            ),
        ),
    )


def _candidate_file_digest(path: Path | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return "missing"
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _parser_contract_digest() -> str:
    return hashlib.sha256(SECTION_PARSER_CONTRACT_VERSION.encode("utf-8")).hexdigest()[:8]


def _checkpoint_step_name(candidate_file: Path | None, mode_key: str = "") -> tuple[str, str]:
    """Use separate checkpoints for queue content and parser evidence contract."""
    digest = _candidate_file_digest(candidate_file)
    contract_digest = _parser_contract_digest()
    mode_suffix = ""
    if mode_key:
        mode_suffix = "_" + re.sub(r"[^A-Za-z0-9._-]+", "_", mode_key.strip()).strip("._")
    if candidate_file:
        return f"step5s_section_ingest_delta_{digest}_{contract_digest}{mode_suffix}", digest
    return f"step5s_section_ingest_{contract_digest}{mode_suffix}", digest


def _arxiv_pdf_url(arxiv_id: Optional[str], doi: Optional[str]) -> Optional[str]:
    aid = normalize_arxiv_id(arxiv_id)
    if not aid and doi:
        clean_doi = normalize_doi(doi) or ""
        m = re.match(r"^10\.48550/arxiv\.(.+)$", clean_doi, re.I)
        if m:
            aid = normalize_arxiv_id(m.group(1))
    if not aid:
        return None
    return f"https://arxiv.org/pdf/{aid}.pdf"


def _select_candidate_ids(conn_v14: sqlite3.Connection, top_n: int) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    def add(pid: Any) -> bool:
        if pid is None:
            return len(ids) >= top_n
        value = str(pid)
        if not value or value in seen:
            return len(ids) >= top_n
        ids.append(value)
        seen.add(value)
        return len(ids) >= top_n

    def add_query(sql: str, params: tuple = ()) -> bool:
        try:
            rows = conn_v14.execute(sql, params).fetchall()
        except sqlite3.Error:
            return False
        for row in rows:
            if add(row[0]):
                return True
        return False

    # Prediction-critical evidence first: future edge endpoints, existing
    # limitation atoms, and main-path nodes all directly affect Claim Cards.
    if _table_exists(conn_v14, "predicted_future_edges"):
        if add_query(
            """
            SELECT src_paper_id FROM predicted_future_edges
            ORDER BY COALESCE(prediction_confidence, predicted_prob, 0) DESC
            LIMIT ?
            """,
            (top_n,),
        ):
            return ids[:top_n]
        if add_query(
            """
            SELECT dst_paper_id FROM predicted_future_edges
            ORDER BY COALESCE(prediction_confidence, predicted_prob, 0) DESC
            LIMIT ?
            """,
            (top_n,),
        ):
            return ids[:top_n]

    if _table_exists(conn_v14, "limitation_atoms"):
        if add_query(
            """
            SELECT paper_id
            FROM limitation_atoms
            ORDER BY
                CASE COALESCE(severity, 'medium')
                    WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1
                END DESC,
                COALESCE(evidence_weight, 0) DESC,
                paper_id
            LIMIT ?
            """,
            (top_n,),
        ):
            return ids[:top_n]

    if _table_exists(conn_v14, "main_path_edges"):
        cols = {row[1] for row in conn_v14.execute("PRAGMA table_info(main_path_edges)").fetchall()}
        src_col = "source_paper_id" if "source_paper_id" in cols else "citing_id"
        dst_col = "target_paper_id" if "target_paper_id" in cols else "cited_id"
        if add_query(
            f"""
            SELECT {src_col}
            FROM main_path_edges
            WHERE is_main_path = 1
            ORDER BY COALESCE(main_path_weight, spc, 0) DESC
            LIMIT ?
            """,
            (top_n,),
        ):
            return ids[:top_n]
        if add_query(
            f"""
            SELECT {dst_col}
            FROM main_path_edges
            WHERE is_main_path = 1
            ORDER BY COALESCE(main_path_weight, spc, 0) DESC
            LIMIT ?
            """,
            (top_n,),
        ):
            return ids[:top_n]

    if _table_exists(conn_v14, "subgraph_nodes"):
        if add_query(
            """
            SELECT paper_id
            FROM subgraph_nodes
            WHERE is_keystone = 1
            ORDER BY keystone_score_v14 DESC
            LIMIT ?
            """,
            (top_n,),
        ):
            return ids[:top_n]

    if _table_exists(conn_v14, "branch_lineages"):
        try:
            rows = conn_v14.execute(
                """
                SELECT split_evidence_json
                FROM branch_lineages
                ORDER BY COALESCE(split_confidence, 0) DESC
                """
            ).fetchall()
        except sqlite3.Error:
            rows = []
        for row in rows:
            try:
                payload = json.loads(row[0] or "{}")
            except Exception:
                payload = {}
            for pid in payload.get("driver_papers") or []:
                if add(pid):
                    return ids[:top_n]

    # Representativeness layer: one high-signal representative per visual
    # cluster, ordered by cluster size. This prevents a top-N section budget from
    # collapsing into only a few dense branches.
    if _table_exists(conn_v14, "visual_nodes"):
        try:
            rows = conn_v14.execute(
                """
                SELECT v.paper_id, v.cluster_id, v.node_size,
                       COALESCE(s.keystone_score_v14, 0) AS keystone_score,
                       COUNT(*) OVER (PARTITION BY v.cluster_id) AS cluster_size
                FROM visual_nodes v
                LEFT JOIN subgraph_nodes s ON s.paper_id = v.paper_id
                ORDER BY cluster_size DESC, v.cluster_id,
                         keystone_score DESC, COALESCE(v.node_size, 0) DESC,
                         v.paper_id
                """
            ).fetchall()
        except sqlite3.Error:
            rows = []
        represented_clusters: set[str] = set()
        for row in rows:
            cluster_id = str(row[1] or "")
            if not cluster_id or cluster_id in represented_clusters:
                continue
            represented_clusters.add(cluster_id)
            if add(row[0]):
                return ids[:top_n]

    if _table_exists(conn_v14, "subgraph_nodes"):
        add_query(
            """
            SELECT paper_id
            FROM subgraph_nodes
            ORDER BY
                COALESCE(keystone_score_v14, 0) DESC,
                COALESCE(node_size, 0) DESC,
                paper_id
            LIMIT ?
            """,
            (top_n,),
        )
    return ids


def load_candidates(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    top_n: int,
    corpus_id: str | None = None,
    candidate_ids: list[str] | None = None,
) -> list[dict]:
    ids = candidate_ids or _select_candidate_ids(conn_v14, top_n)
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = conn_main.execute(
        f"""
        SELECT id, title, arxiv_id, doi, s2_paper_id
        FROM papers
        WHERE id IN ({placeholders})
          {"AND id IN (SELECT paper_id FROM temp.v14b_corpus_papers)" if corpus_id else ""}
        """,
        ids,
    ).fetchall()
    row_by_id = {str(r["id"]): dict(r) for r in rows}
    # `ids` is already an evidence-budget ordering: future endpoints,
    # branch drivers, main-path nodes, topic-gap papers, and keystones.
    # Re-sorting by year silently starves the highest-value evidence gaps.
    papers = [row_by_id[pid] for pid in ids if pid in row_by_id]

    if SECTION_INGEST_REQUIRE_ARXIV:
        papers = [
            p for p in papers
            if _arxiv_pdf_url(p.get("arxiv_id"), p.get("doi"))
        ]
    return papers


def _candidate_priority(row: dict[str, Any]) -> float:
    for key in ("priority", "priority_score"):
        try:
            return float(row.get(key) or 0.0)
        except (TypeError, ValueError):
            continue
    return 0.0


def _read_candidate_csv_rows(path: Path) -> tuple[set[str], list[dict[str, Any]]] | None:
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        first_line = sample.splitlines()[0] if sample.splitlines() else ""
        if "," not in first_line:
            return None
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        if not fieldnames:
            return None
        rows = list(enumerate(reader))
        if "candidate_paper_ids" in fieldnames:
            rows.sort(key=lambda item: (-_candidate_priority(item[1]), item[0]))
        return fieldnames, [row for _, row in rows]


def _split_candidate_paper_ids(raw: Any) -> list[str]:
    return [
        value.strip()
        for value in re.split(r"[;,]", str(raw or ""))
        if value.strip()
    ]


def _candidate_row_paper_ids(row: dict[str, Any], fieldnames: set[str]) -> list[str]:
    if "candidate_paper_ids" in fieldnames:
        return (
            _split_candidate_paper_ids(row.get("candidate_paper_ids"))
            or _split_candidate_paper_ids(row.get("paper_id"))
        )
    if "paper_id" in fieldnames:
        return _split_candidate_paper_ids(row.get("paper_id"))
    return []


REPAIR_CONTRACT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "repair_id": ("repair_id", "repair_ids"),
    "source_contract": ("source_contract", "source_contracts"),
    "target_pipeline_steps": ("target_pipeline_steps",),
    "retrieval_modes": ("retrieval_modes",),
    "parser_contract": ("parser_contract", "parser_contracts"),
    "claim_scope": ("claim_scope", "claim_scopes"),
    "evidence_grade": ("evidence_grade", "evidence_grades"),
    "topic": ("topic",),
    "gap_type": ("gap_type",),
    "bottleneck": ("bottleneck",),
    "frontfill_query": ("frontfill_query",),
    "required_sections": ("required_sections",),
}


def _normalise_repair_contract(contract: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in contract.items():
        if key in {"paper_id", "candidate_paper_ids"}:
            continue
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
            clean[key] = value[:2000]
        elif isinstance(value, (int, float, bool)):
            clean[key] = value
        elif isinstance(value, (list, tuple)):
            values = [v for v in value if v not in (None, "")]
            if values:
                clean[key] = values
        elif isinstance(value, dict):
            nested = _normalise_repair_contract(value)
            if nested:
                clean[key] = nested
        else:
            text = str(value).strip()
            if text:
                clean[key] = text[:2000]
    if clean:
        clean.setdefault("contract_source", "candidate_file")
    return clean


def _normalise_repair_contracts(
    contracts: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> list[dict[str, Any]]:
    if not contracts:
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        clean = _normalise_repair_contract(contract)
        if not clean:
            continue
        key = json.dumps(clean, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def _merge_repair_contracts(
    existing: list[dict[str, Any]] | None,
    incoming: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    return _normalise_repair_contracts([*(existing or []), *(incoming or [])])


def _row_repair_contracts(row: dict[str, Any]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    raw_contracts = str(row.get("repair_contracts_json") or "").strip()
    if raw_contracts:
        try:
            parsed = json.loads(raw_contracts)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            contracts.append(parsed)
        elif isinstance(parsed, list):
            contracts.extend([item for item in parsed if isinstance(item, dict)])

    fallback: dict[str, Any] = {}
    for out_key, aliases in REPAIR_CONTRACT_FIELD_ALIASES.items():
        for alias in aliases:
            value = row.get(alias)
            if value not in (None, ""):
                fallback[out_key] = value
                break
    if fallback:
        contracts.append(fallback)
    return _normalise_repair_contracts(contracts)


def read_candidate_file(path: Path | None, limit: int | None = None) -> list[str] | None:
    if not path:
        return None
    ids: list[str] = []
    seen: set[str] = set()
    csv_rows = _read_candidate_csv_rows(Path(path))
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        first_line = sample.splitlines()[0] if sample.splitlines() else ""
        if csv_rows:
            fieldnames, rows = csv_rows
            if "candidate_paper_ids" in fieldnames or "paper_id" in fieldnames:
                raw_values = (
                    pid
                    for row in rows
                    for pid in _candidate_row_paper_ids(row, fieldnames)
                )
            else:
                f.seek(0)
                raw_values = (line.split(",")[0] for line in f)
        elif "," in first_line:
            raw_values = (line.split(",")[0] for line in f)
        else:
            raw_values = (line.split(",")[0] for line in f)
        for raw in raw_values:
            pid = str(raw or "").strip()
            if not pid or pid in seen or pid == "paper_id":
                continue
            ids.append(pid)
            seen.add(pid)
            if limit and len(ids) >= int(limit):
                break
    return ids


def read_candidate_repair_contracts(path: Path | None) -> dict[str, list[dict[str, Any]]]:
    """Map candidate paper ids to repair contracts carried by the queue CSV."""
    if not path:
        return {}
    csv_rows = _read_candidate_csv_rows(Path(path))
    if not csv_rows:
        return {}
    fieldnames, rows = csv_rows
    repair_by_paper: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        contracts = _row_repair_contracts(row)
        if not contracts:
            continue
        for pid in _candidate_row_paper_ids(row, fieldnames):
            repair_by_paper[pid] = _merge_repair_contracts(
                repair_by_paper.get(pid),
                contracts,
            )
    return repair_by_paper


def _heading_to_section(line: str) -> Optional[str]:
    normalized = re.sub(r"\s+", " ", line.strip())
    normalized = normalized[:120]
    if not normalized:
        return None
    if _looks_like_toc_line(normalized):
        return None
    bare = normalized.strip(" .:;-–—").lower()
    if bare in AMBIGUOUS_FRAGMENT_HEADINGS and not normalized[0].isupper():
        return None
    for sec_name, pattern in SECTION_PATTERNS:
        if pattern.match(normalized):
            return sec_name
    return None


def _looks_like_toc_line(line: str) -> bool:
    clean = re.sub(r"\s+", " ", line.strip())[:180]
    if not clean:
        return False
    if TOC_DOT_LEADER_RE.search(clean):
        return True
    return bool(TOC_NUMBERED_ENTRY_RE.match(clean))


def _is_stop_heading(line: str) -> bool:
    normalized = re.sub(r"\s+", " ", line.strip())[:160]
    return any(pattern.match(normalized) for pattern in STOP_SECTION_PATTERNS)


def _inline_heading_to_section(line: str) -> tuple[Optional[str], str, str]:
    """Detect heading+content lines without using loose keyword extraction.

    Many PDFs expose "1. Results and Discussion. ..." as one text line.  This
    is still section evidence because the section title is explicit.  We avoid
    plain keyword windows here: single-word titles need numbering or a separator
    before the body, so a sentence like "Results show ..." is not promoted to a
    section claim.
    """
    clean = re.sub(r"\s+", " ", line.strip())
    if not clean:
        return None, "", ""
    if _looks_like_toc_line(clean):
        return None, "", ""
    prefix = r"(?P<prefix>\s*(section\s+)?(\d+(\.\d+)*|[ivx]+|[a-z])?[\).:\s-]*)"
    for sec_name, phrases in INLINE_SECTION_PREFIXES:
        for phrase in phrases:
            pattern = re.compile(
                rf"^{prefix}(?P<title>{re.escape(phrase)})\b(?P<sep>\s*[:.\-–—]\s*|\s+)(?P<rest>.*)$",
                re.I,
            )
            match = pattern.match(clean)
            if not match:
                continue
            numbered = bool(re.search(r"(\d+(\.\d+)*|[ivx]+|[a-z])", match.group("prefix") or "", re.I))
            has_section_prefix = bool(re.search(r"\bsection\s+", match.group("prefix") or "", re.I))
            if (
                phrase.lower() in AMBIGUOUS_FRAGMENT_HEADINGS
                and not clean[0].isupper()
                and not numbered
                and not has_section_prefix
            ):
                continue
            sep = match.group("sep") or ""
            rest = (match.group("rest") or "").strip()
            title_is_specific = len(phrase.split()) > 1
            has_strong_separator = bool(re.search(r"[:.\-–—]", sep))
            strategy = "inline_heading"
            if rest and not (numbered or title_is_specific or has_strong_separator):
                first = re.match(r"([A-Za-z][A-Za-z-]*)", rest)
                first_word = first.group(1).lower() if first else ""
                looks_like_heading_body = (
                    phrase.lower() in LOOSE_INLINE_HEADINGS
                    and bool(rest[:1])
                    and (rest[:1].isupper() or rest[:1].isdigit())
                    and first_word not in FALSE_INLINE_BODY_STARTS
                )
                if not looks_like_heading_body:
                    continue
                strategy = "loose_inline_heading"
            return sec_name, rest, strategy
    return None, "", ""


def _embedded_heading_sections(text: str) -> list[tuple[str, str]]:
    """Extract explicit numbered headings embedded inside a long PDF text block.

    This is intentionally stricter than keyword-window extraction.  It only
    accepts numbered/roman section headings such as "5. Conclusions ..." that
    PDF parsers sometimes flatten into the middle of a page block.  The output
    remains section evidence, but the strategy is exposed downstream so the UI
    can mark it as weaker than clean heading-continuation extraction.
    """
    clean = re.sub(r"\s+", " ", text.replace("\x00", " ").strip())
    if len(clean) < SECTION_INGEST_MIN_CHARS:
        return []
    phrase_pairs: list[tuple[str, str]] = []
    for sec_name, phrases in INLINE_SECTION_PREFIXES:
        for phrase in phrases:
            phrase_pairs.append((sec_name, phrase))
    # Longer phrases first so "results and discussion" wins over "results".
    phrase_pairs.sort(key=lambda item: len(item[1]), reverse=True)

    def heading_re(phrases: list[str]) -> re.Pattern:
        phrase_alt = "|".join(re.escape(p) for p in phrases)
        return re.compile(
            rf"(?:^|[.;!?]\s+)"
            rf"(?P<num>(?:section\s+)?(?:\d+(?:\.\d+)*|[ivx]+)\s*[\).:\-–—]?\s+)"
            rf"(?P<title>{phrase_alt})\b"
            rf"(?P<sep>\s*[:.\-–—]\s*|\s+)",
            re.I,
        )

    target_patterns = [
        (sec_name, heading_re([phrase]))
        for sec_name, phrase in phrase_pairs
    ]
    boundary_pattern = heading_re(
        [phrase for _, phrase in phrase_pairs]
        + list(EMBEDDED_BOUNDARY_PHRASES)
    )
    boundaries = sorted({m.start() for m in boundary_pattern.finditer(clean)} | {len(clean)})
    found: list[tuple[int, int, str, str]] = []
    for sec_name, pattern in target_patterns:
        for match in pattern.finditer(clean):
            candidate_prefix = clean[match.start(): min(len(clean), match.end() + 120)]
            if TOC_DOT_LEADER_RE.search(candidate_prefix):
                continue
            next_boundary = next((b for b in boundaries if b > match.start()), len(clean))
            body = clean[match.end():next_boundary].strip(" .;:-–—")
            if len(body) >= SECTION_INGEST_MIN_CHARS:
                found.append((match.start(), next_boundary, sec_name, body))
    found.sort(key=lambda item: item[0])

    out: list[tuple[str, str]] = []
    occupied: set[tuple[int, int]] = set()
    for start, end, sec_name, body in found:
        if (start, end) in occupied:
            continue
        occupied.add((start, end))
        out.append((sec_name, body))
    return out


def _terminal_summary_sections(blocks) -> list[dict[str, Any]]:
    """Weak fallback for old short papers with no explicit target headings.

    This intentionally does not infer a full decision-grade section.  It only
    captures terminal summary cues from the final page window so downstream atom
    search can inspect traceable context without promoting it as strong section
    evidence.
    """
    block_items: list[tuple[int, int, str]] = []
    page_values: list[int] = []
    for idx, block in enumerate(blocks):
        text = (getattr(block, "text", "") or "").replace("\x00", " ").strip()
        if not text:
            continue
        raw_page = getattr(block, "page_no", None)
        page_no = int(raw_page) if isinstance(raw_page, (int, float)) and int(raw_page) > 0 else 0
        if page_no:
            page_values.append(page_no)
        block_items.append((idx, page_no, text))
    if not block_items:
        return []

    max_page = max(page_values) if page_values else 0
    if max_page <= 0:
        min_final_page = 0
        min_final_index = int(len(block_items) * 0.65)
    elif max_page == 1:
        min_final_page = 1
        min_final_index = 0
    elif max_page == 2:
        min_final_page = 2
        min_final_index = 0
    else:
        min_final_page = max_page - 1
        min_final_index = 0

    candidates: list[dict[str, Any]] = []
    for idx, page_no, text in block_items:
        in_final_window = (
            (page_no and page_no >= min_final_page)
            or (not page_no and idx >= min_final_index)
        )
        if not in_final_window:
            continue
        clean = re.sub(r"\s+", " ", text).strip()
        match = TERMINAL_SUMMARY_CUE_RE.search(clean)
        if not match:
            continue
        body = clean[match.start():].strip()
        stop = TERMINAL_SUMMARY_STOP_RE.search(body, pos=max(1, match.end() - match.start()))
        if stop:
            body = body[: stop.start()].strip(" .;:-–—")
        if len(body) < SECTION_INGEST_MIN_CHARS:
            continue
        candidates.append(
            {
                "section_name": "conclusion",
                "text": body[:1200],
                "pages": [page_no] if page_no else [],
                "n_blocks": 1,
                "extraction_strategies": ["terminal_cue_summary"],
            }
        )
    return candidates[:1]


def extract_sections_with_metadata(blocks) -> dict[str, dict[str, Any]]:
    sections: dict[str, list[str]] = {name: [] for name, _ in SECTION_PATTERNS}
    section_pages: dict[str, set[int]] = {name: set() for name, _ in SECTION_PATTERNS}
    section_blocks: dict[str, int] = {name: 0 for name, _ in SECTION_PATTERNS}
    section_strategies: dict[str, set[str]] = {name: set() for name, _ in SECTION_PATTERNS}
    current: Optional[str] = None

    def append_section(sec_name: str, sec_text: str, page_no: Any, strategy: str) -> None:
        clean_text = re.sub(r"\s+", " ", sec_text.strip())
        if not clean_text:
            return
        if clean_text in sections[sec_name]:
            section_strategies[sec_name].add(strategy)
            return
        sections[sec_name].append(clean_text[:1200])
        section_blocks[sec_name] += 1
        section_strategies[sec_name].add(strategy)
        if page_no:
            section_pages[sec_name].add(int(page_no))

    for block in blocks:
        text = (block.text or "").replace("\x00", " ").strip()
        if not text:
            continue
        page_no = getattr(block, "page_no", None)

        # Keep parser-level section hints as a weak backup.
        hint = (block.section_hint or "").lower()
        if hint == "limitations":
            append_section("limitations", text, page_no, "parser_hint")
        elif hint == "conclusion":
            append_section("conclusion", text, page_no, "parser_hint")

        block_had_section_signal = False
        for line in text.splitlines():
            clean = line.strip()
            if not clean:
                continue
            if _is_stop_heading(clean):
                current = None
                continue
            heading = _heading_to_section(clean)
            if heading:
                current = heading
                section_strategies[current].add("explicit_heading")
                block_had_section_signal = True
                continue
            inline_heading, inline_rest, inline_strategy = _inline_heading_to_section(clean)
            if inline_heading:
                block_had_section_signal = True
                if inline_rest:
                    append_section(inline_heading, inline_rest, page_no, inline_strategy or "inline_heading")
                current = None if inline_strategy == "loose_inline_heading" else inline_heading
                continue
            if current:
                append_section(current, clean, page_no, "heading_continuation")
                block_had_section_signal = True
        if not block_had_section_signal:
            for embedded_section, embedded_text in _embedded_heading_sections(text):
                append_section(embedded_section, embedded_text, page_no, "embedded_heading")

    if not any(sections.values()):
        for fallback in _terminal_summary_sections(blocks):
            sec_name = str(fallback.get("section_name") or "conclusion")
            sections[sec_name].append(str(fallback.get("text") or "")[:1200])
            section_blocks[sec_name] += int(fallback.get("n_blocks") or 1)
            section_strategies[sec_name].update(fallback.get("extraction_strategies") or [])
            for page_no in fallback.get("pages") or []:
                if isinstance(page_no, (int, float)) and int(page_no) > 0:
                    section_pages[sec_name].add(int(page_no))

    merged: dict[str, dict[str, Any]] = {}
    for sec_name, lines in sections.items():
        if not lines:
            continue
        blob = re.sub(r"\s+", " ", " ".join(lines)).strip()
        if len(blob) < SECTION_INGEST_MIN_CHARS:
            continue
        pages = sorted(section_pages.get(sec_name, set()))
        merged[sec_name] = {
            "text": blob[:SECTION_INGEST_MAX_CHARS],
            "pages": pages,
            "n_blocks": int(section_blocks.get(sec_name, 0)),
            "extraction_strategies": sorted(section_strategies.get(sec_name, set())),
        }
    return merged


def extract_sections_from_blocks(blocks) -> dict[str, str]:
    """Compatibility shim returning only section_text."""
    sections = extract_sections_with_metadata(blocks)
    return {name: str(payload.get("text") or "") for name, payload in sections.items()}


def parse_pdf_pages_with_timeout(path: str):
    """Parse one PDF with a hard wall-clock cap.

    Some arXiv PDFs contain malformed graphics streams that can keep the parser
    busy for a long time without producing section evidence.  The section
    ingest is a prioritised evidence crawler, so a single pathological PDF must
    be marked as failed and let the run continue rather than blocking the whole
    top12000 evidence budget.
    """

    def _raise_timeout(_signum, _frame):
        raise TimeoutError(f"PDF parse exceeded {SECTION_PARSE_TIMEOUT_SEC}s")

    old_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, max(1, SECTION_PARSE_TIMEOUT_SEC))
    try:
        return parse_pdf_pages(path)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def _has_primary_sections(conn: sqlite3.Connection, paper_id: str) -> bool:
    placeholders = ",".join("?" * len(PRIMARY_SECTION_NAMES))
    row = conn.execute(
        f"""
        SELECT COUNT(*) FROM paper_sections
        WHERE paper_id = ?
          AND section_name IN ({placeholders})
          AND section_text IS NOT NULL
          AND length(trim(section_text)) >= ?
        """,
        (paper_id, *PRIMARY_SECTION_NAMES, SECTION_INGEST_MIN_CHARS),
    ).fetchone()
    return bool(row and row[0])


def _has_current_primary_sections(conn: sqlite3.Connection, paper_id: str) -> bool:
    placeholders = ",".join("?" * len(PRIMARY_SECTION_NAMES))
    rows = conn.execute(
        f"""
        SELECT section_meta_json
        FROM paper_sections
        WHERE paper_id = ?
          AND section_name IN ({placeholders})
          AND section_text IS NOT NULL
          AND length(trim(section_text)) >= ?
        """,
        (paper_id, *PRIMARY_SECTION_NAMES, SECTION_INGEST_MIN_CHARS),
    ).fetchall()
    return any(
        _json_obj(row[0]).get("parser_contract_version") == SECTION_PARSER_CONTRACT_VERSION
        for row in rows
    )


def upsert_sections(
    conn: sqlite3.Connection,
    paper_id: str,
    sections: dict[str, dict[str, Any]],
    source_url: str,
    *,
    source_storage_uri: str = "",
    repair_contracts: list[dict[str, Any]] | None = None,
) -> int:
    inserted = 0
    repair_contracts_payload = _normalise_repair_contracts(repair_contracts)
    for sec_name, payload in sections.items():
        sec_text = str((payload or {}).get("text") or "").strip()
        if not sec_text:
            continue
        pages = payload.get("pages") if isinstance(payload, dict) else None
        if isinstance(pages, list):
            pages = [
                int(p) for p in pages
                if isinstance(p, (int, float)) and int(p) > 0
            ]
        else:
            pages = []
        section_pages_json = json.dumps(sorted(set(pages)), ensure_ascii=False)
        section_meta = {
            "n_pages": len(set(pages)),
            "n_blocks": int((payload or {}).get("n_blocks") or 0),
            "extraction_strategies": list((payload or {}).get("extraction_strategies") or []),
            "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
            "parser_contract_guards": list(SECTION_PARSER_CONTRACT_GUARDS),
        }
        if source_storage_uri:
            section_meta["source_delivery"] = "local_raw_pdf_cache"
            section_meta["source_storage_uri"] = source_storage_uri
        else:
            section_meta["source_delivery"] = "network_pdf_fetch"
        if repair_contracts_payload:
            section_meta["repair_contracts"] = repair_contracts_payload
            section_meta["repair_contract_source"] = "candidate_file"
        section_meta_json = json.dumps(section_meta, ensure_ascii=False)
        existing = conn.execute(
            """
            SELECT section_text, section_meta_json
            FROM paper_sections
            WHERE paper_id = ? AND section_name = ?
            """,
            (paper_id, sec_name),
        ).fetchone()
        if existing:
            old_text = str(existing[0] or "")
            old_meta = _json_obj(existing[1])
            old_is_current = old_meta.get("parser_contract_version") == SECTION_PARSER_CONTRACT_VERSION
            should_replace = (not old_is_current) or len(sec_text) >= len(old_text)
            if should_replace:
                conn.execute(
                    """
                    UPDATE paper_sections
                    SET section_text = ?, source_type = ?, parser_name = ?, source_url = ?,
                        section_pages_json = ?, section_meta_json = ?
                    WHERE paper_id = ? AND section_name = ?
                    """,
                    (
                        sec_text,
                        "arxiv_pdf",
                        SECTION_PARSER_NAME,
                        source_url,
                        section_pages_json,
                        section_meta_json,
                        paper_id,
                        sec_name,
                    ),
                )
            elif repair_contracts_payload:
                merged_contracts = _merge_repair_contracts(
                    old_meta.get("repair_contracts")
                    if isinstance(old_meta.get("repair_contracts"), list)
                    else [],
                    repair_contracts_payload,
                )
                if merged_contracts != old_meta.get("repair_contracts"):
                    old_meta["repair_contracts"] = merged_contracts
                    old_meta["repair_contract_source"] = "candidate_file"
                    conn.execute(
                        """
                        UPDATE paper_sections
                        SET section_meta_json = ?
                        WHERE paper_id = ? AND section_name = ?
                        """,
                        (
                            json.dumps(old_meta, ensure_ascii=False),
                            paper_id,
                            sec_name,
                        ),
                    )
        else:
            conn.execute(
                """
                INSERT INTO paper_sections
                    (paper_id, section_name, section_text, source_type, parser_name, source_url,
                     section_pages_json, section_meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    sec_name,
                    sec_text,
                    "arxiv_pdf",
                    SECTION_PARSER_NAME,
                    source_url,
                    section_pages_json,
                    section_meta_json,
                ),
            )
        inserted += 1
    return inserted


def _sanitize_raw_pdf_path_part(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return clean.strip("._") or "unknown"


def _raw_pdf_storage_relpath_for_arxiv(arxiv_id: str) -> Path:
    aid = normalize_arxiv_id(arxiv_id) or arxiv_id
    if "/" in aid:
        category, paper = aid.split("/", 1)
        return Path("pdfs") / "arxiv" / _sanitize_raw_pdf_path_part(category) / f"{_sanitize_raw_pdf_path_part(paper)}.pdf"
    prefix = _sanitize_raw_pdf_path_part(aid[:4] or "misc")
    return Path("pdfs") / "arxiv" / prefix / f"{_sanitize_raw_pdf_path_part(aid)}.pdf"


def _is_probable_pdf(path: Path, max_bytes: int = RAW_PDF_MAX_BYTES) -> bool:
    try:
        st = path.stat()
        if st.st_size <= 0 or st.st_size > max_bytes:
            return False
        with path.open("rb") as fh:
            return fh.read(4) == b"%PDF"
    except OSError:
        return False


def _connect_raw_pdf_manifest(path: Path, *, timeout: float = 2.0) -> sqlite3.Connection:
    """Open the external raw-PDF manifest for read-only section reuse checks."""
    attempts: tuple[tuple[str, bool], ...] = (
        (f"file:{path}?mode=ro", True),
        (str(path), False),
    )
    last_error: sqlite3.Error | None = None
    for target, is_uri in attempts:
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(target, uri=is_uri, timeout=timeout)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            return conn
        except sqlite3.Error as exc:
            last_error = exc
            if conn is not None:
                conn.close()
    if last_error:
        raise last_error
    raise sqlite3.OperationalError(f"could not open raw PDF manifest: {path}")


def _manifest_pdf_path(
    paper: dict,
    *,
    store_root: Path | None = RAW_PDF_STORE_ROOT,
    manifest_path: Path | None = RAW_PDF_MANIFEST,
) -> Path | None:
    if not store_root or not manifest_path or not manifest_path.exists():
        return None
    try:
        conn = _connect_raw_pdf_manifest(manifest_path, timeout=2.0)
        try:
            cols = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(raw_pdf_downloads)").fetchall()
            }
            if not {"status", "storage_path"} <= cols:
                return None
            order_sql = ", ".join(
                col
                for col in ("downloaded_at", "updated_at", "first_seen_at")
                if col in cols
            )
            order_clause = f"ORDER BY {order_sql} DESC" if order_sql else ""
            candidate_keys: list[tuple[str, str, bool]] = [
                ("paper_id", str(paper.get("id") or "").strip(), False),
                ("arxiv_id", normalize_arxiv_id(paper.get("arxiv_id")) or "", False),
                ("doi", normalize_doi(paper.get("doi")) or "", True),
                ("s2_paper_id", normalize_s2_paper_id(paper.get("s2_paper_id")) or "", False),
            ]
            row = None
            for col, value, use_lower in candidate_keys:
                if not value or col not in cols:
                    continue
                predicate = f"lower({col}) = ?" if use_lower else f"{col} = ?"
                row = conn.execute(
                    f"""
                    SELECT storage_path
                    FROM raw_pdf_downloads
                    WHERE status = 'success'
                      AND COALESCE(storage_path, '') != ''
                      AND {predicate}
                    {order_clause}
                    LIMIT 1
                    """,
                    (value.lower() if use_lower else value,),
                ).fetchone()
                if row:
                    break
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    path = Path(str(row["storage_path"] or ""))
    return path if path.is_absolute() else store_root / path


def _local_raw_pdf_path(
    paper: dict,
    *,
    store_root: Path | None = RAW_PDF_STORE_ROOT,
    manifest_path: Path | None = RAW_PDF_MANIFEST,
    prefer_local_raw_pdf: bool | None = None,
) -> Path | None:
    prefer = SECTION_INGEST_PREFER_LOCAL_RAW_PDF if prefer_local_raw_pdf is None else prefer_local_raw_pdf
    if not (prefer and store_root):
        return None
    candidates: list[Path] = []
    manifest_hit = _manifest_pdf_path(paper, store_root=store_root, manifest_path=manifest_path)
    if manifest_hit:
        candidates.append(manifest_hit)
    arxiv_id = normalize_arxiv_id(paper.get("arxiv_id"))
    if arxiv_id:
        candidates.append(store_root / _raw_pdf_storage_relpath_for_arxiv(arxiv_id))
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if _is_probable_pdf(path):
            return path
    return None


def read_local_raw_pdf(
    paper: dict,
    *,
    store_root: Path | None = RAW_PDF_STORE_ROOT,
    manifest_path: Path | None = RAW_PDF_MANIFEST,
    prefer_local_raw_pdf: bool | None = None,
) -> tuple[bytes | None, Path | None]:
    path = _local_raw_pdf_path(
        paper,
        store_root=store_root,
        manifest_path=manifest_path,
        prefer_local_raw_pdf=prefer_local_raw_pdf,
    )
    if not path:
        return None, None
    try:
        return path.read_bytes(), path
    except OSError:
        return None, None


def download_pdf(client: httpx.Client, url: str) -> Optional[bytes]:
    for attempt in range(3):
        try:
            resp = client.get(url, timeout=SECTION_INGEST_TIMEOUT_SEC)
            if resp.status_code == 200 and resp.content:
                return resp.content
            if resp.status_code in (429, 503):
                wait_s = min(30, 4 * (attempt + 1))
                logger.warning("PDF fetch %s -> %s, retry in %ss", url, resp.status_code, wait_s)
                import time

                time.sleep(wait_s)
                continue
            logger.debug("PDF fetch failed %s status=%s", url, resp.status_code)
            return None
        except Exception as exc:
            logger.debug("PDF fetch error %s: %s", url, exc)
    return None


def semantic_pdf_url(client: httpx.Client, paper: dict) -> Optional[str]:
    headers = {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}
    ids = []
    if paper.get("s2_paper_id"):
        ids.append(str(paper["s2_paper_id"]).strip())
    if paper.get("doi"):
        ids.append(f"DOI:{normalize_doi(paper['doi'])}")
    if paper.get("arxiv_id"):
        ids.append(f"ARXIV:{normalize_arxiv_id(paper['arxiv_id'])}")
    ids = [x for x in ids if x and not x.endswith(":None")]
    if not ids:
        return None

    for pid in ids:
        try:
            resp = client.get(
                f"https://api.semanticscholar.org/graph/v1/paper/{pid}",
                params={"fields": "openAccessPdf"},
                headers=headers,
                timeout=SECTION_INGEST_TIMEOUT_SEC,
            )
            if resp.status_code != 200:
                continue
            data = resp.json() or {}
            open_pdf = data.get("openAccessPdf") or {}
            pdf_url = open_pdf.get("url")
            if pdf_url and isinstance(pdf_url, str):
                return pdf_url
        except Exception:
            continue
    return None


def resolve_pdf_url(client: httpx.Client, paper: dict) -> Optional[str]:
    arxiv_url = _arxiv_pdf_url(paper.get("arxiv_id"), paper.get("doi"))
    if arxiv_url:
        return arxiv_url
    if SECTION_INGEST_REQUIRE_ARXIV:
        return None
    return semantic_pdf_url(client, paper)


def run_section_ingest(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    top_n: int = SECTION_INGEST_TOP_N,
    limit: Optional[int] = None,
    resume: bool = True,
    corpus_id: str | None = None,
    candidate_file: Path | None = None,
    raw_pdf_store_root: Path | None = RAW_PDF_STORE_ROOT,
    raw_pdf_manifest: Path | None = RAW_PDF_MANIFEST,
    prefer_local_raw_pdf: bool = SECTION_INGEST_PREFER_LOCAL_RAW_PDF,
    local_raw_pdf_only: bool = False,
    refresh_local_raw_pdf: bool = False,
) -> dict:
    checkpoint_mode = (
        "local_raw_pdf_only_refresh"
        if local_raw_pdf_only and refresh_local_raw_pdf
        else "local_raw_pdf_only"
        if local_raw_pdf_only
        else "local_raw_pdf_refresh"
        if refresh_local_raw_pdf
        else ""
    )
    step_name, candidate_digest = _checkpoint_step_name(candidate_file, checkpoint_mode)
    ck = Checkpoint(step_name)
    if resume and ck.done():
        data = ck.load()
        logger.info("Step5s 已完成 (%d sections), checkpoint=%s, 跳过", data.get("records_n", 0), step_name)
        return data

    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    conn_main.execute("PRAGMA journal_mode=WAL")
    ensure_corpus_schema(conn_main)
    scoped_count = create_temp_corpus_table(conn_main, corpus_id)
    ensure_sections_table(conn_main)

    conn_v14 = get_v14b_conn(db_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    n_target = int(limit or top_n or LIMITATION_TOP_N)
    candidate_ids = read_candidate_file(candidate_file, limit=n_target if limit else None)
    repair_contracts_by_paper = read_candidate_repair_contracts(candidate_file)
    papers = load_candidates(
        conn_main,
        conn_v14,
        n_target,
        corpus_id=corpus_id,
        candidate_ids=candidate_ids,
    )
    if limit:
        papers = papers[: int(limit)]

    logger.info(
        "Step5s candidates=%d (top_n=%d candidate_file=%s checkpoint=%s)",
        len(papers),
        n_target,
        candidate_file or "",
        step_name,
    )
    if not papers:
        stats = {
            "records_n": 0,
            "papers_n": 0,
            "with_primary_sections": 0,
            "candidate_repair_contract_papers": len(repair_contracts_by_paper),
            "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
            "parser_contract_digest": _parser_contract_digest(),
        }
        ck.mark_done(records_n=0, meta=stats)
        upsert_step_meta(conn_v14, step_name, "done", records_n=0)
        conn_main.close()
        conn_v14.close()
        return stats

    primary_hit = 0
    inserted_sections = 0
    parsed_papers = 0
    skipped_existing = 0
    skipped_no_pdf = 0
    skipped_no_local_raw_pdf = 0
    failed_parse = 0
    local_cache_hits = 0
    network_pdf_fetches = 0
    section_counter = {name: 0 for name, _ in SECTION_PATTERNS}
    run_id = f"section_ingest_{utc_now()}"

    # Keep concurrency intentionally low to avoid memory pressure on local Macs.
    limits = httpx.Limits(max_connections=max(1, SECTION_INGEST_CONCURRENCY))
    with httpx.Client(limits=limits, follow_redirects=True, trust_env=SECTION_INGEST_TRUST_ENV) as client:
        with make_progress(papers, desc="Step5s sections") as pbar:
            for paper in pbar:
                pid = paper["id"]
                paper_repair_contracts = repair_contracts_by_paper.get(pid, [])
                has_any_primary = _has_primary_sections(conn_main, pid)
                has_current_primary = _has_current_primary_sections(conn_main, pid)
                blob, local_pdf_path = read_local_raw_pdf(
                    paper,
                    store_root=raw_pdf_store_root,
                    manifest_path=raw_pdf_manifest,
                    prefer_local_raw_pdf=prefer_local_raw_pdf,
                )
                if has_current_primary and not (refresh_local_raw_pdf and local_pdf_path):
                    skipped_existing += 1
                    primary_hit += 1
                    record_ingest_attempt(
                        conn_main,
                        paper_id=pid,
                        outcome="already_has_primary",
                        run_id=run_id,
                        detail=(
                            "Current primary section exists; local raw PDF refresh disabled."
                            if local_pdf_path
                            else ""
                        ),
                        primary_sections=1,
                        candidate_file=candidate_file,
                        repair_contracts=paper_repair_contracts,
                    )
                    conn_main.commit()
                    continue

                pdf_url = _arxiv_pdf_url(paper.get("arxiv_id"), paper.get("doi"))
                if blob and local_pdf_path:
                    local_cache_hits += 1
                    pdf_url = pdf_url or f"file://{local_pdf_path}"
                elif local_raw_pdf_only:
                    skipped_no_local_raw_pdf += 1
                    record_ingest_attempt(
                        conn_main,
                        paper_id=pid,
                        outcome="no_local_raw_pdf",
                        run_id=run_id,
                        detail="Local raw PDF only mode is enabled and no reusable cache hit was found.",
                        candidate_file=candidate_file,
                        repair_contracts=paper_repair_contracts,
                    )
                    conn_main.commit()
                    continue
                else:
                    pdf_url = resolve_pdf_url(client, paper)
                if not pdf_url:
                    skipped_no_pdf += 1
                    record_ingest_attempt(
                        conn_main,
                        paper_id=pid,
                        outcome="no_pdf_url",
                        run_id=run_id,
                        detail="No arXiv PDF and Semantic Scholar openAccessPdf unavailable or disabled.",
                        candidate_file=candidate_file,
                        repair_contracts=paper_repair_contracts,
                    )
                    conn_main.commit()
                    continue
                if has_any_primary:
                    logger.info(
                        "Re-parsing legacy primary section evidence with current parser contract: paper=%s",
                        pid,
                    )
                if not blob:
                    network_pdf_fetches += 1
                    blob = download_pdf(client, pdf_url)
                if not blob:
                    skipped_no_pdf += 1
                    record_ingest_attempt(
                        conn_main,
                        paper_id=pid,
                        outcome="pdf_download_failed",
                        run_id=run_id,
                        source_url=pdf_url,
                        detail="PDF request returned no bytes.",
                        candidate_file=candidate_file,
                        repair_contracts=paper_repair_contracts,
                    )
                    conn_main.commit()
                    continue

                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(blob)
                    tmp_path = tmp.name
                try:
                    blocks = parse_pdf_pages_with_timeout(tmp_path)
                except TimeoutError as exc:
                    logger.warning("PDF parse timeout paper=%s url=%s: %s", pid, pdf_url, exc)
                    failed_parse += 1
                    record_ingest_attempt(
                        conn_main,
                        paper_id=pid,
                        outcome="parse_timeout",
                        run_id=run_id,
                        source_url=pdf_url,
                        detail=str(exc),
                        candidate_file=candidate_file,
                        repair_contracts=paper_repair_contracts,
                    )
                    conn_main.commit()
                    continue
                except Exception as exc:
                    logger.warning("PDF parse failed paper=%s url=%s: %s", pid, pdf_url, exc)
                    failed_parse += 1
                    record_ingest_attempt(
                        conn_main,
                        paper_id=pid,
                        outcome="parser_exception",
                        run_id=run_id,
                        source_url=pdf_url,
                        detail=f"{type(exc).__name__}: {exc}",
                        candidate_file=candidate_file,
                        repair_contracts=paper_repair_contracts,
                    )
                    conn_main.commit()
                    continue
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                if not blocks:
                    failed_parse += 1
                    record_ingest_attempt(
                        conn_main,
                        paper_id=pid,
                        outcome="parse_no_blocks",
                        run_id=run_id,
                        source_url=pdf_url,
                        detail="Parser returned zero text blocks.",
                        candidate_file=candidate_file,
                        repair_contracts=paper_repair_contracts,
                    )
                    conn_main.commit()
                    continue

                sections = extract_sections_with_metadata(blocks)
                if not sections:
                    failed_parse += 1
                    record_ingest_attempt(
                        conn_main,
                        paper_id=pid,
                        outcome="no_target_sections",
                        run_id=run_id,
                        source_url=pdf_url,
                        detail="PDF parsed, but no target evidence sections were detected.",
                        candidate_file=candidate_file,
                        repair_contracts=paper_repair_contracts,
                    )
                    conn_main.commit()
                    continue

                parsed_papers += 1
                inserted_now = upsert_sections(
                    conn_main,
                    pid,
                    sections,
                    pdf_url,
                    source_storage_uri=str(local_pdf_path or ""),
                    repair_contracts=paper_repair_contracts,
                )
                inserted_sections += inserted_now
                for sec_name in sections:
                    section_counter[sec_name] = section_counter.get(sec_name, 0) + 1
                primary_now = sum(1 for sec in sections if sec in PRIMARY_SECTION_NAMES)
                record_ingest_attempt(
                    conn_main,
                    paper_id=pid,
                    outcome="success_primary" if primary_now else "success_secondary_only",
                    run_id=run_id,
                    source_url=pdf_url,
                    detail=(
                        f"PDF bytes loaded from raw cache: {local_pdf_path}"
                        if local_pdf_path
                        else ""
                    ),
                    inserted_sections=inserted_now,
                    primary_sections=primary_now,
                    candidate_file=candidate_file,
                    repair_contracts=paper_repair_contracts,
                )
                conn_main.commit()
                if primary_now:
                    primary_hit += 1

                pbar.set_postfix(
                    parsed=parsed_papers,
                    primary=primary_hit,
                    sections=inserted_sections,
                )

    coverage = primary_hit / max(1, len(papers))
    stats = {
        "records_n": inserted_sections,
        "papers_n": len(papers),
        "corpus_id": corpus_id,
        "scoped_papers": scoped_count if corpus_id else len(papers),
        "parsed_papers": parsed_papers,
        "with_primary_sections": primary_hit,
        "primary_section_coverage": coverage,
        "skipped_existing": skipped_existing,
        "skipped_no_pdf": skipped_no_pdf,
        "skipped_no_local_raw_pdf": skipped_no_local_raw_pdf,
        "failed_parse": failed_parse,
        "local_raw_pdf_cache_hits": local_cache_hits,
        "network_pdf_fetches": network_pdf_fetches,
        "local_raw_pdf_only": bool(local_raw_pdf_only),
        "refresh_local_raw_pdf": bool(refresh_local_raw_pdf),
        "raw_pdf_store_root": str(raw_pdf_store_root or ""),
        "raw_pdf_manifest": str(raw_pdf_manifest or ""),
        "section_counter": section_counter,
        "claim_supporting_sections_enabled": list(PRIMARY_SECTION_NAMES),
        "candidate_file": str(candidate_file) if candidate_file else None,
        "candidate_digest": candidate_digest,
        "candidate_repair_contract_papers": len(repair_contracts_by_paper),
        "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
        "parser_contract_digest": _parser_contract_digest(),
        "run_kind": "delta_queue" if candidate_file else "topn_scan",
    }
    logger.info("Step5s done: %s", stats)
    ck.mark_done(records_n=inserted_sections, meta=stats)
    upsert_step_meta(conn_v14, step_name, "done", records_n=inserted_sections)

    conn_main.close()
    conn_v14.close()
    return stats


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step5s_section_ingest",
        description="Step 5s: ingest PDF section evidence into paper_sections",
    )
    add_common_args(parser)
    parser.add_argument("--top-n", type=int, default=SECTION_INGEST_TOP_N)
    parser.add_argument(
        "--candidate-file",
        type=Path,
        default=None,
        help=(
            "Optional CSV/text file with paper_id or candidate_paper_ids column, "
            "or one paper id per line; used for delta evidence queues."
        ),
    )
    parser.add_argument(
        "--raw-pdf-store-root",
        type=Path,
        default=RAW_PDF_STORE_ROOT,
        help="Local/external raw PDF store root used before network fetch.",
    )
    parser.add_argument(
        "--raw-pdf-manifest",
        type=Path,
        default=RAW_PDF_MANIFEST,
        help="SQLite manifest for the local/external raw PDF store.",
    )
    parser.add_argument(
        "--prefer-local-raw-pdf",
        dest="prefer_local_raw_pdf",
        action="store_true",
        default=SECTION_INGEST_PREFER_LOCAL_RAW_PDF,
        help="Prefer local raw PDF cache before resolving network PDF URLs.",
    )
    parser.add_argument(
        "--no-prefer-local-raw-pdf",
        dest="prefer_local_raw_pdf",
        action="store_false",
        help="Disable local raw PDF cache lookup for this run.",
    )
    parser.add_argument(
        "--local-raw-pdf-only",
        action="store_true",
        help="Only parse papers that have a local raw PDF cache hit; do not fetch network PDFs.",
    )
    parser.add_argument(
        "--refresh-local-raw-pdf",
        action="store_true",
        help="Reparse current-contract papers when a local raw PDF exists so source_storage_uri is materialized.",
    )
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step5s_section_ingest", level=log_level)
    run_section_ingest(
        db_main=Path(args.db) if args.db else DB_MAIN,
        db_v14=Path(args.db_v14) if args.db_v14 else DB_V14,
        top_n=args.top_n,
        limit=args.limit or LIMIT,
        resume=args.resume,
        corpus_id=args.corpus_id,
        candidate_file=args.candidate_file,
        raw_pdf_store_root=Path(args.raw_pdf_store_root).expanduser() if args.raw_pdf_store_root else None,
        raw_pdf_manifest=Path(args.raw_pdf_manifest).expanduser() if args.raw_pdf_manifest else None,
        prefer_local_raw_pdf=bool(args.prefer_local_raw_pdf),
        local_raw_pdf_only=bool(args.local_raw_pdf_only),
        refresh_local_raw_pdf=bool(args.refresh_local_raw_pdf),
    )


if __name__ == "__main__":
    main()
