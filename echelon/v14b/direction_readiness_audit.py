"""Audit whether future-growth candidates are ready to become Claim Cards.

The product goal is not to maximize the number of future edges.  It is to
separate calibrated candidate generation from evidence-backed, actionable
research directions.  This audit reports which step is blocking that promotion.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from echelon.v14b.evidence_contracts import (
    PRIMARY_SECTION_NAMES,
    SECTION_PARSER_CONTRACT_VERSION,
    section_strategy_quality,
)
from echelon.v14b.cited_work_backfill import load_cited_work_backfill_run_state
from echelon.v14b.cited_work_backfill_queue import load_cited_work_backfill_state
from echelon.v14b.future_candidate_lifecycle import run_audit as run_lifecycle_audit
from echelon.v14b.topic_gap_no_target_inspection import load_topic_gap_no_target_inspection_state
from echelon.v14b.topic_gap_section_evidence_audit import load_topic_gap_section_triage_state

WEAK_SECTION_STRATEGIES = {
    "loose_inline_heading",
    "parser_hint",
    "legacy_unknown_strategy",
}


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.Error:
        return 0
    return row[0] if row else 0


def load_queue_paper_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: Any) -> None:
        paper_id = str(raw or "").strip()
        if paper_id and paper_id not in seen:
            seen.add(paper_id)
            out.append(paper_id)

    try:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                add(row.get("paper_id"))
                for raw in str(row.get("candidate_paper_ids") or "").replace(",", ";").split(";"):
                    add(raw)
    except Exception:
        return []
    return out


def _chunks(values: list[str], size: int = 500) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def _json_obj(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _rewrite_candidate_score_keys(value: Any) -> Any:
    key_map = {
        "prediction_confidence_avg": "candidate_ranking_score_avg",
        "min_vgae_confidence": "min_candidate_score_threshold",
        "vgae_top_n": "candidate_edges_used",
        "raw_predicted_prob": "raw_candidate_score",
        "calibrated_predicted_prob": "calibrated_candidate_score",
    }
    if isinstance(value, dict):
        return {key_map.get(str(k), str(k)): _rewrite_candidate_score_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite_candidate_score_keys(v) for v in value]
    return value


def _public_latest_fusion_audit(row: dict[str, Any] | None) -> dict[str, Any]:
    """Render Step6 audit metadata with public candidate-generator semantics."""
    if not row:
        return {}
    scalar_key_map = {
        "run_id": "run_id",
        "n_terminals": "terminals_considered",
        "n_vgae_preds_top": "candidate_edges_used",
        "n_vgae_preds_total": "future_candidate_edges_total",
        "n_cross_field_total": "cross_field_candidate_edges_total",
        "n_unresolved": "unresolved_limitations_used",
        "n_candidates": "fusion_candidates",
        "n_directions": "fusion_directions",
        "output_directions": "fusion_directions",
        "adequacy_label": "adequacy_label",
        "remaining_risk": "remaining_risk",
        "created_at": "created_at",
    }
    public: dict[str, Any] = {}
    for old_key, new_key in scalar_key_map.items():
        if old_key in row and row.get(old_key) is not None:
            public[new_key] = row.get(old_key)
    json_key_map = {
        "limitation_quality_json": "limitation_quality_distribution",
        "evidence_path_json": "evidence_path_distribution",
        "candidate_tier_json": "candidate_tier_distribution",
        "calibration_json": "calibration_summary",
    }
    for old_key, new_key in json_key_map.items():
        if old_key in row and row.get(old_key):
            public[new_key] = _rewrite_candidate_score_keys(_json_obj(row.get(old_key)))
    return public


def _section_quality_from_strategies(strategies: set[str]) -> str:
    return section_strategy_quality(strategies)


def primary_section_paper_count(conn: sqlite3.Connection, paper_ids: list[str] | None = None) -> int:
    section_names = tuple(name.lower() for name in PRIMARY_SECTION_NAMES)
    ph_names = ",".join("?" for _ in section_names)
    base = f"""
        SELECT COUNT(DISTINCT paper_id)
        FROM paper_sections
        WHERE lower(section_name) IN ({ph_names})
          AND length(trim(section_text)) >= 80
    """
    if paper_ids is None:
        return int(scalar(conn, base, section_names) or 0)
    if not paper_ids:
        return 0
    total = 0
    for chunk in _chunks(paper_ids):
        ph_ids = ",".join("?" for _ in chunk)
        total += int(
            scalar(
                conn,
                base + f" AND paper_id IN ({ph_ids})",
                section_names + tuple(chunk),
            )
            or 0
        )
    return total


def primary_section_strategy_quality(
    conn: sqlite3.Connection,
    paper_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Summarize whether primary section evidence is strongly traceable.

    Section quantity alone is not enough for decision-grade claims.  A paper
    parsed from explicit/embedded headings has different provenance than a
    paper found only by loose inline heuristics or legacy rows without parser
    metadata.  This audit keeps those sources separate so downstream Claim
    Cards can remain honest about evidence strength.
    """
    if not table_exists(conn, "paper_sections"):
        return {
            "primary_section_rows": 0,
            "primary_section_papers": 0,
            "strategy_counts": {},
            "parser_name_counts": {},
            "parser_contract_version_counts": {},
            "paper_quality_counts": {},
            "current_contract_papers": 0,
            "current_contract_rate": 0.0,
            "decision_grade_papers": 0,
            "decision_grade_rate": 0.0,
            "strong_or_moderate_papers": 0,
            "weak_only_papers": 0,
            "weak_only_rate": 0.0,
        }

    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(paper_sections)").fetchall()}
    has_meta = "section_meta_json" in cols
    has_parser_name = "parser_name" in cols
    section_names = tuple(name.lower() for name in PRIMARY_SECTION_NAMES)
    ph_names = ",".join("?" for _ in section_names)
    select_meta = "section_meta_json" if has_meta else "NULL AS section_meta_json"
    select_parser = "parser_name" if has_parser_name else "NULL AS parser_name"
    base = f"""
        SELECT paper_id, lower(section_name) AS section_name, {select_meta}, {select_parser}
        FROM paper_sections
        WHERE lower(section_name) IN ({ph_names})
          AND length(trim(section_text)) >= 80
    """
    params: tuple[Any, ...] = section_names
    if paper_ids:
        ph_ids = ",".join("?" for _ in paper_ids)
        base += f" AND paper_id IN ({ph_ids})"
        params = section_names + tuple(paper_ids)

    strategy_counts: dict[str, int] = {}
    parser_name_counts: dict[str, int] = {}
    parser_contract_version_counts: dict[str, int] = {}
    paper_best_quality: dict[str, str] = {}
    current_contract_papers: set[str] = set()
    decision_grade_papers: set[str] = set()
    quality_rank = {"weak": 0, "moderate": 1, "strong": 2}
    rows = conn.execute(base, params).fetchall()
    for paper_id, _section_name, raw_meta, raw_parser_name in rows:
        pid = str(paper_id)
        meta = _json_obj(raw_meta)
        parser_name = str(raw_parser_name or "legacy_unknown_parser")
        parser_name_counts[parser_name] = parser_name_counts.get(parser_name, 0) + 1
        contract_version = str(meta.get("parser_contract_version") or "legacy_unknown_contract")
        parser_contract_version_counts[contract_version] = parser_contract_version_counts.get(contract_version, 0) + 1
        if contract_version == SECTION_PARSER_CONTRACT_VERSION:
            current_contract_papers.add(pid)
        raw_strategies = meta.get("extraction_strategies") or []
        strategies = {
            str(item).strip()
            for item in raw_strategies
            if str(item).strip()
        }
        if not strategies:
            strategies = {"legacy_unknown_strategy"}
        for strategy in sorted(strategies):
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        quality = _section_quality_from_strategies(strategies)
        if contract_version == SECTION_PARSER_CONTRACT_VERSION and quality in {"strong", "moderate"}:
            decision_grade_papers.add(pid)
        if pid not in paper_best_quality or quality_rank[quality] > quality_rank.get(paper_best_quality[pid], 0):
            paper_best_quality[pid] = quality

    paper_quality_counts = {
        quality: sum(1 for q in paper_best_quality.values() if q == quality)
        for quality in ("strong", "moderate", "weak")
    }
    primary_papers = len(paper_best_quality)
    strong_or_moderate = paper_quality_counts["strong"] + paper_quality_counts["moderate"]
    weak_only = paper_quality_counts["weak"]
    return {
        "primary_section_rows": len(rows),
        "primary_section_papers": primary_papers,
        "strategy_counts": dict(sorted(strategy_counts.items())),
        "parser_name_counts": dict(sorted(parser_name_counts.items())),
        "parser_contract_version_counts": dict(sorted(parser_contract_version_counts.items())),
        "paper_quality_counts": paper_quality_counts,
        "current_contract_papers": len(current_contract_papers),
        "current_contract_rate": len(current_contract_papers) / max(1, primary_papers),
        "decision_grade_papers": len(decision_grade_papers),
        "decision_grade_rate": len(decision_grade_papers) / max(1, primary_papers),
        "strong_or_moderate_papers": strong_or_moderate,
        "weak_only_papers": weak_only,
        "weak_only_rate": weak_only / max(1, primary_papers),
    }


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _top_counts(counts: dict[str, Any], limit: int = 3) -> str:
    pairs = sorted(
        ((str(key), int(value or 0)) for key, value in (counts or {}).items()),
        key=lambda item: (-item[1], item[0]),
    )
    return ", ".join(f"{key}:{value:,}" for key, value in pairs[:limit]) or "none"


