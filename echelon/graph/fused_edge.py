"""
V13: fused_edge.py — 4 类边融合 (边权合并)

4 类边:
  1. cite_direct  — 直接引用次数 (整数)
  2. co_citation  — 共被引次数 (整数)
  3. bib_couple   — 书目耦合次数 (整数)
  4. semantic_bridge — 语义桥接相似度 (float, 已在 [0,1])

fused_weight 公式 ∈ [0, 1]:
  w_cite  = 0.30·norm_log(cite_direct) + 0.40·norm_log(co_citation) + 0.30·norm_log(bib_couple)
  w_sem   = semantic_bridge (cosine, 已 [0,1])
  fused   = α·w_cite + (1-α)·w_sem
  final   = clip(fused · cross_topic_bonus · time_decay, 0, 1)

cross_topic_bonus = 2.0 if cross_topic else 1.0
time_decay ∈ [0.3, 1.0]  (0.3 = 最旧边的最大衰减)
"""

from __future__ import annotations

import math
from datetime import date
from typing import Dict, Optional, Tuple


# ─────────────────────────────────────────────
# 归一化辅助
# ─────────────────────────────────────────────

def normalize_log(value: int, max_val: int) -> float:
    """
    对引用类计数做 log 归一化到 [0, 1]。

    norm = log(1 + value) / log(1 + max_val)

    Args:
        value:   原始计数 (≥0)
        max_val: 归一化基准最大值 (> 0)

    Returns:
        float ∈ [0.0, 1.0]
    """
    if value <= 0:
        return 0.0
    if max_val <= 0:
        return 0.0
    return min(1.0, math.log(1 + value) / math.log(1 + max_val))


# ─────────────────────────────────────────────
# 时间衰减辅助
# ─────────────────────────────────────────────

def compute_time_decay(
    src_pub_date: Optional[date],
    dst_pub_date: Optional[date],
    reference_date: Optional[date] = None,
    decay_half_life_years: float = 5.0,
    min_decay: float = 0.3,
) -> float:
    """
    根据两篇论文发表时间的较早者计算时间衰减系数。

    decay = max(min_decay, exp(-age_years / decay_half_life_years * ln2))

    当日期缺失时返回 1.0 (无衰减)。

    Args:
        src_pub_date:         源节点发表日期
        dst_pub_date:         目标节点发表日期
        reference_date:       参考日期 (默认 today)
        decay_half_life_years: 半衰期 (年, 默认 5)
        min_decay:            最小衰减系数 (默认 0.3)

    Returns:
        float ∈ [min_decay, 1.0]
    """
    if src_pub_date is None and dst_pub_date is None:
        return 1.0

    if reference_date is None:
        reference_date = date.today()

    # 取更旧的那篇论文的日期
    dates = [d for d in (src_pub_date, dst_pub_date) if d is not None]
    oldest = min(dates)

    age_days = (reference_date - oldest).days
    if age_days <= 0:
        return 1.0

    age_years = age_days / 365.25
    # 指数衰减: decay = exp(-age_years / half_life * ln(2))
    decay = math.exp(-age_years / decay_half_life_years * math.log(2))
    return max(min_decay, min(1.0, decay))


# ─────────────────────────────────────────────
# 核心融合函数
# ─────────────────────────────────────────────

