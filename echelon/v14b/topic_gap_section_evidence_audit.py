"""Triage section-evidence blockers for benchmark topic gaps.

The multi-topic regression queue is not just a work list.  It is the evidence
debt that prevents Topic Dossiers, bottleneck lineage, and Claim Cards from
being promoted as decision-grade.  This audit classifies each queued paper into
the smallest next action instead of hiding every miss behind a generic
"section evidence missing" label.
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

from echelon.v14b.config import DB_MAIN, REPORT_DIR
from echelon.v14b.evidence_contracts import (
    PRIMARY_SECTION_NAMES,
    SECTION_PARSER_CONTRACT_VERSION,
    is_decision_section,
    normalize_section_key,
    section_provenance_strength,
)
from echelon.v14b.utils import add_common_args, setup_logging

DECISION_SECTION_MIN_CHARS = 80
PROMOTION_THRESHOLD = 0.70


def _loads(raw: Any, default: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not raw:
        return default
    try:
        parsed = json.loads(str(raw))
    except Exception:
        return default
    return parsed


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _chunks(values: list[str], size: int = 800) -> list[list[str]]:
    return [values[idx:idx + size] for idx in range(0, len(values), size)]


def _truthy(raw: Any) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _split_reasons(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item or "").strip()]
    return [part.strip() for part in str(raw or "").split("|") if part.strip()]


def _topic_gap_tags(reasons: list[str]) -> tuple[list[str], list[str]]:
    topics: set[str] = set()
    gap_types: set[str] = set()
    for reason in reasons:
        if reason.startswith("topic_gap:"):
            parts = reason.split(":")
            if len(parts) >= 2 and parts[1]:
                topics.add(parts[1])
            if len(parts) >= 3 and parts[2]:
                gap_types.add(parts[2])
        elif reason.startswith("topic:"):
            topic = reason.split(":", 1)[1].strip()
            if topic:
                topics.add(topic)
        elif reason.startswith("topic_gap_"):
            gap_types.add(reason)
    return sorted(topics), sorted(gap_types)


def _arxiv_pdf_url(raw: Any) -> str:
    arxiv_id = str(raw or "").strip()
    if not arxiv_id:
        return ""
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"


def _load_queue_rows(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        rows: list[dict[str, Any]] = []
        if "candidate_paper_ids" in fieldnames and "paper_id" not in fieldnames:
            for raw in reader:
                ids = [
                    item.strip()
                    for item in str(raw.get("candidate_paper_ids") or "").replace(",", ";").split(";")
                    if item.strip()
                ]
                for pid in ids:
                    rows.append(
                        {
                            "paper_id": pid,
                            "priority_score": raw.get("priority") or "",
                            "reasons": "|".join(
                                part
                                for part in (
                                    f"topic:{raw.get('topic') or ''}",
                                    f"topic_gap:{raw.get('topic') or ''}:{raw.get('gap_type') or ''}",
                                    f"bottleneck:{raw.get('bottleneck') or ''}",
                                )
                                if not part.endswith(":")
                            ),
                            "source_url": "",
                            "title": "",
                            "eligible_pdf": "",
                        }
                    )
        else:
            rows = [dict(raw) for raw in reader if str(raw.get("paper_id") or "").strip()]

    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        pid = str(row.get("paper_id") or "").strip()
        if not pid:
            continue
        reasons = _split_reasons(row.get("reasons"))
        if pid not in merged:
            merged[pid] = dict(row)
            merged[pid]["paper_id"] = pid
            merged[pid]["reasons"] = reasons
            continue
        existing = merged[pid]
        existing["reasons"] = sorted(set(_split_reasons(existing.get("reasons"))).union(reasons))
        for key in ("title", "source_url", "doi", "arxiv_id", "openalex_id", "s2_paper_id"):
            if not existing.get(key) and row.get(key):
                existing[key] = row.get(key)
        try:
            existing["priority_score"] = max(
                float(existing.get("priority_score") or 0),
                float(row.get("priority_score") or 0),
            )
        except (TypeError, ValueError):
            pass

    out = list(merged.values())
    out.sort(key=lambda r: (-float(r.get("priority_score") or 0), r["paper_id"]))
    return out[:limit] if limit else out


def _paper_metadata(conn: sqlite3.Connection, paper_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not paper_ids or not _table_exists(conn, "papers"):
        return {}
    cols = _cols(conn, "papers")
    requested = (
        "id",
        "title",
        "publication_year",
        "publication_date",
        "arxiv_id",
        "doi",
        "openalex_id",
        "s2_paper_id",
        "cited_by_count",
    )
    select = [col if col in cols else f"NULL AS {col}" for col in requested]
    out: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(paper_ids):
        ph = ",".join("?" for _ in chunk)
        for row in conn.execute(
            f"SELECT {', '.join(select)} FROM papers WHERE id IN ({ph})",
            chunk,
        ).fetchall():
            payload = dict(row)
            out[str(payload["id"])] = payload
    return out


def _latest_attempts(conn: sqlite3.Connection, paper_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not paper_ids or not _table_exists(conn, "section_ingest_attempts"):
        return {}
    cols = _cols(conn, "section_ingest_attempts")
    wanted = (
        "attempt_id",
        "paper_id",
        "attempt_ts",
        "outcome",
        "source_url",
        "detail",
        "inserted_sections",
        "primary_sections",
        "candidate_file",
        "parser_name",
        "parser_contract_version",
    )
    select = [col if col in cols else f"NULL AS {col}" for col in wanted]
    out: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(paper_ids):
        ph = ",".join("?" for _ in chunk)
        for row in conn.execute(
            f"""
            SELECT * FROM (
                SELECT {', '.join(select)},
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
        ).fetchall():
            out[str(row["paper_id"])] = dict(row)
    return out


