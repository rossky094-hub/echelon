"""
Step 3: V14 调权 KeystoneScore

在 V13 keystone_score_v6 基础上使用 V14 权重表:
  - fresh: 加重 mechanism_novelty + breakthrough_lang + bridging
  - growing: 加重 bridging + burst
  - mature: 加重 cd_subdomain + bridging

输出: papers 表新增列 keystone_score_v14, lifecycle_v14

CLI:
    python -m echelon.v14b.step3_keystone_v14 --help
    python -m echelon.v14b.step3_keystone_v14
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional, Dict

from echelon.v14b.config import DB_MAIN, DB_V14, LIFECYCLE_WEIGHTS_V14, LIMIT
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.utils import setup_logging, Checkpoint, add_common_args, make_progress
from echelon.seeds.lifecycle_weights import (
    determine_lifecycle,
    _safe_clip_v6,
    LifecycleStage,
    ALL_SIGNALS,
)

logger = logging.getLogger("echelon.v14b.step3_keystone_v14")

# ---------------------------------------------------------------------------
# V14 评分核心函数
# ---------------------------------------------------------------------------

def keystone_score_v14(
    signals: Dict[str, Optional[float]],
    paper,
    today: Optional[date] = None,
) -> tuple[float, str]:
    """
    V14-B 生命周期自适应加权调和均值 KeystoneScore。

    使用 LIFECYCLE_WEIGHTS_V14 权重表(与 V13 LIFECYCLE_WEIGHTS 不同)。
    算法与 keystone_score_v6 相同,只替换权重字典。

    Args:
        signals: Dict mapping signal name → value (None = skip)
        paper:   Object/dict with publication_date
        today:   Reference date

    Returns:
        (score: float, lifecycle: str)  score ∈ [0.0, 1.0]
    """
    if today is None:
        today = date.today()

    lifecycle: LifecycleStage = determine_lifecycle(paper, today=today)
    weights = LIFECYCLE_WEIGHTS_V14[lifecycle]

    pos_signals: Dict[str, float] = {}
    neg_penalty_total: float = 0.0

    for key, weight in weights.items():
        val = signals.get(key)
        if val is None:
            continue
        if weight == 0.0:
            continue

        val_clipped = _safe_clip_v6(float(val))

        if weight > 0:
            pos_signals[key] = val_clipped
        else:
            neg_penalty_total += weight * val_clipped

    if not pos_signals:
        result = 0.5 + neg_penalty_total
        return _safe_clip_v6(result), lifecycle

    # Weighted harmonic mean with ε=0.5 smoothing
    EPSILON = 0.5
    pos_weights = {k: weights[k] for k in pos_signals}
    w_total = sum(pos_weights.values())

    denominator = sum(
        pos_weights[k] / (pos_signals[k] + EPSILON)
        for k in pos_signals
    )

    if denominator <= 0:
        return _safe_clip_v6(0.5 + neg_penalty_total), lifecycle

    harmonic = w_total / denominator
    score = harmonic - EPSILON + neg_penalty_total
    return _safe_clip_v6(score), lifecycle


# ---------------------------------------------------------------------------
# DB 操作
# ---------------------------------------------------------------------------

def ensure_v14_columns(conn: sqlite3.Connection) -> None:
    """添加 keystone_score_v14, lifecycle_v14 列到 papers 表(如不存在)"""
    for col_def in [
        ("keystone_score_v14", "REAL"),
        ("lifecycle_v14",      "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE papers ADD COLUMN {col_def[0]} {col_def[1]}")
        except Exception:
            pass
    conn.commit()


def load_papers_with_signals(
    conn: sqlite3.Connection,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    加载论文及其已计算的信号值。

    信号可能分散在多个表中(keystone_signals, papers, 等)。
    用已有列或默认值填充。
    """
    from echelon.v14b.utils import table_columns

    paper_cols = table_columns(conn, "papers")
    signal_defaults = {
        "c_recency": 0.5,
        "c_venue": 0.5,
        "c_team_disrupt": 0.5,
        "c_recent_burst": 0.5,
        "c_review_filter": 0.0,
        "c_bib_breadth": 0.5,
        "c_cocite_breadth": None,
        "c_bridging_centrality": 0.5,
        "c_cd_subdomain": None,
        "c_semantic_outlier": 0.5,
        "c_breakthrough_lang": 0.5,
        "c_mechanism_novelty": 0.5,
    }
    base_cols = [
        "p.id",
        "p.publication_date",
        "p.cited_by_count",
        "p.primary_field_id",
    ]
    signal_select = []
    for col, default in signal_defaults.items():
        if col in paper_cols:
            if default is None:
                signal_select.append(f"p.{col}")
            else:
                signal_select.append(f"COALESCE(p.{col}, {default}) AS {col}")
        elif default is None:
            signal_select.append(f"NULL AS {col}")
        else:
            signal_select.append(f"{default} AS {col}")

    q = f"""
        SELECT
            {', '.join(base_cols + signal_select)}
        FROM papers p
        ORDER BY p.id
    """
    if limit:
        q += f" LIMIT {limit}"

    rows = conn.execute(q).fetchall()
    return [dict(r) for r in rows]


