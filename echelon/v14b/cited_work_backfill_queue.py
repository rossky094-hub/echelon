"""Prepare high-value cited-work backfill targets for V14B.

Reference relinking can only join works that already exist in the local corpus.
When the relink audit says no-local-match references dominate, the next
evidence-building move is not fuzzy matching or broader LLM use.  It is to
frontfill the missing cited works with exact provider IDs, then rerun exact
relinking.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, DB_V14
from echelon.v14b.reference_relink_audit import (
    PROVIDERS,
    build_paper_id_maps,
    evaluate_reference,
    scalar,
    table_columns,
    table_exists,
)
from echelon.v14b.utils import setup_logging


PROVIDER_BOOSTS = {
    "doi": 35.0,
    "openalex": 30.0,
    "arxiv": 25.0,
    "s2": 20.0,
}

REASON_BOOSTS: tuple[tuple[str, float], ...] = (
    ("topic_gap_key_turning_section", 80.0),
    ("topic_gap_bottleneck_evidence", 75.0),
    ("topic_gap_claim_card_inputs", 65.0),
    ("topic_gap", 60.0),
    ("main_path_node", 50.0),
    ("branch_split_driver", 45.0),
    ("limitation_evidence", 42.0),
    ("resolution_evidence", 38.0),
    ("top_keystone", 35.0),
    ("future_endpoint", 32.0),
    ("future edge", 30.0),
    ("future_", 28.0),
    ("active_learning_uncertainty_hotspot", 20.0),
    ("cluster_representative", 10.0),
)

QUEUE_FIELDNAMES = [
    "rank",
    "priority_score",
    "raw_priority_score",
    "provider",
    "normalized_id",
    "doi",
    "openalex_id",
    "arxiv_id",
    "s2_paper_id",
    "external_id_sample",
    "citing_paper_count",
    "high_value_categories",
    "evidence_gap_reasons",
    "top_citing_papers",
    "top_citing_titles",
    "provider_backfill_strategy",
    "last_backfill_status",
    "last_backfill_attempted_at",
    "backfill_attempt_penalty",
    "claim_scope",
    "evidence_grade",
    "uncertainty_reasons_json",
]


@dataclass
class SeedPaper:
    paper_id: str
    priority_score: float
    reasons: set[str] = field(default_factory=set)
    title: str = ""


@dataclass
class BackfillTarget:
    provider: str
    norm: str
    external_sample: str
    citing_scores: dict[str, float] = field(default_factory=dict)
    citing_titles: dict[str, str] = field(default_factory=dict)
    reasons: set[str] = field(default_factory=set)
    categories: set[str] = field(default_factory=set)
    provider_boost: float = 0.0
    last_backfill_status: str = ""
    last_backfill_error: str = ""
    last_backfill_attempted_at: str = ""

    def raw_priority_score(self) -> float:
        scores = list(self.citing_scores.values())
        max_score = max(scores, default=0.0)
        support = len(scores)
        support_boost = 18.0 * math.sqrt(max(0, support - 1))
        breadth_boost = min(80.0, 0.05 * sum(scores))
        return round(max_score + support_boost + breadth_boost, 4)

    def attempt_penalty(self) -> float:
        status = self.last_backfill_status
        error = self.last_backfill_error.lower()
        if status in {"identity_mismatch"}:
            return 2200.0
        if status == "fetch_failed" and "not_found" in error:
            return 1800.0
        if status == "fetch_failed":
            return 450.0
        if status in {"dry_run_pending_fetch"}:
            return 0.0
        return 0.0

    def priority_score(self) -> float:
        return round(max(0.0, self.raw_priority_score() - self.attempt_penalty()), 4)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def jdumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _clean_cell(value: Any) -> str:
    return " ".join(str(value or "").split())


def _loads_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    try:
        parsed = json.loads(str(value))
    except Exception:
        return []
    if isinstance(parsed, list):
        return [str(v) for v in parsed if str(v).strip()]
    if isinstance(parsed, dict):
        return [str(k) for k, v in parsed.items() if v]
    return []


def _reason_boost(reasons: set[str]) -> float:
    total = 0.0
    for reason in reasons:
        low = reason.lower()
        for marker, boost in REASON_BOOSTS:
            if marker in low:
                total += boost
                break
    return min(total, 260.0)


def _reason_category(reason: str) -> str:
    low = reason.lower()
    if low.startswith("topic_gap"):
        return "topic_gap"
    if low.startswith("topic:"):
        return "topic"
    if ":" in reason:
        return reason.split(":", 1)[0]
    return reason


def _gap_reasons(reasons: set[str]) -> list[str]:
    markers = ("gap", "bottleneck", "limitation", "resolution", "future", "claim_card", "main_path", "branch_split")
    selected = [r for r in sorted(reasons) if any(marker in r.lower() for marker in markers)]
    return selected or sorted(reasons)[:8]


def _provider_columns(provider: str, norm: str) -> dict[str, str]:
    return {
        "doi": norm if provider == "doi" else "",
        "openalex_id": norm if provider == "openalex" else "",
        "arxiv_id": norm if provider == "arxiv" else "",
        "s2_paper_id": norm if provider == "s2" else "",
    }


def _provider_strategy(provider: str) -> str:
    strategies = {
        "doi": "Resolve DOI through Crossref/OpenAlex, insert the canonical work, then rerun exact reference relinking.",
        "openalex": "Fetch the OpenAlex Work by W ID, add its provider IDs and references, then rerun exact reference relinking.",
        "arxiv": "Fetch arXiv metadata/PDF when in corpus scope, parse sections, then rerun exact reference relinking.",
        "s2": "Fetch Semantic Scholar paper metadata/references by paperId when available, then rerun exact reference relinking.",
    }
    return strategies.get(provider, "Resolve by exact provider ID, insert locally, then rerun exact reference relinking.")


def _load_backfill_attempts(conn: sqlite3.Connection) -> dict[tuple[str, str], dict[str, Any]]:
    if not table_exists(conn, "cited_work_backfill_attempts"):
        return {}
    cols = table_columns(conn, "cited_work_backfill_attempts")
    required = {"target_provider", "target_norm", "status"}
    if not required.issubset(cols):
        return {}
    error_sql = "error" if "error" in cols else "NULL AS error"
    attempted_sql = "attempted_at" if "attempted_at" in cols else "NULL AS attempted_at"
    rows = conn.execute(
        f"""
        SELECT target_provider, target_norm, status, {error_sql}, {attempted_sql}
        FROM cited_work_backfill_attempts
        """
    ).fetchall()
    return {
        (str(row["target_provider"] or ""), str(row["target_norm"] or "")): {
            "status": str(row["status"] or ""),
            "error": str(row["error"] or ""),
            "attempted_at": str(row["attempted_at"] or ""),
        }
        for row in rows
    }


def _merge_seed(seeds: dict[str, SeedPaper], seed: SeedPaper) -> None:
    existing = seeds.get(seed.paper_id)
    if existing is None:
        seeds[seed.paper_id] = seed
        return
    existing.priority_score = max(existing.priority_score, seed.priority_score)
    existing.reasons.update(seed.reasons)
    if not existing.title and seed.title:
        existing.title = seed.title


def load_priority_seed_papers(
    conn_v14: sqlite3.Connection,
    *,
    topic_gap_queue: Path | None = None,
) -> dict[str, SeedPaper]:
    """Load the current high-value citing-paper context.

    The seed set is intentionally evidence-driven.  It comes from the section
    priority audit and optional multi-topic evidence-gap queue, not from a gold
    topic allowlist.
    """
    seeds: dict[str, SeedPaper] = {}
    if table_exists(conn_v14, "section_priority_papers"):
        cols = table_columns(conn_v14, "section_priority_papers")
        select_cols = [
            "paper_id",
            "priority_score" if "priority_score" in cols else "0.0 AS priority_score",
            "reasons_json" if "reasons_json" in cols else "NULL AS reasons_json",
            "title" if "title" in cols else "NULL AS title",
        ]
        where = ""
        params: tuple[Any, ...] = ()
        if "audit_ts" in cols:
            latest = scalar(conn_v14, "SELECT MAX(audit_ts) FROM section_priority_papers")
            if latest:
                where = "WHERE audit_ts = ?"
                params = (latest,)
        rows = conn_v14.execute(f"SELECT {', '.join(select_cols)} FROM section_priority_papers {where}", params)
        for row in rows.fetchall():
            pid = str(row["paper_id"] or "").strip()
            if not pid:
                continue
            try:
                priority = float(row["priority_score"] or 0.0)
            except Exception:
                priority = 0.0
            _merge_seed(
                seeds,
                SeedPaper(
                    paper_id=pid,
                    priority_score=priority,
                    reasons=set(_loads_list(row["reasons_json"])),
                    title=str(row["title"] or ""),
                ),
            )

    if topic_gap_queue and topic_gap_queue.exists():
        with topic_gap_queue.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                pid = str(raw.get("paper_id") or "").strip()
                if not pid:
                    continue
                try:
                    priority = float(raw.get("priority_score") or 0.0)
                except Exception:
                    priority = 0.0
                reasons = set(_loads_list(raw.get("reasons")))
                reasons.add("topic_gap_queue")
                _merge_seed(
                    seeds,
                    SeedPaper(
                        paper_id=pid,
                        priority_score=priority + 120.0,
                        reasons=reasons,
                        title=str(raw.get("title") or ""),
                    ),
                )
    return seeds


def _prepare_seed_temp_table(conn: sqlite3.Connection, seeds: dict[str, SeedPaper]) -> None:
    conn.execute("DROP TABLE IF EXISTS temp.v14b_cited_work_seed_papers")
    conn.execute(
        """
        CREATE TEMP TABLE v14b_cited_work_seed_papers (
            paper_id TEXT PRIMARY KEY,
            priority_score REAL,
            reasons_json TEXT,
            title TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO v14b_cited_work_seed_papers
            (paper_id, priority_score, reasons_json, title)
        VALUES (?, ?, ?, ?)
        """,
        [
            (
                seed.paper_id,
                seed.priority_score,
                json.dumps(sorted(seed.reasons), ensure_ascii=False),
                seed.title,
            )
            for seed in seeds.values()
        ],
    )


def _candidate_reference_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cols = table_columns(conn, "paper_references")
    required = {"citing_paper_id", "cited_paper_id_external", "cited_paper_id_internal"}
    if not required.issubset(cols):
        missing = sorted(required - cols)
        raise RuntimeError(f"paper_references table missing required columns: {missing}")
    provider_sql = "pr.cited_paper_id_provider" if "cited_paper_id_provider" in cols else "NULL AS cited_paper_id_provider"
    norm_sql = "pr.cited_paper_id_norm" if "cited_paper_id_norm" in cols else "NULL AS cited_paper_id_norm"
    return conn.execute(
        f"""
        SELECT pr.rowid,
               pr.citing_paper_id,
               pr.cited_paper_id_external,
               {provider_sql},
               {norm_sql},
               seed.priority_score AS citing_priority_score,
               seed.reasons_json AS citing_reasons_json,
               seed.title AS citing_title
        FROM paper_references pr
        JOIN temp.v14b_cited_work_seed_papers seed
          ON seed.paper_id = pr.citing_paper_id
        WHERE pr.cited_paper_id_external IS NOT NULL
          AND trim(pr.cited_paper_id_external) <> ''
          AND COALESCE(pr.cited_paper_id_internal, '') = ''
        ORDER BY seed.priority_score DESC, pr.rowid
        """
    ).fetchall()


def collect_targets(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    *,
    topic_gap_queue: Path | None,
) -> tuple[dict[tuple[str, str], BackfillTarget], dict[str, Any]]:
    seeds = load_priority_seed_papers(conn_v14, topic_gap_queue=topic_gap_queue)
    if not seeds:
        return {}, {
            "seed_papers": 0,
            "reference_rows_scanned": 0,
            "no_local_match_refs": 0,
            "excluded_status_counts": {},
        }

    id_maps = build_paper_id_maps(conn_main)
    attempts = _load_backfill_attempts(conn_main)
    _prepare_seed_temp_table(conn_main, seeds)
    rows = _candidate_reference_rows(conn_main)
    targets: dict[tuple[str, str], BackfillTarget] = {}
    status_counts = Counter()
    provider_counts = Counter()
    seen_citing_target: set[tuple[str, str, str]] = set()

    for row in rows:
        candidate = evaluate_reference(row, id_maps)
        status_counts[candidate.status] += 1
        if candidate.status != "no_local_match":
            continue
        if candidate.provider not in PROVIDERS or not candidate.norm:
            continue
        provider = str(candidate.provider)
        norm = str(candidate.norm)
        key = (provider, norm)
        citing_id = str(row["citing_paper_id"] or "")
        dedupe_key = (citing_id, provider, norm)
        if dedupe_key in seen_citing_target:
            continue
        seen_citing_target.add(dedupe_key)
        seed_reasons = set(_loads_list(row["citing_reasons_json"]))
        try:
            seed_priority = float(row["citing_priority_score"] or 0.0)
        except Exception:
            seed_priority = 0.0
        provider_boost = PROVIDER_BOOSTS.get(provider, 0.0)
        score = seed_priority + provider_boost + _reason_boost(seed_reasons)
        target = targets.get(key)
        if target is None:
            target = BackfillTarget(
                provider=provider,
                norm=norm,
                external_sample=str(candidate.cited_paper_id_external or ""),
                provider_boost=provider_boost,
            )
            attempt = attempts.get(key) or {}
            target.last_backfill_status = str(attempt.get("status") or "")
            target.last_backfill_error = str(attempt.get("error") or "")
            target.last_backfill_attempted_at = str(attempt.get("attempted_at") or "")
            targets[key] = target
        target.citing_scores[citing_id] = max(target.citing_scores.get(citing_id, 0.0), score)
        title = str(row["citing_title"] or "")
        if title and citing_id not in target.citing_titles:
            target.citing_titles[citing_id] = title
        target.reasons.update(seed_reasons)
        target.categories.update(_reason_category(reason) for reason in seed_reasons)
        provider_counts[provider] += 1

    summary = {
        "seed_papers": len(seeds),
        "reference_rows_scanned": len(rows),
        "no_local_match_refs": int(status_counts.get("no_local_match") or 0),
        "excluded_status_counts": {
            status: count
            for status, count in sorted(status_counts.items())
            if status != "no_local_match"
        },
        "provider_reference_counts": dict(sorted(provider_counts.items())),
        "attempt_feedback_counts": dict(Counter(
            str(target.last_backfill_status)
            for target in targets.values()
            if target.last_backfill_status
        )),
    }
    return targets, summary


def rows_from_targets(targets: dict[tuple[str, str], BackfillTarget], *, limit: int) -> list[dict[str, Any]]:
    sorted_targets = sorted(
        targets.values(),
        key=lambda target: (-target.priority_score(), -len(target.citing_scores), target.provider, target.norm),
    )
    rows: list[dict[str, Any]] = []
    for rank, target in enumerate(sorted_targets[:limit], start=1):
        citing_sorted = sorted(target.citing_scores.items(), key=lambda item: (-item[1], item[0]))
        top_citing_ids = [pid for pid, _score in citing_sorted[:8]]
        top_titles = [target.citing_titles.get(pid, "") for pid in top_citing_ids if target.citing_titles.get(pid)]
        provider_cols = _provider_columns(target.provider, target.norm)
        rows.append(
            {
                "rank": rank,
                "priority_score": target.priority_score(),
                "raw_priority_score": target.raw_priority_score(),
                "provider": target.provider,
                "normalized_id": target.norm,
                **provider_cols,
                "external_id_sample": _clean_cell(target.external_sample),
                "citing_paper_count": len(target.citing_scores),
                "high_value_categories": ";".join(sorted(target.categories)),
                "evidence_gap_reasons": ";".join(_gap_reasons(target.reasons)[:16]),
                "top_citing_papers": ";".join(top_citing_ids),
                "top_citing_titles": ";".join(_clean_cell(title) for title in top_titles[:8]),
                "provider_backfill_strategy": _provider_strategy(target.provider),
                "last_backfill_status": target.last_backfill_status,
                "last_backfill_attempted_at": target.last_backfill_attempted_at,
                "backfill_attempt_penalty": target.attempt_penalty(),
                "claim_scope": "evidence_frontfill_task",
                "evidence_grade": "missing_local_cited_work",
                "uncertainty_reasons_json": json.dumps(
                    [
                        "cited work is referenced by high-value local papers but is missing from the local corpus",
                        "backfill target is an evidence acquisition task, not a scientific conclusion",
                        "exact provider ID still needs metadata ingestion before it can support citation evolution claims",
                    ],
                    ensure_ascii=False,
                ),
            }
        )
    return rows


def write_outputs(
    *,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    out_dir: Path,
    queue_path: Path,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "cited_work_backfill_queue.json"
    md_path = out_dir / "cited_work_backfill_queue.md"

    with queue_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=QUEUE_FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in QUEUE_FIELDNAMES})

    provider_counts = Counter(str(row["provider"]) for row in rows)
    payload = {
        "generated_at": summary["generated_at"],
        "queue_rows": len(rows),
        "summary": summary,
        "provider_counts": dict(sorted(provider_counts.items())),
        "top_targets": rows[:50],
        "paths": {
            "queue": str(queue_path),
            "json": str(json_path),
            "markdown": str(md_path),
        },
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# V14B Cited Work Backfill Queue",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- seed papers: {int(summary.get('seed_papers') or 0):,}",
        f"- high-value reference rows scanned: {int(summary.get('reference_rows_scanned') or 0):,}",
        f"- no-local-match refs from seeds: {int(summary.get('no_local_match_refs') or 0):,}",
        f"- queued exact provider-ID targets: {len(rows):,}",
        "",
        "## Provider Mix",
        "",
        "| provider | queued targets |",
        "| --- | ---: |",
    ]
    for provider, count in sorted(provider_counts.items()):
        lines.append(f"| {provider} | {count:,} |")
    excluded = summary.get("excluded_status_counts") or {}
    if excluded:
        lines.extend(["", "## Excluded Local States", "", "| status | references |", "| --- | ---: |"])
        for status, count in sorted(excluded.items()):
            lines.append(f"| {status} | {int(count):,} |")
    attempt_feedback = summary.get("attempt_feedback_counts") or {}
    if attempt_feedback:
        lines.extend(["", "## Prior Backfill Attempts", "", "| last status | targets still queued |", "| --- | ---: |"])
        for status, count in sorted(attempt_feedback.items()):
            lines.append(f"| {status} | {int(count):,} |")
    lines.extend(
        [
            "",
            "## Top Targets",
            "",
            "| rank | provider | normalized_id | score | penalty | last status | citing papers | categories |",
            "| ---: | --- | --- | ---: | ---: | --- | ---: | --- |",
        ]
    )
    for row in rows[:30]:
        lines.append(
            f"| {row['rank']} | {row['provider']} | `{row['normalized_id']}` | "
            f"{float(row['priority_score']):.2f} | {float(row.get('backfill_attempt_penalty') or 0.0):.2f} | "
            f"{row.get('last_backfill_status') or ''} | {int(row['citing_paper_count'])} | "
            f"{_clean_cell(row['high_value_categories'])} |"
        )
    lines.extend(
        [
            "",
            "## Product Interpretation",
            "",
            "This queue is an evidence-acquisition worklist.  Processing it can raise linked-reference coverage "
            "after exact relinking, but queued targets do not themselves prove branch evolution, main-path causality, "
            "or Claim Card conclusions.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload["paths"]


def run_queue(
    *,
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    out_dir: Path = Path("reports/v14b_pilot"),
    queue_path: Path = Path("data/v14b/cited_work_backfill_queue.csv"),
    topic_gap_queue: Path | None = Path("data/v14b/topic_evidence_gap_delta_queue.csv"),
    limit: int = 2000,
) -> dict[str, Any]:
    conn_main = sqlite3.connect(str(db_main), timeout=30)
    conn_main.row_factory = sqlite3.Row
    conn_main.execute("PRAGMA busy_timeout=30000")
    conn_v14 = sqlite3.connect(str(db_v14), timeout=30)
    conn_v14.row_factory = sqlite3.Row
    try:
        targets, summary = collect_targets(
            conn_main,
            conn_v14,
            topic_gap_queue=topic_gap_queue,
        )
        summary = {"generated_at": utc_now(), **summary}
        rows = rows_from_targets(targets, limit=limit)
        paths = write_outputs(rows=rows, summary=summary, out_dir=out_dir, queue_path=queue_path)
        provider_counts = Counter(str(row["provider"]) for row in rows)
        return {
            "generated_at": summary["generated_at"],
            "queue_rows": len(rows),
            "summary": summary,
            "provider_counts": dict(sorted(provider_counts.items())),
            "top_targets": rows[:20],
            "paths": paths,
        }
    finally:
        conn_main.close()
        conn_v14.close()


def load_cited_work_backfill_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "path": str(path)}
    provider_counts: Counter[str] = Counter()
    top_targets: list[dict[str, Any]] = []
    rows = 0
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                rows += 1
                provider = str(raw.get("provider") or "unknown")
                provider_counts[provider] += 1
                if len(top_targets) < 10:
                    top_targets.append(
                        {
                            "rank": raw.get("rank"),
                            "provider": raw.get("provider"),
                            "normalized_id": raw.get("normalized_id"),
                            "priority_score": raw.get("priority_score"),
                            "citing_paper_count": raw.get("citing_paper_count"),
                            "claim_scope": raw.get("claim_scope"),
                            "evidence_grade": raw.get("evidence_grade"),
                        }
                    )
    except Exception as exc:
        return {"available": False, "path": str(path), "reason": str(exc)}
    return {
        "available": True,
        "path": str(path),
        "status": "ready" if rows else "empty",
        "queue_rows": rows,
        "provider_counts": dict(sorted(provider_counts.items())),
        "top_targets": top_targets,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build a high-value exact-ID cited-work backfill queue.")
    parser.add_argument("--db", type=Path, default=DB_MAIN)
    parser.add_argument("--db-v14", type=Path, default=DB_V14)
    parser.add_argument("--out-dir", type=Path, default=Path("reports/v14b_pilot"))
    parser.add_argument("--queue", type=Path, default=Path("data/v14b/cited_work_backfill_queue.csv"))
    parser.add_argument("--topic-gap-queue", type=Path, default=Path("data/v14b/topic_evidence_gap_delta_queue.csv"))
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    setup_logging("cited_work_backfill_queue", level=getattr(logging, str(args.log_level).upper()))
    result = run_queue(
        db_main=args.db,
        db_v14=args.db_v14,
        out_dir=args.out_dir,
        queue_path=args.queue,
        topic_gap_queue=args.topic_gap_queue,
        limit=args.limit,
    )
    print(jdumps({"queue_rows": result["queue_rows"], "provider_counts": result["provider_counts"], "paths": result["paths"]}))


if __name__ == "__main__":
    main()
