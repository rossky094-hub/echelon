"""Evidence-bone audit for Echelon V14B.

This audit turns the vague statement "linked refs and section evidence are too
thin" into actionable failure taxonomies.  It is intentionally read-only for
the library and pilot databases, so it can run while section/OpenAlex frontfill
continues.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, DB_V14
from echelon.v14b.direction_readiness_audit import PRIMARY_SECTION_NAMES, scalar, table_exists
from echelon.v14b.evidence_contracts import section_provenance_strength
from echelon.v14b.step5s_section_ingest import SECTION_PARSER_CONTRACT_VERSION


REFERENCE_KIND_SQL = """
CASE
  WHEN COALESCE(cited_paper_id_provider, '') IN ('doi', 'DOI') OR lower(COALESCE(cited_paper_id_external, '')) LIKE '10.%'
    THEN 'doi_unlinked'
  WHEN COALESCE(cited_paper_id_provider, '') IN ('openalex', 'OpenAlex') OR COALESCE(cited_paper_id_norm, '') LIKE 'W%'
       OR lower(COALESCE(cited_paper_id_external, '')) LIKE '%openalex.org/w%'
    THEN 'openalex_unlinked'
  WHEN COALESCE(cited_paper_id_provider, '') IN ('arxiv', 'arXiv') OR COALESCE(cited_paper_id_norm, '') GLOB '[0-9][0-9][0-9][0-9].*'
       OR lower(COALESCE(cited_paper_id_external, '')) LIKE '%arxiv%'
    THEN 'arxiv_unlinked'
  WHEN lower(COALESCE(cited_paper_id_provider, '')) IN ('s2', 'semantic_scholar', 'semanticscholar')
    THEN 's2_unlinked'
  WHEN COALESCE(cited_paper_id_norm, '') = ''
    THEN 'missing_normalized_id'
  WHEN length(COALESCE(cited_paper_id_external, '')) < 12
    THEN 'weak_reference_string'
  ELSE 'other_unlinked'
END
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def pct(n: int | float, d: int | float) -> float:
    return 0.0 if not d else float(n) / float(d)


def pct_str(value: float) -> str:
    return f"{value * 100:.1f}%"


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def infer_current_primary_section(row: dict[str, Any]) -> int:
    raw = row.get("current_primary_section")
    if raw not in (None, ""):
        return int(raw or 0)
    coverage = row.get("coverage_json")
    if not coverage:
        return 0
    try:
        payload = json.loads(str(coverage))
    except (TypeError, ValueError):
        return 0
    try:
        rate = float(payload.get("current_primary_section_rate") or 0.0)
        total = int(row.get("total") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(total, int(round(rate * total))))


def infer_decision_grade_primary_section(row: dict[str, Any]) -> int:
    raw = row.get("decision_grade_primary_section")
    if raw not in (None, ""):
        return int(raw or 0)
    coverage = row.get("coverage_json")
    if not coverage:
        return 0
    try:
        payload = json.loads(str(coverage))
    except (TypeError, ValueError):
        return 0
    try:
        rate = float(payload.get("decision_grade_primary_section_rate") or 0.0)
        total = int(row.get("total") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(total, int(round(rate * total))))