def compute_and_write_v14_scores(
    conn: sqlite3.Connection,
    papers: list[dict],
    batch_size: int = 500,
) -> tuple[int, dict]:
    """
    批量计算 V14 KeystoneScore 并写入 DB。

    Returns:
        (n_written, lifecycle_distribution)
    """
    lifecycle_counts = {"fresh": 0, "growing": 0, "mature": 0}
    updates = []

    with make_progress(papers, desc="V14 KeystoneScore") as pbar:
        for p in pbar:
            # 构建信号字典
            signals = {
                "c_recency":            p.get("c_recency"),
                "c_venue":              p.get("c_venue"),
                "c_team_disrupt":       p.get("c_team_disrupt"),
                "c_recent_burst":       p.get("c_recent_burst"),
                "c_review_filter":      p.get("c_review_filter"),
                "c_bib_breadth":        p.get("c_bib_breadth"),
                "c_cocite_breadth":     p.get("c_cocite_breadth"),
                "c_bridging_centrality": p.get("c_bridging_centrality"),
                "c_cd_subdomain":       p.get("c_cd_subdomain"),
                "c_semantic_outlier":   p.get("c_semantic_outlier"),
                "c_breakthrough_lang":  p.get("c_breakthrough_lang"),
                "c_mechanism_novelty":  p.get("c_mechanism_novelty"),
            }

            # 构建 paper 对象(用于 determine_lifecycle)
            class _Paper:
                pass
            paper_obj = _Paper()

            pub_date = p.get("publication_date")
            if pub_date and isinstance(pub_date, str):
                try:
                    parts = pub_date.split("-")
                    paper_obj.publication_date = date(
                        int(parts[0]),
                        int(parts[1]) if len(parts) > 1 else 1,
                        int(parts[2]) if len(parts) > 2 else 1,
                    )
                except (ValueError, IndexError):
                    paper_obj.publication_date = None
            else:
                paper_obj.publication_date = pub_date

            score, lifecycle = keystone_score_v14(signals, paper_obj)
            lifecycle_counts[lifecycle] = lifecycle_counts.get(lifecycle, 0) + 1
            updates.append((score, lifecycle, p["id"]))

    # 批量写入
    written = 0
    for i in range(0, len(updates), batch_size):
        batch = updates[i: i + batch_size]
        conn.executemany(
            "UPDATE papers SET keystone_score_v14 = ?, lifecycle_v14 = ? WHERE id = ?",
            batch,
        )
        conn.commit()
        written += len(batch)

    return written, lifecycle_counts


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_keystone_v14(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    limit: Optional[int] = None,
    resume: bool = True,
) -> dict:
    """执行 Step 3: V14 调权 KeystoneScore"""
    step_name = "step3_keystone_v14"
    ck = Checkpoint(step_name)

    if resume and ck.done():
        data = ck.load()
        logger.info("Step3 已完成 (%d records),跳过", data.get("records_n", 0))
        return data

    conn_v14 = get_v14b_conn(db_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    conn = sqlite3.connect(str(db_main))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    ensure_v14_columns(conn)

    papers = load_papers_with_signals(conn, limit=limit)
    logger.info("加载论文: %d 篇", len(papers))

    n_written, lifecycle_dist = compute_and_write_v14_scores(conn, papers)
    conn.close()

    stats = {
        "records_n": n_written,
        "lifecycle_distribution": lifecycle_dist,
    }
    upsert_step_meta(conn_v14, step_name, "done", records_n=n_written)
    conn_v14.close()
    ck.mark_done(records_n=n_written, meta=stats)
    logger.info(
        "Step3 完成: %d scores written, lifecycle=%s",
        n_written, lifecycle_dist,
    )
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step3_keystone_v14",
        description="Step 3: V14 调权 KeystoneScore",
    )
    add_common_args(parser)
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step3_keystone_v14", level=log_level)

    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14
    limit = args.limit or LIMIT

    run_keystone_v14(db_main=db_main, db_v14=db_v14, limit=limit, resume=args.resume)


if __name__ == "__main__":
    main()
