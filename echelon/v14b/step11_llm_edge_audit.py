"""
Step 11: Stratified LLM edge audit for the V14B visual graph.

This step intentionally separates planning from spending:

  - plan mode creates a stratified audit queue and cost estimate.
  - execute mode consumes pending items with an explicit max-calls cap.

Default strategy:
  - all future_growth edges
  - all main_path edges
  - all branch_lineages, or a configured sample
  - sampled citation / semantic_similarity / cocitation edges
  - extra low-confidence, high-centrality, cross-cluster, cross-field edges

CLI:
    python -m echelon.v14b.step11_llm_edge_audit --help
    make llm-edge-audit-plan
    LLM_PROVIDER=doubao make llm-edge-audit-run V14B_LLM_EDGE_AUDIT_MAX_CALLS=100
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from echelon.v14b.config import DB_V14, REPORT_DIR
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.llm_client import LLMClient, get_cost_tracker
from echelon.v14b.utils import setup_logging, add_common_args, make_progress

logger = logging.getLogger("echelon.v14b.step11_llm_edge_audit")


DEFAULT_SAMPLE_PER_LAYER = int(os.environ.get("V14B_LLM_EDGE_AUDIT_LAYER_SAMPLE", "2000"))
DEFAULT_EXTRA_SAMPLE = int(os.environ.get("V14B_LLM_EDGE_AUDIT_EXTRA_SAMPLE", "8000"))
DEFAULT_OUTPUT_TOKENS = int(os.environ.get("V14B_LLM_EDGE_AUDIT_OUTPUT_TOKENS", "180"))
DEFAULT_MAX_CALLS = int(os.environ.get("V14B_LLM_EDGE_AUDIT_MAX_CALLS", "100"))
DEFAULT_ABSTRACT_CHARS = int(os.environ.get("V14B_LLM_EDGE_AUDIT_ABSTRACT_CHARS", "700"))

# RMB per 1M tokens. Override from env if the Volcengine console price differs.
DOUBAO_INPUT_RMB_PER_M = float(os.environ.get("V14B_DOUBAO_INPUT_RMB_PER_M", "0.8"))
DOUBAO_OUTPUT_RMB_PER_M = float(os.environ.get("V14B_DOUBAO_OUTPUT_RMB_PER_M", "8.0"))

EDGE_LAYERS_TO_SAMPLE = ("citation", "semantic_similarity", "cocitation")
FULL_EDGE_TYPES = ("future_growth", "main_path")
EXTRA_BUCKETS = ("low_confidence", "high_centrality", "cross_cluster", "cross_field")


DDL = """
CREATE TABLE IF NOT EXISTS llm_edge_audit_jobs (
    job_id                  TEXT PRIMARY KEY,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    provider                TEXT NOT NULL,
    model                   TEXT,
    status                  TEXT NOT NULL DEFAULT 'planned',
    mode                    TEXT NOT NULL DEFAULT 'plan',
    sample_config_json      TEXT NOT NULL,
    selected_items          INTEGER DEFAULT 0,
    audited_items           INTEGER DEFAULT 0,
    approved_items          INTEGER DEFAULT 0,
    flagged_items           INTEGER DEFAULT 0,
    failed_items            INTEGER DEFAULT 0,
    estimated_input_tokens  INTEGER DEFAULT 0,
    estimated_output_tokens INTEGER DEFAULT 0,
    estimated_cost_rmb      REAL DEFAULT 0,
    actual_input_tokens     INTEGER DEFAULT 0,
    actual_output_tokens    INTEGER DEFAULT 0,
    actual_cost_rmb         REAL DEFAULT 0,
    report_path             TEXT,
    notes                   TEXT
);

CREATE TABLE IF NOT EXISTS llm_edge_audit_items (
    job_id              TEXT NOT NULL,
    item_id             TEXT NOT NULL,
    item_type           TEXT NOT NULL,
    target_id           TEXT NOT NULL,
    sample_bucket       TEXT NOT NULL,
    edge_type           TEXT,
    source_paper_id     TEXT,
    target_paper_id     TEXT,
    priority            INTEGER NOT NULL DEFAULT 100,
    prompt_tokens_est   INTEGER DEFAULT 0,
    output_tokens_est   INTEGER DEFAULT 0,
    cost_est_rmb        REAL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'pending',
    payload_json        TEXT NOT NULL,
    result_json         TEXT,
    error               TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    audited_at          TIMESTAMP,
    PRIMARY KEY (job_id, item_id),
    FOREIGN KEY (job_id) REFERENCES llm_edge_audit_jobs(job_id)
);

