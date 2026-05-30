#!/usr/bin/env python3
"""Prevent targeted topic-gap repair from competing with broad section ingest."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


DEFAULT_PATTERN = "step5s_section_ingest"
OVERRIDE_ENV = "V14B_ALLOW_CONCURRENT_TOPIC_GAP_REPAIR"


def _truthy_env(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def _is_active_section_ingest_line(line: str, pattern: str = DEFAULT_PATTERN) -> bool:
    if pattern not in line:
        return False
    ignored_fragments = (
        "watch_step5s_section_ingest.py",
        "guard_topic_gap_repair.py",
        "run_after_frontfill_product_chain.py",
        "SCREEN -dmS",
        "login -pflq",
    )
    return not any(fragment in line for fragment in ignored_fragments)


def active_section_ingest_commands(
    commands: list[str],
    pattern: str = DEFAULT_PATTERN,
) -> list[str]:
    return [
        line.strip()
        for line in commands
        if _is_active_section_ingest_line(line, pattern)
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
        description=(
            "Guard topic-gap section repair so it does not run while the broad "
            "section evidence ingest is active."
        )
    )
    parser.add_argument("--pattern", default=DEFAULT_PATTERN)
    parser.add_argument(
        "--allow-concurrent",
        action="store_true",
        help=f"Override the guard. Equivalent to setting {OVERRIDE_ENV}=1.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    active = active_section_ingest_commands(process_commands(), args.pattern)
    if not active:
        print("topic-gap repair guard: no active broad section ingest detected")
        return 0
    if args.allow_concurrent or _truthy_env(OVERRIDE_ENV):
        print(
            "topic-gap repair guard: override enabled; continuing despite active section ingest",
            file=sys.stderr,
        )
        return 0
    print(
        "topic-gap repair guard: active broad section ingest detected; "
        "wait for it to finish before running make topic-gap-repair",
        file=sys.stderr,
    )
    for line in active[:5]:
        print(f"  {line}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
