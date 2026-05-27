"""
AUDIT-001: cross_paper_consistency 公式修复
原问题: V11.1 用 1 - std/mean, mean 近零时负数/越界
修复: robust 变换 exp(-std/(median+ε)), 值域天然 (0, 1], 非负
"""
from __future__ import annotations

import math
import statistics
from typing import List


def robust_consistency(metric_values: List[float]) -> float:
    """
    [AUDIT-001] V11.2 鲁棒一致性: exp(-std / (|median| + ε))

    公式来自 V11.2 修订:
        consistency = exp(-σ / (|median(V)| + ε))

    特性:
    - 值域天然 ∈ (0, 1], 永不产生负数或越界
    - 使用 median 替代 mean, 对异常值鲁棒
    - ε = 1e-6 防止 median = 0 时除零
    - 单值时: std = 0 → exp(0) = 1.0 (合理: 无法判断一致性时默认完美)
    - 空值: 返回中性值 0.5

    Args:
        metric_values: 来自不同论文对同一物理量的测量值列表

    Returns:
        consistency score ∈ (0, 1]; 越接近 1 表示各论文测量越一致
    """
    if not metric_values:
        return 0.5  # 无数据: 中性值

    if len(metric_values) == 1:
        return 1.0  # 单值: 无法判断一致性, 默认完美一致

    # 标准差 (population std, ddof=0)
    n = len(metric_values)
    mean_v = sum(metric_values) / n
    variance = sum((x - mean_v) ** 2 for x in metric_values) / n
    std = math.sqrt(variance)

    # 中位数 (对异常值鲁棒)
    sorted_v = sorted(metric_values)
    mid = n // 2
    if n % 2 == 0:
        median = (sorted_v[mid - 1] + sorted_v[mid]) / 2.0
    else:
        median = float(sorted_v[mid])

    eps = 1e-6
    result = math.exp(-std / (abs(median) + eps))

    # 保证结果非负 (exp 本身保证, 但防御性断言)
    assert result >= 0.0, f"consistency 为负数: {result}"
    assert result <= 1.0 + 1e-9, f"consistency 越界: {result}"

    return result


def cross_paper_consistency(papers_metric_values: List[List[float]]) -> List[float]:
    """
    [AUDIT-001] 对多组论文的物理量测量值批量计算一致性分数

    Args:
        papers_metric_values: 每个元素是一组论文对同一物理量的测量值列表

    Returns:
        每组的 consistency score 列表
    """
    return [robust_consistency(vals) for vals in papers_metric_values]