CREATE INDEX IF NOT EXISTS idx_llm_edge_audit_items_status
    ON llm_edge_audit_items (job_id, status, priority);
CREATE INDEX IF NOT EXISTS idx_llm_edge_audit_items_bucket
    ON llm_edge_audit_items (job_id, sample_bucket);
CREATE INDEX IF NOT EXISTS idx_llm_edge_audit_items_edge_type
    ON llm_edge_audit_items (job_id, edge_type);
"""


@dataclass
class AuditCandidate:
    item_type: str
    target_id: str
    sample_bucket: str
    priority: int
    edge_type: str | None = None
    source_paper_id: str | None = None
    target_paper_id: str | None = None

    @property
    def item_id(self) -> str:
        return f"{self.item_type}:{self.target_id}"


def ensure_audit_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.commit()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def require_visual_graph(conn: sqlite3.Connection) -> None:
    required = ("visual_edges", "visual_nodes", "visual_paper_details", "branch_lineages", "visual_clusters")
    missing = [t for t in required if not _table_exists(conn, t)]
    if missing:
        raise RuntimeError(f"visual graph tables missing: {missing}; run `make visual-graph` first")


def _rows(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[dict]:
    cur = conn.execute(sql, tuple(params))
    return [dict(row) for row in cur.fetchall()]


def _json_loads(text: str | None, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _stable_sample(values: list[str], n: int, seed: int) -> list[str]:
    values = sorted(dict.fromkeys(values))
    if n <= 0 or len(values) <= n:
        return values
    rng = random.Random(seed)
    return sorted(rng.sample(values, n))


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def _estimate_cost_rmb(input_tokens: int, output_tokens: int = DEFAULT_OUTPUT_TOKENS) -> float:
    return (
        input_tokens * DOUBAO_INPUT_RMB_PER_M / 1_000_000
        + output_tokens * DOUBAO_OUTPUT_RMB_PER_M / 1_000_000
    )


def _append_candidate(
    selected: dict[str, AuditCandidate],
    cand: AuditCandidate,
) -> None:
    existing = selected.get(cand.item_id)
    if existing is None:
        selected[cand.item_id] = cand
        return
    buckets = existing.sample_bucket.split(",")
    if cand.sample_bucket not in buckets:
        buckets.append(cand.sample_bucket)
        existing.sample_bucket = ",".join(buckets)
    existing.priority = min(existing.priority, cand.priority)


def _edge_ids_by_type(conn: sqlite3.Connection, edge_type: str) -> list[str]:
    return [
        r["edge_id"]
        for r in _rows(
            conn,
            "SELECT edge_id FROM visual_edges WHERE edge_type=? ORDER BY edge_id",
            (edge_type,),
        )
    ]


def _edge_candidates_from_ids(
    conn: sqlite3.Connection,
    edge_ids: list[str],
    bucket: str,
    priority: int,
) -> list[AuditCandidate]:
    if not edge_ids:
        return []
    out: list[AuditCandidate] = []
    for i in range(0, len(edge_ids), 900):
        batch = edge_ids[i:i + 900]
        placeholders = ",".join("?" for _ in batch)
        rows = _rows(
            conn,
            f"""
            SELECT edge_id, edge_type, source_paper_id, target_paper_id
            FROM visual_edges
            WHERE edge_id IN ({placeholders})
            """,
            batch,
        )
        for row in rows:
            out.append(AuditCandidate(
                item_type="edge",
                target_id=row["edge_id"],
                sample_bucket=bucket,
                priority=priority,
                edge_type=row["edge_type"],
                source_paper_id=row["source_paper_id"],
                target_paper_id=row["target_paper_id"],
            ))
    return out


def select_audit_candidates(
    conn: sqlite3.Connection,
    *,
    sample_per_layer: int = DEFAULT_SAMPLE_PER_LAYER,
    extra_sample: int = DEFAULT_EXTRA_SAMPLE,
    branch_mode: str = "all",
    branch_sample: int = 3000,
    seed: int = 42,
) -> list[AuditCandidate]:
    selected: dict[str, AuditCandidate] = {}

    # Full high-value product edges.
    for edge_type in FULL_EDGE_TYPES:
        edge_ids = _edge_ids_by_type(conn, edge_type)
        for cand in _edge_candidates_from_ids(conn, edge_ids, f"all_{edge_type}", 10):
            _append_candidate(selected, cand)

    # Full or sampled branch lineages.
    branch_ids = [r["branch_id"] for r in _rows(conn, "SELECT branch_id FROM branch_lineages ORDER BY branch_id")]
    if branch_mode == "sample":
        branch_ids = _stable_sample(branch_ids, branch_sample, seed + 11)
        branch_bucket = "sample_branch_lineage"
    else:
        branch_bucket = "all_branch_lineage"
    for bid in branch_ids:
        _append_candidate(selected, AuditCandidate(
            item_type="branch_lineage",
            target_id=bid,
            sample_bucket=branch_bucket,
            priority=20,
        ))

    # Stratified base samples from large statistical layers.
    for idx, edge_type in enumerate(EDGE_LAYERS_TO_SAMPLE):
        ids = _edge_ids_by_type(conn, edge_type)
        sampled = _stable_sample(ids, sample_per_layer, seed + 100 + idx)
        for cand in _edge_candidates_from_ids(conn, sampled, f"sample_{edge_type}", 40 + idx):
            _append_candidate(selected, cand)

    # Extra priority buckets.  These intentionally overlap with prior buckets;
    # duplicates are collapsed while preserving bucket provenance.
    per_extra = max(1, math.ceil(extra_sample / len(EXTRA_BUCKETS))) if extra_sample else 0
    if per_extra:
        extra_queries = {
            "low_confidence": """
                SELECT edge_id
                FROM visual_edges
                WHERE edge_type IN ('citation','semantic_similarity','cocitation','future_growth','main_path')
                ORDER BY confidence ASC, edge_id
                LIMIT ?
            """,
            "high_centrality": """
                SELECT e.edge_id
                FROM visual_edges e
                JOIN visual_nodes ns ON ns.paper_id = e.source_paper_id
                JOIN visual_nodes nt ON nt.paper_id = e.target_paper_id
                ORDER BY
                    (COALESCE(ns.node_size, 0) + COALESCE(nt.node_size, 0)) DESC,
                    CASE ns.visual_role
                        WHEN 'main_path' THEN 4 WHEN 'future_anchor' THEN 3
                        WHEN 'limitation_bottleneck' THEN 2 ELSE 0 END DESC,
                    CASE nt.visual_role
                        WHEN 'main_path' THEN 4 WHEN 'future_anchor' THEN 3
                        WHEN 'limitation_bottleneck' THEN 2 ELSE 0 END DESC,
                    e.edge_id
                LIMIT ?
            """,
            "cross_cluster": """
                SELECT e.edge_id
                FROM visual_edges e
                JOIN visual_nodes ns ON ns.paper_id = e.source_paper_id
                JOIN visual_nodes nt ON nt.paper_id = e.target_paper_id
                WHERE ns.cluster_id IS NOT NULL
                  AND nt.cluster_id IS NOT NULL
                  AND ns.cluster_id != nt.cluster_id
                ORDER BY e.confidence ASC, e.edge_id
                LIMIT ?
            """,
            "cross_field": """
                SELECT e.edge_id
                FROM visual_edges e
                JOIN visual_paper_details ds ON ds.paper_id = e.source_paper_id
                JOIN visual_paper_details dt ON dt.paper_id = e.target_paper_id
                WHERE json_extract(ds.metadata_json, '$.field') IS NOT NULL
                  AND json_extract(dt.metadata_json, '$.field') IS NOT NULL
                  AND json_extract(ds.metadata_json, '$.field') != json_extract(dt.metadata_json, '$.field')
                ORDER BY e.confidence DESC, e.edge_id
                LIMIT ?
            """,
        }
        for idx, bucket in enumerate(EXTRA_BUCKETS):
            ids = [r["edge_id"] for r in _rows(conn, extra_queries[bucket], (per_extra,))]
            for cand in _edge_candidates_from_ids(conn, ids, bucket, 30 + idx):
                _append_candidate(selected, cand)

    return sorted(selected.values(), key=lambda c: (c.priority, c.item_type, c.target_id))


def _truncate(text: str | None, n: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[:n].rstrip() + "..."


def _paper_payload(conn: sqlite3.Connection, paper_id: str, abstract_chars: int) -> dict:
    row = conn.execute(
        """
        SELECT n.paper_id, n.cluster_id, n.branch_id, n.publication_year,
               n.visual_role, n.uncertainty_score, n.flags_json,
               d.ids_json, d.metadata_json, d.abstract, d.limitations_json,
               d.recommendation_json
        FROM visual_nodes n
        JOIN visual_paper_details d ON d.paper_id = n.paper_id
        WHERE n.paper_id = ?
        """,
        (paper_id,),
    ).fetchone()
    if row is None:
        return {"paper_id": paper_id}
    data = dict(row)
    meta = _json_loads(data.get("metadata_json"), {})
    ids = _json_loads(data.get("ids_json"), {})
    limitations = _json_loads(data.get("limitations_json"), [])
    return {
        "paper_id": paper_id,
        "title": meta.get("title"),
        "year": meta.get("year") or data.get("publication_year"),
        "field": meta.get("field"),
        "subfield": meta.get("subfield"),
        "topic": meta.get("topic"),
        "cluster_id": data.get("cluster_id"),
        "branch_id": data.get("branch_id"),
        "visual_role": data.get("visual_role"),
        "uncertainty_score": data.get("uncertainty_score"),
        "ids": ids,
        "abstract": _truncate(data.get("abstract"), abstract_chars),
        "limitations": limitations[:3] if isinstance(limitations, list) else [],
    }


def build_edge_payload(conn: sqlite3.Connection, cand: AuditCandidate, abstract_chars: int) -> dict:
    row = conn.execute(
        """
        SELECT edge_id, source_paper_id, target_paper_id, edge_type, layer, weight,
               confidence, is_directed, is_main_path, lod_min, evidence_json
        FROM visual_edges
        WHERE edge_id = ?
        """,
        (cand.target_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"edge not found: {cand.target_id}")
    edge = dict(row)
    return {
        "audit_kind": "edge",
        "edge": {
            **edge,
            "evidence": _json_loads(edge.get("evidence_json"), {}),
        },
        "source": _paper_payload(conn, edge["source_paper_id"], abstract_chars),
        "target": _paper_payload(conn, edge["target_paper_id"], abstract_chars),
        "audit_bucket": cand.sample_bucket,
        "audit_instruction": "judge whether this visual graph edge should be kept, downweighted, removed, or marked uncertain",
    }


def build_branch_payload(conn: sqlite3.Connection, cand: AuditCandidate, abstract_chars: int) -> dict:
    row = conn.execute(
        """
        SELECT branch_id, parent_branch_id, split_year, strength, why_json, future_json
        FROM branch_lineages
        WHERE branch_id = ?
        """,
        (cand.target_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"branch lineage not found: {cand.target_id}")
    branch = dict(row)
    child_cluster = conn.execute(
        "SELECT * FROM visual_clusters WHERE branch_id=? ORDER BY n_nodes DESC LIMIT 1",
        (branch["branch_id"],),
    ).fetchone()
    parent_cluster = conn.execute(
        "SELECT * FROM visual_clusters WHERE branch_id=? ORDER BY n_nodes DESC LIMIT 1",
        (branch["parent_branch_id"],),
    ).fetchone() if branch.get("parent_branch_id") else None
    return {
        "audit_kind": "branch_lineage",
        "lineage": {
            **branch,
            "why": _json_loads(branch.get("why_json"), {}),
            "future": _json_loads(branch.get("future_json"), {}),
        },
        "child_cluster": _cluster_payload(child_cluster),
        "parent_cluster": _cluster_payload(parent_cluster),
        "audit_bucket": cand.sample_bucket,
        "audit_instruction": "judge whether this parent-child branch lineage is plausible and useful for explaining field evolution",
    }


def _cluster_payload(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    return {
        "cluster_id": data.get("cluster_id"),
        "branch_id": data.get("branch_id"),
        "label": data.get("label"),
        "n_nodes": data.get("n_nodes"),
        "year_start": data.get("year_start"),
        "year_end": data.get("year_end"),
        "top_terms": _json_loads(data.get("top_terms_json"), []),
        "representative_papers": _json_loads(data.get("representative_papers_json"), [])[:5],
        "evidence": _json_loads(data.get("evidence_json"), {}),
    }


def build_payload(conn: sqlite3.Connection, cand: AuditCandidate, abstract_chars: int) -> dict:
    if cand.item_type == "edge":
        return build_edge_payload(conn, cand, abstract_chars)
    if cand.item_type == "branch_lineage":
        return build_branch_payload(conn, cand, abstract_chars)
    raise ValueError(f"unknown item_type={cand.item_type!r}")


def build_audit_prompt(payload: dict) -> str:
    return (
        "你是 Echelon V14B optics AI4Science 图谱的边审计器。\n"
        "目标是帮助判断图谱是否能解释“为什么长成这样，未来往哪长”。\n"
        "请只依据给出的结构化证据审计，不要补造论文事实。\n\n"
        "请输出 JSON，不要 markdown，字段必须包含：\n"
        "{\n"
        '  "verdict": "keep|downweight|remove|uncertain",\n'
        '  "confidence": 0.0,\n'
        '  "evidence_strength": "strong|medium|weak",\n'
        '  "suggested_weight": 0.0,\n'
        '  "issues": ["..."],\n'
        '  "rationale_zh": "一句中文解释",\n'
        '  "graph_use": "main_backbone|branch_explanation|search_recommendation|future_signal|do_not_use"\n'
        "}\n\n"
        "审计对象如下：\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    )


def _normalize_result(result: dict) -> dict:
    verdict = str(result.get("verdict", "uncertain")).lower()
    if verdict not in {"keep", "downweight", "remove", "uncertain"}:
        verdict = "uncertain"
    try:
        confidence = float(result.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    try:
        suggested_weight = float(result.get("suggested_weight", 0.0))
    except Exception:
        suggested_weight = 0.0
    issues = result.get("issues", [])
    if not isinstance(issues, list):
        issues = [str(issues)]
    return {
        "verdict": verdict,
        "confidence": max(0.0, min(1.0, confidence)),
        "evidence_strength": str(result.get("evidence_strength", "weak")),
        "suggested_weight": max(0.0, min(1.0, suggested_weight)),
        "issues": [str(x)[:300] for x in issues[:8]],
        "rationale_zh": str(result.get("rationale_zh", ""))[:1000],
        "graph_use": str(result.get("graph_use", "do_not_use")),
        "raw": result,
    }


def insert_audit_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    provider: str,
    model: str | None,
    sample_config: dict,
    candidates: list[AuditCandidate],
    abstract_chars: int,
) -> dict:
    ensure_audit_schema(conn)
    conn.execute("DELETE FROM llm_edge_audit_items WHERE job_id=?", (job_id,))

    total_in = 0
    total_out = 0
    total_cost = 0.0
    bucket_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}

    rows = []
    for cand in make_progress(candidates, desc="Prepare audit queue"):
        payload = build_payload(conn, cand, abstract_chars)
        prompt = build_audit_prompt(payload)
        in_tok = _estimate_tokens(prompt)
        out_tok = DEFAULT_OUTPUT_TOKENS
        cost = _estimate_cost_rmb(in_tok, out_tok)
        total_in += in_tok
        total_out += out_tok
        total_cost += cost
        for bucket in cand.sample_bucket.split(","):
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        type_key = cand.edge_type or cand.item_type
        type_counts[type_key] = type_counts.get(type_key, 0) + 1
        rows.append((
            job_id, cand.item_id, cand.item_type, cand.target_id, cand.sample_bucket,
            cand.edge_type, cand.source_paper_id, cand.target_paper_id, cand.priority,
            in_tok, out_tok, cost, "pending", json.dumps(payload, ensure_ascii=False),
        ))

    conn.execute(
        """
        INSERT OR REPLACE INTO llm_edge_audit_jobs
            (job_id, provider, model, status, mode, sample_config_json,
             selected_items, estimated_input_tokens, estimated_output_tokens,
             estimated_cost_rmb, notes)
        VALUES (?, ?, ?, 'planned', 'plan', ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id, provider, model, json.dumps(sample_config, ensure_ascii=False),
            len(candidates), total_in, total_out, total_cost,
            json.dumps({"bucket_counts": bucket_counts, "type_counts": type_counts}, ensure_ascii=False),
        ),
    )
    conn.executemany(
        """
        INSERT INTO llm_edge_audit_items
            (job_id, item_id, item_type, target_id, sample_bucket, edge_type,
             source_paper_id, target_paper_id, priority, prompt_tokens_est,
             output_tokens_est, cost_est_rmb, status, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return {
        "job_id": job_id,
        "selected_items": len(candidates),
        "estimated_input_tokens": total_in,
        "estimated_output_tokens": total_out,
        "estimated_cost_rmb": total_cost,
        "bucket_counts": bucket_counts,
        "type_counts": type_counts,
    }


def write_plan_report(stats: dict, job_id: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"llm_edge_audit_plan_{job_id}.md"
    lines = [
        "# V14B Stratified LLM Edge Audit Plan",
        "",
        f"- Job ID: `{job_id}`",
        f"- Selected items: **{stats['selected_items']:,}**",
        f"- Estimated input tokens: **{stats['estimated_input_tokens']:,}**",
        f"- Estimated output tokens: **{stats['estimated_output_tokens']:,}**",
        f"- Estimated Doubao cost: **¥{stats['estimated_cost_rmb']:.2f}**",
        "",
        "## Buckets",
        "",
        "| bucket | n |",
        "|---|---:|",
    ]
    for key, value in sorted(stats["bucket_counts"].items()):
        lines.append(f"| `{key}` | {value:,} |")
    lines += ["", "## Types", "", "| type | n |", "|---|---:|"]
    for key, value in sorted(stats["type_counts"].items()):
        lines.append(f"| `{key}` | {value:,} |")
    lines += [
        "",
        "## Execution",
        "",
        "Default execution is capped. Increase `V14B_LLM_EDGE_AUDIT_MAX_CALLS` deliberately.",
        "",
        "```bash",
        f"LLM_PROVIDER=doubao python3 -m echelon.v14b.step11_llm_edge_audit --db-v14 db/v14_pilot.sqlite3 --job-id {job_id} --execute --max-calls 100",
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def refresh_job_counts(conn: sqlite3.Connection, job_id: str) -> dict:
    job = conn.execute(
        "SELECT status, mode FROM llm_edge_audit_jobs WHERE job_id=?",
        (job_id,),
    ).fetchone()
    current_status = job["status"] if job else "planned"
    current_mode = job["mode"] if job else "plan"
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS selected_items,
            SUM(status='audited') AS audited_items,
            SUM(status='failed') AS failed_items
        FROM llm_edge_audit_items
        WHERE job_id=?
        """,
        (job_id,),
    ).fetchone()
    verdicts = {
        r["verdict"]: r["n"]
        for r in _rows(
            conn,
            """
            SELECT json_extract(result_json, '$.verdict') AS verdict, COUNT(*) AS n
            FROM llm_edge_audit_items
            WHERE job_id=? AND status='audited'
            GROUP BY verdict
            """,
            (job_id,),
        )
    }
    selected = int(row["selected_items"] or 0)
    audited = int(row["audited_items"] or 0)
    failed = int(row["failed_items"] or 0)
    approved = int(verdicts.get("keep", 0))
    flagged = audited - approved
    processed = audited + failed
    if selected and processed >= selected:
        status = "done"
    elif processed > 0 or current_mode == "execute" or current_status == "running":
        status = "running"
    else:
        status = current_status or "planned"
    conn.execute(
        """
        UPDATE llm_edge_audit_jobs
        SET updated_at=CURRENT_TIMESTAMP, selected_items=?, audited_items=?,
            approved_items=?, flagged_items=?, failed_items=?, status=?
        WHERE job_id=?
        """,
        (
            selected, audited, approved, flagged, failed,
            status,
            job_id,
        ),
    )
    conn.commit()
    return {
        "selected_items": selected,
        "audited_items": audited,
        "approved_items": approved,
        "flagged_items": flagged,
        "failed_items": failed,
        "verdicts": verdicts,
    }