def _section_rows(conn: sqlite3.Connection, paper_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not paper_ids or not _table_exists(conn, "paper_sections"):
        return {}
    cols = _cols(conn, "paper_sections")
    wanted = (
        "paper_id",
        "section_name",
        "section_text",
        "parser_name",
        "source_url",
        "section_meta_json",
    )
    select = [col if col in cols else f"NULL AS {col}" for col in wanted]
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in _chunks(paper_ids):
        ph = ",".join("?" for _ in chunk)
        for row in conn.execute(
            f"SELECT {', '.join(select)} FROM paper_sections WHERE paper_id IN ({ph})",
            chunk,
        ).fetchall():
            meta = _loads(row["section_meta_json"], {})
            strategies = meta.get("extraction_strategies") if isinstance(meta, dict) else []
            section = {
                "paper_id": str(row["paper_id"]),
                "section_name": normalize_section_key(row["section_name"]),
                "section_chars": len(str(row["section_text"] or "").strip()),
                "parser_name": row["parser_name"] or "",
                "source_url": row["source_url"] or "",
                "parser_contract_version": (meta or {}).get("parser_contract_version")
                or "legacy_unknown_contract",
                "extraction_strategies": strategies or [],
                "evidence_grade": (meta or {}).get("evidence_grade") or "",
            }
            out[section["paper_id"]].append(section)
    return out


def _summarize_sections(sections: list[dict[str, Any]]) -> dict[str, Any]:
    primary = [
        s
        for s in sections
        if is_decision_section(s.get("section_name"))
        and int(s.get("section_chars") or 0) >= DECISION_SECTION_MIN_CHARS
    ]
    current = [
        s
        for s in primary
        if s.get("parser_contract_version") == SECTION_PARSER_CONTRACT_VERSION
    ]
    decision_grade = [
        s for s in current if section_provenance_strength(s) in {"strong", "moderate"}
    ]
    stale = [s for s in primary if s not in current]
    return {
        "primary_section_rows": len(primary),
        "current_contract_primary_rows": len(current),
        "decision_grade_primary_rows": len(decision_grade),
        "stale_primary_rows": len(stale),
        "section_names": sorted({str(s.get("section_name")) for s in primary}),
        "current_section_names": sorted({str(s.get("section_name")) for s in current}),
        "decision_grade_section_names": sorted({str(s.get("section_name")) for s in decision_grade}),
        "parser_contract_versions": dict(Counter(str(s.get("parser_contract_version")) for s in primary)),
        "parser_names": dict(Counter(str(s.get("parser_name") or "unknown") for s in primary)),
        "provenance_strengths": dict(Counter(section_provenance_strength(s) for s in primary)),
    }


def _classify(
    *,
    section_summary: dict[str, Any],
    attempt: dict[str, Any] | None,
    eligible_pdf: bool,
) -> tuple[str, str, str]:
    if int(section_summary.get("decision_grade_primary_rows") or 0) > 0:
        return (
            "decision_grade_current_contract",
            "covered",
            "eligible for evidence-gated Topic Dossier and Claim Card use.",
        )
    if int(section_summary.get("current_contract_primary_rows") or 0) > 0:
        return (
            "current_contract_weak",
            "candidate_pool_only",
            "manual or alternate-parser review before high-confidence promotion.",
        )
    if int(section_summary.get("primary_section_rows") or 0) > 0:
        return (
            "stale_parser_contract",
            "candidate_pool_only",
            "reparse with the current section parser contract before evidence promotion.",
        )
    outcome = str((attempt or {}).get("outcome") or "")
    contract = str((attempt or {}).get("parser_contract_version") or "")
    if outcome == "no_target_sections" and contract == SECTION_PARSER_CONTRACT_VERSION:
        return (
            "no_target_sections_after_current_parser",
            "candidate_pool_only",
            "inspect parser misses or alternate full text; keep abstract-only claims weak.",
        )
    if outcome == "no_target_sections":
        return (
            "no_target_sections_unknown_contract",
            "candidate_pool_only",
            "re-run with current parser contract before treating the miss as structural.",
        )
    if outcome in {"pdf_download_failed", "parse_timeout", "parser_exception"}:
        return (
            "retryable_pdf_failure",
            "candidate_pool_only",
            "retry with conservative timeout or alternate open-access URL.",
        )
    if outcome == "parse_no_blocks":
        return (
            "parser_failure",
            "candidate_pool_only",
            "try alternate PDF parser or mark as external-access evidence debt.",
        )
    if outcome == "no_pdf_url":
        return (
            "needs_access_link",
            "candidate_pool_only",
            "backfill DOI/OpenAlex/S2/arXiv access metadata before section ingest.",
        )
    if eligible_pdf:
        return (
            "unattempted_pdf_available",
            "candidate_pool_only",
            "run targeted topic-gap section ingest after active broad ingest is safe.",
        )
    return (
        "not_attempted_no_pdf",
        "candidate_pool_only",
        "recover an open-access PDF or external full-text source before section ingest.",
    )


def run_topic_gap_section_evidence_audit(
    *,
    db_main: Path = DB_MAIN,
    topic_gap_queue: Path = Path("data/v14b/topic_evidence_gap_delta_queue.csv"),
    out_dir: Path = REPORT_DIR,
    limit: int | None = None,
) -> dict[str, Any]:
    queue_rows = _load_queue_rows(topic_gap_queue, limit=limit)
    paper_ids = [str(row["paper_id"]) for row in queue_rows]
    audit_ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    conn = sqlite3.connect(str(db_main))
    conn.row_factory = sqlite3.Row
    try:
        metadata = _paper_metadata(conn, paper_ids)
        attempts = _latest_attempts(conn, paper_ids)
        section_map = _section_rows(conn, paper_ids)
    finally:
        conn.close()

    rows: list[dict[str, Any]] = []
    for queue_pos, queue_row in enumerate(queue_rows, start=1):
        pid = str(queue_row["paper_id"])
        meta = metadata.get(pid, {})
        attempt = attempts.get(pid)
        sections = section_map.get(pid, [])
        section_summary = _summarize_sections(sections)
        source_url = (
            str(queue_row.get("source_url") or "")
            or str((attempt or {}).get("source_url") or "")
            or _arxiv_pdf_url(queue_row.get("arxiv_id") or meta.get("arxiv_id"))
        )
        eligible_pdf = _truthy(queue_row.get("eligible_pdf")) or bool(source_url)
        failure_mode, promotion_policy, next_action = _classify(
            section_summary=section_summary,
            attempt=attempt,
            eligible_pdf=eligible_pdf,
        )
        reasons = _split_reasons(queue_row.get("reasons"))
        topics, gap_types = _topic_gap_tags(reasons)
        rows.append(
            {
                "queue_position": queue_pos,
                "paper_id": pid,
                "title": queue_row.get("title") or meta.get("title") or "",
                "publication_year": queue_row.get("publication_year")
                or meta.get("publication_year")
                or str(meta.get("publication_date") or "")[:4],
                "priority_score": float(queue_row.get("priority_score") or 0),
                "topics": topics,
                "gap_types": gap_types,
                "reasons": reasons,
                "failure_mode": failure_mode,
                "promotion_policy": promotion_policy,
                "next_action": next_action,
                "eligible_pdf": eligible_pdf,
                "source_url": source_url,
                "doi": queue_row.get("doi") or meta.get("doi") or "",
                "arxiv_id": queue_row.get("arxiv_id") or meta.get("arxiv_id") or "",
                "openalex_id": queue_row.get("openalex_id") or meta.get("openalex_id") or "",
                "s2_paper_id": queue_row.get("s2_paper_id") or meta.get("s2_paper_id") or "",
                "latest_attempt_outcome": (attempt or {}).get("outcome") or "",
                "latest_attempt_ts": (attempt or {}).get("attempt_ts") or "",
                "latest_attempt_contract": (attempt or {}).get("parser_contract_version") or "",
                "latest_attempt_parser": (attempt or {}).get("parser_name") or "",
                **section_summary,
            }
        )

    failure_counts = Counter(str(row["failure_mode"]) for row in rows)
    policy_counts = Counter(str(row["promotion_policy"]) for row in rows)
    decision_grade = int(failure_counts.get("decision_grade_current_contract") or 0)
    queue_papers = len(rows)
    decision_grade_rate = decision_grade / max(1, queue_papers)
    topic_summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        topics = row["topics"] or ["unknown"]
        for topic in topics:
            item = topic_summary.setdefault(
                topic,
                {
                    "papers": 0,
                    "decision_grade": 0,
                    "failure_mode_counts": Counter(),
                },
            )
            item["papers"] += 1
            if row["failure_mode"] == "decision_grade_current_contract":
                item["decision_grade"] += 1
            item["failure_mode_counts"][row["failure_mode"]] += 1
    for item in topic_summary.values():
        item["decision_grade_rate"] = item["decision_grade"] / max(1, item["papers"])
        item["failure_mode_counts"] = dict(item["failure_mode_counts"])

    next_actions = [
        {
            "failure_mode": mode,
            "papers": count,
            "action": next(
                row["next_action"] for row in rows if row["failure_mode"] == mode
            ),
        }
        for mode, count in failure_counts.most_common()
        if mode != "decision_grade_current_contract"
    ]
    summary = {
        "status": "pass" if decision_grade_rate >= PROMOTION_THRESHOLD or queue_papers == 0 else "fail",
        "queue_papers": queue_papers,
        "decision_grade_current_contract_papers": decision_grade,
        "decision_grade_current_contract_rate": decision_grade_rate,
        "promotion_threshold": PROMOTION_THRESHOLD,
        "failure_mode_counts": dict(failure_counts),
        "promotion_policy_counts": dict(policy_counts),
        "topic_summary": topic_summary,
        "next_actions": next_actions,
        "blocking_policy": (
            "Benchmark-topic papers below the decision-grade current-contract threshold "
            "must stay out of high-confidence Topic Dossier, bottleneck lineage, and Radar Claim Card promotion."
        ),
    }
    result = {
        "audit_ts": audit_ts,
        "db_main": str(db_main),
        "topic_gap_queue": str(topic_gap_queue),
        "section_parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
        "primary_section_names": list(PRIMARY_SECTION_NAMES),
        "decision_section_min_chars": DECISION_SECTION_MIN_CHARS,
        "summary": summary,
        "rows": rows,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "topic_gap_section_evidence_audit.json"
    md_path = out_dir / "topic_gap_section_evidence_audit.md"
    csv_path = out_dir / "topic_gap_section_evidence_audit.csv"
    result["outputs"] = {
        "json": str(json_path),
        "markdown": str(md_path),
        "csv": str(csv_path),
    }
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(csv_path, rows)
    md_path.write_text(_render_markdown(result), encoding="utf-8")
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "queue_position",
        "paper_id",
        "title",
        "publication_year",
        "priority_score",
        "topics",
        "gap_types",
        "failure_mode",
        "promotion_policy",
        "next_action",
        "eligible_pdf",
        "latest_attempt_outcome",
        "latest_attempt_contract",
        "primary_section_rows",
        "current_contract_primary_rows",
        "decision_grade_primary_rows",
        "stale_primary_rows",
        "section_names",
        "source_url",
        "doi",
        "arxiv_id",
        "openalex_id",
        "s2_paper_id",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            payload = {}
            for key in fieldnames:
                value = row.get(key, "")
                if isinstance(value, list):
                    value = "|".join(str(item) for item in value)
                elif isinstance(value, dict):
                    value = json.dumps(value, ensure_ascii=False, sort_keys=True)
                payload[key] = value
            writer.writerow(payload)


def _render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    rows = result.get("rows") or []
    lines = [
        "# Topic-Gap Section Evidence Audit",
        "",
        f"- audit_ts: `{result['audit_ts']}`",
        f"- queue: `{result['topic_gap_queue']}`",
        f"- parser_contract: `{result['section_parser_contract_version']}`",
        f"- status: `{summary['status']}`",
        f"- decision-grade current-contract coverage: "
        f"`{summary['decision_grade_current_contract_papers']}/{summary['queue_papers']}` "
        f"({summary['decision_grade_current_contract_rate'] * 100:.1f}%)",
        "",
        "## Failure Modes",
        "",
        "| failure_mode | papers |",
        "|---|---:|",
    ]
    for mode, count in Counter(summary["failure_mode_counts"]).most_common():
        lines.append(f"| {mode} | {count:,} |")
    lines.extend(["", "## Next Actions", "", "| failure_mode | papers | action |", "|---|---:|---|"])
    for action in summary["next_actions"]:
        lines.append(
            f"| {action['failure_mode']} | {int(action['papers']):,} | {action['action']} |"
        )
    lines.extend(["", "## Topic Coverage", "", "| topic | papers | decision-grade | rate | top failure modes |", "|---|---:|---:|---:|---|"])
    for topic, item in sorted(summary["topic_summary"].items()):
        counts = Counter(item["failure_mode_counts"])
        top = ", ".join(f"{mode}:{count}" for mode, count in counts.most_common(3))
        lines.append(
            f"| {topic} | {int(item['papers']):,} | {int(item['decision_grade']):,} | "
            f"{float(item['decision_grade_rate']) * 100:.1f}% | {top} |"
        )
    lines.extend(
        [
            "",
            "## Queued Papers",
            "",
            "| pos | paper_id | topics | failure_mode | latest_attempt | title |",
            "|---:|---|---|---|---|---|",
        ]
    )
    for row in rows[:50]:
        topics = ", ".join(str(item) for item in row.get("topics") or ["unknown"])
        lines.append(
            f"| {int(row.get('queue_position') or 0)} | `{_md_cell(row.get('paper_id'))}` | "
            f"{_md_cell(topics)} | `{_md_cell(row.get('failure_mode'))}` | "
            f"`{_md_cell(row.get('latest_attempt_outcome') or 'not_attempted')}` | "
            f"{_md_cell(row.get('title'))} |"
        )
    lines.extend(
        [
            "",
            "## Promotion Policy",
            "",
            summary["blocking_policy"],
        ]
    )
    return "\n".join(lines) + "\n"


def _md_cell(raw: Any) -> str:
    return " ".join(str(raw or "").replace("|", ";").split())


def load_topic_gap_section_triage_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "reason": "unreadable", "path": str(path)}
    summary = loaded.get("summary") if isinstance(loaded, dict) else {}
    if not isinstance(summary, dict):
        return {"available": False, "reason": "missing_summary", "path": str(path)}
    next_actions = summary.get("next_actions") or []
    first_action = ""
    if isinstance(next_actions, list) and next_actions:
        first = next_actions[0] if isinstance(next_actions[0], dict) else {}
        first_action = str(first.get("action") or "")
    return {
        "available": True,
        "path": str(path),
        "status": str(summary.get("status") or "unknown"),
        "queue_papers": int(summary.get("queue_papers") or 0),
        "decision_grade_current_contract_papers": int(
            summary.get("decision_grade_current_contract_papers") or 0
        ),
        "decision_grade_current_contract_rate": float(
            summary.get("decision_grade_current_contract_rate") or 0.0
        ),
        "failure_mode_counts": summary.get("failure_mode_counts") or {},
        "promotion_policy_counts": summary.get("promotion_policy_counts") or {},
        "topic_summary": summary.get("topic_summary") or {},
        "next_action": first_action,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Audit section-evidence blockers in the multi-topic gap queue."
    )
    add_common_args(parser)
    parser.add_argument(
        "--topic-gap-queue",
        type=Path,
        default=Path("data/v14b/topic_evidence_gap_delta_queue.csv"),
    )
    parser.add_argument("--out-dir", type=Path, default=REPORT_DIR)
    args = parser.parse_args(argv)
    setup_logging(
        "topic_gap_section_evidence_audit",
        level=getattr(logging, args.log_level),
    )
    result = run_topic_gap_section_evidence_audit(
        db_main=Path(args.db) if args.db else DB_MAIN,
        topic_gap_queue=args.topic_gap_queue,
        out_dir=args.out_dir,
        limit=args.limit,
    )
    print(json.dumps({"summary": result["summary"], "outputs": result["outputs"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