def reference_taxonomy(conn: sqlite3.Connection, *, sample_limit: int = 8) -> dict[str, Any]:
    if not table_exists(conn, "paper_references"):
        return {"available": False, "reason": "paper_references table missing"}
    total = int(scalar(conn, "SELECT COUNT(*) FROM paper_references") or 0)
    linked = int(
        scalar(
            conn,
            "SELECT COUNT(*) FROM paper_references WHERE COALESCE(cited_paper_id_internal, '') <> ''",
        )
        or 0
    )
    grouped = _rows(
        conn,
        f"""
        SELECT {REFERENCE_KIND_SQL} AS kind, COUNT(*) AS n
        FROM paper_references
        WHERE COALESCE(cited_paper_id_internal, '') = ''
        GROUP BY kind
        ORDER BY n DESC
        """,
    )
    samples: dict[str, list[dict[str, Any]]] = {}
    for row in grouped:
        kind = str(row["kind"])
        samples[kind] = _rows(
            conn,
            f"""
            SELECT citing_paper_id, cited_paper_id_external, cited_paper_id_provider, cited_paper_id_norm
            FROM paper_references
            WHERE COALESCE(cited_paper_id_internal, '') = ''
              AND {REFERENCE_KIND_SQL} = ?
            LIMIT ?
            """,
            (kind, sample_limit),
        )
    return {
        "available": True,
        "refs_total": total,
        "linked_refs": linked,
        "unlinked_refs": total - linked,
        "linked_ref_rate": pct(linked, total),
        "taxonomy": grouped,
        "samples": samples,
        "next_actions": _reference_next_actions(grouped),
    }


def _reference_next_actions(grouped: list[dict[str, Any]]) -> list[str]:
    counts = {str(r["kind"]): int(r["n"] or 0) for r in grouped}
    actions: list[str] = []
    if counts.get("doi_unlinked", 0):
        actions.append("Run DOI-normalized relinking before adding more crawlers; DOI refs should be exact local joins.")
    if counts.get("openalex_unlinked", 0):
        actions.append("Continue OpenAlex W backfill and relink W IDs after each successful batch.")
    if counts.get("arxiv_unlinked", 0):
        actions.append("Normalize arXiv version/category variants, then relink against arxiv_id.")
    if counts.get("missing_normalized_id", 0) or counts.get("weak_reference_string", 0):
        actions.append("Add title/year reference parsing only for high-value unresolved refs; do not fuzzy-link all refs blindly.")
    if counts.get("s2_unlinked", 0):
        actions.append("Keep S2 IDs separate from OpenAlex IDs and relink through s2_paper_id.")
    return actions


