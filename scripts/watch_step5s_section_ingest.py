#!/usr/bin/env python3
"""Watchdog for V14B Step5s section ingest.

Behavior:
- Polls process status, DB counters, and progress log every interval.
- If Step5s process is missing and run_meta status is not done, restarts Step5s.
- Exits automatically when Step5s is marked done.
"""

from __future__ import annotations

import argparse
import datetime as dt
import errno
import json
import pathlib
import re
import shlex
import sqlite3
import subprocess
import time
from typing import Optional

from echelon.v14b.step5s_section_ingest import SECTION_PARSER_CONTRACT_VERSION, SECTION_PARSER_NAME

PROGRESS_RE = re.compile(
    r"(?P<done>\d+)\s*/\s*(?P<total>\d+)\s*"
    r"\[(?P<elapsed>(?:\d+:)?\d{1,2}:\d{2})<"
)


def utc_now() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def run(cmd: list[str], cwd: Optional[pathlib.Path] = None) -> str:
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=False, text=True, capture_output=True)
    except OSError as exc:
        if exc.errno == errno.EPERM:
            return "__permission_denied__"
        raise
    return (p.stdout or "").strip()


def find_step5s_pid(pattern: str) -> str:
    out = run(["ps", "-axo", "pid=,command="])
    if out == "__permission_denied__":
        return "unknown"
    if not out:
        return ""
    for line in out.splitlines():
        if "watch_step5s_section_ingest.py" in line:
            continue
        if "SCREEN -dmS" in line or "login -pflq" in line:
            continue
        if "echelon.v14b.step5s_section_ingest" not in line and "step5s_section_ingest.py" not in line:
            continue
        if pattern not in line:
            continue
        return line.split(maxsplit=1)[0].strip()
    return ""


def get_step5s_status(db_v14: pathlib.Path) -> str:
    conn = sqlite3.connect(str(db_v14))
    try:
        row = conn.execute(
            "SELECT COALESCE(status,'none') FROM v14b_run_meta WHERE step_name='step5s_section_ingest' LIMIT 1"
        ).fetchone()
        return str((row[0] if row else "none") or "none").strip()
    finally:
        conn.close()


def get_section_counts(db_main: pathlib.Path) -> tuple[int, int]:
    conn = sqlite3.connect(str(db_main))
    try:
        row = conn.execute("SELECT COUNT(*), COUNT(DISTINCT paper_id) FROM paper_sections").fetchone()
        if not row:
            return 0, 0
        return int(row[0] or 0), int(row[1] or 0)
    finally:
        conn.close()


