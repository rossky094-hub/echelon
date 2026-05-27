"""
AUDIT-083 P1: openalex_fetcher — editorial/letter/erratum 过滤

在从 OpenAlex 获取论文时, 过滤掉非研究论文类型:
  - editorial   社论
  - letter      通信/快报
  - erratum     勘误

这些类型的 n_authors 通常为 0 或异常值, 引发 c_team_disrupt KeyError.
过滤后 n_authors=0 的情况也由 c_team_disrupt_v5 以中性 0.5 兜底.

同时提供 filter_non_research_works() 用于本地/批量过滤.
"""
from __future__ import annotations

from typing import Iterable, Iterator

# ---------------------------------------------------------------------------
# 过滤集合 (AUDIT-083)
# ---------------------------------------------------------------------------

#: 需要过滤的 OpenAlex work type 集合 (小写)
NON_RESEARCH_TYPES: frozenset[str] = frozenset({
    "editorial",
    "letter",
    "erratum",
    "correction",   # 勘误/更正
    "retraction",   # 撤稿
    "comment",      # 评论
})


def is_research_work(work: dict) -> bool:
    """
    判断 OpenAlex work dict 是否为研究论文.

    过滤规则: type 字段属于 NON_RESEARCH_TYPES → 排除.
    type 字段缺失或 None → 视为研究论文(宽松策略).

    Args:
        work: OpenAlex Work 字典 (含 "type" 字段).

    Returns:
        True = 保留; False = 过滤掉.

    Examples:
        >>> is_research_work({"type": "article"})
        True
        >>> is_research_work({"type": "editorial"})
        False
        >>> is_research_work({"type": "Letter"})
        False
        >>> is_research_work({})
        True
    """
    work_type = (work.get("type") or "").lower().strip()
    return work_type not in NON_RESEARCH_TYPES


def filter_non_research_works(
    works: Iterable[dict],
) -> Iterator[dict]:
    """
    [AUDIT-083] 过滤非研究类论文.

    Args:
        works: OpenAlex Work 字典的可迭代对象.

    Yields:
        type ∉ NON_RESEARCH_TYPES 的 work 字典.

    Examples:
        >>> data = [{"type": "article"}, {"type": "editorial"}, {"type": "letter"}]
        >>> list(filter_non_research_works(data))
        [{'type': 'article'}]
    """
    for work in works:
        if is_research_work(work):
            yield work


def filter_works_batch(works: list[dict]) -> list[dict]:
    """
    批量过滤版本, 返回 list.

    Args:
        works: OpenAlex Work 字典列表.

    Returns:
        过滤后的列表.
    """
    return [w for w in works if is_research_work(w)]