def fused_edge_weight(
    cite_direct: int = 0,
    co_citation: int = 0,
    bib_couple: int = 0,
    semantic_bridge: float = 0.0,
    cross_topic: bool = False,
    time_decay: float = 1.0,
    alpha: float = 0.5,
    max_norm: Optional[Dict[str, int]] = None,
) -> float:
    """
    V13: 4 类边融合公式, 输出 fused_weight ∈ [0, 1]

    公式:
        w_cite  = 0.30·norm_log(cite_direct, max_norm['cite_direct'])
                + 0.40·norm_log(co_citation, max_norm['co_citation'])
                + 0.30·norm_log(bib_couple,  max_norm['bib_couple'])

        w_sem   = clip(semantic_bridge, 0, 1)

        fused   = α·w_cite + (1-α)·w_sem

        bonus   = 2.0 if cross_topic else 1.0
        final   = clip(fused · bonus · time_decay, 0.0, 1.0)

    Args:
        cite_direct:      直接引用次数 (int ≥ 0)
        co_citation:      共被引次数 (int ≥ 0)
        bib_couple:       书目耦合次数 (int ≥ 0)
        semantic_bridge:  语义相似度 (float ∈ [0,1])
        cross_topic:      是否跨主题边 (bool)
        time_decay:       时间衰减系数 ∈ [0.3, 1.0]
        alpha:            引用权 vs 语义权混合比 ∈ [0, 1]
        max_norm:         归一化最大值字典 (可覆盖默认值)

    Returns:
        fused_weight: float ∈ [0.0, 1.0]
    """
    if max_norm is None:
        max_norm = {"cite_direct": 20, "co_citation": 50, "bib_couple": 30}

    # 引用类混合权重 (加权平均)
    w_cite = (
        0.30 * normalize_log(cite_direct, max_norm.get("cite_direct", 20))
        + 0.40 * normalize_log(co_citation, max_norm.get("co_citation", 50))
        + 0.30 * normalize_log(bib_couple, max_norm.get("bib_couple", 30))
    )

    # 语义桥接权重 (已在 [0,1], 做安全裁剪)
    w_sem = max(0.0, min(1.0, semantic_bridge))

    # α 混合
    alpha = max(0.0, min(1.0, alpha))
    fused = alpha * w_cite + (1.0 - alpha) * w_sem

    # 跨主题加成
    cross_topic_bonus = 2.0 if cross_topic else 1.0

    # 时间衰减 (裁剪到合法范围)
    time_decay = max(0.0, min(1.0, time_decay))

    # 最终融合权重
    final = min(1.0, fused * cross_topic_bonus * time_decay)
    return final


# ─────────────────────────────────────────────
# 批量构建融合边表
# ─────────────────────────────────────────────

def build_fused_edge_table(
    edges_by_type: Dict[Tuple, Dict],
    alpha: float = 0.5,
    max_norm: Optional[Dict[str, int]] = None,
    reference_date: Optional[date] = None,
    decay_half_life_years: float = 5.0,
) -> Dict[Tuple, float]:
    """
    批量计算所有边的 fused_weight。

    Args:
        edges_by_type: 边字典, key = (src_paper_id, dst_paper_id), value = {
            "cite_direct":     int,
            "co_citation":     int,
            "bib_couple":      int,
            "semantic_bridge": float,
            "cross_topic":     bool,
            "src_pub_date":    date | None,   # 可选, 用于时间衰减
            "dst_pub_date":    date | None,   # 可选
        }
        alpha:                  混合比 α ∈ [0,1]
        max_norm:               归一化最大值 (默认: cite_direct=20, co_citation=50, bib_couple=30)
        reference_date:         计算时间衰减的参考日期 (默认 today)
        decay_half_life_years:  半衰期 (年, 默认 5)

    Returns:
        { (src_paper_id, dst_paper_id): fused_weight }
    """
    result: Dict[Tuple, float] = {}

    for edge_key, attrs in edges_by_type.items():
        # 时间衰减
        src_date = attrs.get("src_pub_date", None)
        dst_date = attrs.get("dst_pub_date", None)
        if src_date is not None or dst_date is not None:
            td = compute_time_decay(
                src_date, dst_date,
                reference_date=reference_date,
                decay_half_life_years=decay_half_life_years,
            )
        else:
            td = 1.0

        fw = fused_edge_weight(
            cite_direct=int(attrs.get("cite_direct", 0)),
            co_citation=int(attrs.get("co_citation", 0)),
            bib_couple=int(attrs.get("bib_couple", 0)),
            semantic_bridge=float(attrs.get("semantic_bridge", 0.0)),
            cross_topic=bool(attrs.get("cross_topic", False)),
            time_decay=td,
            alpha=alpha,
            max_norm=max_norm,
        )
        result[edge_key] = fw

    return result