def execute_audit_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    provider: str = "doubao",
    model: str | None = None,
    max_calls: int = DEFAULT_MAX_CALLS,
    sleep_s: float = 0.2,
) -> dict:
    ensure_audit_schema(conn)
    client = LLMClient.from_provider(provider, model=model)
    tracker = get_cost_tracker()
    in_before = tracker.total_input_tokens
    out_before = tracker.total_output_tokens

    limit_clause = "" if max_calls <= 0 else "LIMIT ?"
    params: tuple[Any, ...] = (job_id,) if max_calls <= 0 else (job_id, max_calls)
    items = _rows(
        conn,
        f"""
        SELECT item_id, payload_json
        FROM llm_edge_audit_items
        WHERE job_id=? AND status='pending'
        ORDER BY priority, item_id
        {limit_clause}
        """,
        params,
    )
    conn.execute(
        "UPDATE llm_edge_audit_jobs SET status='running', mode='execute', provider=?, model=?, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
        (provider, model, job_id),
    )
    conn.commit()

    for item in make_progress(items, desc="LLM edge audit"):
        item_id = item["item_id"]
        try:
            payload = json.loads(item["payload_json"])
            prompt = build_audit_prompt(payload)
            result = client.extract_json(prompt, max_tokens=DEFAULT_OUTPUT_TOKENS)
            normalized = _normalize_result(result)
            conn.execute(
                """
                UPDATE llm_edge_audit_items
                SET status='audited', result_json=?, error=NULL, audited_at=CURRENT_TIMESTAMP
                WHERE job_id=? AND item_id=?
                """,
                (json.dumps(normalized, ensure_ascii=False), job_id, item_id),
            )
        except Exception as exc:
            logger.warning("LLM audit failed for %s: %s", item_id, exc)
            conn.execute(
                """
                UPDATE llm_edge_audit_items
                SET status='failed', error=?, audited_at=CURRENT_TIMESTAMP
                WHERE job_id=? AND item_id=?
                """,
                (str(exc)[:2000], job_id, item_id),
            )
        conn.commit()
        if sleep_s > 0:
            time.sleep(sleep_s)

    counts = refresh_job_counts(conn, job_id)
    actual_in = tracker.total_input_tokens - in_before
    actual_out = tracker.total_output_tokens - out_before
    actual_cost = _estimate_cost_rmb(actual_in, actual_out)
    conn.execute(
        """
        UPDATE llm_edge_audit_jobs
        SET actual_input_tokens=COALESCE(actual_input_tokens,0)+?,
            actual_output_tokens=COALESCE(actual_output_tokens,0)+?,
            actual_cost_rmb=COALESCE(actual_cost_rmb,0)+?,
            updated_at=CURRENT_TIMESTAMP
        WHERE job_id=?
        """,
        (actual_in, actual_out, actual_cost, job_id),
    )
    conn.commit()
    counts.update({"actual_input_tokens": actual_in, "actual_output_tokens": actual_out, "actual_cost_rmb": actual_cost})
    return counts