_WATCHDOG_TS_RE = re.compile(r"\[(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\]")
_WATCHDOG_COUNT_RE = re.compile(r"rows=(?P<rows>\d+)\s+papers=(?P<papers>\d+)")
_WATCHDOG_DONE_RE = re.compile(r"done=(?P<done>\d+)/(?P<total>\d+)")
_SECTION_PROGRESS_RE = re.compile(
    r"(?P<done>\d+)/(?P<total>\d+)\s+\[(?P<elapsed>\d+:\d{2}:\d{2})<"
)


def _ts_epoch(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _elapsed_to_seconds(value: str) -> int:
    try:
        hours, minutes, seconds = [int(part) for part in value.split(":")]
    except Exception:
        return 0
    return hours * 3600 + minutes * 60 + seconds


def _watchdog_no_evidence_elapsed(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        return {}
    latest: dict[str, Any] | None = None
    last_growth: dict[str, Any] | None = None
    for line in log_path.read_text(errors="ignore").splitlines():
        ts = _WATCHDOG_TS_RE.search(line)
        counts = _WATCHDOG_COUNT_RE.search(line)
        if not ts or not counts:
            continue
        done = _WATCHDOG_DONE_RE.search(line)
        rec = {
            "ts": ts.group("ts"),
            "epoch": _ts_epoch(ts.group("ts")),
            "rows": int(counts.group("rows")),
            "papers": int(counts.group("papers")),
            "done": int(done.group("done")) if done else None,
            "total": int(done.group("total")) if done else None,
        }
        if latest is None or rec["rows"] != latest["rows"] or rec["papers"] != latest["papers"]:
            last_growth = rec
        latest = rec
    if not latest or not last_growth:
        return {}
    out = {
        "log_no_evidence_elapsed_s": int(max(0, latest["epoch"] - last_growth["epoch"])),
        "log_latest_done": latest.get("done"),
        "log_latest_total": latest.get("total"),
    }
    if latest.get("done") is not None and last_growth.get("done") is not None:
        out["log_no_evidence_done_delta"] = int(latest["done"]) - int(last_growth["done"])
    return out


def _watchdog_log_for_state(path: Path) -> Path:
    name = path.name
    if name.endswith("_state.json"):
        return path.with_name(name[: -len("_state.json")] + ".log")
    return path.with_suffix(".log")


def _section_progress_log_for_state(path: Path) -> Path | None:
    name = path.name
    if name == "section_delta_watchdog_state.json":
        return path.with_name("step5s_section_delta.log")
    if name == "section_top12000_watchdog_state.json":
        return path.with_name("step5s_section_top12000.log")
    return None


def _section_progress_tail(log_path: Path | None) -> dict[str, Any]:
    if log_path is None or not log_path.exists():
        return {}
    text = log_path.read_text(errors="ignore")
    chunks = [chunk for chunk in text.replace("\n", "\r").split("\r") if "Step5s sections:" in chunk]
    if not chunks:
        return {}
    match = _SECTION_PROGRESS_RE.search(chunks[-1])
    if not match:
        return {}
    done = int(match.group("done"))
    total = int(match.group("total"))
    elapsed_s = _elapsed_to_seconds(match.group("elapsed"))
    return {
        "progress_latest_done": done,
        "progress_latest_total": total,
        "progress_elapsed_s": elapsed_s,
        "progress_log": str(log_path),
    }


def _max_int(*values: Any) -> int | None:
    parsed = []
    for value in values:
        try:
            if value is not None:
                parsed.append(int(value))
        except Exception:
            continue
    return max(parsed) if parsed else None


def load_section_frontfill_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "reason": "unreadable"}
    if not isinstance(state, dict):
        return {"available": False, "reason": "not_object"}
    no_evidence_delta = int(state.get("no_evidence_done_delta") or 0)
    no_evidence_elapsed_s = int(state.get("no_evidence_elapsed_s") or 0)
    low_yield_intervals = int(state.get("low_yield_intervals") or 0)
    no_current_contract_delta = int(state.get("no_current_contract_done_delta") or 0)
    no_current_contract_elapsed_s = int(state.get("no_current_contract_elapsed_s") or 0)
    current_contract_low_yield_intervals = int(state.get("current_contract_low_yield_intervals") or 0)
    log_path = _watchdog_log_for_state(path)
    log_state = _watchdog_no_evidence_elapsed(log_path)
    progress_state = _section_progress_tail(_section_progress_log_for_state(path))
    no_evidence_delta = max(no_evidence_delta, int(log_state.get("log_no_evidence_done_delta") or 0))
    no_evidence_elapsed_s = max(no_evidence_elapsed_s, int(log_state.get("log_no_evidence_elapsed_s") or 0))
    latest_done = _max_int(
        state.get("done"),
        log_state.get("log_latest_done"),
        progress_state.get("progress_latest_done"),
    )
    latest_total = _max_int(
        state.get("total"),
        log_state.get("log_latest_total"),
        progress_state.get("progress_latest_total"),
    )
    if low_yield_intervals >= 2 or no_evidence_elapsed_s >= 4 * 3600:
        status = "soft_stall"
    elif no_evidence_delta >= 200:
        status = "low_yield"
    else:
        status = "running_or_unknown"
    if current_contract_low_yield_intervals >= 2 or no_current_contract_elapsed_s >= 4 * 3600:
        contract_status = "soft_stall"
    elif no_current_contract_delta >= 200:
        contract_status = "low_yield"
    else:
        contract_status = "running_or_unknown"
    return {
        "available": True,
        "source": path.stem.replace("_watchdog_state", ""),
        "state_path": str(path),
        "watchdog_log": str(log_path),
        **progress_state,
        "status": status,
        "done": latest_done,
        "total": latest_total,
        "state_done": state.get("done"),
        "state_total": state.get("total"),
        "log_latest_done": log_state.get("log_latest_done"),
        "log_latest_total": log_state.get("log_latest_total"),
        "rows": state.get("rows"),
        "papers": state.get("papers"),
        "primary_section_papers": state.get("primary_section_papers"),
        "current_contract_primary_section_papers": state.get("current_contract_primary_section_papers"),
        "parser_contract_version": state.get("parser_contract_version"),
        "no_evidence_done_delta": no_evidence_delta,
        "no_evidence_elapsed_s": no_evidence_elapsed_s,
        "low_yield_intervals": low_yield_intervals,
        "current_contract_status": contract_status,
        "no_current_contract_done_delta": no_current_contract_delta,
        "no_current_contract_elapsed_s": no_current_contract_elapsed_s,
        "current_contract_low_yield_intervals": current_contract_low_yield_intervals,
    }


def select_section_frontfill_state(repo_root: Path = Path(".")) -> dict[str, Any]:
    candidates = [
        repo_root / "logs/v14b/section_delta_watchdog_state.json",
        repo_root / "logs/v14b/section_top12000_watchdog_state.json",
    ]
    existing = [p for p in candidates if p.exists()]
    if not existing:
        return {"available": False}
    latest = max(existing, key=lambda p: p.stat().st_mtime)
    return load_section_frontfill_state(latest)


def _parse_log_ts(line: str) -> datetime | None:
    match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def load_openalex_frontfill_state(
    path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    now = now or datetime.now()
    targets = None
    processed = None
    total = None
    ok = None
    fail = None
    last_ts = None
    last_progress_ts = None
    cooldown_ts = None
    cooldown_s = None
    done = False
    fetch_failures = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return {"available": False, "reason": "unreadable", "log_path": str(path)}
    for line in lines:
        ts = _parse_log_ts(line)
        if ts is not None:
            last_ts = ts
        match = re.search(r"OpenAlex backfill targets:\s*(\d+)", line)
        if match:
            processed = None
            total = None
            ok = None
            fail = None
            cooldown_ts = None
            cooldown_s = None
            last_progress_ts = None
            done = False
            fetch_failures = 0
            targets = int(match.group(1))
        match = re.search(
            r"OpenAlex backfill progress:\s*processed=(\d+)/(\d+)\s+ok=(\d+)\s+fail=(\d+)",
            line,
        )
        if match:
            processed = int(match.group(1))
            total = int(match.group(2))
            ok = int(match.group(3))
            fail = int(match.group(4))
            last_progress_ts = ts or last_ts
        match = re.search(r"OpenAlex 429, cooldown ([0-9.]+)s", line)
        if match:
            cooldown_ts = ts or last_ts
            cooldown_s = float(match.group(1))
        if "OpenAlex fetch failed paper=" in line:
            fetch_failures += 1
        if "OpenAlex backfill done:" in line:
            done = True
            last_progress_ts = ts or last_ts
            match = re.search(r"'records_n':\s*(\d+).*'failed':\s*(\d+)", line)
            if match:
                ok = int(match.group(1))
                fail = int(match.group(2))
    status = "running_or_unknown"
    cooldown_remaining_s = 0
    cooldown_until = None
    if done:
        status = "completed"
    elif cooldown_ts is not None and cooldown_s is not None:
        cooldown_until_dt = cooldown_ts + timedelta(seconds=cooldown_s)
        cooldown_until = cooldown_until_dt.isoformat(timespec="seconds")
        cooldown_remaining_s = int(max(0, (cooldown_until_dt - now).total_seconds()))
        status = "cooling_down_or_stopped" if cooldown_remaining_s > 0 else "stalled_after_cooldown"
    elif last_ts is not None and (now - last_ts).total_seconds() > 6 * 3600:
        status = "stale_without_completion"
    return {
        "available": True,
        "source": path.stem,
        "log_path": str(path),
        "status": status,
        "targets": targets,
        "processed": processed,
        "total": total or targets,
        "ok": ok,
        "fail": fail,
        "fetch_failures_logged": fetch_failures,
        "last_event_at": last_ts.isoformat(timespec="seconds") if last_ts else None,
        "last_progress_at": last_progress_ts.isoformat(timespec="seconds") if last_progress_ts else None,
        "cooldown_seconds": cooldown_s,
        "cooldown_until": cooldown_until,
        "cooldown_remaining_s": cooldown_remaining_s,
    }


def select_openalex_frontfill_state(repo_root: Path = Path(".")) -> dict[str, Any]:
    log_dir = repo_root / "logs/v14b"
    candidates = [log_dir / "openalex_backfill_current.log", *log_dir.glob("step0_openalex_backfill_*.log")]
    existing = [p for p in candidates if p.exists()]
    if not existing:
        return {"available": False}
    latest = max(existing, key=lambda p: p.stat().st_mtime)
    return load_openalex_frontfill_state(latest)


def load_reference_relink_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "reason": "unreadable", "path": str(path)}
    summary = loaded.get("candidate_summary") if isinstance(loaded, dict) else {}
    if not isinstance(summary, dict):
        return {"available": False, "reason": "missing_candidate_summary", "path": str(path)}
    counts = summary.get("status_counts") or {}
    scanned = int(summary.get("scanned_unlinked_refs") or 0)
    exact = int(counts.get("exact_linkable") or 0)
    no_local = int(counts.get("no_local_match") or 0)
    ambiguous = int(counts.get("ambiguous_local_match") or 0)
    exact_rate = exact / max(1, scanned)
    no_local_rate = no_local / max(1, scanned)
    if scanned and no_local_rate >= 0.95 and exact_rate < 0.01:
        status = "local_corpus_gap_dominates"
        next_action = (
            "Prioritize high-value cited-work backfill for missing DOI/OpenAlex/S2/arXiv references; "
            "broad relinking has little remaining yield until the cited papers exist locally."
        )
    elif exact:
        status = "exact_relink_pending"
        next_action = "Run reference-relink-apply when no frontfill writer is active, then rerun graph features."
    elif ambiguous:
        status = "dedup_required_before_relink"
        next_action = "Resolve duplicate local provider IDs before applying additional citation links."
    else:
        status = "no_pending_exact_relinks"
        next_action = "Keep citation claims uncertainty-scoped; improve coverage through cited-work ingestion, not fuzzy relinking."
    return {
        "available": True,
        "path": str(path),
        "status": status,
        "scanned_unlinked_refs": scanned,
        "exact_linkable_refs": exact,
        "no_local_match_refs": no_local,
        "ambiguous_local_match_refs": ambiguous,
        "exact_linkable_rate": exact_rate,
        "no_local_match_rate": no_local_rate,
        "next_action": next_action,
    }


def select_reference_relink_state(
    repo_root: Path = Path("."),
    report_dir: Path | None = None,
) -> dict[str, Any]:
    candidates = []
    if report_dir is not None:
        candidates.append(report_dir / "reference_relink_audit.json")
    candidates.append(repo_root / "reports/v14b_pilot/reference_relink_audit.json")
    existing = [p for p in candidates if p.exists()]
    if not existing:
        return {"available": False}
    latest = max(existing, key=lambda p: p.stat().st_mtime)
    return load_reference_relink_state(latest)


def collect_metrics(
    db_main: Path,
    db_v14: Path,
    topic_gap_queue: Path | None = None,
) -> dict[str, Any]:
    topic_gap_queue = topic_gap_queue or Path("data/v14b/topic_evidence_gap_delta_queue.csv")
    main = sqlite3.connect(str(db_main))
    try:
        papers = int(scalar(main, "SELECT COUNT(*) FROM papers") or 0)
        refs = int(scalar(main, "SELECT COUNT(*) FROM paper_references") or 0)
        linked_refs = int(
            scalar(
                main,
                """
                SELECT COUNT(*) FROM paper_references
                WHERE COALESCE(cited_paper_id_internal, '') <> ''
                """,
            )
            or 0
        )
        openalex_w = int(
            scalar(
                main,
                """
                SELECT COUNT(*) FROM papers
                WHERE openalex_id LIKE 'W%' OR openalex_id LIKE 'https://openalex.org/W%'
                """,
            )
            or 0
        )
        section_rows = int(scalar(main, "SELECT COUNT(*) FROM paper_sections") or 0)
        section_papers = int(scalar(main, "SELECT COUNT(DISTINCT paper_id) FROM paper_sections") or 0)
        primary_section_papers = primary_section_paper_count(main)
        section_quality = primary_section_strategy_quality(main)
        topic_gap_ids = load_queue_paper_ids(topic_gap_queue)
        topic_gap_primary_section_papers = primary_section_paper_count(main, topic_gap_ids)
        topic_gap_section_quality = primary_section_strategy_quality(main, topic_gap_ids)
    finally:
        main.close()

    v14 = sqlite3.connect(str(db_v14))
    try:
        counts: dict[str, int] = {}
        for table in (
            "predicted_future_edges",
            "limitation_atoms",
            "limitation_resolutions",
            "fusion_evidence_audit",
            "future_directions",
            "direction_claim_cards",
            "visual_edges",
            "branch_lineages",
        ):
            counts[table] = int(scalar(v14, f"SELECT COUNT(*) FROM {table}") or 0) if table_exists(v14, table) else 0
        complete_cards = (
            int(scalar(v14, "SELECT COUNT(*) FROM direction_claim_cards WHERE five_question_complete=1") or 0)
            if table_exists(v14, "direction_claim_cards")
            else 0
        )
        high_conf_cards = (
            int(scalar(v14, "SELECT COUNT(*) FROM direction_claim_cards WHERE high_confidence_eligible=1") or 0)
            if table_exists(v14, "direction_claim_cards")
            else 0
        )
        future_visual_edges = (
            int(scalar(v14, "SELECT COUNT(*) FROM visual_edges WHERE layer='future'") or 0)
            if table_exists(v14, "visual_edges")
            else 0
        )
        latest_fusion = None
        if table_exists(v14, "fusion_evidence_audit") and counts["fusion_evidence_audit"]:
            cols = [r[1] for r in v14.execute("PRAGMA table_info(fusion_evidence_audit)").fetchall()]
            row = v14.execute("SELECT * FROM fusion_evidence_audit ORDER BY rowid DESC LIMIT 1").fetchone()
            latest_fusion = dict(zip(cols, row)) if row else None
    finally:
        v14.close()
    future_candidate_edges = counts.pop("predicted_future_edges", 0)

    return {
        "papers": papers,
        "refs": refs,
        "linked_refs": linked_refs,
        "linked_ref_rate": linked_refs / max(1, refs),
        "openalex_w": openalex_w,
        "openalex_w_rate": openalex_w / max(1, papers),
        "section_rows": section_rows,
        "section_papers": section_papers,
        "primary_section_papers": primary_section_papers,
        "primary_section_rate": primary_section_papers / max(1, papers),
        "section_evidence_quality": section_quality,
        "topic_gap_queue_path": str(topic_gap_queue),
        "topic_gap_queue_papers": len(topic_gap_ids),
        "topic_gap_primary_section_papers": topic_gap_primary_section_papers,
        "topic_gap_primary_section_rate": topic_gap_primary_section_papers / max(1, len(topic_gap_ids)),
        "topic_gap_decision_grade_section_papers": int(topic_gap_section_quality.get("decision_grade_papers") or 0),
        "topic_gap_decision_grade_section_rate": int(topic_gap_section_quality.get("decision_grade_papers") or 0) / max(1, len(topic_gap_ids)),
        "topic_gap_section_evidence_quality": topic_gap_section_quality,
        "future_candidate_edges": future_candidate_edges,
        **counts,
        "complete_claim_cards": complete_cards,
        "high_confidence_claim_cards": high_conf_cards,
        "future_visual_edges": future_visual_edges,
        "latest_fusion": latest_fusion,
    }


def classify_blockers(m: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    future_candidate_edges = int(m.get("future_candidate_edges") or m.get("predicted_future_edges") or 0)
    if m["linked_ref_rate"] < 0.30:
        relink = m.get("reference_relink_state") or {}
        cited_work_queue = m.get("cited_work_backfill_queue_state") or {}
        relink_detail = ""
        next_action = "Continue provider ID repair and reference relinking after OpenAlex/S2 identifiers stabilize."
        if relink.get("available"):
            relink_detail = (
                f" Reference relink audit: {int(relink.get('exact_linkable_refs') or 0):,} exact-linkable, "
                f"{int(relink.get('no_local_match_refs') or 0):,} no-local-match."
            )
            next_action = str(relink.get("next_action") or next_action)
            cited_work_run = m.get("cited_work_backfill_run_state") or {}
            if (
                relink.get("status") == "local_corpus_gap_dominates"
                and cited_work_queue.get("available")
                and int(cited_work_queue.get("queue_rows") or 0)
            ):
                if cited_work_run.get("available") and int(cited_work_run.get("inserted_or_updated") or 0):
                    if int(cited_work_run.get("relink_updates_applied") or 0):
                        next_action = (
                            "Continue processing the remaining cited-work queue in small exact-ID batches; "
                            "rerun exact relink and graph features after each applied batch."
                        )
                    else:
                        next_action = (
                            "Rerun reference-relink-apply, graph features, and downstream audits after the cited-work "
                            "backfill run; continue processing the remaining queue in small exact-ID batches."
                        )
                else:
                    next_action = (
                        "Process the high-value cited-work backfill queue, then rerun reference-relink-apply, "
                        "graph features, and downstream audits."
                    )
        blockers.append(
            {
                "gate": "citation_graph_bone",
                "severity": "high",
                "why": (
                    f"linked refs are {pct(m['linked_ref_rate'])}; branch/main-path claims need uncertainty labels."
                    f"{relink_detail}"
                ),
                "next_action": next_action,
            }
        )
    if m["primary_section_papers"] < 8000:
        blockers.append(
            {
                "gate": "section_evidence",
                "severity": "high",
                "why": f"primary section evidence covers only {m['primary_section_papers']:,} papers.",
                "next_action": "Finish top12000 section ingest, then run delta section queue for main/future/branch/keystone papers.",
            }
        )
    section_quality = m.get("section_evidence_quality") or {}
    weak_only_rate = float(section_quality.get("weak_only_rate") or 0.0)
    strong_or_moderate = int(section_quality.get("strong_or_moderate_papers") or 0)
    if m.get("primary_section_papers", 0) and (weak_only_rate > 0.25 or strong_or_moderate < 1000):
        blockers.append(
            {
                "gate": "section_evidence_provenance",
                "severity": "medium",
                "why": (
                    "primary section evidence quality is still fragile: "
                    f"{strong_or_moderate:,} papers have strong/moderate parser provenance; "
                    f"weak-only rate is {pct(weak_only_rate)}."
                ),
                "next_action": (
                    "Use explicit/embedded heading evidence for bottleneck and Claim Card promotion; "
                    "keep loose/legacy section matches as weak evidence until manually audited or re-parsed."
                ),
            }
        )
    if (
        m.get("primary_section_papers", 0)
        and "current_contract_papers" in section_quality
        and float(section_quality.get("current_contract_rate") or 0.0) < 0.70
    ):
        blockers.append(
            {
                "gate": "section_parser_contract_coverage",
                "severity": "medium",
                "why": (
                    "primary section evidence has current parser-contract coverage for only "
                    f"{int(section_quality.get('current_contract_papers') or 0):,}/"
                    f"{int(section_quality.get('primary_section_papers') or m.get('primary_section_papers') or 0):,} papers "
                    f"({pct(float(section_quality.get('current_contract_rate') or 0.0))}); "
                    "legacy parser-contract sections may predate TOC/fragment guards."
                ),
                "next_action": (
                    "Re-run section evidence with the current parser contract before promoting "
                    "section-derived bottleneck, Topic Dossier, or Claim Card claims."
                ),
            }
        )
    if m.get("topic_gap_queue_papers", 0) and m.get("topic_gap_decision_grade_section_rate", 0.0) < 0.70:
        triage = m.get("topic_gap_section_triage_state") or {}
        triage_detail = ""
        next_action = (
            "Run make topic-gap-section-audit, then repair the largest concrete bucket: "
            "stale parser-contract rows need current-contract reparse, current-parser no-target rows "
            "need parser/full-text inspection, and unattempted PDF rows need targeted ingest."
        )
        if triage.get("available"):
            counts = triage.get("failure_mode_counts") or {}
            triage_detail = (
                " Triage: "
                f"current-parser no-target={int(counts.get('no_target_sections_after_current_parser') or 0):,}, "
                f"stale-contract={int(counts.get('stale_parser_contract') or 0):,}, "
                f"unattempted-PDF={int(counts.get('unattempted_pdf_available') or 0):,}."
            )
            next_action = str(triage.get("next_action") or next_action)
        no_target = m.get("topic_gap_no_target_inspection_state") or {}
        if no_target.get("available"):
            counts = no_target.get("classification_counts") or {}
            triage_detail += (
                " No-target inspection: "
                f"parser-target-signal={int(no_target.get('parser_target_signal_papers') or 0):,}, "
                f"subthreshold-target-signal={int(no_target.get('subthreshold_target_signal_papers') or 0):,}, "
                f"sectionless/non-target-heading={int(counts.get('sectionless_or_non_target_heading_format') or 0):,}."
            )
            if int(no_target.get("parser_target_signal_papers") or 0) == 0:
                next_action = str(no_target.get("next_action") or next_action)
        blockers.append(
            {
                "gate": "multi_topic_evidence_gap",
                "severity": "high",
                "why": (
                    "multi-topic regression still has decision-grade section evidence for only "
                    f"{int(m.get('topic_gap_decision_grade_section_papers') or 0):,}/"
                    f"{int(m.get('topic_gap_queue_papers') or 0):,} queued benchmark-topic papers "
                    f"({pct(float(m.get('topic_gap_decision_grade_section_rate') or 0.0))}); "
                    f"raw primary-section coverage is {int(m.get('topic_gap_primary_section_papers') or 0):,}/"
                    f"{int(m.get('topic_gap_queue_papers') or 0):,} "
                    f"({pct(float(m.get('topic_gap_primary_section_rate') or 0.0))})."
                    f"{triage_detail}"
                ),
                "next_action": next_action,
            }
        )
    topic_gap_quality = m.get("topic_gap_section_evidence_quality") or {}
    if (
        m.get("topic_gap_primary_section_papers", 0)
        and float(topic_gap_quality.get("weak_only_rate") or 0.0) > 0.25
    ):
        blockers.append(
            {
                "gate": "multi_topic_section_provenance",
                "severity": "medium",
                "why": (
                    "benchmark-topic gap papers have primary sections, but too many are weak parser matches "
                    f"({pct(float(topic_gap_quality.get('weak_only_rate') or 0.0))} weak-only)."
                ),
                "next_action": (
                    "Do not pass multi-topic Dossier claims on loose parser evidence alone; "
                    "re-parse or audit those topic papers before promotion."
                ),
            }
        )
    frontfill = m.get("section_frontfill_state") or {}
    if frontfill.get("status") in {"low_yield", "soft_stall"}:
        delta = int(frontfill.get("no_evidence_done_delta") or 0)
        elapsed_h = float(frontfill.get("no_evidence_elapsed_s") or 0) / 3600.0
        delta_text = f"{delta:,} candidates" if delta else "candidate delta unknown"
        blockers.append(
            {
                "gate": "section_frontfill_efficiency",
                "severity": "high" if frontfill.get("status") == "soft_stall" else "medium",
                "why": (
                    f"section frontfill is {frontfill.get('status')}: "
                    f"{delta_text} and {elapsed_h:.1f}h since last evidence growth."
                ),
                "next_action": (
                    "Do not wait passively for topN. Run queue audit/delta handoff for high-value papers "
                    "and classify no-target-section/no-PDF/timeout failures before promoting bottleneck claims."
                ),
            }
        )
    if frontfill.get("current_contract_status") in {"low_yield", "soft_stall"}:
        delta = int(frontfill.get("no_current_contract_done_delta") or 0)
        elapsed_h = float(frontfill.get("no_current_contract_elapsed_s") or 0) / 3600.0
        blockers.append(
            {
                "gate": "section_frontfill_contract_efficiency",
                "severity": "high" if frontfill.get("current_contract_status") == "soft_stall" else "medium",
                "why": (
                    f"section frontfill is {frontfill.get('current_contract_status')} for current parser-contract evidence: "
                    f"{delta:,} scanned items and {elapsed_h:.1f}h since current-contract primary-section growth."
                ),
                "next_action": (
                    "Ensure the active Step5s process was started with the current parser contract and prioritize "
                    "stale-parser-contract reparse queues before promoting section-derived claims."
                ),
            }
        )
    if future_candidate_edges and not m["future_directions"]:
        blockers.append(
            {
                "gate": "fusion_materialization",
                "severity": "high",
                "why": "Step5b produced future candidates but live future_directions is empty.",
                "next_action": "After section evidence improves, rerun Step5c -> Step6 -> Step13; do not promote raw GNN edges.",
            }
        )
    if m["future_directions"] and not m["direction_claim_cards"]:
        blockers.append(
            {
                "gate": "claim_card_generation",
                "severity": "high",
                "why": "future_directions exist but Step13 Claim Cards are missing.",
                "next_action": "Run Step13 and enforce five-question gates.",
            }
        )
    if m["direction_claim_cards"] and not m["complete_claim_cards"]:
        blockers.append(
            {
                "gate": "radar_eligibility",
                "severity": "medium",
                "why": "Claim Cards exist but none answer all five hard questions.",
                "next_action": "Improve section-level bottleneck, enabler, and minimal validation experiment evidence.",
            }
        )
    if m["openalex_w_rate"] < 0.70:
        blockers.append(
            {
                "gate": "openalex_topic_coverage",
                "severity": "medium",
                "why": f"OpenAlex W coverage is {pct(m['openalex_w_rate'])}; cross-field claims need uncertainty.",
                "next_action": "Keep conservative OpenAlex backfill; use local field/topic fallback while labeling uncertainty.",
            }
        )
    openalex_frontfill = m.get("openalex_frontfill_state") or {}
    if (
        m["openalex_w_rate"] < 0.70
        and openalex_frontfill.get("status")
        in {"cooling_down_or_stopped", "stalled_after_cooldown", "stale_without_completion"}
    ):
        if openalex_frontfill.get("status") == "cooling_down_or_stopped":
            next_action = (
                "Respect the OpenAlex 429 cooldown; resume conservative backfill after cooldown "
                "before promoting cross-field/topic claims."
            )
            severity = "medium"
        else:
            next_action = (
                "Restart conservative OpenAlex backfill or run local field-topic repair before "
                "cross-corpus or cross-field claims are treated as decision-grade."
            )
            severity = "high"
        blockers.append(
            {
                "gate": "openalex_frontfill_health",
                "severity": severity,
                "why": (
                    "OpenAlex frontfill is "
                    f"{openalex_frontfill.get('status')}; processed="
                    f"{openalex_frontfill.get('processed')}/{openalex_frontfill.get('total')}, "
                    f"cooldown_remaining_hours="
                    f"{float(openalex_frontfill.get('cooldown_remaining_s') or 0) / 3600.0:.1f}."
                ),
                "next_action": next_action,
            }
        )
    return blockers


def readiness_level(m: dict[str, Any], blockers: list[dict[str, str]]) -> str:
    future_candidate_edges = int(m.get("future_candidate_edges") or m.get("predicted_future_edges") or 0)
    if m["high_confidence_claim_cards"] > 0:
        return "decision_grade_available"
    if m["complete_claim_cards"] > 0:
        return "actionable_but_not_high_confidence"
    if m["future_visual_edges"] > 0 or future_candidate_edges > 0:
        return "candidate_generator_only"
    return "not_ready"


def render_markdown(metrics: dict[str, Any], blockers: list[dict[str, str]], level: str) -> str:
    frontfill = metrics.get("section_frontfill_state") or {}
    frontfill_line = []
    if frontfill.get("available"):
        source = frontfill.get("source") or "unknown"
        current_contract_primary = frontfill.get("current_contract_primary_section_papers")
        current_contract_primary_text = (
            str(current_contract_primary)
            if current_contract_primary is not None
            else "unknown"
        )
        frontfill_line = [
            f"- section frontfill health: {frontfill.get('status')} [{source}] "
            f"(done={frontfill.get('done')}/{frontfill.get('total')}, "
            f"no_evidence_delta={int(frontfill.get('no_evidence_done_delta') or 0):,}, "
            f"no_evidence_hours={float(frontfill.get('no_evidence_elapsed_s') or 0) / 3600.0:.1f}, "
            f"current_contract_primary={current_contract_primary_text}, "
            f"contract_status={frontfill.get('current_contract_status')}, "
            f"no_current_contract_delta={int(frontfill.get('no_current_contract_done_delta') or 0):,}, "
            f"no_current_contract_hours={float(frontfill.get('no_current_contract_elapsed_s') or 0) / 3600.0:.1f})"
        ]
    openalex_frontfill = metrics.get("openalex_frontfill_state") or {}
    openalex_frontfill_line = []
    if openalex_frontfill.get("available"):
        openalex_frontfill_line = [
            f"- OpenAlex frontfill health: {openalex_frontfill.get('status')} "
            f"[{openalex_frontfill.get('source') or 'unknown'}] "
            f"(processed={openalex_frontfill.get('processed')}/"
            f"{openalex_frontfill.get('total')}, ok={openalex_frontfill.get('ok')}, "
            f"fail={openalex_frontfill.get('fail')}, cooldown_hours="
            f"{float(openalex_frontfill.get('cooldown_remaining_s') or 0) / 3600.0:.1f})"
        ]
    topic_gap_triage = metrics.get("topic_gap_section_triage_state") or {}
    topic_gap_triage_line = []
    if topic_gap_triage.get("available"):
        counts = topic_gap_triage.get("failure_mode_counts") or {}
        topic_gap_triage_line = [
            f"- topic-gap section triage: `{topic_gap_triage.get('status')}`; "
            f"current-parser no-target={int(counts.get('no_target_sections_after_current_parser') or 0):,}; "
            f"stale-contract={int(counts.get('stale_parser_contract') or 0):,}; "
            f"unattempted-PDF={int(counts.get('unattempted_pdf_available') or 0):,}"
        ]
    no_target_inspection = metrics.get("topic_gap_no_target_inspection_state") or {}
    no_target_inspection_line = []
    if no_target_inspection.get("available"):
        counts = no_target_inspection.get("classification_counts") or {}
        no_target_inspection_line = [
            f"- topic-gap no-target inspection: `{no_target_inspection.get('status')}`; "
            f"parser-target-signal={int(no_target_inspection.get('parser_target_signal_papers') or 0):,}; "
            f"subthreshold-target-signal={int(no_target_inspection.get('subthreshold_target_signal_papers') or 0):,}; "
            f"sectionless/non-target-heading="
            f"{int(counts.get('sectionless_or_non_target_heading_format') or 0):,}"
        ]
    lines = [
        "# Direction Readiness Audit",
        "",
        f"- generated_at: `{datetime.utcnow().isoformat(timespec='seconds')}Z`",
        f"- readiness_level: `{level}`",
        "",
        "## Metrics",
        "",
        f"- linked refs: {metrics['linked_refs']:,} / {metrics['refs']:,} ({pct(metrics['linked_ref_rate'])})",
        *(
            [
                f"- reference relink audit: `{(metrics.get('reference_relink_state') or {}).get('status')}`; "
                f"exact-linkable={(int((metrics.get('reference_relink_state') or {}).get('exact_linkable_refs') or 0)):,}; "
                f"no-local-match={(int((metrics.get('reference_relink_state') or {}).get('no_local_match_refs') or 0)):,}"
            ]
            if (metrics.get("reference_relink_state") or {}).get("available")
            else []
        ),
        *(
            [
                f"- cited-work backfill queue: `{(metrics.get('cited_work_backfill_queue_state') or {}).get('status')}`; "
                f"targets={(int((metrics.get('cited_work_backfill_queue_state') or {}).get('queue_rows') or 0)):,}; "
                f"providers={json.dumps((metrics.get('cited_work_backfill_queue_state') or {}).get('provider_counts') or {}, ensure_ascii=False, sort_keys=True)}"
            ]
            if (metrics.get("cited_work_backfill_queue_state") or {}).get("available")
            else []
        ),
        *(
            [
                f"- cited-work backfill run: `{(metrics.get('cited_work_backfill_run_state') or {}).get('status')}`; "
                f"processed={(int((metrics.get('cited_work_backfill_run_state') or {}).get('processed_targets') or 0)):,}; "
                f"inserted_or_updated={(int((metrics.get('cited_work_backfill_run_state') or {}).get('inserted_or_updated') or 0)):,}"
            ]
            if (metrics.get("cited_work_backfill_run_state") or {}).get("available")
            else []
        ),
        f"- OpenAlex W IDs: {metrics['openalex_w']:,} ({pct(metrics['openalex_w_rate'])})",
        *openalex_frontfill_line,
        f"- section evidence: {metrics['section_rows']:,} rows / {metrics['section_papers']:,} papers",
        f"- primary section evidence: {metrics['primary_section_papers']:,} papers ({pct(metrics['primary_section_rate'])})",
        f"- primary section provenance: "
        f"{int((metrics.get('section_evidence_quality') or {}).get('strong_or_moderate_papers') or 0):,} "
        f"strong/moderate papers; weak-only="
        f"{pct(float((metrics.get('section_evidence_quality') or {}).get('weak_only_rate') or 0.0))}",
        f"- current section parser contract: "
        f"{int((metrics.get('section_evidence_quality') or {}).get('current_contract_papers') or 0):,} "
        f"papers ({pct(float((metrics.get('section_evidence_quality') or {}).get('current_contract_rate') or 0.0))})",
        f"- section parser contracts: "
        f"{_top_counts((metrics.get('section_evidence_quality') or {}).get('parser_contract_version_counts') or {})}",
        f"- multi-topic evidence-gap queue: "
        f"{int(metrics.get('topic_gap_decision_grade_section_papers') or 0):,} / "
        f"{int(metrics.get('topic_gap_queue_papers') or 0):,} decision-grade section covered "
        f"({pct(float(metrics.get('topic_gap_decision_grade_section_rate') or 0.0))}); "
        f"raw primary={int(metrics.get('topic_gap_primary_section_papers') or 0):,} "
        f"({pct(float(metrics.get('topic_gap_primary_section_rate') or 0.0))})",
        *topic_gap_triage_line,
        *no_target_inspection_line,
        *frontfill_line,
        f"- future candidate edges: {metrics['future_candidate_edges']:,}",
        f"- visual future edges: {metrics['future_visual_edges']:,}",
        f"- future directions: {metrics['future_directions']:,}",
        f"- Claim Cards: {metrics['direction_claim_cards']:,}; complete={metrics['complete_claim_cards']:,}; high_confidence={metrics['high_confidence_claim_cards']:,}",
        "",
        "## Blockers",
        "",
    ]
    if not blockers:
        lines.append("- No blocking gate detected. Run goal alignment audit before promoting claims.")
    for b in blockers:
        lines.append(f"- **{b['gate']}** ({b['severity']}): {b['why']} Next: {b['next_action']}")
    if metrics.get("latest_fusion"):
        public_fusion = _public_latest_fusion_audit(metrics["latest_fusion"])
        lines.extend(["", "## Latest Fusion Audit", "", "```json", json.dumps(public_fusion, ensure_ascii=False, indent=2), "```"])
    if metrics.get("candidate_lifecycle_summary"):
        lifecycle = metrics["candidate_lifecycle_summary"]
        lines.extend(
            [
                "",
                "## Future Candidate Lifecycle",
                "",
                f"- total candidates: {int(lifecycle.get('total_candidates') or 0):,}",
                f"- radar eligible: {int(lifecycle.get('radar_eligible') or 0):,}",
                "",
                "| state | count |",
                "| --- | ---: |",
            ]
        )
        for state, count in sorted((lifecycle.get("state_counts") or {}).items()):
            lines.append(f"| {state} | {int(count):,} |")
        if lifecycle.get("missing_gate_counts"):
            lines.extend(["", "### Missing Claim Gates", "", "| gate | count |", "| --- | ---: |"])
            for gate, count in sorted(
                lifecycle["missing_gate_counts"].items(),
                key=lambda kv: (-kv[1], kv[0]),
            ):
                lines.append(f"| {gate} | {int(count):,} |")
    lines.extend(
        [
            "",
            "## Product Interpretation",
            "",
            "- `candidate_generator_only` means the graph can suggest where to inspect, but Radar must stay empty.",
            "- `actionable_but_not_high_confidence` means Claim Cards are complete but still exploratory.",
            "- `decision_grade_available` requires high-confidence Claim Cards with calibrated future evidence and strong section evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_audit(
    db_main: Path,
    db_v14: Path,
    out_dir: Path,
    topic_gap_queue: Path | None = None,
) -> dict[str, Any]:
    lifecycle = run_lifecycle_audit(db_main, db_v14, out_dir, write_table=True)
    metrics = collect_metrics(db_main, db_v14, topic_gap_queue=topic_gap_queue)
    metrics["candidate_lifecycle_summary"] = lifecycle["summary"]
    metrics["section_frontfill_state"] = select_section_frontfill_state(Path("."))
    metrics["openalex_frontfill_state"] = select_openalex_frontfill_state(Path("."))
    metrics["reference_relink_state"] = select_reference_relink_state(Path("."), out_dir)
    metrics["cited_work_backfill_queue_state"] = load_cited_work_backfill_state(
        Path("data/v14b/cited_work_backfill_queue.csv")
    )
    metrics["cited_work_backfill_run_state"] = load_cited_work_backfill_run_state(
        out_dir / "cited_work_backfill_run.json"
    )
    metrics["topic_gap_section_triage_state"] = load_topic_gap_section_triage_state(
        out_dir / "topic_gap_section_evidence_audit.json"
    )
    metrics["topic_gap_no_target_inspection_state"] = load_topic_gap_no_target_inspection_state(
        out_dir / "topic_gap_no_target_inspection.json"
    )
    blockers = classify_blockers(metrics)
    level = readiness_level(metrics, blockers)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = render_markdown(metrics, blockers, level)
    md_path = out_dir / "direction_readiness_audit.md"
    json_path = out_dir / "direction_readiness_audit.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(
        json.dumps({"metrics": metrics, "blockers": blockers, "readiness_level": level}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"readiness_level": level, "blockers": blockers, "report": str(md_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit future direction and Claim Card readiness.")
    parser.add_argument("--db", default="db/echelon_library.sqlite3")
    parser.add_argument("--db-v14", default="db/v14_pilot.sqlite3")
    parser.add_argument("--out-dir", default="reports/v14b_pilot")
    parser.add_argument("--topic-gap-queue", default="data/v14b/topic_evidence_gap_delta_queue.csv")
    args = parser.parse_args()
    result = run_audit(Path(args.db), Path(args.db_v14), Path(args.out_dir), topic_gap_queue=Path(args.topic_gap_queue))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
