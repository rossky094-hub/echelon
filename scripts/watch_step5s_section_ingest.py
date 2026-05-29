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
import json
import pathlib
import re
import shlex
import sqlite3
import subprocess
import time
from typing import Optional

PROGRESS_RE = re.compile(
    r"(?P<done>\d+)\s*/\s*(?P<total>\d+)\s*"
    r"\[(?P<elapsed>(?:\d+:)?\d{1,2}:\d{2})<"
)


def utc_now() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def run(cmd: list[str], cwd: Optional[pathlib.Path] = None) -> str:
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=False, text=True, capture_output=True)
    return (p.stdout or "").strip()


def find_step5s_pid(pattern: str) -> str:
    out = run(["ps", "-axo", "pid=,command="])
    if not out:
        return ""
    for line in out.splitlines():
        if "watch_step5s_section_ingest.py" in line:
            continue
        if "SCREEN -dmS" in line or "login -pflq" in line:
            continue
        if "step5s_section_ingest" not in line:
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
    parser.add_argument("--no-restart-on-stall", action="store_true")
    parser.add_argument(
        "--restart-cmd",
        default="python3 -m echelon.v14b.step5s_section_ingest --db db/echelon_library.sqlite3 --db-v14 db/v14_pilot.sqlite3 --top-n 1200",
    )
    parser.add_argument(
        "--pid-pattern",
        default="python -m echelon.v14b.step5s_section_ingest --db db/echelon_library.sqlite3 --db-v14 db/v14_pilot.sqlite3 --top-n 1200",
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

    append_log(log_file, f"[START] {utc_now()} step5s watchdog interval={args.interval_sec}s")

    while True:
        ts = utc_now()
        pid = find_step5s_pid(args.pid_pattern)
        status = get_step5s_status(db_v14)
        rows, papers = get_section_counts(db_main)
        progress_data = parse_progress(progress_log)
        progress = get_progress(progress_log)
        done = progress_data.get("done")
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
        low_yield = (
            rows_delta <= 0
            and done_delta is not None
            and done_delta >= int(args.low_yield_progress_items)
        )
        hard_stall = (
            pid
            and stale_intervals >= int(args.stale_intervals)
            and now - last_change_ts >= int(args.stall_min_sec)
            and (not log_mtime or now - log_mtime >= int(args.stall_min_sec))
        )
        append_log(
            log_file,
            (
                f"[{ts}] pid={pid or 'none'} status={status} rows={rows} papers={papers} "
                f"delta_rows={rows_delta} delta_papers={papers_delta} "
                f"stale_intervals={stale_intervals} {progress}"
            ),
        )
        if low_yield:
            append_log(
                log_file,
                (
                    f"[{ts}] LOW_YIELD_SCAN progress_delta={done_delta} rows_delta={rows_delta}; "
                    "crawler is alive but current candidate segment is not producing usable sections"
                ),
            )
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

        if not pid:
            if status == "done":
                append_log(log_file, f"[{ts}] step5s done; watchdog exit")
                break
            append_log(log_file, f"[{ts}] step5s missing and not done; restart: {' '.join(restart_argv)}")
            subprocess.Popen(restart_argv, cwd=str(repo_root))
            time.sleep(15)

        _write_state(
            state_file,
            {
                "updated_at": ts,
                "rows": rows,
                "papers": papers,
                "done": done,
                "total": progress_data.get("total"),
                "last_change_ts": last_change_ts,
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
