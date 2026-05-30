#!/usr/bin/env python3
"""Run the downstream product chain once evidence frontfill is ready.

This script is intentionally gate-driven.  The project goal is decision-grade
Topic Dossiers and Claim Cards, so the downstream chain should not silently
promote weak evidence just because a crawler process exists.  The gates are
configurable, and `--force` is available for partial-data smoke tests.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import shlex
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

PRIMARY_SECTION_NAMES = (
    "limitation",
    "limitations",
    "discussion",
    "conclusion",
    "conclusions",
    "future_work",
    "future work",
    "future directions",
    "results",
    "error_analysis",
    "ablation",
    "method",
    "methods",
    "experiments",
)


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
        refs = 0
        linked_refs = 0
        if table_exists(conn, "paper_references"):
            refs = int(scalar(conn, "SELECT COUNT(*) FROM paper_references") or 0)
            ref_cols = {row[1] for row in conn.execute("PRAGMA table_info(paper_references)").fetchall()}
            if "cited_paper_id_internal" in ref_cols:
                linked_refs = int(
                    scalar(
                        conn,
                        """
                        SELECT COUNT(*)
                        FROM paper_references
                        WHERE cited_paper_id_internal IS NOT NULL
                          AND cited_paper_id_internal <> ''
                        """,
                    )
                    or 0
                )
            elif "cited_paper_id" in ref_cols:
                linked_refs = int(
                    scalar(
                        conn,
                        """
                        SELECT COUNT(*)
                        FROM paper_references
                        WHERE cited_paper_id IS NOT NULL
                          AND cited_paper_id <> ''
                        """,
                    )
                    or 0
                )
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
            row = conn.execute(
                f"""
                SELECT COUNT(DISTINCT paper_id)
                FROM paper_sections
                WHERE lower(section_name) IN ({",".join("?" for _ in PRIMARY_SECTION_NAMES)})
                  AND length(trim(section_text)) >= 80
                """,
                PRIMARY_SECTION_NAMES,
            ).fetchone()
            primary_section_papers = int(row[0] if row else 0)
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
        "refs": refs,
        "linked_refs": linked_refs,
        "linked_ref_rate": linked_refs / max(1, refs),
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


def read_queue_paper_ids(queue_path: pathlib.Path) -> list[str]:
    if not queue_path.exists():
        return []
    seen: set[str] = set()
    ids: list[str] = []

    def add(raw: str) -> None:
        pid = (raw or "").strip()
        if not pid or pid == "paper_id" or pid in seen:
            return
        seen.add(pid)
        ids.append(pid)

    with queue_path.open("r", encoding="utf-8") as f:
        first = f.readline()
        f.seek(0)
        if "," in first:
            reader = csv.DictReader(f)
            for row in reader:
                if "paper_id" in row:
                    add(row.get("paper_id", ""))
                for raw in str(row.get("candidate_paper_ids") or "").replace(",", ";").split(";"):
                    add(raw)
        else:
            for line in f:
                add(line.strip().split(",")[0])
    return ids


def collect_topic_gap_queue_metrics(db_main: pathlib.Path, queue_path: pathlib.Path) -> dict:
    ids = read_queue_paper_ids(queue_path)
    metrics = {
        "queue_path": str(queue_path),
        "exists": queue_path.exists(),
        "paper_ids": len(ids),
        "primary_section_papers": 0,
        "missing_primary_section_papers": len(ids),
        "primary_section_rate": 1.0 if not ids else 0.0,
    }
    if not ids:
        return metrics

    covered_ids: set[str] = set()
    conn = sqlite3.connect(str(db_main))
    try:
        if table_exists(conn, "paper_sections"):
            section_placeholders = ",".join("?" for _ in PRIMARY_SECTION_NAMES)
            for start in range(0, len(ids), 800):
                chunk = ids[start : start + 800]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT paper_id
                    FROM paper_sections
                    WHERE paper_id IN ({placeholders})
                      AND lower(section_name) IN ({section_placeholders})
                      AND length(trim(section_text)) >= 80
                    """,
                    (*chunk, *PRIMARY_SECTION_NAMES),
                ).fetchall()
                covered_ids.update(str(row[0]) for row in rows)
    finally:
        conn.close()

    covered = len(covered_ids)
    metrics["primary_section_papers"] = covered
    metrics["missing_primary_section_papers"] = max(0, len(ids) - covered)
    metrics["primary_section_rate"] = covered / max(1, len(ids))
    return metrics


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


def topic_gap_queue_ready(metrics: dict, args: argparse.Namespace) -> tuple[bool, list[str]]:
    if args.skip_topic_gap_gate:
        return True, []
    if not metrics.get("exists") or not metrics.get("paper_ids"):
        return True, []
    rate = float(metrics.get("primary_section_rate") or 0.0)
    if rate >= args.min_topic_gap_primary_rate:
        return True, []
    return False, [
        (
            "topic_gap_primary_section_rate "
            f"{rate:.3f} < {args.min_topic_gap_primary_rate:.3f} "
            f"({metrics.get('primary_section_papers', 0)}/{metrics.get('paper_ids', 0)})"
        )
    ]


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _is_active_section_ingest_line(line: str, pattern: str = "step5s_section_ingest") -> bool:
    if pattern not in line:
        return False
    if "watch_step5s_section_ingest.py" in line:
        return False
    if "SCREEN -dmS" in line or "login -pflq" in line:
        return False
    if "run_after_frontfill_product_chain.py" in line:
        return False
    return True


def active_section_ingest(pattern: str = "step5s_section_ingest") -> bool:
    proc = subprocess.run(
        ["ps", "-axo", "command="],
        check=False,
        text=True,
        capture_output=True,
    )
    return any(
        _is_active_section_ingest_line(line, pattern)
        for line in (proc.stdout or "").splitlines()
    )


