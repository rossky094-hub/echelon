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
import pathlib
import re
import shlex
import sqlite3
import subprocess
import time
from typing import Optional

PROGRESS_RE = re.compile(r"\|\s*(\d+)\/(\d+)\s*\[(\d+):(\d+)<")


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


def get_progress(progress_log: pathlib.Path) -> str:
    if not progress_log.exists():
        return "progress=na"
    text = progress_log.read_text(errors="ignore")
    chunks = [c for c in text.replace("\n", "\r").split("\r") if "Step5s sections:" in c and "/1000" in c]
    if not chunks:
        return "progress=na"
    last = chunks[-1]
    m = PROGRESS_RE.search(last)
    if not m:
        return "progress=na"
    done = int(m.group(1))
    total = int(m.group(2))
    mm = int(m.group(3))
    ss = int(m.group(4))
    elapsed = mm * 60 + ss
    sec_per_item = (elapsed / done) if done else 0.0
    eta_min = ((total - done) * sec_per_item / 60.0) if done else 0.0
    return f"done={done}/{total} elapsed_s={elapsed} sec_per_item={sec_per_item:.2f} eta_min={eta_min:.1f}"


def append_log(log_file: pathlib.Path, message: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(message.rstrip() + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch Step5s section ingest until done.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--db-main", default="db/echelon_library.sqlite3")
    parser.add_argument("--db-v14", default="db/v14_pilot.sqlite3")
    parser.add_argument("--progress-log", default="logs/v14b/e2e_product_chain_run_20260529_074838_cont_section_single.log")
    parser.add_argument("--log-file", default="logs/v14b/section_watchdog.log")
    parser.add_argument("--interval-sec", type=int, default=1800)
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
    restart_argv = shlex.split(args.restart_cmd)

    append_log(log_file, f"[START] {utc_now()} step5s watchdog interval={args.interval_sec}s")

    while True:
        ts = utc_now()
        pid = find_step5s_pid(args.pid_pattern)
        status = get_step5s_status(db_v14)
        rows, papers = get_section_counts(db_main)
        progress = get_progress(progress_log)
        append_log(
            log_file,
            f"[{ts}] pid={pid or 'none'} status={status} rows={rows} papers={papers} {progress}",
        )

        if not pid:
            if status == "done":
                append_log(log_file, f"[{ts}] step5s done; watchdog exit")
                break
            append_log(log_file, f"[{ts}] step5s missing and not done; restart: {' '.join(restart_argv)}")
            subprocess.Popen(restart_argv, cwd=str(repo_root))
            time.sleep(15)

        time.sleep(max(60, int(args.interval_sec)))


if __name__ == "__main__":
    main()
