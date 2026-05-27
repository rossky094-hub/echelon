"""
[修订自 V11.4-N1] 时间窗对 cite_direct 密度有根本影响。
新论文 cite_direct 密度低不是 bug 是数据特性。Pilot 应根据 age_priority 自适应。

现象:
- 2024-2026 数据 cite_direct = 510 (语料新,引用关系未形成)
- 2022-2023 数据 cite_direct = 1042 (2 倍)

根因:
新论文发表后 12-18 个月内,被同期论文引用极少。
1k 抽样级别下,cite_direct 在新语料里不是有效信号。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, Tuple

AgePriority = Literal["fresh", "established", "mature"]

# 采样窗口定义: (min_months_ago, max_months_ago)
# from_date = today - max_months_ago
# to_date   = today - min_months_ago
SAMPLING_WINDOWS: dict[str, tuple[int, int]] = {
    "fresh":       (6, 18),    # 月,适合发现 emerging
    "established": (12, 36),   # 月,默认,cite_direct 信号充足
    "mature":      (36, 60),   # 月,cite_direct 强但已知度高
}


def select_pilot_sampling_window(
    target_size: int,
    age_priority: AgePriority = "established",
    today: date | None = None,
) -> Tuple[date, date]:
    """
    返回 (from_date, to_date) 采样窗口。

    Args:
        target_size:   目标语料大小(当前未用于窗口计算,预留扩展)
        age_priority:  采样优先级。
                       "fresh"       → 6-18 月窗口 (emerging, cite_direct 弱)
                       "established" → 12-36 月窗口 (默认, cite_direct 充足)
                       "mature"      → 36-60 月窗口 (cite_direct 强但已知)
        today:         基准日期,默认 date.today()

    Returns:
        (from_date, to_date): 开始日期和结束日期
    """
    today = today or date.today()
    months_min, months_max = SAMPLING_WINDOWS[age_priority]
    # to_date: 距今 min_months 前 (最新)
    to_date = today - timedelta(days=int(months_min * 30.4))
    # from_date: 距今 max_months 前 (最旧)
    from_date = today - timedelta(days=int(months_max * 30.4))
    return from_date, to_date


def adaptive_cite_direct_weight(corpus_avg_age_months: float) -> float:
    """
    基于语料平均 age,返回 cite_direct 边权重的自适应系数 [0.3, 1.0]。

    设计:
      age < 12 月:   0.3  (新语料,cite_direct 弱信号)
      age 12-18 月:  0.3 → 1.0 线性插值
      age ≥ 18 月:   1.0  (cite_direct 已稳定)

    Args:
        corpus_avg_age_months: 语料平均发表年龄(月)

    Returns:
        float in [0.3, 1.0]
    """
    if corpus_avg_age_months < 12:
        return 0.3
    if corpus_avg_age_months >= 18:
        return 1.0
    # 线性插值: 12 → 0.3, 18 → 1.0
    return 0.3 + (corpus_avg_age_months - 12) * 0.7 / 6


def adaptive_cocitation_weight(corpus_avg_age_months: float) -> float:
    """
    与 cite_direct 互补:新语料 cocite 更重要,老语料 cite_direct 更重要。

    设计:
      age < 12 月:   1.0  (新语料,cocite 是主要信号)
      age 12-36 月:  1.0 → 0.7 线性
      age ≥ 36 月:   0.7  (老语料,降权 cocite 以避免噪声)

    Args:
        corpus_avg_age_months: 语料平均发表年龄(月)

    Returns:
        float in [0.7, 1.0]
    """
    if corpus_avg_age_months < 12:
        return 1.0
    if corpus_avg_age_months >= 36:
        return 0.7
    # 线性插值: 12 → 1.0, 36 → 0.7
    return 1.0 - (corpus_avg_age_months - 12) * 0.3 / 24


def compute_corpus_avg_age_months(
    papers: list,
    today: date | None = None,
) -> float:
    """
    计算语料平均年龄(月)。

    Args:
        papers: Paper 对象列表,需有 publication_date 字段 (datetime.date)
        today:  基准日期,默认 date.today()

    Returns:
        平均年龄(月),如果语料为空返回 0.0
    """
    if not papers:
        return 0.0
    today = today or date.today()
    ages = []
    for p in papers:
        pub_date = getattr(p, "publication_date", None)
        if pub_date is None:
            continue
        age_days = (today - pub_date).days
        ages.append(age_days / 30.4)
    return sum(ages) / len(ages) if ages else 0.0
