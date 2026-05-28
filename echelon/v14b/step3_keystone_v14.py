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
import json
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

SIGNAL_DEFAULTS = {
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

# These signals carry much of the "why this paper matters for evolution" burden.
# If they silently fall back to defaults, the score should be pulled toward
# neutral instead of pretending to be strongly discriminative.
KEYSTONE_CRITICAL_SIGNALS = {
    "c_recent_burst",
    "c_cocite_breadth",
    "c_bridging_centrality",
    "c_cd_subdomain",
    "c_semantic_outlier",
}

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
        ("keystone_signal_quality_v14", "REAL"),
        ("keystone_signal_coverage_v14", "REAL"),
        ("keystone_signal_flags_v14", "TEXT"),
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
    base_cols = [
        "p.id",
        "p.publication_date",
        "p.cited_by_count",
        "p.primary_field_id",
    ]
    signal_select = []
    for col in SIGNAL_DEFAULTS:
        if col in paper_cols:
            signal_select.append(f"p.{col} AS {col}")
        else:
            signal_select.append(f"NULL AS {col}")

    q = f"""
        SELECT
            {', '.join(base_cols + signal_select)}
        FROM papers p
        ORDER BY p.id
    """
    if limit:
        q += f" LIMIT {limit}"

    rows = conn.execute(q).fetchall()
    out = []
    for row in rows:
        rec = dict(row)
        observed = 0
        critical_observed = 0
        defaults_used = []
        missing_columns = []
        for signal, default in SIGNAL_DEFAULTS.items():
            column_present = signal in paper_cols
            has_value = rec.get(signal) is not None
            if column_present and has_value:
                observed += 1
                if signal in KEYSTONE_CRITICAL_SIGNALS:
                    critical_observed += 1
                continue
            if not column_present:
                missing_columns.append(signal)
            defaults_used.append(signal)
            rec[signal] = default

        coverage = observed / max(1, len(SIGNAL_DEFAULTS))
        critical_coverage = critical_observed / max(1, len(KEYSTONE_CRITICAL_SIGNALS))
        reliability = max(0.20, min(1.0, 0.45 * coverage + 0.55 * critical_coverage))
        if coverage >= 0.95 and critical_coverage >= 0.95:
            reliability = 1.0
        flags = {
            "coverage": coverage,
            "critical_coverage": critical_coverage,
            "reliability": reliability,
            "defaults_used": defaults_used,
            "missing_columns": missing_columns,
            "critical_defaults": sorted(set(defaults_used) & KEYSTONE_CRITICAL_SIGNALS),
        }
        rec["__signal_quality"] = flags
        out.append(rec)
    return out


def quality_adjusted_keystone_score(raw_score: float, reliability: float) -> float:
    """Pull low-quality signal scores toward neutral instead of overclaiming."""
    reliability = max(0.0, min(1.0, float(reliability)))
    return _safe_clip_v6(0.5 + (float(raw_score) - 0.5) * reliability)


def compute_and_write_v14_scores(
    conn: sqlite3.Connection,
    papers: list[dict],
    batch_size: int = 500,
) -> tuple[int, dict, dict]:
    """
    批量计算 V14 KeystoneScore 并写入 DB。

    Returns:
        (n_written, lifecycle_distribution)
    """
    lifecycle_counts = {"fresh": 0, "growing": 0, "mature": 0}
    updates = []
    quality_values = []
    critical_default_counts = 0

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

            raw_score, lifecycle = keystone_score_v14(signals, paper_obj)
            signal_quality = p.get("__signal_quality") or {}
            reliability = float(signal_quality.get("reliability", 1.0))
            score = quality_adjusted_keystone_score(raw_score, reliability)
            lifecycle_counts[lifecycle] = lifecycle_counts.get(lifecycle, 0) + 1
            quality_values.append(reliability)
            if signal_quality.get("critical_defaults"):
                critical_default_counts += 1
            updates.append((
                score,
                lifecycle,
                reliability,
                float(signal_quality.get("coverage", 1.0)),
                json.dumps(signal_quality, ensure_ascii=False),
                p["id"],
            ))

    # 批量写入
    written = 0
    for i in range(0, len(updates), batch_size):
        batch = updates[i: i + batch_size]
        conn.executemany(
            """
            UPDATE papers
            SET keystone_score_v14 = ?,
                lifecycle_v14 = ?,
                keystone_signal_quality_v14 = ?,
                keystone_signal_coverage_v14 = ?,
                keystone_signal_flags_v14 = ?
            WHERE id = ?
            """,
            batch,
        )
        conn.commit()
        written += len(batch)

    quality_summary = {
        "avg_signal_reliability": sum(quality_values) / max(1, len(quality_values)),
        "min_signal_reliability": min(quality_values) if quality_values else 0.0,
        "critical_default_papers": critical_default_counts,
    }
    return written, lifecycle_counts, quality_summary


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

    n_written, lifecycle_dist, quality_summary = compute_and_write_v14_scores(conn, papers)
    conn.close()

    stats = {
        "records_n": n_written,
        "lifecycle_distribution": lifecycle_dist,
        "signal_quality": quality_summary,
    }
    upsert_step_meta(
        conn_v14,
        step_name,
        "done",
        records_n=n_written,
        notes=json.dumps(quality_summary, ensure_ascii=False),
    )
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
