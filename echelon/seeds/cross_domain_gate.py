"""
AUDIT-013 P1: 跨领域硬门双轨 — 成熟论文 vs 新论文专属通道

设计:
  - mature(age ≥ 6 月): bridging_centrality z-score ≥ 0 (正中位以上)
  - new_paper(age < 6 月): bib_breadth 代理 — 参考文献跨 ≥ 3 个 topic
    理由: 新论文的 cocite/bridging 数据不足, 改用 bib 多样性判断跨域能力
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Protocol


# ---------------------------------------------------------------------------
# 论文接口协议 (duck typing, 不要求继承)
# ---------------------------------------------------------------------------

class PaperLike(Protocol):
    """最小协议: cross_domain_gate_v5 所需属性"""
    bridging_centrality_zscore: float
    reference_topics: List[str]  # 每条参考文献所属 topic


# ---------------------------------------------------------------------------
# 双轨跨领域硬门
# ---------------------------------------------------------------------------

def bib_breadth(reference_topics: List[str]) -> int:
    """
    计算参考文献跨越的 topic 数量 (去重).

    Args:
        reference_topics: 所有参考文献的 topic 标签列表 (可重复).

    Returns:
        唯一 topic 数量.

    Examples:
        >>> bib_breadth(["photonics", "ML", "robotics", "photonics"])
        3
        >>> bib_breadth([])
        0
    """
    return len(set(t.strip().lower() for t in reference_topics if t.strip()))


def cross_domain_gate_v5(
    paper: PaperLike,
    age_months: float,
    min_bridging_zscore: float = 0.0,
    min_bib_topics: int = 3,
) -> bool:
    """
    [AUDIT-013] 跨领域硬门 — 双轨判定.

    mature 轨 (age ≥ 6 月):
        bridging_centrality_zscore ≥ min_bridging_zscore (默认 0)
        桥接中心性 z-score 正中位及以上才视为跨领域.

    new_paper 轨 (age < 6 月):
        bib_breadth(paper.reference_topics) ≥ min_bib_topics (默认 3)
        新论文 cocite/bridging 数据不足, 改用参考文献多 topic 多样性代理.

    Args:
        paper:               论文对象 (需含 bridging_centrality_zscore 和
                             reference_topics).
        age_months:          论文年龄 (月), 从发表日到今天.
        min_bridging_zscore: mature 轨的 z-score 阈值 (默认 0.0).
        min_bib_topics:      new_paper 轨的最少 topic 数 (默认 3).

    Returns:
        True = 通过跨领域硬门; False = 未通过.

    Examples:
        >>> class P:
        ...     bridging_centrality_zscore = 0.5
        ...     reference_topics = ["A", "B", "C"]
        >>> cross_domain_gate_v5(P(), age_months=12)
        True
        >>> class Q:
        ...     bridging_centrality_zscore = -0.5
        ...     reference_topics = ["A"]
        >>> cross_domain_gate_v5(Q(), age_months=12)
        False
    """
    if age_months >= 6:
        # ── mature 轨: bridging_centrality z-score ──────────────────────────
        return paper.bridging_centrality_zscore >= min_bridging_zscore
    else:
        # ── new_paper 轨: bib 多样性 ─────────────────────────────────────────
        n_topics = bib_breadth(getattr(paper, "reference_topics", []))
        return n_topics >= min_bib_topics


# ---------------------------------------------------------------------------
# 辅助: 门控结果描述
# ---------------------------------------------------------------------------

def describe_gate_result(paper: PaperLike, age_months: float) -> dict:
    """返回门控判定的详细信息 (用于日志/调试)."""
    passed = cross_domain_gate_v5(paper, age_months)
    track = "mature" if age_months >= 6 else "new_paper"
    if track == "mature":
        metric_name = "bridging_centrality_zscore"
        metric_value = paper.bridging_centrality_zscore
        threshold = 0.0
    else:
        metric_name = "bib_n_topics"
        metric_value = bib_breadth(getattr(paper, "reference_topics", []))
        threshold = 3

    return {
        "passed": passed,
        "track": track,
        "age_months": age_months,
        "metric_name": metric_name,
        "metric_value": metric_value,
        "threshold": threshold,
    }
