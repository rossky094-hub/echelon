"""
AUDIT-034 P1: 综述细分 7 子类型 — 规则匹配分类器

7 类:
  survey      — 系统性调研, 大量文献覆盖
  tutorial    — 教程/入门指南
  perspective — 观点/见解
  outlook     — 展望/未来方向
  roadmap     — 路线图/技术规划
  review      — 综合综述 (不含上述特殊类型)
  non_review  — 非综述原创论文

review_penalty 权重:
  survey / tutorial / review → 0.7  (综述性, 降权)
  perspective / outlook / roadmap → 1.0  (前瞻性, 保留)
  non_review → 1.0  (原创研究, 保留)
"""
from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# 关键词规则 — 按优先级排列 (高优先级在前)
# ---------------------------------------------------------------------------

_RULES: list[tuple[str, list[str]]] = [
    ("tutorial", [
        r"\btutorial\b",
        r"\bprimer\b",
        r"\bintroduction to\b",
        r"\bbeginners?\b",
        r"\bstep.by.step\b",
        r"\bhands.on\b",
        r"\bpractical guide\b",
    ]),
    ("roadmap", [
        r"\broadmap\b",
        r"\btechnology roadmap\b",
        r"\bstrategic plan\b",
        r"\bdevelopment plan\b",
        r"\bpath forward\b",
    ]),
    ("outlook", [
        r"\boutlook\b",
        r"\bfuture directions?\b",
        r"\bfuture perspectives?\b",
        r"\bopen problems?\b",
        r"\bchallenges? and opportunities\b",
        r"\bfuture challenges?\b",
        r"\bwhither\b",
    ]),
    ("perspective", [
        r"\bperspective\b",
        r"\bopinion\b",
        r"\bcommentary\b",
        r"\bviewpoint\b",
        r"\beditorial perspective\b",
        r"\bpoint of view\b",
    ]),
    ("survey", [
        r"\bsurvey\b",
        r"\bsystematic review\b",
        r"\bmeta.analysis\b",
        r"\bliterature review\b",
        r"\bscoping review\b",
        r"\bsystematic literature\b",
        r"\bcomprehensive review\b",
        r"\bstate.of.the.art\b",
        r"\bstate of the art\b",
        r"\boverview\b",
    ]),
    ("review", [
        r"\breview\b",
        r"\brecent advances?\b",
        r"\brecent progress\b",
        r"\brecent developments?\b",
        r"\badvances? in\b",
        r"\bprogress in\b",
        r"\bstate of\b",
    ]),
]

# 如果标题 + 摘要都不含上述关键词 → non_review
_NON_REVIEW_LABEL = "non_review"


def classify_review_subtype(
    title: str,
    abstract: Optional[str] = None,
) -> str:
    """
    [AUDIT-034] 按规则匹配将论文分类为 7 种综述子类型之一.

    分类逻辑:
      1. 优先匹配标题 (weight × 2)
      2. 再匹配摘要
      3. 按规则列表顺序, 第一个匹配的子类型获胜
      4. 无匹配 → non_review

    Args:
        title:    论文标题 (必填).
        abstract: 摘要文本 (可选, 为 None 时只看标题).

    Returns:
        子类型标签之一: survey / tutorial / perspective /
        outlook / roadmap / review / non_review

    Examples:
        >>> classify_review_subtype("A Tutorial on Quantum Computing", "")
        'tutorial'
        >>> classify_review_subtype("Novel Metasurface Design", "We propose...")
        'non_review'
        >>> classify_review_subtype("Roadmap for Photonic Integration")
        'roadmap'
    """
    title_lower = (title or "").lower()
    abstract_lower = (abstract or "").lower()
    combined = title_lower + " " + abstract_lower

    for subtype, patterns in _RULES:
        for pattern in patterns:
            # 标题匹配 — 权重较高, 先检查
            if re.search(pattern, title_lower):
                return subtype
            # 摘要匹配
            if abstract_lower and re.search(pattern, abstract_lower):
                return subtype

    return _NON_REVIEW_LABEL


# ---------------------------------------------------------------------------
# 综述惩罚系数
# ---------------------------------------------------------------------------

_PENALTY_MAP: dict[str, float] = {
    "survey": 0.7,
    "tutorial": 0.7,
    "review": 0.7,
    "perspective": 1.0,
    "outlook": 1.0,
    "roadmap": 1.0,
    "non_review": 1.0,
}


def review_penalty(subtype: str) -> float:
    """
    [AUDIT-034] 按子类型返回综述惩罚系数.

    survey / tutorial / review → 0.7  (降权, 综述不直接产生突破)
    perspective / outlook / roadmap → 1.0 (保留权重, 有前瞻价值)
    non_review → 1.0  (原创研究, 无惩罚)

    Args:
        subtype: classify_review_subtype() 返回的标签.

    Returns:
        惩罚系数 ∈ {0.7, 1.0}.

    Raises:
        KeyError: 如果 subtype 不在已知列表.
    """
    return _PENALTY_MAP[subtype]


def classify_and_penalize(title: str, abstract: Optional[str] = None) -> tuple[str, float]:
    """
    便捷函数: 分类并返回 (subtype, penalty) 元组.

    Returns:
        (subtype, penalty_factor)
    """
    subtype = classify_review_subtype(title, abstract)
    penalty = review_penalty(subtype)
    return subtype, penalty
