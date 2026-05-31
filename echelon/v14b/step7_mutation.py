"""
Step 7: Evidence-scoped mutation hypotheses.

Primary output:
  - mutation_hypotheses table derived from Step13 Claim Cards.
  - Every hypothesis inherits evidence_grade, claim_scope, uncertainty reasons,
    source evidence objects, and falsification conditions.

Legacy visual signals:
  - mutation_red: mature paper + CD-index > 0.3
  - mutation_orange: cross-field bridge score > p90
  - mutation_purple: 18-month burstiness > p95

The visual flags stay graph-inspection signals only; they do not create
scientific conclusions without a Claim Card contract.

CLI:
    python -m echelon.v14b.step7_mutation --help
    python -m echelon.v14b.step7_mutation
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np

from echelon.v14b.corpus_registry import create_temp_corpus_table, ensure_corpus_schema
from echelon.v14b.config import (
    DB_MAIN, DB_V14,
    MUTATION_RED_CD_THRESHOLD,
    MUTATION_ORANGE_BRIDGE_PERCENTILE,
    MUTATION_PURPLE_BURST_PERCENTILE,
    MUTATION_BURST_WINDOW_MONTHS,
    LIMIT,
)
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.utils import setup_logging, Checkpoint, add_common_args

logger = logging.getLogger("echelon.v14b.step7_mutation")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return bool(row)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _count(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0] or 0) if row else 0


def _safe_json_loads(raw: object, default: object) -> object:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return default


def _jdumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def ensure_mutation_hypothesis_schema(conn_v14: sqlite3.Connection) -> None:
    conn_v14.executescript(
        """
        CREATE TABLE IF NOT EXISTS mutation_hypotheses (
            hypothesis_id                       TEXT PRIMARY KEY,
            claim_card_id                       TEXT NOT NULL,
            direction_id                        INTEGER,
            direction_name                      TEXT,
            mutation_type                       TEXT NOT NULL,
            hypothesis_text                     TEXT NOT NULL,
            minimal_validation_experiment_json  TEXT NOT NULL,
            falsification_conditions_json       TEXT NOT NULL,
            evidence_grade                      TEXT NOT NULL,
            claim_scope                         TEXT NOT NULL,
            source_claim_scope                  TEXT,
            uncertainty_reasons_json            TEXT NOT NULL DEFAULT '[]',
            source_evidence_objects_json        TEXT NOT NULL DEFAULT '[]',
            quality_gate_json                   TEXT,
            created_at                          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_mutation_hypotheses_claim_card
            ON mutation_hypotheses (claim_card_id);
        CREATE INDEX IF NOT EXISTS idx_mutation_hypotheses_scope
            ON mutation_hypotheses (claim_scope, evidence_grade);
        """
    )
    conn_v14.commit()


# ---------------------------------------------------------------------------
# 红色突变: CD-index > 0.3 的 mature 论文
# ---------------------------------------------------------------------------

def mark_red_mutations(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    node_ids: list[int],
    cd_threshold: float = MUTATION_RED_CD_THRESHOLD,
) -> set[int]:
    """
    标记红色突变节点: mature lifecycle + CD-index > 阈值。
    """
    red_ids = set()
    placeholders = ",".join("?" * len(node_ids))

    # 优先从 papers 表读取 cd_index
    try:
        rows = conn_main.execute(f"""
            SELECT p.id
            FROM papers p
            WHERE p.id IN ({placeholders})
              AND p.lifecycle_v14 = 'mature'
              AND p.c_cd_subdomain > ?
        """, node_ids + [cd_threshold]).fetchall()
        red_ids = {row[0] for row in rows}
    except Exception:
        # c_cd_subdomain 可能不存在
        # 降级: 读 mature 且 cited_by_count 高的论文作为代理
        try:
            rows = conn_main.execute(f"""
                SELECT id FROM papers
                WHERE id IN ({placeholders})
                  AND lifecycle_v14 = 'mature'
                  AND cited_by_count > 100
            """, node_ids).fetchall()
            red_ids = {row[0] for row in rows}
        except Exception as exc:
            logger.warning("红色突变标记失败: %s", exc)

    logger.info("红色突变节点: %d (cd_threshold=%.2f)", len(red_ids), cd_threshold)
    return red_ids


# ---------------------------------------------------------------------------
# 橙色突变: 跨 Field 桥接分数 > p90
# ---------------------------------------------------------------------------

def compute_bridge_scores(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    node_ids: list[int],
) -> dict[int, float]:
    """
    计算每个节点的跨 Field 桥接分数。

    桥接分数 = 该论文引用/被引用的 distinct fields 数量 / 总论文数
    """
    placeholders = ",".join("?" * len(node_ids))

    # 统计每个节点的引用网络中 distinct fields
    scores = {}

    try:
        for nid in node_ids:
            # 找该节点的直接邻居
            rows = conn_main.execute("""
                SELECT p.primary_field_id
                FROM papers p
                JOIN paper_references pr ON p.id = pr.cited_paper_id_internal
                WHERE pr.citing_paper_id = ?
                  AND p.primary_field_id IS NOT NULL
                UNION
                SELECT p.primary_field_id
                FROM papers p
                JOIN paper_references pr ON p.id = pr.citing_paper_id
                WHERE pr.cited_paper_id_internal = ?
                  AND p.primary_field_id IS NOT NULL
            """, (nid, nid)).fetchall()

            fields = {row[0] for row in rows}
            # 归一化: distinct fields / 26
            scores[nid] = len(fields) / 26.0

    except Exception as exc:
        logger.warning("桥接分数计算失败: %s", exc)
        scores = {nid: 0.0 for nid in node_ids}

    return scores


def mark_orange_mutations(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    node_ids: list[int],
    percentile: float = MUTATION_ORANGE_BRIDGE_PERCENTILE,
) -> set[int]:
    """
    标记橙色突变节点: 跨 Field 桥接分数 > p90。
    """
    # 先从 c_bridging_centrality 读取(如果存在)
    orange_ids = set()
    try:
        placeholders = ",".join("?" * len(node_ids))
        rows = conn_main.execute(f"""
            SELECT id, c_bridging_centrality
            FROM papers
            WHERE id IN ({placeholders})
              AND c_bridging_centrality IS NOT NULL
        """, node_ids).fetchall()

        if rows:
            all_scores = [(row[0], row[1]) for row in rows]
            scores_only = [s for _, s in all_scores]
            threshold = float(np.percentile(scores_only, percentile * 100))
            orange_ids = {nid for nid, s in all_scores if s >= threshold}
            logger.info("橙色突变节点: %d (bridge >= p%.0f=%.4f)",
                       len(orange_ids), percentile * 100, threshold)
            return orange_ids
    except Exception:
        pass

    # 降级: 计算桥接分数
    bridge_scores = compute_bridge_scores(conn_main, conn_v14, node_ids)
    if bridge_scores:
        vals = list(bridge_scores.values())
        threshold = float(np.percentile(vals, percentile * 100))
        orange_ids = {nid for nid, s in bridge_scores.items() if s >= threshold}

    logger.info("橙色突变节点: %d", len(orange_ids))
    return orange_ids


# ---------------------------------------------------------------------------
# 紫色突变: 18 月内 burstiness > p95
# ---------------------------------------------------------------------------

def compute_burst_scores(
    conn_main: sqlite3.Connection,
    node_ids: list[int],
    window_months: int = MUTATION_BURST_WINDOW_MONTHS,
) -> dict[int, float]:
    """
    计算每个节点的 burstiness 分数。

    Burstiness = 18 月内被引数 / (总被引数 × 年均引用率)
    代理: c_recent_burst 列 (如已计算)
    """
    burst_scores = {}
    try:
        placeholders = ",".join("?" * len(node_ids))
        rows = conn_main.execute(f"""
            SELECT id, c_recent_burst, cited_by_count, publication_year
            FROM papers
            WHERE id IN ({placeholders})
        """, node_ids).fetchall()

        for row in rows:
            nid = row[0]
            burst = row[1]
            if burst is not None:
                burst_scores[nid] = float(burst)
            else:
                # 用 cited_by_count 和年份代理
                total_cite = row[2] or 0
                pub_year = row[3] or 2020
                age_years = max(1, date.today().year - pub_year)
                # 简单代理: 高引用 + 年轻 = 高 burst
                annual_rate = total_cite / age_years
                burst_scores[nid] = min(1.0, annual_rate / 100)

    except Exception as exc:
        logger.warning("Burst 分数计算失败: %s", exc)
        burst_scores = {nid: 0.0 for nid in node_ids}

    return burst_scores


def mark_purple_mutations(
    conn_main: sqlite3.Connection,
    node_ids: list[int],
    percentile: float = MUTATION_PURPLE_BURST_PERCENTILE,
) -> set[int]:
    """
    标记紫色突变节点: 18 月 burstiness > p95。
    """
    burst_scores = compute_burst_scores(conn_main, node_ids)
    if not burst_scores:
        return set()

    vals = list(burst_scores.values())
    if not vals or max(vals) <= 0:
        logger.warning("Burst 分数全为 0,跳过紫色突变标记以避免全图误标")
        return set()
    threshold = float(np.percentile(vals, percentile * 100))
    if threshold <= 0:
        logger.warning("Burst 阈值 <= 0,跳过紫色突变标记以避免全图误标")
        return set()
    purple_ids = {nid for nid, s in burst_scores.items() if s >= threshold}

    logger.info("紫色突变节点: %d (burst >= p%.0f=%.4f)",
               len(purple_ids), percentile * 100, threshold)
    return purple_ids


# ---------------------------------------------------------------------------
# Evidence-scoped mutation hypotheses
# ---------------------------------------------------------------------------

def _mutation_scope(*, five_question_complete: bool, high_confidence_eligible: bool) -> str:
    if high_confidence_eligible:
        return "validated_followup_candidate"
    if five_question_complete:
        return "candidate_pool_only"
    return "not_for_user_claim"


def _mutation_hypothesis_text(
    *,
    direction_name: str,
    root_constraint: dict,
    minimal_experiment: dict,
) -> str:
    constraint = str(root_constraint.get("constraint") or root_constraint.get("type") or "").strip()
    experiment = str(minimal_experiment.get("experiment") or "").strip()
    if constraint and experiment:
        return f"Test whether {direction_name} can relax `{constraint}` via: {experiment}"
    if experiment:
        return f"Test whether {direction_name} is viable via: {experiment}"
    return f"Test whether {direction_name} has a falsifiable validation path."


def build_mutation_hypotheses(conn_v14: sqlite3.Connection) -> list[dict]:
    """Build deterministic mutation hypotheses from Step13 Claim Cards."""
    ensure_mutation_hypothesis_schema(conn_v14)
    required = {
        "claim_card_id",
        "direction_id",
        "direction_name",
        "root_constraint_json",
        "minimal_validation_experiment_json",
        "evidence_grade",
        "claim_scope",
        "uncertainty_reasons_json",
        "evidence_objects_json",
        "five_question_complete",
        "high_confidence_eligible",
        "quality_gate_json",
    }
    if not required <= _columns(conn_v14, "direction_claim_cards"):
        return []

    hypotheses: list[dict] = []
    rows = conn_v14.execute(
        """
        SELECT claim_card_id, direction_id, direction_name,
               root_constraint_json, minimal_validation_experiment_json,
               evidence_grade, claim_scope, uncertainty_reasons_json,
               evidence_objects_json, five_question_complete,
               high_confidence_eligible, quality_gate_json
        FROM direction_claim_cards
        ORDER BY high_confidence_eligible DESC, five_question_complete DESC, direction_id
        """
    ).fetchall()
    for row in rows:
        claim_card_id = str(row["claim_card_id"])
        direction_id = int(row["direction_id"] or 0)
        direction_name = str(row["direction_name"] or f"direction_{direction_id}")
        minimal_experiment = _safe_json_loads(row["minimal_validation_experiment_json"], {})
        if not isinstance(minimal_experiment, dict):
            minimal_experiment = {}
        falsification = minimal_experiment.get("falsification_conditions") or []
        if not falsification:
            continue
        root_constraint = _safe_json_loads(row["root_constraint_json"], {})
        if not isinstance(root_constraint, dict):
            root_constraint = {}
        source_reasons = _safe_json_loads(row["uncertainty_reasons_json"], [])
        if not isinstance(source_reasons, list):
            source_reasons = []
        uncertainty_reasons = sorted(
            set(
                [
                    *[str(reason) for reason in source_reasons if str(reason).strip()],
                    "mutation hypothesis inherits Step13 Claim Card evidence and cannot promote itself",
                    "mutation hypothesis is a falsifiable follow-up, not a standalone conclusion",
                ]
            )
        )
        five_complete = bool(int(row["five_question_complete"] or 0))
        high_confidence = bool(int(row["high_confidence_eligible"] or 0))
        hypotheses.append(
            {
                "hypothesis_id": f"mutation:{claim_card_id}",
                "claim_card_id": claim_card_id,
                "direction_id": direction_id,
                "direction_name": direction_name,
                "mutation_type": "minimal_validation_followup",
                "hypothesis_text": _mutation_hypothesis_text(
                    direction_name=direction_name,
                    root_constraint=root_constraint,
                    minimal_experiment=minimal_experiment,
                )[:800],
                "minimal_validation_experiment_json": _jdumps(minimal_experiment),
                "falsification_conditions_json": _jdumps(falsification),
                "evidence_grade": str(row["evidence_grade"] or "incomplete_claim_card"),
                "claim_scope": _mutation_scope(
                    five_question_complete=five_complete,
                    high_confidence_eligible=high_confidence,
                ),
                "source_claim_scope": str(row["claim_scope"] or ""),
                "uncertainty_reasons_json": _jdumps(uncertainty_reasons),
                "source_evidence_objects_json": str(row["evidence_objects_json"] or "[]"),
                "quality_gate_json": str(row["quality_gate_json"] or "{}"),
            }
        )
    return hypotheses


def write_mutation_hypotheses(conn_v14: sqlite3.Connection, hypotheses: list[dict]) -> int:
    ensure_mutation_hypothesis_schema(conn_v14)
    conn_v14.execute("DELETE FROM mutation_hypotheses")
    if hypotheses:
        conn_v14.executemany(
            """
            INSERT OR REPLACE INTO mutation_hypotheses (
                hypothesis_id, claim_card_id, direction_id, direction_name,
                mutation_type, hypothesis_text, minimal_validation_experiment_json,
                falsification_conditions_json, evidence_grade, claim_scope,
                source_claim_scope, uncertainty_reasons_json,
                source_evidence_objects_json, quality_gate_json
            ) VALUES (
                :hypothesis_id, :claim_card_id, :direction_id, :direction_name,
                :mutation_type, :hypothesis_text, :minimal_validation_experiment_json,
                :falsification_conditions_json, :evidence_grade, :claim_scope,
                :source_claim_scope, :uncertainty_reasons_json,
                :source_evidence_objects_json, :quality_gate_json
            )
            """,
            hypotheses,
        )
    conn_v14.commit()
    return len(hypotheses)


# ---------------------------------------------------------------------------
# DB 写入
# ---------------------------------------------------------------------------

def write_mutations(
    conn_v14: sqlite3.Connection,
    red_ids: set[int],
    orange_ids: set[int],
    purple_ids: set[int],
) -> int:
    """更新 subgraph_nodes 的突变标记列"""
    all_ids = red_ids | orange_ids | purple_ids

    # 重置所有突变标记
    conn_v14.execute("""
        UPDATE subgraph_nodes
        SET mutation_red = 0, mutation_orange = 0, mutation_purple = 0
    """)

    if not all_ids:
        conn_v14.commit()
        return 0

    updates = []
    for nid in all_ids:
        updates.append((
            int(nid in red_ids),
            int(nid in orange_ids),
            int(nid in purple_ids),
            nid,
        ))

    conn_v14.executemany("""
        UPDATE subgraph_nodes
        SET mutation_red = ?, mutation_orange = ?, mutation_purple = ?
        WHERE paper_id = ?
    """, updates)
    conn_v14.commit()

    return len(all_ids)


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_mutation(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    limit: Optional[int] = None,
    resume: bool = True,
    corpus_id: str | None = None,
) -> dict:
    """执行 Step 7: 三色突变标记"""
    step_name = "step7_mutation"
    ck = Checkpoint(step_name)

    if resume and ck.done():
        data = ck.load()
        conn_v14_resume = get_v14b_conn(db_v14)
        ensure_mutation_hypothesis_schema(conn_v14_resume)
        claim_cards = _count(conn_v14_resume, "direction_claim_cards")
        mutation_hypotheses = _count(conn_v14_resume, "mutation_hypotheses")
        conn_v14_resume.close()
        if not claim_cards or mutation_hypotheses:
            logger.info("Step7 已完成 (%d mutations),跳过", data.get("records_n", 0))
            return data
        logger.info(
            "Step7 checkpoint predates mutation_hypotheses contract; rerunning evidence-scoped mutations"
        )

    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    ensure_corpus_schema(conn_main)
    scoped_count = create_temp_corpus_table(conn_main, corpus_id)

    conn_v14 = get_v14b_conn(db_v14)
    ensure_mutation_hypothesis_schema(conn_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    # 获取子图节点列表
    rows = conn_v14.execute("SELECT paper_id FROM subgraph_nodes").fetchall()
    node_ids = [row[0] for row in rows]
    if corpus_id:
        node_ids = [
            pid
            for pid in node_ids
            if conn_main.execute(
                "SELECT 1 FROM temp.v14b_corpus_papers WHERE paper_id = ? LIMIT 1",
                (pid,),
            ).fetchone()
        ]
    if limit:
        node_ids = node_ids[:limit]
    logger.info("子图节点数: %d", len(node_ids))

    # 三色标记
    red_ids = mark_red_mutations(conn_main, conn_v14, node_ids)
    orange_ids = mark_orange_mutations(conn_main, conn_v14, node_ids)
    purple_ids = mark_purple_mutations(conn_main, node_ids)
    mutation_hypotheses = build_mutation_hypotheses(conn_v14)

    # 写入
    n_written = write_mutations(conn_v14, red_ids, orange_ids, purple_ids)
    n_hypotheses = write_mutation_hypotheses(conn_v14, mutation_hypotheses)
    output_records = n_written + n_hypotheses
    upsert_step_meta(conn_v14, step_name, "done", records_n=output_records)

    conn_main.close()
    conn_v14.close()

    stats = {
        "red": len(red_ids),
        "orange": len(orange_ids),
        "purple": len(purple_ids),
        "total_marked": n_written,
        "mutation_hypotheses": n_hypotheses,
        "corpus_id": corpus_id,
        "scoped_papers": scoped_count if corpus_id else len(node_ids),
        "records_n": output_records,
    }
    ck.mark_done(records_n=output_records, meta=stats)
    logger.info(
        "Step7 完成: red=%d orange=%d purple=%d visual_total=%d mutation_hypotheses=%d",
        len(red_ids), len(orange_ids), len(purple_ids), n_written, n_hypotheses,
    )
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step7_mutation",
        description="Step 7: evidence-scoped mutation hypotheses and legacy visual mutation flags",
    )
    add_common_args(parser)
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step7_mutation", level=log_level)

    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14
    limit = args.limit or LIMIT

    run_mutation(
        db_main=db_main,
        db_v14=db_v14,
        limit=limit,
        resume=args.resume,
        corpus_id=args.corpus_id,
    )


if __name__ == "__main__":
    main()