def _table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def get_latest_attempt_parser_contract(db_main: pathlib.Path) -> dict:
    """Return the latest Step5s attempt parser metadata, if available."""
    conn = sqlite3.connect(str(db_main))
    try:
        cols = _table_cols(conn, "section_ingest_attempts")
        if not cols:
            return {}
        parser_name_expr = "parser_name" if "parser_name" in cols else "NULL AS parser_name"
        contract_expr = (
            "parser_contract_version"
            if "parser_contract_version" in cols
            else "NULL AS parser_contract_version"
        )
        row = conn.execute(
            f"""
            SELECT paper_id, attempt_ts, outcome, {parser_name_expr}, {contract_expr}
            FROM section_ingest_attempts
            ORDER BY attempt_ts DESC, attempt_id DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return {}
        return {
            "paper_id": row[0],
            "attempt_ts": row[1],
            "outcome": row[2],
            "parser_name": row[3],
            "parser_contract_version": row[4],
        }
    finally:
        conn.close()


def has_parser_contract_mismatch(attempt: dict) -> bool:
    if not attempt:
        return False
    parser_name = str(attempt.get("parser_name") or "").strip()
    contract = str(attempt.get("parser_contract_version") or "").strip()
    if contract:
        return contract != SECTION_PARSER_CONTRACT_VERSION
    if parser_name:
        return parser_name != SECTION_PARSER_NAME
    return True


PRIMARY_SECTION_NAMES = {
    "limitation",
    "limitations",
    "discussion",
    "conclusion",
    "conclusions",
    "future_work",
    "future works",
    "future directions",
    "results",
    "error_analysis",
    "error analysis",
    "ablation",
    "method",
    "methods",
    "experiments",
    "experiment",
}


def get_primary_section_contract_counts(db_main: pathlib.Path) -> tuple[int, int]:
    """Count all primary sections and the subset parsed under the current contract."""
    conn = sqlite3.connect(str(db_main))
    try:
        has_meta = "section_meta_json" in _table_cols(conn, "paper_sections")
        paper_ids = conn.execute(
            """
            SELECT DISTINCT paper_id, section_name, section_text
                   {meta_select}
            FROM paper_sections
            WHERE paper_id IS NOT NULL
            """.format(meta_select=", section_meta_json" if has_meta else "")
        ).fetchall()
        # Keep this small and explicit: the watchdog uses the count as a value gate,
        # not as a scientific metric, so we require a minimum text length.
        primary: set[str] = set()
        current_contract: set[str] = set()
        for row in paper_ids:
            pid, name, text = row[:3]
            if (
                str(name or "").strip().lower() not in PRIMARY_SECTION_NAMES
                or len(str(text or "").strip()) < 80
            ):
                continue
            paper_id = str(pid)
            primary.add(paper_id)
            if has_meta:
                try:
                    meta = json.loads(row[3] or "{}")
                except Exception:
                    meta = {}
                if meta.get("parser_contract_version") == SECTION_PARSER_CONTRACT_VERSION:
                    current_contract.add(paper_id)
        return len(primary), len(current_contract)
    finally:
        conn.close()


def get_primary_section_papers(db_main: pathlib.Path) -> int:
    """Count papers with primary local section evidence, regardless of parser contract."""
    primary, _current_contract = get_primary_section_contract_counts(db_main)
    return primary


def is_step5s_done(status: str, progress_data: dict) -> bool:
    if str(status or "").strip().lower() in {"done", "completed", "success", "succeeded"}:
        return True
    done = progress_data.get("done")
    total = progress_data.get("total")
    return done is not None and total is not None and int(done) >= int(total) > 0


def _elapsed_to_seconds(raw: str) -> int:
    parts = [int(x) for x in raw.split(":")]
    if len(parts) == 2:
        mm, ss = parts
        return mm * 60 + ss
    if len(parts) == 3:
        hh, mm, ss = parts
        return hh * 3600 + mm * 60 + ss
    return 0


def parse_progress(progress_log: pathlib.Path) -> dict:
    if not progress_log.exists():
        return {"progress": "na", "done": None, "total": None, "elapsed_s": None}
    text = progress_log.read_text(errors="ignore")
    chunks = [
        c for c in text.replace("\n", "\r").split("\r")
        if "Step5s sections:" in c
    ]
    if not chunks:
        return {"progress": "na", "done": None, "total": None, "elapsed_s": None}
    last = chunks[-1]
    m = PROGRESS_RE.search(last)
    if not m:
        return {"progress": "na", "done": None, "total": None, "elapsed_s": None}
    done = int(m.group("done"))
    total = int(m.group("total"))
    elapsed = _elapsed_to_seconds(m.group("elapsed"))
    sec_per_item = (elapsed / done) if done else 0.0
    eta_min = ((total - done) * sec_per_item / 60.0) if done else 0.0
    return {
        "progress": "ok",
        "done": done,
        "total": total,
        "elapsed_s": elapsed,
        "sec_per_item": sec_per_item,
        "eta_min": eta_min,
        "raw": last[-240:],
    }


def get_progress(progress_log: pathlib.Path) -> str:
    data = parse_progress(progress_log)
    if data.get("progress") != "ok":
        return "progress=na"
    return (
        f"done={data['done']}/{data['total']} "
        f"elapsed_s={data['elapsed_s']} "
        f"sec_per_item={float(data['sec_per_item']):.2f} "
        f"eta_min={float(data['eta_min']):.1f}"
    )


def append_log(log_file: pathlib.Path, message: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(message.rstrip() + "\n")


def handoff_reason(primary_section_papers: int, threshold: int) -> str:
    if primary_section_papers >= threshold:
        return "frontfill_threshold_met"
    return "frontfill_threshold_not_met_downstream_gate_will_hold"


def _kill_pid(pid: str) -> None:
    if not pid:
        return
    subprocess.run(["kill", "-TERM", pid], check=False)


def _load_state(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _write_state(path: pathlib.Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch Step5s section ingest until done.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--db-main", default="db/echelon_library.sqlite3")
    parser.add_argument("--db-v14", default="db/v14_pilot.sqlite3")
    parser.add_argument("--progress-log", default="logs/v14b/e2e_product_chain_run_20260529_074838_cont_section_single.log")
    parser.add_argument("--log-file", default="logs/v14b/section_watchdog.log")
    parser.add_argument("--state-file", default="logs/v14b/section_watchdog_state.json")
    parser.add_argument("--interval-sec", type=int, default=1800)
    parser.add_argument("--stale-intervals", type=int, default=3)
    parser.add_argument("--stall-min-sec", type=int, default=7200)
    parser.add_argument("--low-yield-progress-items", type=int, default=200)
    parser.add_argument(
        "--soft-stall-intervals",
        type=int,
        default=2,
        help=(
            "Number of consecutive low-yield evidence intervals before marking a "
            "soft stall. This does not kill Step5s; it makes evidence debt visible."
        ),
    )
    parser.add_argument("--no-restart-on-stall", action="store_true")
    parser.add_argument(
        "--no-restart-on-contract-mismatch",
        action="store_true",
        help=(
            "Do not terminate a running Step5s process when latest attempts show "
            "an older parser or missing parser-contract metadata."
        ),
    )
    parser.add_argument(
        "--restart-cmd",
        default="python3 -m echelon.v14b.step5s_section_ingest --db db/echelon_library.sqlite3 --db-v14 db/v14_pilot.sqlite3 --top-n 1200",
    )
    parser.add_argument(
        "--pid-pattern",
        default="python -m echelon.v14b.step5s_section_ingest --db db/echelon_library.sqlite3 --db-v14 db/v14_pilot.sqlite3 --top-n 1200",
    )
    parser.add_argument(
        "--handoff-cmd",
        default="",
        help=(
            "Optional command to start once top-N frontfill is complete but primary "
            "section evidence remains below threshold."
        ),
    )
    parser.add_argument(
        "--handoff-min-primary-section-papers",
        type=int,
        default=8000,
        help=(
            "Primary-section paper count used in the handoff log. The downstream "
            "post-frontfill chain owns the real evidence gates."
        ),
    )
    args = parser.parse_args()

    repo_root = pathlib.Path(args.repo_root).resolve()
    db_main = (repo_root / args.db_main).resolve()
    db_v14 = (repo_root / args.db_v14).resolve()
    progress_log = (repo_root / args.progress_log).resolve()
    log_file = (repo_root / args.log_file).resolve()
    state_file = (repo_root / args.state_file).resolve()
    restart_argv = shlex.split(args.restart_cmd)
    state = _load_state(state_file)
    last_rows = int(state.get("rows") or 0)
    last_papers = int(state.get("papers") or 0)
    last_done = state.get("done")
    last_change_ts = float(state.get("last_change_ts") or time.time())
    stale_intervals = int(state.get("stale_intervals") or 0)
    last_evidence_rows = int(state.get("last_evidence_rows", last_rows) or 0)
    last_evidence_papers = int(state.get("last_evidence_papers", last_papers) or 0)
    last_evidence_done = state.get("last_evidence_done", last_done)
    last_evidence_ts = float(state.get("last_evidence_ts") or last_change_ts)
    low_yield_intervals = int(state.get("low_yield_intervals") or 0)
    last_current_contract_primary = int(state.get("current_contract_primary_section_papers") or 0)
    last_contract_evidence_done = state.get("last_contract_evidence_done", last_done)
    last_contract_evidence_ts = float(state.get("last_contract_evidence_ts") or last_change_ts)
    current_contract_low_yield_intervals = int(state.get("current_contract_low_yield_intervals") or 0)
    contract_mismatch_restart_attempt_ts = state.get("contract_mismatch_restart_attempt_ts")

    append_log(log_file, f"[START] {utc_now()} step5s watchdog interval={args.interval_sec}s")

    while True:
        ts = utc_now()
        pid = find_step5s_pid(args.pid_pattern)
        status = get_step5s_status(db_v14)
        rows, papers = get_section_counts(db_main)
        progress_data = parse_progress(progress_log)
        progress = get_progress(progress_log)
        done = progress_data.get("done")
        primary_section_papers, current_contract_primary_section_papers = get_primary_section_contract_counts(db_main)
        latest_attempt_contract = get_latest_attempt_parser_contract(db_main)
        parser_contract_mismatch = has_parser_contract_mismatch(latest_attempt_contract)
        log_mtime = progress_log.stat().st_mtime if progress_log.exists() else 0.0
        now = time.time()

        db_changed = rows != last_rows or papers != last_papers
        progress_changed = done is not None and done != last_done
        if db_changed or progress_changed:
            stale_intervals = 0
            last_change_ts = now
        else:
            stale_intervals += 1

        rows_delta = rows - last_rows
        papers_delta = papers - last_papers
        done_delta = (int(done) - int(last_done)) if done is not None and last_done is not None else None
        evidence_changed = rows != last_evidence_rows or papers != last_evidence_papers
        if evidence_changed or last_evidence_done is None:
            last_evidence_rows = rows
            last_evidence_papers = papers
            last_evidence_done = done
            last_evidence_ts = now
            low_yield_intervals = 0
        no_evidence_done_delta = (
            int(done) - int(last_evidence_done)
            if done is not None and last_evidence_done is not None
            else 0
        )
        no_evidence_elapsed_s = int(max(0, now - last_evidence_ts))
        low_yield = (
            no_evidence_done_delta >= int(args.low_yield_progress_items)
            and rows == last_evidence_rows
            and papers == last_evidence_papers
        )
        if low_yield:
            low_yield_intervals += 1
        elif evidence_changed:
            low_yield_intervals = 0
        evidence_soft_stall = low_yield and low_yield_intervals >= int(args.soft_stall_intervals)
        contract_evidence_changed = current_contract_primary_section_papers != last_current_contract_primary
        if contract_evidence_changed or last_contract_evidence_done is None:
            last_current_contract_primary = current_contract_primary_section_papers
            last_contract_evidence_done = done
            last_contract_evidence_ts = now
            current_contract_low_yield_intervals = 0
        no_current_contract_done_delta = (
            int(done) - int(last_contract_evidence_done)
            if done is not None and last_contract_evidence_done is not None
            else 0
        )
        no_current_contract_elapsed_s = int(max(0, now - last_contract_evidence_ts))
        contract_low_yield = (
            no_current_contract_done_delta >= int(args.low_yield_progress_items)
            and current_contract_primary_section_papers == last_current_contract_primary
        )
        if contract_low_yield:
            current_contract_low_yield_intervals += 1
        elif contract_evidence_changed:
            current_contract_low_yield_intervals = 0
        contract_evidence_soft_stall = (
            contract_low_yield
            and current_contract_low_yield_intervals >= int(args.soft_stall_intervals)
        )
        hard_stall = (
            pid
            and pid != "unknown"
            and stale_intervals >= int(args.stale_intervals)
            and now - last_change_ts >= int(args.stall_min_sec)
            and (not log_mtime or now - log_mtime >= int(args.stall_min_sec))
        )
        append_log(
            log_file,
            (
                f"[{ts}] pid={pid or 'none'} status={status} rows={rows} papers={papers} "
                f"primary_section_papers={primary_section_papers} "
                f"current_contract_primary_section_papers={current_contract_primary_section_papers} "
                f"delta_rows={rows_delta} delta_papers={papers_delta} "
                f"no_evidence_done_delta={no_evidence_done_delta} "
                f"no_current_contract_done_delta={no_current_contract_done_delta} "
                f"no_evidence_elapsed_s={no_evidence_elapsed_s} "
                f"no_current_contract_elapsed_s={no_current_contract_elapsed_s} "
                f"low_yield_intervals={low_yield_intervals} "
                f"current_contract_low_yield_intervals={current_contract_low_yield_intervals} "
                f"latest_attempt_parser={latest_attempt_contract.get('parser_name') or 'unknown'} "
                f"latest_attempt_contract={latest_attempt_contract.get('parser_contract_version') or 'unknown'} "
                f"parser_contract_mismatch={int(parser_contract_mismatch)} "
                f"stale_intervals={stale_intervals} {progress}"
            ),
        )
        if parser_contract_mismatch:
            append_log(
                log_file,
                (
                    f"[{ts}] SECTION_PARSER_CONTRACT_MISMATCH "
                    f"latest_attempt_ts={latest_attempt_contract.get('attempt_ts') or 'unknown'} "
                    f"parser={latest_attempt_contract.get('parser_name') or 'unknown'} "
                    f"contract={latest_attempt_contract.get('parser_contract_version') or 'unknown'} "
                    f"expected_parser={SECTION_PARSER_NAME} expected_contract={SECTION_PARSER_CONTRACT_VERSION}"
                ),
            )
        mismatch_attempt_ts = latest_attempt_contract.get("attempt_ts") if parser_contract_mismatch else None
        should_restart_contract_mismatch = (
            bool(pid)
            and pid != "unknown"
            and parser_contract_mismatch
            and not args.no_restart_on_contract_mismatch
            and mismatch_attempt_ts
            and mismatch_attempt_ts != contract_mismatch_restart_attempt_ts
        )
        if low_yield:
            append_log(
                log_file,
                (
                    f"[{ts}] LOW_YIELD_SCAN progress_delta={no_evidence_done_delta} "
                    f"rows_delta=0 papers_delta=0 elapsed_s={no_evidence_elapsed_s}; "
                    "crawler is alive but current candidate segment is not producing usable sections"
                ),
            )
        if evidence_soft_stall:
            append_log(
                log_file,
                (
                    f"[{ts}] SECTION_EVIDENCE_SOFT_STALL progress_delta={no_evidence_done_delta} "
                    f"low_yield_intervals={low_yield_intervals}; "
                    "keep process conservative, but treat topN as low-yield and prepare delta/frontier queue"
                ),
            )
        if contract_evidence_soft_stall:
            append_log(
                log_file,
                (
                    f"[{ts}] SECTION_CONTRACT_EVIDENCE_SOFT_STALL "
                    f"progress_delta={no_current_contract_done_delta} "
                    f"current_contract_primary_section_papers={current_contract_primary_section_papers} "
                    f"contract={SECTION_PARSER_CONTRACT_VERSION}; "
                    "crawler may be producing legacy/weak evidence, but not current parser-contract evidence"
                ),
            )
        if should_restart_contract_mismatch:
            append_log(
                log_file,
                (
                    f"[{ts}] terminate Step5s pid={pid} due to parser-contract mismatch; "
                    f"restart Step5s with current code: {' '.join(restart_argv)}"
                ),
            )
            _kill_pid(pid)
            time.sleep(20)
            subprocess.Popen(restart_argv, cwd=str(repo_root))
            contract_mismatch_restart_attempt_ts = mismatch_attempt_ts
            stale_intervals = 0
            last_change_ts = time.time()
        if hard_stall:
            append_log(
                log_file,
                (
                    f"[{ts}] HARD_STALL pid={pid} no DB/progress/log advance for "
                    f"{int(now - last_change_ts)}s"
                ),
            )
            if not args.no_restart_on_stall:
                append_log(log_file, f"[{ts}] terminate stalled Step5s pid={pid}")
                _kill_pid(pid)
                time.sleep(20)
                append_log(log_file, f"[{ts}] restart Step5s: {' '.join(restart_argv)}")
                subprocess.Popen(restart_argv, cwd=str(repo_root))
                stale_intervals = 0
                last_change_ts = time.time()

        step_done = is_step5s_done(status, progress_data)
        if step_done:
            if args.handoff_cmd:
                if not state.get("handoff_started_at"):
                    append_log(
                        log_file,
                        (
                            f"[{ts}] HANDOFF_START reason={handoff_reason(primary_section_papers, int(args.handoff_min_primary_section_papers))} "
                            f"primary_section_papers={primary_section_papers} "
                            f"threshold={args.handoff_min_primary_section_papers}: {args.handoff_cmd}"
                        ),
                    )
                    subprocess.Popen(shlex.split(args.handoff_cmd), cwd=str(repo_root))
                    state["handoff_started_at"] = ts
                    state["handoff_cmd"] = args.handoff_cmd
                else:
                    append_log(
                        log_file,
                        (
                            f"[{ts}] HANDOFF_ALREADY_STARTED at={state.get('handoff_started_at')} "
                            f"primary_section_papers={primary_section_papers}"
                        ),
                    )
            _write_state(
                state_file,
                {
                    **state,
                    "updated_at": ts,
                    "rows": rows,
                    "papers": papers,
                    "primary_section_papers": primary_section_papers,
                    "current_contract_primary_section_papers": current_contract_primary_section_papers,
                    "done": done,
                    "total": progress_data.get("total"),
                    "last_change_ts": last_change_ts,
                    "last_evidence_rows": last_evidence_rows,
                    "last_evidence_papers": last_evidence_papers,
                    "last_evidence_done": last_evidence_done,
                    "last_evidence_ts": last_evidence_ts,
                    "last_contract_evidence_done": last_contract_evidence_done,
                    "last_contract_evidence_ts": last_contract_evidence_ts,
                    "no_evidence_done_delta": no_evidence_done_delta,
                    "no_evidence_elapsed_s": no_evidence_elapsed_s,
                    "no_current_contract_done_delta": no_current_contract_done_delta,
                    "no_current_contract_elapsed_s": no_current_contract_elapsed_s,
                    "low_yield_intervals": low_yield_intervals,
                    "current_contract_low_yield_intervals": current_contract_low_yield_intervals,
                    "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
                    "latest_attempt_parser_name": latest_attempt_contract.get("parser_name"),
                    "latest_attempt_parser_contract_version": latest_attempt_contract.get("parser_contract_version"),
                    "latest_attempt_ts": latest_attempt_contract.get("attempt_ts"),
                    "parser_contract_mismatch": parser_contract_mismatch,
                    "contract_mismatch_restart_attempt_ts": contract_mismatch_restart_attempt_ts,
                    "stale_intervals": stale_intervals,
                    "status": status,
                },
            )
            append_log(log_file, f"[{ts}] step5s done; watchdog exit")
            break

        if not pid:
            if step_done:
                append_log(log_file, f"[{ts}] step5s done; watchdog exit")
                break
            append_log(log_file, f"[{ts}] step5s missing and not done; restart: {' '.join(restart_argv)}")
            subprocess.Popen(restart_argv, cwd=str(repo_root))
            if parser_contract_mismatch and mismatch_attempt_ts:
                contract_mismatch_restart_attempt_ts = mismatch_attempt_ts
            time.sleep(15)

        _write_state(
            state_file,
            {
                "updated_at": ts,
                "rows": rows,
                "papers": papers,
                "primary_section_papers": primary_section_papers,
                "current_contract_primary_section_papers": current_contract_primary_section_papers,
                "done": done,
                "total": progress_data.get("total"),
                "last_change_ts": last_change_ts,
                "last_evidence_rows": last_evidence_rows,
                "last_evidence_papers": last_evidence_papers,
                "last_evidence_done": last_evidence_done,
                "last_evidence_ts": last_evidence_ts,
                "last_contract_evidence_done": last_contract_evidence_done,
                "last_contract_evidence_ts": last_contract_evidence_ts,
                "no_evidence_done_delta": no_evidence_done_delta,
                "no_evidence_elapsed_s": no_evidence_elapsed_s,
                "no_current_contract_done_delta": no_current_contract_done_delta,
                "no_current_contract_elapsed_s": no_current_contract_elapsed_s,
                "low_yield_intervals": low_yield_intervals,
                "current_contract_low_yield_intervals": current_contract_low_yield_intervals,
                "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
                "latest_attempt_parser_name": latest_attempt_contract.get("parser_name"),
                "latest_attempt_parser_contract_version": latest_attempt_contract.get("parser_contract_version"),
                "latest_attempt_ts": latest_attempt_contract.get("attempt_ts"),
                "parser_contract_mismatch": parser_contract_mismatch,
                "contract_mismatch_restart_attempt_ts": contract_mismatch_restart_attempt_ts,
                "stale_intervals": stale_intervals,
                "status": status,
            },
        )
        last_rows = rows
        last_papers = papers
        last_done = done
        time.sleep(max(60, int(args.interval_sec)))


if __name__ == "__main__":
    main()