def section_coverage(conn_main: sqlite3.Connection, conn_v14: sqlite3.Connection) -> dict[str, Any]:
    if not table_exists(conn_main, "paper_sections"):
        return {"available": False, "reason": "paper_sections table missing"}
    ph = ",".join("?" for _ in PRIMARY_SECTION_NAMES)
    rows = int(scalar(conn_main, "SELECT COUNT(*) FROM paper_sections") or 0)
    papers = int(scalar(conn_main, "SELECT COUNT(DISTINCT paper_id) FROM paper_sections") or 0)
    primary = int(
        scalar(
            conn_main,
            f"""
            SELECT COUNT(DISTINCT paper_id)
            FROM paper_sections
            WHERE section_name IN ({ph})
              AND length(trim(section_text)) >= 80
            """,
            tuple(PRIMARY_SECTION_NAMES),
        )
        or 0
    )
    current_primary = 0
    decision_grade_primary = 0
    if "section_meta_json" in columns(conn_main, "paper_sections"):
        current_rows = conn_main.execute(
            f"""
            SELECT paper_id, section_name, section_meta_json
            FROM paper_sections
            WHERE section_name IN ({ph})
              AND length(trim(section_text)) >= 80
            """,
            tuple(PRIMARY_SECTION_NAMES),
        ).fetchall()
        current_ids = set()
        decision_grade_ids = set()
        for row in current_rows:
            try:
                payload = json.loads(str(row["section_meta_json"] or "{}"))
            except (TypeError, ValueError):
                payload = {}
            if payload.get("parser_contract_version") == SECTION_PARSER_CONTRACT_VERSION:
                paper_id = str(row["paper_id"])
                current_ids.add(paper_id)
                strength = section_provenance_strength(
                    {
                        "section_name": row["section_name"],
                        "extraction_strategies": payload.get("extraction_strategies"),
                        "evidence_grade": payload.get("evidence_grade"),
                        "parser_contract_version": payload.get("parser_contract_version"),
                    }
                )
                if strength in {"strong", "moderate"}:
                    decision_grade_ids.add(paper_id)
        current_primary = len(current_ids)
        decision_grade_primary = len(decision_grade_ids)
    section_name_rows = _rows(
        conn_main,
        """
        SELECT lower(section_name) AS section_name, COUNT(*) AS rows, COUNT(DISTINCT paper_id) AS papers
        FROM paper_sections
        GROUP BY lower(section_name)
        ORDER BY rows DESC
        LIMIT 20
        """,
    )
    latest_attempts = []
    attempt_totals = []
    if table_exists(conn_main, "section_ingest_attempts"):
        attempt_totals = _rows(
            conn_main,
            """
            SELECT outcome, COUNT(*) AS n
            FROM section_ingest_attempts
            GROUP BY outcome
            ORDER BY n DESC
            """,
        )
        latest_attempts = _rows(
            conn_main,
            """
            SELECT outcome, COUNT(*) AS n
            FROM (
                SELECT paper_id, outcome,
                       ROW_NUMBER() OVER (
                           PARTITION BY paper_id
                           ORDER BY attempt_ts DESC, attempt_id DESC
                       ) AS rn
                FROM section_ingest_attempts
            )
            WHERE rn = 1
            GROUP BY outcome
            ORDER BY n DESC
            """,
        )
    priority_summary = []
    priority_totals = {}
    if table_exists(conn_v14, "section_priority_summary"):
        latest = scalar(conn_v14, "SELECT MAX(audit_ts) FROM section_priority_summary")
        if latest:
            summary_cols = columns(conn_v14, "section_priority_summary")
            current_expr = (
                "current_primary_section"
                if "current_primary_section" in summary_cols
                else "NULL AS current_primary_section"
            )
            decision_expr = (
                "decision_grade_primary_section"
                if "decision_grade_primary_section" in summary_cols
                else "NULL AS decision_grade_primary_section"
            )
            coverage_expr = "coverage_json" if "coverage_json" in summary_cols else "NULL AS coverage_json"
            priority_summary = _rows(
                conn_v14,
                f"""
                SELECT category, total, in_top_n, any_section, primary_section,
                       {current_expr}, {decision_expr}, eligible_pdf, {coverage_expr}
                FROM section_priority_summary
                WHERE audit_ts = ?
                ORDER BY total DESC, category
                """,
                (latest,),
            )
            for row in priority_summary:
                row["current_primary_section"] = infer_current_primary_section(row)
                row["decision_grade_primary_section"] = infer_decision_grade_primary_section(row)
    if table_exists(conn_v14, "section_priority_papers"):
        paper_cols = columns(conn_v14, "section_priority_papers")
        current_missing_predicate = (
            "has_current_primary_section=0"
            if "has_current_primary_section" in paper_cols
            else "has_primary_section=0"
        )
        decision_grade_missing_predicate = (
            "has_decision_grade_primary_section=0"
            if "has_decision_grade_primary_section" in paper_cols
            else current_missing_predicate
        )
        priority_totals = {
            "high_value_papers": int(scalar(conn_v14, "SELECT COUNT(*) FROM section_priority_papers") or 0),
            "missing_primary_with_pdf": int(
                scalar(
                    conn_v14,
                    "SELECT COUNT(*) FROM section_priority_papers WHERE has_primary_section=0 AND eligible_pdf=1",
                )
                or 0
            ),
            "missing_current_primary_with_pdf": int(
                scalar(
                    conn_v14,
                    f"SELECT COUNT(*) FROM section_priority_papers WHERE {current_missing_predicate} AND eligible_pdf=1",
                )
                or 0
            ),
            "missing_decision_grade_primary_with_pdf": int(
                scalar(
                    conn_v14,
                    f"SELECT COUNT(*) FROM section_priority_papers WHERE {decision_grade_missing_predicate} AND eligible_pdf=1",
                )
                or 0
            ),
            "missing_primary_in_top_n": int(
                scalar(
                    conn_v14,
                    "SELECT COUNT(*) FROM section_priority_papers WHERE has_primary_section=0 AND eligible_pdf=1 AND in_top_n=1",
                )
                or 0
            ),
            "missing_current_primary_in_top_n": int(
                scalar(
                    conn_v14,
                    f"SELECT COUNT(*) FROM section_priority_papers WHERE {current_missing_predicate} AND eligible_pdf=1 AND in_top_n=1",
                )
                or 0
            ),
            "missing_decision_grade_primary_in_top_n": int(
                scalar(
                    conn_v14,
                    f"SELECT COUNT(*) FROM section_priority_papers WHERE {decision_grade_missing_predicate} AND eligible_pdf=1 AND in_top_n=1",
                )
                or 0
            ),
        }
    return {
        "available": True,
        "section_rows": rows,
        "section_papers": papers,
        "primary_section_papers": primary,
        "current_contract_primary_section_papers": current_primary,
        "decision_grade_primary_section_papers": decision_grade_primary,
        "section_name_distribution": section_name_rows,
        "attempt_totals": attempt_totals,
        "latest_attempt_outcomes": latest_attempts,
        "priority_totals": priority_totals,
        "priority_summary": priority_summary,
        "next_actions": _section_next_actions(priority_summary, priority_totals, latest_attempts),
    }


