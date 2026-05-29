"""Quarterly incremental run orchestration for multi-corpus V14B.

Workflow:
  1) incremental crawl for one corpus
  2) id-repair -> graph-features -> embeddings -> quality-audit
  3) reset-pilot -> Step2..Step6 -> Step13 -> Step7..Step10 -> Step12
  4) write corpus snapshot + delta report
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, DB_V14, REPORT_DIR
from echelon.v14b.corpus_registry import (
    begin_corpus_run,
    bulk_assign_by_topic_keyword,
    create_temp_corpus_table,
    ensure_corpus_schema,
    finish_corpus_run,
    load_previous_snapshot,
    normalize_corpus_id,
    now_run_id,
    register_corpus,
    write_corpus_snapshot,
)
from echelon.v14b.utils import setup_logging

logger = logging.getLogger("echelon.v14b.quarterly_run")


def _quarter_id(d: date) -> str:
    q = ((d.month - 1) // 3) + 1
    return f"{d.year}Q{q}"


def _quarter_start(d: date) -> date:
    q = ((d.month - 1) // 3) + 1
    month = 1 + (q - 1) * 3
    return date(d.year, month, 1)


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    logger.info("RUN: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, env=env)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _candidate_keywords(corpus_id: str, set_spec: str) -> list[str]:
    vals = [corpus_id or ""]
    vals.extend(re.split(r"[^a-zA-Z0-9._-]+", set_spec or ""))
    keywords: list[str] = []
    seen: set[str] = set()
    for raw in vals:
        if not raw:
            continue
        for token in re.split(r"[^a-zA-Z0-9]+", raw):
            key = token.strip().lower()
            if len(key) < 3:
                continue
            if key in seen:
                continue
            seen.add(key)
            keywords.append(key)
    return keywords


def _bootstrap_corpus_membership(
    conn: sqlite3.Connection,
    *,
    corpus_id: str,
    set_spec: str,
) -> int:
    scoped = create_temp_corpus_table(conn, corpus_id)
    if scoped > 0:
        return scoped

    candidates = _candidate_keywords(corpus_id, set_spec)
    assigned = 0
    for kw in candidates:
        try:
            assigned += int(
                bulk_assign_by_topic_keyword(
                    conn,
                    corpus_id=corpus_id,
                    topic_keyword=kw,
                    assignment_source=f"bootstrap:{kw}",
                )
                or 0
            )
        except Exception:
            logger.exception(
                "bootstrap keyword assignment failed: corpus=%s kw=%s",
                corpus_id,
                kw,
            )
    scoped = create_temp_corpus_table(conn, corpus_id)
    logger.info(
        "bootstrap corpus membership: corpus=%s keywords=%s assigned=%d scoped=%d",
        corpus_id,
        candidates,
        assigned,
        scoped,
    )
    return scoped


def _compute_metrics(
    *,
    db_main: Path,
    db_v14: Path,
    corpus_id: str,
) -> dict[str, Any]:
    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    ensure_corpus_schema(conn_main)
    scoped = create_temp_corpus_table(conn_main, corpus_id)

    papers = int(scoped)
    refs = _scalar(
        conn_main,
        """
        SELECT COUNT(*)
        FROM paper_references
        WHERE citing_paper_id IN (SELECT paper_id FROM temp.v14b_corpus_papers)
        """,
    )
    linked_refs = _scalar(
        conn_main,
        """
        SELECT COUNT(*)
        FROM paper_references
        WHERE citing_paper_id IN (SELECT paper_id FROM temp.v14b_corpus_papers)
          AND cited_paper_id_internal IS NOT NULL
        """,
    )
    openalex_w = _scalar(
        conn_main,
        """
        SELECT COUNT(*)
        FROM papers
        WHERE id IN (SELECT paper_id FROM temp.v14b_corpus_papers)
          AND openalex_id LIKE 'W%'
        """,
    )
    with_field = _scalar(
        conn_main,
        """
        SELECT COUNT(*)
        FROM papers
        WHERE id IN (SELECT paper_id FROM temp.v14b_corpus_papers)
          AND primary_field_id IS NOT NULL
          AND length(trim(primary_field_id)) > 0
        """,
    )
    pending_enrich = _scalar(
        conn_main,
        """
        SELECT COUNT(*)
        FROM papers
        WHERE id IN (SELECT paper_id FROM temp.v14b_corpus_papers)
          AND (openalex_enriched IS NULL OR openalex_enriched = 0)
        """,
    )
    conn_main.close()

    conn_v14 = sqlite3.connect(str(db_v14))
    conn_v14.row_factory = sqlite3.Row
    visual_nodes = _scalar(conn_v14, "SELECT COUNT(*) FROM visual_nodes") if _table_exists(conn_v14, "visual_nodes") else 0
    visual_edges = _scalar(conn_v14, "SELECT COUNT(*) FROM visual_edges") if _table_exists(conn_v14, "visual_edges") else 0
    visual_clusters = _scalar(conn_v14, "SELECT COUNT(*) FROM visual_clusters") if _table_exists(conn_v14, "visual_clusters") else 0
    branch_lineages = _scalar(conn_v14, "SELECT COUNT(*) FROM branch_lineages") if _table_exists(conn_v14, "branch_lineages") else 0
    future_dirs = _scalar(conn_v14, "SELECT COUNT(*) FROM future_directions") if _table_exists(conn_v14, "future_directions") else 0
    conn_v14.close()

    return {
        "papers": papers,
        "pending_enrich": pending_enrich,
        "openalex_w_coverage": round(openalex_w / max(1, papers), 4),
        "field_coverage": round(with_field / max(1, papers), 4),
        "refs": refs,
        "linked_refs": linked_refs,
        "linked_ref_ratio": round(linked_refs / max(1, refs), 4),
        "future_directions": future_dirs,
        "visual_nodes": visual_nodes,
        "visual_edges": visual_edges,
        "visual_clusters": visual_clusters,
        "branch_lineages": branch_lineages,
    }


def _delta_report(path: Path, *, corpus_id: str, quarter_id: str, current: dict, previous: dict | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Quarterly Snapshot Delta",
        "",
        f"- Corpus: **{corpus_id}**",
        f"- Quarter: **{quarter_id}**",
        f"- Generated: {datetime.utcnow().isoformat()}Z",
        "",
        "| Metric | Current | Previous | Delta |",
        "|---|---:|---:|---:|",
    ]
    keys = [
        "papers",
        "pending_enrich",
        "refs",
        "linked_refs",
        "linked_ref_ratio",
        "openalex_w_coverage",
        "field_coverage",
        "future_directions",
        "visual_nodes",
        "visual_edges",
        "visual_clusters",
        "branch_lineages",
    ]
    prev_metrics = (previous or {}).get("metrics_json") if previous else None
    if isinstance(prev_metrics, str):
        try:
            prev_metrics = json.loads(prev_metrics)
        except Exception:
            prev_metrics = {}
    prev_metrics = prev_metrics or {}
    for key in keys:
        cur = current.get(key, 0)
        prev = prev_metrics.get(key, 0)
        try:
            delta = float(cur) - float(prev)
            delta_str = f"{delta:.4f}" if isinstance(cur, float) or isinstance(prev, float) else f"{int(delta)}"
        except Exception:
            delta_str = "n/a"
        lines.append(f"| {key} | {cur} | {prev} | {delta_str} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_quarterly(
    *,
    corpus_id: str,
    corpus_name: str,
    quarter_id: str | None,
    provider: str,
    set_spec: str,
    db_main: Path,
    db_v14: Path,
    report_dir: Path,
    from_date: str | None,
    to_date: str | None,
    max_results: int | None,
    run_crawl: bool,
) -> dict[str, Any]:
    cid = normalize_corpus_id(corpus_id)
    today = date.today()
    qid = quarter_id or _quarter_id(today)
    run_id = now_run_id(corpus_id=cid, quarter_id=qid)

    conn = sqlite3.connect(str(db_main))
    conn.row_factory = sqlite3.Row
    ensure_corpus_schema(conn)
    register_corpus(
        conn,
        corpus_id=cid,
        corpus_name=corpus_name,
        source_provider=provider,
        source_set_spec=set_spec,
    )
    _bootstrap_corpus_membership(conn, corpus_id=cid, set_spec=set_spec)
    previous = load_previous_snapshot(conn, cid, qid)

    if not from_date:
        if previous and previous.get("created_at"):
            prev_day = str(previous["created_at"])[:10]
            d = date.fromisoformat(prev_day) + timedelta(days=1)
            from_date = d.isoformat()
        else:
            from_date = _quarter_start(today).isoformat()
    if not to_date:
        to_date = today.isoformat()

    begin_corpus_run(
        conn,
        run_id=run_id,
        corpus_id=cid,
        quarter_id=qid,
        run_type="quarterly",
        db_v14_path=str(db_v14),
        report_dir=str(report_dir),
        notes={
            "provider": provider,
            "set_spec": set_spec,
            "from_date": from_date,
            "to_date": to_date,
            "run_crawl": run_crawl,
        },
    )
    conn.close()

    env = os.environ.copy()
    env.setdefault("OMP_NUM_THREADS", "4")
    env.setdefault("VECLIB_MAXIMUM_THREADS", "4")
    env.setdefault("MKL_NUM_THREADS", "4")
    env.setdefault("NUMEXPR_NUM_THREADS", "4")
    env.setdefault("V14B_EMBEDDING_BATCH_SIZE", "16")

    status = "succeeded"
    error_text = None
    try:
        if run_crawl:
            crawl_cmd = [
                sys.executable,
                "-m",
                "echelon.crawler.worker",
                "--provider",
                provider,
                "--set",
                set_spec,
                "--from",
                from_date,
                "--to",
                to_date,
                "--db",
                str(db_main),
                "--corpus-id",
                cid,
            ]
            if max_results and int(max_results) > 0:
                crawl_cmd.extend(["--max", str(int(max_results))])
            _run(crawl_cmd, env=env)

        chain = [
            [sys.executable, "-m", "echelon.v14b.step0_id_repair", "--db", str(db_main), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step0_graph_features", "--db", str(db_main), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step0_embeddings", "--db", str(db_main), "--corpus-id", cid, "--batch-size", env["V14B_EMBEDDING_BATCH_SIZE"]],
            [sys.executable, "-m", "echelon.v14b.step0_quality_audit", "--db", str(db_main), "--out-dir", str(report_dir), "--corpus-id", cid, "--fail-on", "none"],
            [sys.executable, "-m", "echelon.v14b.step0_reset_pilot", "--db-v14", str(db_v14)],
            [sys.executable, "-m", "echelon.v14b.step2_mainpath", "--db", str(db_main), "--db-v14", str(db_v14), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step3_keystone_v14", "--db", str(db_main), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step4_subgraph", "--db", str(db_main), "--db-v14", str(db_v14), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step5a_scibert", "--db", str(db_main), "--db-v14", str(db_v14), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step5b_vgae", "--db", str(db_main), "--db-v14", str(db_v14), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step5s_section_ingest", "--db", str(db_main), "--db-v14", str(db_v14), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step5c_limitation", "--db", str(db_main), "--db-v14", str(db_v14), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step6_fusion", "--db", str(db_main), "--db-v14", str(db_v14), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step13_first_principles_history", "--db", str(db_main), "--db-v14", str(db_v14), "--out-dir", str(report_dir), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step7_mutation", "--db", str(db_main), "--db-v14", str(db_v14), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step8_layout", "--db", str(db_main), "--db-v14", str(db_v14), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step9_report", "--db", str(db_main), "--db-v14", str(db_v14), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step10_visual_graph_builder", "--db", str(db_main), "--db-v14", str(db_v14), "--corpus-id", cid],
            [sys.executable, "-m", "echelon.v14b.step12_goal_alignment_audit", "--db", str(db_main), "--db-v14", str(db_v14), "--out-dir", str(report_dir), "--corpus-id", cid],
        ]
        for cmd in chain:
            _run(cmd, env=env)
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error_text = str(exc)
        logger.exception("quarterly run failed")

    metrics = _compute_metrics(db_main=db_main, db_v14=db_v14, corpus_id=cid)
    metrics["run_status"] = status
    metrics["error"] = error_text

    conn = sqlite3.connect(str(db_main))
    conn.row_factory = sqlite3.Row
    ensure_corpus_schema(conn)
    write_corpus_snapshot(
        conn,
        snapshot_id=run_id,
        corpus_id=cid,
        quarter_id=qid,
        run_id=run_id,
        db_v14_path=str(db_v14),
        report_dir=str(report_dir),
        metrics=metrics,
    )
    finish_corpus_run(
        conn,
        run_id=run_id,
        status=status,
        notes={"metrics": metrics},
    )
    current_snapshot_row = conn.execute(
        "SELECT * FROM corpus_snapshots WHERE snapshot_id = ? LIMIT 1",
        (run_id,),
    ).fetchone()
    conn.close()

    delta_path = report_dir / f"quarterly_snapshot_delta_{cid}_{qid}.md"
    _delta_report(delta_path, corpus_id=cid, quarter_id=qid, current=metrics, previous=previous)

    return {
        "run_id": run_id,
        "corpus_id": cid,
        "quarter_id": qid,
        "from_date": from_date,
        "to_date": to_date,
        "status": status,
        "metrics": metrics,
        "delta_report": str(delta_path),
        "previous_snapshot": previous,
        "latest_snapshot": dict(current_snapshot_row) if current_snapshot_row else None,
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.quarterly_run",
        description="Quarterly incremental corpus run + graph rebuild + snapshot",
    )
    parser.add_argument("--corpus-id", required=True)
    parser.add_argument("--corpus-name", default=None)
    parser.add_argument("--quarter-id", default=None)
    parser.add_argument("--provider", default="arxiv")
    parser.add_argument("--set-spec", default="physics:physics:optics")
    parser.add_argument("--from-date", default=None)
    parser.add_argument("--to-date", default=None)
    parser.add_argument("--max-results", type=int, default=None)
    parser.add_argument("--skip-crawl", action="store_true")
    parser.add_argument("--db", default=str(DB_MAIN))
    parser.add_argument("--db-v14", default=str(DB_V14))
    parser.add_argument("--report-dir", default=str(REPORT_DIR))
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    setup_logging("quarterly_run", level=getattr(logging, args.log_level.upper(), logging.INFO))
    result = run_quarterly(
        corpus_id=args.corpus_id,
        corpus_name=args.corpus_name or args.corpus_id,
        quarter_id=args.quarter_id,
        provider=args.provider,
        set_spec=args.set_spec,
        db_main=Path(args.db),
        db_v14=Path(args.db_v14),
        report_dir=Path(args.report_dir),
        from_date=args.from_date,
        to_date=args.to_date,
        max_results=args.max_results,
        run_crawl=not args.skip_crawl,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
