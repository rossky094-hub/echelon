"""Recall candidate section atoms for missing typed-chain stages.

This report is intentionally conservative.  It helps a reviewer inspect why a
topic-gap repair contract has a partial bottleneck chain by retrieving
same-paper atoms for the missing stages and a few cross-paper examples for
classifier/parser tuning.  It never closes a contract and never promotes fuzzy
hits into Step13 or Radar conclusions.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, REPORT_DIR
from echelon.v14b.section_atoms import (
    ATOM_EMBEDDING_DIM,
    ATOM_EMBEDDING_MODEL,
    FUZZY_SEARCH_SEMANTICS,
    section_atom_search_contract,
    search_section_atoms,
    search_section_atoms_fuzzy,
)
from echelon.v14b.utils import add_common_args


CHAIN_STAGES = (
    "constraint",
    "failure_mechanism",
    "attempted_path",
    "local_fix",
    "new_constraint",
)

STAGE_QUERY_CUES = {
    "constraint": "constraint limitation bottleneck requirement tradeoff difficult insufficient",
    "failure_mechanism": "failure mechanism loss noise instability defect degradation mismatch",
    "attempted_path": "attempted path approach method design architecture fabrication optimization",
    "local_fix": "local fix mitigate resolve improve enable demonstrate address",
    "new_constraint": "new constraint however still remains future work open question unresolved",
}

TARGET_CLOSURE_STATES = {"partial_chain_incomplete", "open_topic_chain_mismatch"}
PROMOTION_POLICY = "candidate_recall_only_no_direct_promotion"
RECALL_PAYLOAD_KEYS = (
    "query",
    "same_paper_candidate_count",
    "cross_paper_template_count",
    "same_paper_candidate_hits",
    "cross_paper_stage_examples",
    "search_contract",
    "cannot_close_contract",
    "review_required_before_chain_rebuild",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"missing topic-gap triage JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"topic-gap triage JSON must be an object: {path}")
    return data


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _stage_counts(value: Any) -> dict[str, int]:
    if isinstance(value, dict):
        counts: dict[str, int] = {}
        for stage, count in value.items():
            stage_name = str(stage or "")
            if stage_name not in CHAIN_STAGES:
                continue
            try:
                n = int(count or 0)
            except (TypeError, ValueError):
                n = 1
            counts[stage_name] = max(n, 1)
        return counts
    if isinstance(value, list):
        return dict(Counter(str(stage) for stage in value if str(stage) in CHAIN_STAGES))
    return {}


def _task_rows(triage: dict[str, Any], *, limit: int | None = None) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for row in triage.get("rows") or []:
        if not isinstance(row, dict):
            continue
        row_missing = _stage_counts(row.get("section_atom_chain_missing_stages"))
        for closure in row.get("repair_contract_closures") or []:
            if not isinstance(closure, dict):
                continue
            state = str(closure.get("closure_state") or "")
            if state not in TARGET_CLOSURE_STATES:
                continue
            missing = _stage_counts(closure.get("missing_stages")) or row_missing
            if not missing:
                continue
            for stage in CHAIN_STAGES:
                if stage not in missing:
                    continue
                tasks.append(
                    {
                        "paper_id": closure.get("paper_id") or row.get("paper_id") or "",
                        "title": row.get("title") or closure.get("title") or "",
                        "topic": closure.get("topic") or (row.get("topics") or [""])[0],
                        "bottleneck": closure.get("bottleneck") or "",
                        "gap_type": closure.get("gap_type") or (row.get("gap_types") or [""])[0],
                        "repair_id": closure.get("repair_id") or "",
                        "source_contract": closure.get("source_contract") or "",
                        "closure_state": state,
                        "failure_mode": closure.get("failure_mode") or row.get("failure_mode") or "",
                        "frontfill_query": closure.get("frontfill_query") or "",
                        "missing_stage": stage,
                        "missing_stage_count": int(missing.get(stage) or 1),
                        "priority_score": _as_float(row.get("priority_score")),
                        "next_action": closure.get("next_action") or row.get("next_action") or "",
                        "claim_scope": "evidence_repair_candidate_recall_only",
                        "promotion_policy": PROMOTION_POLICY,
                    }
                )
                if limit is not None and len(tasks) >= int(limit):
                    return tasks
    return tasks


def _query_for_task(task: dict[str, Any]) -> str:
    stage = str(task.get("missing_stage") or "")
    parts = [
        task.get("topic"),
        task.get("bottleneck"),
        task.get("frontfill_query"),
        task.get("title"),
        STAGE_QUERY_CUES.get(stage, stage),
    ]
    seen: set[str] = set()
    clean_parts: list[str] = []
    for part in parts:
        text = " ".join(str(part or "").split())
        if not text or text in seen:
            continue
        seen.add(text)
        clean_parts.append(text)
    return " ".join(clean_parts)


def _truncate(text: Any, limit: int = 420) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _slim_hit(hit: dict[str, Any], *, candidate_scope: str, retrieval_channel: str) -> dict[str, Any]:
    item = {
        "candidate_scope": candidate_scope,
        "retrieval_channels": [retrieval_channel],
        "atom_id": hit.get("atom_id") or "",
        "paper_id": hit.get("paper_id") or "",
        "title": hit.get("title") or "",
        "section_name": hit.get("section_name") or "",
        "atom_type": hit.get("atom_type") or "",
        "atom_text": _truncate(hit.get("atom_text")),
        "page_start": hit.get("page_start"),
        "page_end": hit.get("page_end"),
        "span": hit.get("span"),
        "source_storage_uri": hit.get("source_storage_uri") or "",
        "parser_contract_version": hit.get("parser_contract_version") or "",
        "evidence_grade": hit.get("evidence_grade") or "",
        "claim_scope": "retrieval_context_only",
        "search_mode": hit.get("search_mode") or retrieval_channel,
        "search_semantics": hit.get("search_semantics") or FUZZY_SEARCH_SEMANTICS,
        "rank_score": hit.get("rank_score"),
        "similarity_score": hit.get("similarity_score"),
        "vector_score": hit.get("vector_score"),
        "lexical_overlap_score": hit.get("lexical_overlap_score"),
        "uncertainty_reasons": hit.get("uncertainty_reasons") or [],
    }
    return {key: value for key, value in item.items() if value not in (None, "", [])}


def _merge_candidate_hits(
    exact_hits: list[dict[str, Any]],
    fuzzy_hits: list[dict[str, Any]],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    by_atom_id: dict[str, dict[str, Any]] = {}
    for hit in exact_hits:
        item = _slim_hit(
            hit,
            candidate_scope="same_paper_missing_stage_atom",
            retrieval_channel="exact_atom_type_filter",
        )
        atom_id = str(item.get("atom_id") or "")
        by_atom_id[atom_id] = item
        merged.append(item)
    for hit in fuzzy_hits:
        atom_id = str(hit.get("atom_id") or "")
        existing = by_atom_id.get(atom_id)
        if existing:
            channels = list(existing.get("retrieval_channels") or [])
            if "fuzzy_vector_recall" not in channels:
                channels.append("fuzzy_vector_recall")
            existing["retrieval_channels"] = channels
            for key in ("similarity_score", "vector_score", "lexical_overlap_score"):
                if key in hit:
                    existing[key] = hit[key]
            existing["search_semantics"] = FUZZY_SEARCH_SEMANTICS
            continue
        item = _slim_hit(
            hit,
            candidate_scope="same_paper_missing_stage_atom",
            retrieval_channel="fuzzy_vector_recall",
        )
        by_atom_id[atom_id] = item
        merged.append(item)
    return merged[: int(top_k)]


def _recall_for_task(
    conn: sqlite3.Connection,
    task: dict[str, Any],
    *,
    top_k: int,
    embedding_model: str,
    embedding_dim: int,
    min_fuzzy_score: float,
    include_cross_paper_templates: bool,
) -> dict[str, Any]:
    paper_id = str(task.get("paper_id") or "")
    stage = str(task.get("missing_stage") or "")
    query = _query_for_task(task)
    same_paper_filters = {"paper_id": paper_id, "atom_type": stage}
    exact_hits = search_section_atoms(
        conn,
        "",
        top_k=top_k,
        filters=same_paper_filters,
        ensure_schema=False,
    )
    fuzzy_hits = search_section_atoms_fuzzy(
        conn,
        query,
        top_k=top_k,
        filters=same_paper_filters,
        embedding_model=embedding_model,
        embedding_dim=int(embedding_dim),
        min_score=min_fuzzy_score,
        ensure_schema=False,
    )
    same_paper_candidates = _merge_candidate_hits(exact_hits, fuzzy_hits, top_k=top_k)
    cross_hits: list[dict[str, Any]] = []
    if include_cross_paper_templates:
        cross_hits = [
            _slim_hit(
                hit,
                candidate_scope="cross_paper_stage_template_only",
                retrieval_channel="fuzzy_vector_recall",
            )
            for hit in search_section_atoms_fuzzy(
                conn,
                query,
                top_k=max(top_k * 2, top_k),
                filters={"atom_type": stage},
                embedding_model=embedding_model,
                embedding_dim=int(embedding_dim),
                min_score=min_fuzzy_score,
                ensure_schema=False,
            )
            if str(hit.get("paper_id") or "") != paper_id
        ][:top_k]
    return {
        **task,
        "query": query,
        "same_paper_candidate_count": len(same_paper_candidates),
        "cross_paper_template_count": len(cross_hits),
        "same_paper_candidate_hits": same_paper_candidates,
        "cross_paper_stage_examples": cross_hits,
        "search_contract": section_atom_search_contract("typed_stage_gap_candidate_recall"),
        "cannot_close_contract": True,
        "review_required_before_chain_rebuild": True,
    }


def build_topic_gap_stage_candidate_recall(
    *,
    db_main: Path = DB_MAIN,
    triage_json: Path = REPORT_DIR / "topic_gap_section_evidence_audit.json",
    out_dir: Path = REPORT_DIR,
    top_k: int = 5,
    limit: int | None = None,
    embedding_model: str = ATOM_EMBEDDING_MODEL,
    embedding_dim: int = ATOM_EMBEDDING_DIM,
    min_fuzzy_score: float = 0.0,
    include_cross_paper_templates: bool = False,
) -> dict[str, Any]:
    triage = _load_json(triage_json)
    tasks = _task_rows(triage, limit=limit)
    conn = sqlite3.connect(str(db_main), timeout=30)
    conn.row_factory = sqlite3.Row
    rows: list[dict[str, Any]] = []
    recall_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
    for task in tasks:
        cache_key = (
            str(task.get("paper_id") or ""),
            str(task.get("missing_stage") or ""),
            _query_for_task(task),
        )
        payload = recall_cache.get(cache_key)
        if payload is None:
            recalled = _recall_for_task(
                conn,
                task,
                top_k=top_k,
                embedding_model=embedding_model,
                embedding_dim=int(embedding_dim),
                min_fuzzy_score=float(min_fuzzy_score),
                include_cross_paper_templates=bool(include_cross_paper_templates),
            )
            payload = {key: recalled.get(key) for key in RECALL_PAYLOAD_KEYS}
            recall_cache[cache_key] = payload
        rows.append({**task, **payload})
    conn.close()

    missing_stage_counts = Counter(str(row.get("missing_stage") or "") for row in rows)
    same_paper_hits = sum(int(row.get("same_paper_candidate_count") or 0) for row in rows)
    cross_paper_hits = sum(int(row.get("cross_paper_template_count") or 0) for row in rows)
    report = {
        "generated_at": utc_now(),
        "db_main": str(db_main),
        "source_triage_json": str(triage_json),
        "source_triage_audit_ts": triage.get("audit_ts") or "",
        "status": "ready" if rows else "empty",
        "claim_scope": "evidence_repair_candidate_recall_only",
        "promotion_policy": PROMOTION_POLICY,
        "policy": (
            "Same-paper stage hits are inspection candidates for deterministic chain rebuilds; "
            "cross-paper fuzzy examples are optional parser/classifier tuning templates only. "
            "No hit can close a repair contract or promote a Step13/Radar claim."
        ),
        "search_contract": section_atom_search_contract("typed_stage_gap_candidate_recall"),
        "summary": {
            "candidate_tasks": len(rows),
            "unique_papers": len({str(row.get("paper_id") or "") for row in rows if row.get("paper_id")}),
            "missing_stage_counts": dict(missing_stage_counts),
            "same_paper_candidate_hits": same_paper_hits,
            "cross_paper_template_hits": cross_paper_hits,
            "cross_paper_templates_enabled": bool(include_cross_paper_templates),
            "tasks_with_same_paper_candidates": sum(
                1 for row in rows if int(row.get("same_paper_candidate_count") or 0) > 0
            ),
        },
        "rows": rows,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "topic_gap_stage_candidate_recall.json"
    md_path = out_dir / "topic_gap_stage_candidate_recall.md"
    csv_path = out_dir / "topic_gap_stage_candidate_recall.csv"
    report["outputs"] = {"json": str(json_path), "markdown": str(md_path), "csv": str(csv_path)}
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    _write_csv(csv_path, report)
    return report


def _write_csv(path: Path, report: dict[str, Any]) -> None:
    fieldnames = [
        "paper_id",
        "repair_id",
        "topic",
        "missing_stage",
        "candidate_scope",
        "candidate_paper_id",
        "atom_id",
        "section_name",
        "atom_type",
        "evidence_grade",
        "claim_scope",
        "retrieval_channels",
        "score",
        "source_storage_uri",
        "atom_text",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in report.get("rows") or []:
            hits = list(row.get("same_paper_candidate_hits") or []) + list(
                row.get("cross_paper_stage_examples") or []
            )
            if not hits:
                writer.writerow(
                    {
                        "paper_id": row.get("paper_id") or "",
                        "repair_id": row.get("repair_id") or "",
                        "topic": row.get("topic") or "",
                        "missing_stage": row.get("missing_stage") or "",
                        "claim_scope": row.get("claim_scope") or "",
                    }
                )
                continue
            for hit in hits:
                writer.writerow(
                    {
                        "paper_id": row.get("paper_id") or "",
                        "repair_id": row.get("repair_id") or "",
                        "topic": row.get("topic") or "",
                        "missing_stage": row.get("missing_stage") or "",
                        "candidate_scope": hit.get("candidate_scope") or "",
                        "candidate_paper_id": hit.get("paper_id") or "",
                        "atom_id": hit.get("atom_id") or "",
                        "section_name": hit.get("section_name") or "",
                        "atom_type": hit.get("atom_type") or "",
                        "evidence_grade": hit.get("evidence_grade") or "",
                        "claim_scope": hit.get("claim_scope") or "",
                        "retrieval_channels": ",".join(hit.get("retrieval_channels") or []),
                        "score": hit.get("similarity_score") or hit.get("rank_score") or "",
                        "source_storage_uri": hit.get("source_storage_uri") or "",
                        "atom_text": hit.get("atom_text") or "",
                    }
                )


def _render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Topic-Gap Typed Stage Candidate Recall",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- status: `{report['status']}`",
        f"- claim_scope: `{report['claim_scope']}`",
        f"- promotion_policy: `{report['promotion_policy']}`",
        f"- candidate tasks: `{summary['candidate_tasks']}`; unique papers: `{summary['unique_papers']}`",
        f"- same-paper candidate hits: `{summary['same_paper_candidate_hits']}`",
        f"- cross-paper template hits: `{summary['cross_paper_template_hits']}`",
        "",
        "## Missing Stages",
        "",
        "| stage | tasks |",
        "|---|---:|",
    ]
    for stage, count in Counter(summary.get("missing_stage_counts") or {}).most_common():
        lines.append(f"| `{stage}` | {int(count):,} |")
    lines.extend(
        [
            "",
            "## Contract",
            "",
            "- Same-paper hits are inspection candidates before deterministic chain rebuild.",
            "- Cross-paper fuzzy hits are templates for parser/classifier tuning only.",
            "- No candidate closes a repair contract or promotes a Step13/Radar claim.",
            "",
            "## Top Tasks",
            "",
            "| paper_id | topic | missing_stage | same-paper hits | cross-paper examples | first candidate |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    for row in _unique_top_rows(report.get("rows") or [])[:25]:
        first_hit = (row.get("same_paper_candidate_hits") or row.get("cross_paper_stage_examples") or [{}])[0]
        first = f"{first_hit.get('section_name', '')}: {first_hit.get('atom_text', '')}"
        lines.append(
            f"| `{_md(row.get('paper_id'))}` | {_md(row.get('topic'))} | "
            f"`{_md(row.get('missing_stage'))}` | {int(row.get('same_paper_candidate_count') or 0)} | "
            f"{int(row.get('cross_paper_template_count') or 0)} | {_md(_truncate(first, 160))} |"
        )
    lines.append("")
    return "\n".join(lines)


def _unique_top_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in sorted(
        rows,
        key=lambda item: (
            -int(item.get("same_paper_candidate_count") or 0),
            -_as_float(item.get("priority_score")),
            str(item.get("paper_id") or ""),
            str(item.get("missing_stage") or ""),
        ),
    ):
        key = (
            str(row.get("paper_id") or ""),
            str(row.get("topic") or ""),
            str(row.get("missing_stage") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _md(value: Any) -> str:
    return " ".join(str(value or "").replace("|", ";").split())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Recall candidate atoms for missing topic-gap typed-chain stages.")
    add_common_args(parser)
    parser.add_argument(
        "--triage-json",
        type=Path,
        default=REPORT_DIR / "topic_gap_section_evidence_audit.json",
    )
    parser.add_argument("--out-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--embedding-model", default=ATOM_EMBEDDING_MODEL)
    parser.add_argument("--embedding-dim", type=int, default=ATOM_EMBEDDING_DIM)
    parser.add_argument("--min-fuzzy-score", type=float, default=0.0)
    parser.add_argument(
        "--include-cross-paper-templates",
        action="store_true",
        help="Also scan cross-paper fuzzy examples for parser/classifier tuning; slower and never contract-closing.",
    )
    args = parser.parse_args(argv)
    report = build_topic_gap_stage_candidate_recall(
        db_main=args.db or DB_MAIN,
        triage_json=args.triage_json,
        out_dir=args.out_dir,
        top_k=args.top_k,
        limit=args.limit,
        embedding_model=args.embedding_model,
        embedding_dim=args.embedding_dim,
        min_fuzzy_score=args.min_fuzzy_score,
        include_cross_paper_templates=args.include_cross_paper_templates,
    )
    print(json.dumps({"status": report["status"], "summary": report["summary"], "outputs": report["outputs"]}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
