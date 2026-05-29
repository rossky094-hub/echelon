#!/usr/bin/env python3
"""Run the downstream product chain once evidence frontfill is ready.

This script is intentionally gate-driven.  The project goal is decision-grade
Topic Dossiers and Claim Cards, so the downstream chain should not silently
promote weak evidence just because a crawler process exists.  The gates are
configurable, and `--force` is available for partial-data smoke tests.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
from datetime import datetime


DEFAULT_STEPS = (
    "limitation",
    "fusion",
    "first-principles",
    "mutation",
    "layout",
    "report",
    "visual-graph",
    "goal-audit",
)

STEP_MODULES = {
    "limitation": ("echelon.v14b.step5c_limitation", ()),
    "fusion": ("echelon.v14b.step6_fusion", ()),
    "first-principles": ("echelon.v14b.step13_first_principles_history", ("--out-dir", "reports/v14b_pilot")),
    "mutation": ("echelon.v14b.step7_mutation", ()),
    "layout": ("echelon.v14b.step8_layout", ()),
    "report": ("echelon.v14b.step9_report", ()),
    "visual-graph": ("echelon.v14b.step10_visual_graph_builder", ()),
    "goal-audit": ("echelon.v14b.step12_goal_alignment_audit", ("--out-dir", "reports/v14b_pilot")),
}

EVIDENCE_SENSITIVE_STEPS = {
    "limitation",
    "fusion",
    "mutation",
    "layout",
    "report",
}


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def log(path: pathlib.Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{utc_now()}] {message}"
    print(line)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def scalar(conn: sqlite3.Connection, sql: str, default=0):
    try:
        row = conn.execute(sql).fetchone()
    except sqlite3.Error:
        return default
    return row[0] if row else default


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def collect_metrics(db_main: pathlib.Path, db_v14: pathlib.Path) -> dict:
    conn = sqlite3.connect(str(db_main))
    try:
        papers = int(scalar(conn, "SELECT COUNT(*) FROM papers") or 0)
        openalex_w = int(
            scalar(
                conn,
                "SELECT COUNT(*) FROM papers WHERE openalex_id LIKE 'W%' OR openalex_id LIKE 'https://openalex.org/W%'",
            )
            or 0
        )
        primary_field = int(
            scalar(conn, "SELECT COUNT(*) FROM papers WHERE primary_field_id IS NOT NULL AND primary_field_id <> ''")
            or 0
        )
        section_rows = 0
        section_papers = 0
        primary_section_papers = 0
        if table_exists(conn, "paper_sections"):
            section_rows = int(scalar(conn, "SELECT COUNT(*) FROM paper_sections") or 0)
            section_papers = int(scalar(conn, "SELECT COUNT(DISTINCT paper_id) FROM paper_sections") or 0)
            primary_section_papers = int(
                scalar(
                    conn,
                    """
                    SELECT COUNT(DISTINCT paper_id)
                    FROM paper_sections
                    WHERE section_name IN (
                        'limitation','limitations','discussion','conclusion','conclusions',
                        'future_work','future directions','results','error_analysis',
                        'ablation','method','methods','experiments'
                    )
                      AND length(trim(section_text)) >= 80
                    """,
                )
                or 0
            )
    finally:
        conn.close()

    v14_counts: dict[str, int] = {}
    if db_v14.exists():
        conn_v14 = sqlite3.connect(str(db_v14))
        try:
            for table in (
                "limitation_atoms",
                "limitation_resolutions",
                "future_directions",
                "direction_claim_cards",
                "visual_nodes",
                "visual_edges",
            ):
                v14_counts[table] = int(scalar(conn_v14, f"SELECT COUNT(*) FROM {table}") or 0) if table_exists(conn_v14, table) else 0
        finally:
            conn_v14.close()
    return {
        "papers": papers,
        "openalex_w": openalex_w,
        "openalex_w_rate": openalex_w / max(1, papers),
        "primary_field": primary_field,
        "primary_field_rate": primary_field / max(1, papers),
        "section_rows": section_rows,
        "section_papers": section_papers,
        "primary_section_papers": primary_section_papers,
        "primary_section_rate": primary_section_papers / max(1, papers),
        "v14": v14_counts,
    }


def frontfill_ready(metrics: dict, args: argparse.Namespace) -> tuple[bool, list[str]]:
    failures = []
    if metrics["primary_section_papers"] < args.min_primary_section_papers:
        failures.append(
            f"primary_section_papers {metrics['primary_section_papers']} < {args.min_primary_section_papers}"
        )
    if metrics["openalex_w_rate"] < args.min_openalex_w_rate:
        failures.append(
            f"openalex_w_rate {metrics['openalex_w_rate']:.3f} < {args.min_openalex_w_rate:.3f}"
        )
    if metrics["primary_field_rate"] < args.min_primary_field_rate:
        failures.append(
            f"primary_field_rate {metrics['primary_field_rate']:.3f} < {args.min_primary_field_rate:.3f}"
        )
    return not failures, failures


def build_step_command(
    *,
    python_exe: str,
    step: str,
    db_main: pathlib.Path,
    db_v14: pathlib.Path,
    corpus_id: str | None = None,
    force_rerun: bool = True,
) -> list[str]:
    if step not in STEP_MODULES:
        return ["make", step]

    module, extra = STEP_MODULES[step]
    cmd = [
        python_exe,
        "-m",
        module,
        "--db",
        str(db_main),
        "--db-v14",
        str(db_v14),
    ]
    if corpus_id:
        cmd += ["--corpus-id", corpus_id]
    if force_rerun and step in EVIDENCE_SENSITIVE_STEPS:
        cmd.append("--no-resume")
    cmd.extend(extra)
    return cmd


def run_step(
    repo_root: pathlib.Path,
    step: str,
    env: dict,
    log_file: pathlib.Path,
    *,
    python_exe: str,
    db_main: pathlib.Path,
    db_v14: pathlib.Path,
    corpus_id: str | None,
    force_rerun: bool,
) -> None:
    cmd = build_step_command(
        python_exe=python_exe,
        step=step,
        db_main=db_main,
        db_v14=db_v14,
        corpus_id=corpus_id,
        force_rerun=force_rerun,
    )
    log(log_file, f"RUN {' '.join(cmd)}")
    with log_file.open("a", encoding="utf-8") as f:
        p = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=env,
            text=True,
            stdout=f,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if p.returncode != 0:
        raise RuntimeError(f"step {step} failed with exit={p.returncode}; see {log_file}")
    log(log_file, f"DONE {step}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run post-frontfill V14B product chain when evidence gates pass.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--db-main", default="db/echelon_library.sqlite3")
    parser.add_argument("--db-v14", default="db/v14_pilot.sqlite3")
    parser.add_argument("--log-file", default="logs/v14b/after_frontfill_product_chain.log")
    parser.add_argument("--min-primary-section-papers", type=int, default=int(os.getenv("V14B_MIN_PRIMARY_SECTION_PAPERS", "8000")))
    parser.add_argument("--min-openalex-w-rate", type=float, default=float(os.getenv("V14B_MIN_OPENALEX_W_RATE", "0.70")))
    parser.add_argument("--min-primary-field-rate", type=float, default=float(os.getenv("V14B_MIN_PRIMARY_FIELD_RATE", "0.95")))
    parser.add_argument("--step", action="append", default=None)
    parser.add_argument("--force", action="store_true", help="Run even if evidence gates are not ready; use only for smoke tests.")
    parser.add_argument("--corpus-id", default=os.getenv("V14B_CORPUS_ID") or None)
    parser.add_argument(
        "--resume-downstream",
        action="store_true",
        help=(
            "Allow checkpoint resume for evidence-sensitive downstream steps. "
            "Default is to rebuild Step5c/6/7/8/9 after frontfill so new "
            "section/OpenAlex evidence actually reaches Claim Cards and reports."
        ),
    )
    args = parser.parse_args(argv)

    repo_root = pathlib.Path(args.repo_root).resolve()
    db_main = (repo_root / args.db_main).resolve()
    db_v14 = (repo_root / args.db_v14).resolve()
    log_file = (repo_root / args.log_file).resolve()
    metrics = collect_metrics(db_main, db_v14)
    ready, failures = frontfill_ready(metrics, args)
    log(log_file, "FRONTFILL_METRICS " + json.dumps(metrics, ensure_ascii=False, sort_keys=True))
    if failures:
        log(log_file, "FRONTFILL_WAIT " + "; ".join(failures))
    if not ready and not args.force:
        return 0

    env = os.environ.copy()
    env.setdefault("OMP_NUM_THREADS", "4")
    env.setdefault("VECLIB_MAXIMUM_THREADS", "4")
    env.setdefault("MKL_NUM_THREADS", "4")
    env.setdefault("NUMEXPR_NUM_THREADS", "4")
    env.setdefault("V14B_EMBEDDING_BATCH_SIZE", "16")
    env.setdefault("V14B_AUDIT_FAIL_ON", "none")
    force_rerun = not args.resume_downstream
    for step in (args.step or list(DEFAULT_STEPS)):
        run_step(
            repo_root,
            step,
            env,
            log_file,
            python_exe=sys.executable or "python3",
            db_main=db_main,
            db_v14=db_v14,
            corpus_id=args.corpus_id,
            force_rerun=force_rerun,
        )
    metrics_after = collect_metrics(db_main, db_v14)
    log(log_file, "PRODUCT_CHAIN_DONE " + json.dumps(metrics_after, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        raise
