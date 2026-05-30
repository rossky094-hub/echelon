#!/usr/bin/env python3
"""Prevent OpenAlex backfill from ignoring active 429 cooldowns."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echelon.v14b.direction_readiness_audit import select_openalex_frontfill_state


OVERRIDE_ENV = "V14B_ALLOW_OPENALEX_BACKFILL_DURING_COOLDOWN"
DUPLICATE_OVERRIDE_ENV = "V14B_ALLOW_CONCURRENT_OPENALEX_BACKFILL"
PROCESS_PATTERN = "echelon.v14b.step0_openalex_backfill"


def _truthy_env(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def _is_active_openalex_backfill_line(line: str, pattern: str = PROCESS_PATTERN) -> bool:
    if pattern not in line:
        return False
    ignored_fragments = (
        "guard_openalex_backfill.py",
        "rg step0_openalex_backfill",
        "rg 'step5s_section_ingest",
    )
    return not any(fragment in line for fragment in ignored_fragments)


def active_openalex_backfill_commands(
    commands: list[str],
    pattern: str = PROCESS_PATTERN,
) -> list[str]:
    return [
        line.strip()
        for line in commands
        if _is_active_openalex_backfill_line(line, pattern)
    ]


def process_commands() -> list[str]:
    proc = subprocess.run(
        ["ps", "-axo", "command="],
        check=False,
        text=True,
        capture_output=True,
    )
    return (proc.stdout or "").splitlines()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guard OpenAlex backfill against duplicate runs and active 429 cooldowns."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--process-pattern", default=PROCESS_PATTERN)
    parser.add_argument(
        "--allow-cooldown",
        action="store_true",
        help=f"Override an active OpenAlex cooldown. Equivalent to {OVERRIDE_ENV}=1.",
    )
    parser.add_argument(
        "--allow-concurrent",
        action="store_true",
        help=f"Override duplicate-process protection. Equivalent to {DUPLICATE_OVERRIDE_ENV}=1.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    active = active_openalex_backfill_commands(process_commands(), args.process_pattern)
    if active and not (args.allow_concurrent or _truthy_env(DUPLICATE_OVERRIDE_ENV)):
        print(
            "OpenAlex backfill guard: active OpenAlex backfill already detected; "
            "not starting a duplicate run",
            file=sys.stderr,
        )
        for line in active[:5]:
            print(f"  {line}", file=sys.stderr)
        return 4

    state = select_openalex_frontfill_state(Path(args.repo_root))
    status = state.get("status")
    cooldown_remaining = int(state.get("cooldown_remaining_s") or 0)
    if (
        status == "cooling_down_or_stopped"
        and cooldown_remaining > 0
        and not (args.allow_cooldown or _truthy_env(OVERRIDE_ENV))
    ):
        hours = cooldown_remaining / 3600.0
        print(
            "OpenAlex backfill guard: active 429 cooldown detected; "
            f"wait {hours:.1f}h before running make openalex-backfill",
            file=sys.stderr,
        )
        print(
            f"  latest_log={state.get('log_path')} processed={state.get('processed')}/"
            f"{state.get('total')} cooldown_until={state.get('cooldown_until')}",
            file=sys.stderr,
        )
        return 3

    print(f"OpenAlex backfill guard: ok status={status or 'unknown'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