def _section_next_actions(
    summary: list[dict[str, Any]],
    totals: dict[str, Any],
    latest_attempts: list[dict[str, Any]] | None = None,
) -> list[str]:
    actions: list[str] = []
    missing_decision_grade = totals.get("missing_decision_grade_primary_with_pdf", totals.get("missing_current_primary_with_pdf", 0))
    if missing_decision_grade:
        actions.append(
            "After top12000 completes, run the delta/action queue for high-value papers missing decision-grade primary sections."
        )
    weak_categories = [
        str(row["category"])
        for row in summary
        if int(row.get("total") or 0) >= 10
        and pct(
            int(row.get("decision_grade_primary_section") if row.get("decision_grade_primary_section") is not None else row.get("current_primary_section") or 0),
            int(row.get("total") or 0),
        )
        < 0.20
    ]
    if weak_categories:
        actions.append("Prioritize decision-grade section evidence for weak high-value classes: " + ", ".join(weak_categories[:8]))
    attempt_counts = {str(r.get("outcome")): int(r.get("n") or 0) for r in (latest_attempts or [])}
    if attempt_counts.get("no_pdf_url", 0):
        actions.append("For no_pdf_url papers, synthesize access links and backfill OA PDF metadata before retrying section ingest.")
    if attempt_counts.get("pdf_download_failed", 0) or attempt_counts.get("parse_timeout", 0):
        actions.append("Retry only high-value retryable PDF failures with conservative concurrency; do not broaden to all PDFs.")
    if attempt_counts.get("no_target_sections", 0):
        actions.append("Mark no_target_sections papers as weak evidence unless alternate parser/Sci-Bot sections are available.")
    return actions


LOG_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pdf_graphics_warning", re.compile(r"Cannot set gray .* color", re.I)),
    ("timeout", re.compile(r"timeout|timed out", re.I)),
    ("download_failure", re.compile(r"download|http|connection|server disconnected|failed", re.I)),
    ("parser_exception", re.compile(r"traceback|exception|error", re.I)),
    ("low_yield_scan", re.compile(r"LOW_YIELD_SCAN", re.I)),
    ("section_evidence_soft_stall", re.compile(r"SECTION_EVIDENCE_SOFT_STALL", re.I)),
    ("hard_stall", re.compile(r"HARD_STALL", re.I)),
)