def create_job_id() -> str:
    return "edgeaudit-" + datetime.utcnow().strftime("%Y%m%d%H%M%S")


def run_edge_audit(
    *,
    db_v14: Path = DB_V14,
    job_id: str | None = None,
    execute: bool = False,
    sample_per_layer: int = DEFAULT_SAMPLE_PER_LAYER,
    extra_sample: int = DEFAULT_EXTRA_SAMPLE,
    branch_mode: str = "all",
    branch_sample: int = 3000,
    seed: int = 42,
    provider: str = "doubao",
    model: str | None = None,
    max_calls: int = DEFAULT_MAX_CALLS,
    sleep_s: float = 0.2,
    abstract_chars: int = DEFAULT_ABSTRACT_CHARS,
) -> dict:
    conn = get_v14b_conn(db_v14)
    ensure_audit_schema(conn)
    require_visual_graph(conn)
    step_name = "step11_llm_edge_audit"
    upsert_step_meta(conn, step_name, "running")

    if job_id is None:
        job_id = create_job_id()
        sample_config = {
            "sample_per_layer": sample_per_layer,
            "extra_sample": extra_sample,
            "branch_mode": branch_mode,
            "branch_sample": branch_sample,
            "seed": seed,
            "abstract_chars": abstract_chars,
            "doubao_input_rmb_per_m": DOUBAO_INPUT_RMB_PER_M,
            "doubao_output_rmb_per_m": DOUBAO_OUTPUT_RMB_PER_M,
        }
        candidates = select_audit_candidates(
            conn,
            sample_per_layer=sample_per_layer,
            extra_sample=extra_sample,
            branch_mode=branch_mode,
            branch_sample=branch_sample,
            seed=seed,
        )
        stats = insert_audit_job(
            conn,
            job_id=job_id,
            provider=provider,
            model=model,
            sample_config=sample_config,
            candidates=candidates,
            abstract_chars=abstract_chars,
        )
        report_path = write_plan_report(stats, job_id)
        conn.execute("UPDATE llm_edge_audit_jobs SET report_path=? WHERE job_id=?", (str(report_path), job_id))
        conn.commit()
        logger.info("LLM edge audit plan ready: %s", report_path)
    else:
        row = conn.execute("SELECT * FROM llm_edge_audit_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"job_id not found: {job_id}")
        stats = dict(row)

    if execute:
        logger.info("Executing LLM edge audit job=%s provider=%s max_calls=%s", job_id, provider, max_calls)
        stats.update(execute_audit_job(
            conn,
            job_id=job_id,
            provider=provider,
            model=model,
            max_calls=max_calls,
            sleep_s=sleep_s,
        ))
    else:
        refresh_job_counts(conn, job_id)

    final_counts = refresh_job_counts(conn, job_id)
    upsert_step_meta(conn, step_name, "done", records_n=final_counts["selected_items"], notes=f"job_id={job_id}")
    conn.close()
    final_counts.update({"job_id": job_id})
    return final_counts


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step11_llm_edge_audit",
        description="Step 11: stratified Doubao/LLM audit for visual graph edges",
    )
    add_common_args(parser)
    parser.add_argument("--job-id", default=None, help="Existing job_id to execute/resume")
    parser.add_argument("--execute", action="store_true", help="Call LLM for pending audit items")
    parser.add_argument("--sample-per-layer", type=int, default=DEFAULT_SAMPLE_PER_LAYER)
    parser.add_argument("--extra-sample", type=int, default=DEFAULT_EXTRA_SAMPLE)
    parser.add_argument("--branch-mode", choices=["all", "sample"], default="all")
    parser.add_argument("--branch-sample", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "doubao"))
    parser.add_argument("--model", default=os.environ.get("DOUBAO_MODEL"))
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS, help="0 means all pending items")
    parser.add_argument("--sleep", type=float, default=float(os.environ.get("V14B_LLM_EDGE_AUDIT_SLEEP", "0.2")))
    parser.add_argument("--abstract-chars", type=int, default=DEFAULT_ABSTRACT_CHARS)
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step11_llm_edge_audit", level=log_level)
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14

    stats = run_edge_audit(
        db_v14=db_v14,
        job_id=args.job_id,
        execute=args.execute,
        sample_per_layer=args.sample_per_layer,
        extra_sample=args.extra_sample,
        branch_mode=args.branch_mode,
        branch_sample=args.branch_sample,
        seed=args.seed,
        provider=args.provider,
        model=args.model,
        max_calls=args.max_calls,
        sleep_s=args.sleep,
        abstract_chars=args.abstract_chars,
    )
    logger.info("Step11 stats: %s", json.dumps(stats, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