def run_topic_gap_frontfill(
    *,
    repo_root: pathlib.Path,
    env: dict,
    log_file: pathlib.Path,
    args: argparse.Namespace,
) -> bool:
    """Run the targeted topic-gap section frontfill before downstream claims.

    The normal top12000 section ingest may finish with benchmark-topic gaps still
    open.  Those papers are exactly where Topic Dossier and Claim Card quality
    is most fragile, so the product chain should repair them before generating
    new user-facing conclusions.  We only run when no section ingest process is
    already alive, so this never competes with the current PDF parser.
    """
    if not args.run_topic_gap_frontfill:
        return False
    if active_section_ingest(args.active_section_pattern):
        log(
            log_file,
            "TOPIC_GAP_FRONTFILL_WAIT active section ingest is still running; not starting a competing PDF pass",
        )
        return False
    cmd = shlex.split(args.topic_gap_frontfill_cmd)
    log(log_file, f"RUN_TOPIC_GAP_FRONTFILL {' '.join(cmd)}")
    frontfill_env = env.copy()
    frontfill_env.setdefault("V14B_SECTION_INGEST_CONCURRENCY", "1")
    frontfill_env.setdefault("V14B_SECTION_PARSE_TIMEOUT_SEC", "180")
    with log_file.open("a", encoding="utf-8") as f:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=frontfill_env,
            text=True,
            stdout=f,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"topic-gap frontfill failed with exit={proc.returncode}; see {log_file}")
    log(log_file, "DONE_TOPIC_GAP_FRONTFILL")
    return True


def should_run_topic_gap_frontfill(args: argparse.Namespace, topic_gap_ready: bool) -> bool:
    """Benchmark-topic evidence repair is allowed before broad section gates pass.

    The broad 8k primary-section target protects full-corpus claims, but the
    Topic Dossier acceptance tests depend on a much smaller set of key turning
    papers, future endpoints, branch drivers, and bottleneck evidence.  If the
    wide topN pass finishes with low yield, blocking this targeted queue behind
    the same wide gate would keep the product waiting while the most valuable
    papers remain unevidenced.
    """
    return (
        bool(args.run_topic_gap_frontfill)
        and not bool(args.force)
        and not bool(args.skip_topic_gap_gate)
        and not bool(topic_gap_ready)
    )


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
    parser.add_argument("--topic-gap-queue", default=os.getenv("V14B_TOPIC_GAP_SECTION_QUEUE", "data/v14b/topic_evidence_gap_delta_queue.csv"))
    parser.add_argument("--min-topic-gap-primary-rate", type=float, default=float(os.getenv("V14B_MIN_TOPIC_GAP_PRIMARY_RATE", "0.70")))
    parser.add_argument("--skip-topic-gap-gate", action="store_true")
    parser.add_argument(
        "--run-topic-gap-frontfill",
        action="store_true",
        default=_bool_env("V14B_RUN_TOPIC_GAP_FRONTFILL", True),
        help="When base frontfill gates pass but benchmark-topic gaps remain, run the targeted topic-gap section pass.",
    )
    parser.add_argument(
        "--no-run-topic-gap-frontfill",
        action="store_false",
        dest="run_topic_gap_frontfill",
    )
    parser.add_argument(
        "--topic-gap-frontfill-cmd",
        default=os.getenv("V14B_TOPIC_GAP_FRONTFILL_CMD", "make topic-gap-repair"),
    )
    parser.add_argument("--active-section-pattern", default="step5s_section_ingest")
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
    env = os.environ.copy()
    env.setdefault("OMP_NUM_THREADS", "4")
    env.setdefault("VECLIB_MAXIMUM_THREADS", "4")
    env.setdefault("MKL_NUM_THREADS", "4")
    env.setdefault("NUMEXPR_NUM_THREADS", "4")
    env.setdefault("V14B_EMBEDDING_BATCH_SIZE", "16")
    env.setdefault("V14B_AUDIT_FAIL_ON", "none")

    metrics = collect_metrics(db_main, db_v14)
    topic_gap_metrics = collect_topic_gap_queue_metrics(db_main, (repo_root / args.topic_gap_queue).resolve())
    metrics["topic_gap_queue"] = topic_gap_metrics
    base_ready, base_failures = frontfill_ready(metrics, args)
    topic_gap_ready, topic_gap_failures = topic_gap_queue_ready(topic_gap_metrics, args)
    log(log_file, "FRONTFILL_METRICS " + json.dumps(metrics, ensure_ascii=False, sort_keys=True))

    if should_run_topic_gap_frontfill(args, topic_gap_ready):
        if run_topic_gap_frontfill(repo_root=repo_root, env=env, log_file=log_file, args=args):
            metrics = collect_metrics(db_main, db_v14)
            topic_gap_metrics = collect_topic_gap_queue_metrics(db_main, (repo_root / args.topic_gap_queue).resolve())
            metrics["topic_gap_queue"] = topic_gap_metrics
            base_ready, base_failures = frontfill_ready(metrics, args)
            topic_gap_ready, topic_gap_failures = topic_gap_queue_ready(topic_gap_metrics, args)
            log(log_file, "FRONTFILL_METRICS_AFTER_TOPIC_GAP " + json.dumps(metrics, ensure_ascii=False, sort_keys=True))

    failures = list(base_failures)
    if topic_gap_failures:
        failures.extend(topic_gap_failures)
    ready = base_ready and topic_gap_ready
    if failures:
        log(log_file, "FRONTFILL_WAIT " + "; ".join(failures))
    if not ready and not args.force:
        return 0

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