def section_log_taxonomy(log_paths: list[Path]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    progress = {"done": None, "total": None, "raw": ""}
    progress_re = re.compile(r"(?P<done>\d+)\s*/\s*(?P<total>\d+)")
    for path in log_paths:
        if not path.exists():
            continue
        for line in path.read_text(errors="ignore").splitlines():
            if "Step5s sections:" in line:
                m = progress_re.search(line)
                if m:
                    progress = {"done": int(m.group("done")), "total": int(m.group("total")), "raw": line[-260:]}
            for label, pattern in LOG_PATTERNS:
                if pattern.search(line):
                    counts[label] += 1
                    samples.setdefault(label, [])
                    if len(samples[label]) < 5:
                        samples[label].append(line[:300])
    return {
        "event_counts": dict(counts),
        "samples": samples,
        "progress": progress,
        "next_actions": _log_next_actions(counts),
    }


WATCHDOG_TS_RE = re.compile(r"\[(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\]")
WATCHDOG_COUNT_RE = re.compile(r"rows=(?P<rows>\d+)\s+papers=(?P<papers>\d+)")
WATCHDOG_PRIMARY_RE = re.compile(r"primary_section_papers=(?P<primary>\d+)")
WATCHDOG_DONE_RE = re.compile(r"done=(?P<done>\d+)/(?P<total>\d+)")


def _parse_ts(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def watchdog_history(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        return {"available": False}
    latest: dict[str, Any] | None = None
    last_evidence: dict[str, Any] | None = None
    records = 0
    for line in log_path.read_text(errors="ignore").splitlines():
        ts_m = WATCHDOG_TS_RE.search(line)
        count_m = WATCHDOG_COUNT_RE.search(line)
        if not ts_m or not count_m:
            continue
        primary_m = WATCHDOG_PRIMARY_RE.search(line)
        done_m = WATCHDOG_DONE_RE.search(line)
        records += 1
        rec = {
            "ts": ts_m.group("ts"),
            "ts_epoch": _parse_ts(ts_m.group("ts")),
            "rows": int(count_m.group("rows")),
            "papers": int(count_m.group("papers")),
            "primary_section_papers": int(primary_m.group("primary")) if primary_m else 0,
            "done": int(done_m.group("done")) if done_m else None,
            "total": int(done_m.group("total")) if done_m else None,
        }
        if latest is None or rec["rows"] != latest["rows"] or rec["papers"] != latest["papers"]:
            last_evidence = rec
        latest = rec
    if not latest:
        return {"available": False, "records": records}
    if last_evidence is None:
        last_evidence = latest
    no_evidence_elapsed_s = int(max(0, float(latest["ts_epoch"]) - float(last_evidence["ts_epoch"])))
    no_evidence_done_delta = 0
    if latest.get("done") is not None and last_evidence.get("done") is not None:
        no_evidence_done_delta = int(latest["done"]) - int(last_evidence["done"])
    return {
        "available": True,
        "records": records,
        "latest": latest,
        "last_evidence_growth": last_evidence,
        "no_evidence_elapsed_s": no_evidence_elapsed_s,
        "no_evidence_done_delta": max(0, no_evidence_done_delta),
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _max_int(*values: Any) -> int | None:
    parsed: list[int] = []
    for value in values:
        try:
            if value is not None:
                parsed.append(int(value))
        except Exception:
            continue
    return max(parsed) if parsed else None


def frontfill_health(
    sections: dict[str, Any],
    logs: dict[str, Any],
    state_file: Path,
    watchdog_history_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify whether frontfill is strengthening evidence, not just running.

    The value objective is decision-grade evidence.  A process that advances
    through PDFs but does not add primary sections should be visible as a
    product blocker even if the OS process is healthy.
    """
    state = _load_json(state_file)
    progress = logs.get("progress") or {}
    progress_done = progress.get("done")
    progress_total = progress.get("total")
    state_done = state.get("done")
    state_total = state.get("total")
    done = _max_int(state_done, progress_done)
    total = _max_int(state_total, progress_total)
    rows = max(int(state.get("rows") or 0), int(sections.get("section_rows") or 0))
    papers = max(int(state.get("papers") or 0), int(sections.get("section_papers") or 0))
    primary = max(
        int(state.get("primary_section_papers") or 0),
        int(sections.get("primary_section_papers") or 0),
    )
    no_evidence_delta = int(state.get("no_evidence_done_delta") or 0)
    no_evidence_elapsed_s = int(state.get("no_evidence_elapsed_s") or 0)
    low_yield_intervals = int(state.get("low_yield_intervals") or 0)
    history = watchdog_history_data or {}
    if history.get("available"):
        no_evidence_delta = max(no_evidence_delta, int(history.get("no_evidence_done_delta") or 0))
        no_evidence_elapsed_s = max(no_evidence_elapsed_s, int(history.get("no_evidence_elapsed_s") or 0))
        latest = history.get("latest") or {}
        done = _max_int(done, latest.get("done"))
        total = _max_int(total, latest.get("total"))
    event_counts = logs.get("event_counts") or {}
    soft_stall_events = int(event_counts.get("section_evidence_soft_stall") or 0)
    low_yield_events = int(event_counts.get("low_yield_scan") or 0)

    if soft_stall_events or low_yield_intervals >= 2 or no_evidence_elapsed_s >= 4 * 3600:
        status = "soft_stall"
    elif no_evidence_delta >= 200 or low_yield_events:
        status = "low_yield"
    elif primary < 8000:
        status = "insufficient_but_running"
    else:
        status = "evidence_gate_ready"

    recommendation = {
        "soft_stall": (
            "Do not wait for topN completion as if it were productive evidence growth. "
            "Keep the single live process conservative, but prepare/advance the high-value "
            "delta queue and classify no-PDF/no-target-section/timeouts before downstream claims."
        ),
        "low_yield": (
            "Treat the current candidate segment as low-yield evidence acquisition; prioritize "
            "main path, future endpoints, branch drivers, top keystone, and benchmark-topic papers."
        ),
        "insufficient_but_running": (
            "Continue section frontfill and keep all bottleneck/Claim Card conclusions scoped "
            "until the high-value primary-section budget is met."
        ),
        "evidence_gate_ready": (
            "Primary section evidence has crossed the configured gate; downstream Step5c/6/13 "
            "can be rerun from a stronger evidence base."
        ),
    }[status]

    return {
        "status": status,
        "done": done,
        "total": total,
        "state_done": state_done,
        "state_total": state_total,
        "progress_done": progress_done,
        "progress_total": progress_total,
        "rows": rows,
        "papers": papers,
        "primary_section_papers": primary,
        "no_evidence_done_delta": no_evidence_delta,
        "no_evidence_elapsed_s": no_evidence_elapsed_s,
        "low_yield_intervals": low_yield_intervals,
        "low_yield_events": low_yield_events,
        "soft_stall_events": soft_stall_events,
        "watchdog_history": history,
        "state_file": str(state_file),
        "source": state_file.stem.replace("_watchdog_state", ""),
        "recommendation": recommendation,
    }


def _log_next_actions(counts: Counter[str]) -> list[str]:
    actions: list[str] = []
    if counts.get("pdf_graphics_warning", 0) > 100:
        actions.append("Suppress or downgrade noisy PDF graphics warnings so true parser failures remain visible.")
    if counts.get("section_evidence_soft_stall", 0):
        actions.append("Section frontfill is in evidence soft-stall; prepare adaptive delta queue instead of passively waiting for topN.")
    if counts.get("low_yield_scan", 0):
        actions.append("Treat current low-yield section segment as evidence-budget issue; rely on delta queue handoff after topN.")
    if counts.get("timeout", 0) or counts.get("download_failure", 0):
        actions.append("Keep single-process section ingest and add retry classification before increasing concurrency.")
    return actions


def collect_audit(
    *,
    db_main: Path,
    db_v14: Path,
    section_log: Path,
    watchdog_log: Path,
    watchdog_state: Path,
    openalex_log: Path,
) -> dict[str, Any]:
    with connect(db_main) as conn_main, connect(db_v14) as conn_v14:
        refs = reference_taxonomy(conn_main)
        sections = section_coverage(conn_main, conn_v14)
    logs = section_log_taxonomy([section_log, watchdog_log, openalex_log])
    logs["source"] = {
        "section_log": str(section_log),
        "watchdog_log": str(watchdog_log),
        "watchdog_state": str(watchdog_state),
    }
    history = watchdog_history(watchdog_log)
    health = frontfill_health(sections, logs, watchdog_state, history)
    return {
        "generated_at": utc_now(),
        "reference_taxonomy": refs,
        "section_coverage": sections,
        "frontfill_log_taxonomy": logs,
        "frontfill_health": health,
        "product_interpretation": (
            "Evidence Bone remains the limiting factor if linked refs are below 30% "
            "or primary section evidence is below the high-value claim budget. "
            "The graph can guide inspection, but claims must remain scoped and uncertainty-labeled."
        ),
    }


def render_markdown(result: dict[str, Any]) -> str:
    refs = result["reference_taxonomy"]
    sections = result["section_coverage"]
    logs = result["frontfill_log_taxonomy"]
    health = result.get("frontfill_health") or {}
    lines = [
        "# V14B Evidence Bone Audit",
        "",
        f"- generated_at: `{result['generated_at']}`",
        "",
        "## Reference Linkage",
        "",
    ]
    if refs.get("available"):
        lines.extend(
            [
                f"- linked refs: {refs['linked_refs']:,} / {refs['refs_total']:,} ({pct_str(refs['linked_ref_rate'])})",
                f"- unlinked refs: {refs['unlinked_refs']:,}",
                "",
                "| unlinked kind | count |",
                "| --- | ---: |",
            ]
        )
        for row in refs["taxonomy"]:
            lines.append(f"| {row['kind']} | {int(row['n']):,} |")
    else:
        lines.append(f"- unavailable: {refs.get('reason')}")
    lines.extend(["", "## Section Evidence", ""])
    if sections.get("available"):
        lines.extend(
            [
                f"- section rows: {sections['section_rows']:,}",
                f"- section papers: {sections['section_papers']:,}",
                f"- primary section papers: {sections['primary_section_papers']:,}",
                f"- current parser-contract primary section papers: {sections.get('current_contract_primary_section_papers', 0):,}",
                f"- decision-grade primary section papers: {sections.get('decision_grade_primary_section_papers', 0):,}",
                "",
                "### High-Value Priority Coverage",
                "",
                "| category | total | in topN | any section | primary section | current parser primary | decision-grade primary | eligible PDF |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in sections.get("priority_summary") or []:
            lines.append(
                f"| {row['category']} | {int(row['total']):,} | {int(row['in_top_n']):,} | "
                f"{int(row['any_section']):,} | {int(row['primary_section']):,} | "
                f"{int(row.get('current_primary_section') or 0):,} | "
                f"{int(row.get('decision_grade_primary_section') or 0):,} | "
                f"{int(row['eligible_pdf']):,} |"
            )
        if sections.get("latest_attempt_outcomes"):
            lines.extend(
                [
                    "",
                    "### Latest Section Ingest Outcomes",
                    "",
                    "| outcome | papers |",
                    "| --- | ---: |",
                ]
            )
            for row in sections.get("latest_attempt_outcomes") or []:
                lines.append(f"| {row['outcome']} | {int(row['n']):,} |")
    else:
        lines.append(f"- unavailable: {sections.get('reason')}")
    lines.extend(["", "## Frontfill Log Signals", "", "| event | count |", "| --- | ---: |"])
    for key, value in sorted((logs.get("event_counts") or {}).items(), key=lambda kv: kv[1], reverse=True):
        lines.append(f"| {key} | {value:,} |")
    prog = logs.get("progress") or {}
    if prog.get("done"):
        source = (logs.get("source") or {}).get("section_log") or "unknown"
        lines.extend(["", f"- section progress: {prog.get('done')}/{prog.get('total')} ({source})"])
    lines.extend(
        [
            "",
            "## Frontfill Health",
            "",
            f"- status: `{health.get('status', 'unknown')}`",
            f"- source: `{health.get('source', 'unknown')}`",
            f"- progress: `{health.get('done')}/{health.get('total')}`",
            f"- rows / papers / primary papers: `{int(health.get('rows') or 0):,}` / `{int(health.get('papers') or 0):,}` / `{int(health.get('primary_section_papers') or 0):,}`",
            f"- candidates since last evidence growth: `{int(health.get('no_evidence_done_delta') or 0):,}`",
            f"- seconds since last evidence growth: `{int(health.get('no_evidence_elapsed_s') or 0):,}`",
            f"- recommendation: {health.get('recommendation', 'n/a')}",
        ]
    )
    lines.extend(["", "## Recommended Next Actions", ""])
    actions = []
    actions.extend(refs.get("next_actions") or [])
    actions.extend(sections.get("next_actions") or [])
    actions.extend(logs.get("next_actions") or [])
    if not actions:
        actions.append("No immediate evidence-bone action found; continue frontfill monitoring.")
    for action in actions:
        lines.append(f"- {action}")
    lines.extend(["", "## Product Interpretation", "", result["product_interpretation"]])
    return "\n".join(lines) + "\n"


def _default_frontfill_paths() -> tuple[Path, Path, Path]:
    candidates = [
        (
            Path("logs/v14b/step5s_section_delta.log"),
            Path("logs/v14b/section_delta_watchdog.log"),
            Path("logs/v14b/section_delta_watchdog_state.json"),
        ),
        (
            Path("logs/v14b/step5s_section_top12000.log"),
            Path("logs/v14b/section_top12000_watchdog.log"),
            Path("logs/v14b/section_top12000_watchdog_state.json"),
        ),
    ]
    existing = [paths for paths in candidates if any(path.exists() for path in paths)]
    if not existing:
        return candidates[1]

    def newest(paths: tuple[Path, Path, Path]) -> float:
        return max((path.stat().st_mtime for path in paths if path.exists()), default=0.0)

    return max(existing, key=newest)


def run_audit(
    *,
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    out_dir: Path = Path("reports/v14b_pilot"),
    section_log: Path | None = None,
    watchdog_log: Path | None = None,
    watchdog_state: Path | None = None,
    openalex_log: Path = Path("logs/v14b/openalex_backfill_current.log"),
) -> dict[str, Any]:
    if section_log is None or watchdog_log is None or watchdog_state is None:
        default_section, default_watchdog, default_state = _default_frontfill_paths()
        section_log = section_log or default_section
        watchdog_log = watchdog_log or default_watchdog
        watchdog_state = watchdog_state or default_state
    result = collect_audit(
        db_main=db_main,
        db_v14=db_v14,
        section_log=section_log,
        watchdog_log=watchdog_log,
        watchdog_state=watchdog_state,
        openalex_log=openalex_log,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "evidence_bone_audit.md"
    json_path = out_dir / "evidence_bone_audit.json"
    md_path.write_text(render_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"report": str(md_path), "json": str(json_path), "generated_at": result["generated_at"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit V14B evidence bone failure taxonomy.")
    parser.add_argument("--db", default=str(DB_MAIN))
    parser.add_argument("--db-v14", default=str(DB_V14))
    parser.add_argument("--out-dir", default="reports/v14b_pilot")
    parser.add_argument("--section-log", default=None)
    parser.add_argument("--watchdog-log", default=None)
    parser.add_argument("--watchdog-state", default=None)
    parser.add_argument("--openalex-log", default="logs/v14b/openalex_backfill_current.log")
    args = parser.parse_args()
    result = run_audit(
        db_main=Path(args.db),
        db_v14=Path(args.db_v14),
        out_dir=Path(args.out_dir),
        section_log=Path(args.section_log) if args.section_log else None,
        watchdog_log=Path(args.watchdog_log) if args.watchdog_log else None,
        watchdog_state=Path(args.watchdog_state) if args.watchdog_state else None,
        openalex_log=Path(args.openalex_log),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
