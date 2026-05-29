"""
Step 7: 三色突变标记

红 (mutation_red):   mature 论文 + CD-index > 0.3
橙 (mutation_orange): 跨 Field 桥接分数 > p90
紫 (mutation_purple): 18 月内 burstiness > p95

输出: subgraph_nodes 表的 mutation_red/orange/purple 列

CLI:
    python -m echelon.v14b.step7_mutation --help
    python -m echelon.v14b.step7_mutation
"""
from __future__ import annotations

import argparse
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
    if not all_ids:
        return 0

    # 重置所有突变标记
    conn_v14.execute("""
        UPDATE subgraph_nodes
        SET mutation_red = 0, mutation_orange = 0, mutation_purple = 0
    """)

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
        logger.info("Step7 已完成 (%d mutations),跳过", data.get("records_n", 0))
        return data

    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    ensure_corpus_schema(conn_main)
    scoped_count = create_temp_corpus_table(conn_main, corpus_id)

    conn_v14 = get_v14b_conn(db_v14)
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

    # 写入
    n_written = write_mutations(conn_v14, red_ids, orange_ids, purple_ids)
    upsert_step_meta(conn_v14, step_name, "done", records_n=n_written)

    conn_main.close()
    conn_v14.close()

    stats = {
        "red": len(red_ids),
        "orange": len(orange_ids),
        "purple": len(purple_ids),
        "total_marked": n_written,
        "corpus_id": corpus_id,
        "scoped_papers": scoped_count if corpus_id else len(node_ids),
        "records_n": n_written,
    }
    ck.mark_done(records_n=n_written, meta=stats)
    logger.info(
        "Step7 完成: red=%d orange=%d purple=%d total=%d",
        len(red_ids), len(orange_ids), len(purple_ids), n_written,
    )
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step7_mutation",
        description="Step 7: 三色突变标记",
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
