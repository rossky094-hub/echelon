"""
AUDIT-004 P1: Severity 取 Max → Trimmed Mean (去首尾各 10%)

原问题: severity 取 Max 会放大"学术炒作"型论文的噪声最高分,
       导致 1-2 个 outlier 即可把任意论文的 severity 拉到顶端。

修复: 改用 trimmed mean(去除首尾各 trim_pct 比例极值后求均值)
     - 对单篇或 2 篇: fallback 到普通均值(不做 trim)
     - trim_pct=0.10 即去掉最低 10% + 最高 10%, 保留中间 80%
     - 保证对极端 outlier 鲁棒

V11.5 P1-B: 新建独立模块,向后兼容 (score_keystone.py 引用此模块)
"""
from __future__ import annotations

import math
from typing import List, Optional


def trimmed_mean(values: List[float], trim_pct: float = 0.10) -> float:
    """
    [AUDIT-004 P1] 去首尾各 trim_pct 比例极值后求均值 (Trimmed Mean)

    设计点:
    - values 长度 < 2: 直接返回均值(或空列表返回 0.0)
    - 去除比例向下取整 (floor), 保守截断, 至少保留 1 个值
    - trim 后若无值剩余, fallback 到全均值

    Args:
        values:    待聚合的数值列表 (e.g. severity scores)
        trim_pct:  首尾各去除比例, 默认 0.10 (10%)
                   取值范围 [0.0, 0.49]; 0.0 等价于普通均值

    Returns:
        trimmed mean 值; 空列表返回 0.0

    Examples:
        >>> trimmed_mean([1.0, 2.0, 3.0, 4.0, 5.0])
        3.0
        >>> trimmed_mean([0.1, 0.8, 0.85, 0.9, 10.0], trim_pct=0.20)
        0.85
        >>> trimmed_mean([])
        0.0
        >>> trimmed_mean([0.5])
        0.5
    """
    if not values:
        return 0.0

    n = len(values)
    if n == 1:
        return float(values[0])

    # 校验 trim_pct 合法性
    trim_pct = max(0.0, min(0.49, float(trim_pct)))

    sorted_vals = sorted(float(v) for v in values)

    # 计算截断数量 (floor 保守截断)
    k = math.floor(n * trim_pct)

    # 确保 trim 后至少保留 1 个值
    # k*2 >= n 则 fallback 到全均值
    if k == 0 or k * 2 >= n:
        # trim_pct 过小或列表太短 → 普通均值
        return sum(sorted_vals) / n

    trimmed = sorted_vals[k : n - k]
    return sum(trimmed) / len(trimmed)


def severity_aggregate(
    severities: List[float],
    method: str = "trimmed_mean",
    trim_pct: float = 0.10,
) -> float:
    """
    [AUDIT-004 P1] 严重度聚合函数

    V11.5 P1: 默认改为 trimmed_mean(去首尾各 10%),替代原 max()。
    保留 'max'/'mean'/'median' 选项供回退测试。

    Args:
        severities: 各审查员/模型输出的严重度评分列表
        method:     聚合方法, 'trimmed_mean'(默认) / 'max' / 'mean' / 'median'
        trim_pct:   trimmed_mean 的截断比例 (仅 method='trimmed_mean' 时有效)

    Returns:
        聚合后的 severity 值

    Examples:
        >>> severity_aggregate([0.3, 0.9, 0.85, 0.88, 9.9])
        0.87  # trimmed_mean 去除 0.3 和 9.9
        >>> severity_aggregate([0.5, 0.8], method='max')
        0.8
    """
    if not severities:
        return 0.0

    if method == "trimmed_mean":
        return trimmed_mean(severities, trim_pct=trim_pct)
    elif method == "max":
        return max(float(v) for v in severities)
    elif method == "mean":
        return sum(float(v) for v in severities) / len(severities)
    elif method == "median":
        sorted_v = sorted(float(v) for v in severities)
        n = len(sorted_v)
        mid = n // 2
        if n % 2 == 0:
            return (sorted_v[mid - 1] + sorted_v[mid]) / 2.0
        return sorted_v[mid]
    else:
        raise ValueError(f"未知聚合方法: {method!r}. 可选: trimmed_mean/max/mean/median")
