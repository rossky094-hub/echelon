"""
AUDIT-086 P1: sMAPE → Brier + AUPRC + F1/Hit Rate@K

问题: sMAPE (Symmetric Mean Absolute Percentage Error) 和 MASE 在概率预测
      场景下不适用:
        - sMAPE 要求数值预测, 对概率 (0-1) 分数无意义
        - MASE 需要朴素预测基线, 在推荐/排序场景构造困难
        - 两者均不衡量排序质量

修复: 使用适合推荐/筛选系统的指标:
  - Brier Score:  概率预测的 MSE, 越低越好 [0, 1]
  - AUPRC:        排序质量, 适合正样本稀少场景 (如论文筛选)
  - Hit Rate@K:   Top-K 推荐中命中真实正样本的比率

注意: 本模块不包含 sMAPE / MASE, 任何调用已被移除.
"""
from __future__ import annotations

import math
from typing import Sequence, Union

import numpy as np

# ---------------------------------------------------------------------------
# Brier Score
# ---------------------------------------------------------------------------

def brier_score(
    y_true: Sequence[Union[int, float]],
    y_pred_prob: Sequence[float],
) -> float:
    """
    [AUDIT-086] Brier Score: 概率预测的均方误差.

    公式: BS = (1/N) Σ (y_pred_prob_i - y_true_i)²

    完美预测 → 0.0; 随机预测 (0.5) → 0.25; 最差 → 1.0.

    Args:
        y_true:      真实标签, 0 或 1 (或 0/1 浮点).
        y_pred_prob: 预测概率 ∈ [0, 1].

    Returns:
        Brier Score ∈ [0, 1].

    Raises:
        ValueError: 长度不匹配 或 输入为空.

    Examples:
        >>> brier_score([1, 0, 1], [0.9, 0.1, 0.8])
        0.020000000000000004
        >>> brier_score([1, 0], [0.5, 0.5])
        0.25
    """
    y_true = list(y_true)
    y_pred_prob = list(y_pred_prob)

    if len(y_true) == 0:
        raise ValueError("brier_score: 输入不能为空")
    if len(y_true) != len(y_pred_prob):
        raise ValueError(
            f"brier_score: 长度不匹配 (y_true={len(y_true)}, "
            f"y_pred_prob={len(y_pred_prob)})"
        )

    n = len(y_true)
    total = sum((p - t) ** 2 for p, t in zip(y_pred_prob, y_true))
    return total / n


# ---------------------------------------------------------------------------
# AUPRC (Area Under Precision-Recall Curve)
# ---------------------------------------------------------------------------

def auprc(
    y_true: Sequence[Union[int, float]],
    y_score: Sequence[float],
) -> float:
    """
    [AUDIT-086] AUPRC: PR 曲线下面积.

    适用场景: 正样本稀少 (论文筛选典型场景), 比 AUROC 更敏感.
    使用 sklearn.metrics.average_precision_score (trapezoid AUC).

    Args:
        y_true:  真实标签 (0/1).
        y_score: 预测分数 (越高越可能为正样本).

    Returns:
        AUPRC ∈ [0, 1]. 完美排序 → 1.0; 随机 ≈ 正样本比例.

    Raises:
        ValueError: 无正样本 或 长度不匹配.

    Examples:
        >>> auprc([1, 0, 1, 0], [0.9, 0.2, 0.8, 0.1])
        1.0
    """
    y_true_arr = list(y_true)
    y_score_arr = list(y_score)

    if len(y_true_arr) == 0:
        raise ValueError("auprc: 输入不能为空")
    if len(y_true_arr) != len(y_score_arr):
        raise ValueError(
            f"auprc: 长度不匹配 (y_true={len(y_true_arr)}, y_score={len(y_score_arr)})"
        )

    n_pos = sum(1 for t in y_true_arr if t > 0)
    if n_pos == 0:
        raise ValueError("auprc: y_true 中没有正样本")

    try:
        from sklearn.metrics import average_precision_score
        return float(average_precision_score(y_true_arr, y_score_arr))
    except ImportError:
        # 手动实现: 按 score 降序, 逐步计算 precision/recall
        return _auprc_manual(y_true_arr, y_score_arr)


def _auprc_manual(y_true: list, y_score: list) -> float:
    """AUPRC 手动实现 (trapezoidal rule), 用于 sklearn 不可用时."""
    pairs = sorted(zip(y_score, y_true), key=lambda x: -x[0])
    n_pos = sum(t for _, t in pairs)
    if n_pos == 0:
        return 0.0

    precisions, recalls = [], []
    tp, fp = 0, 0
    for score, label in pairs:
        if label > 0:
            tp += 1
        else:
            fp += 1
        precisions.append(tp / (tp + fp))
        recalls.append(tp / n_pos)

    # Trapezoidal AUC
    auc = 0.0
    for i in range(1, len(recalls)):
        auc += (recalls[i] - recalls[i - 1]) * (precisions[i] + precisions[i - 1]) / 2
    return auc


# ---------------------------------------------------------------------------
# Hit Rate@K
# ---------------------------------------------------------------------------

def hit_rate_at_k(
    predicted: Sequence,
    actual: Sequence,
    k: int,
) -> float:
    """
    [AUDIT-086] Hit Rate@K: Top-K 推荐中命中真实集合的比率.

    公式: |predicted[:K] ∩ actual| / min(K, |actual|)

    Args:
        predicted: 预测排序列表 (按相关性降序).
        actual:    真实正样本集合.
        k:         取 Top-K.

    Returns:
        Hit Rate ∈ [0, 1].

    Raises:
        ValueError: k ≤ 0.

    Examples:
        >>> hit_rate_at_k(["a", "b", "c", "d"], ["a", "c"], k=2)
        0.5
        >>> hit_rate_at_k(["a", "b", "c"], ["a", "b", "c"], k=3)
        1.0
        >>> hit_rate_at_k(["x", "y"], ["a", "b"], k=2)
        0.0
    """
    if k <= 0:
        raise ValueError(f"hit_rate_at_k: k 必须 > 0, 得到 {k}")

    predicted = list(predicted)
    actual_set = set(actual)

    if not actual_set:
        return 0.0

    top_k = predicted[:k]
    hits = sum(1 for item in top_k if item in actual_set)
    denominator = min(k, len(actual_set))
    return hits / denominator


# ---------------------------------------------------------------------------
# F1@K
# ---------------------------------------------------------------------------

def f1_at_k(
    predicted: Sequence,
    actual: Sequence,
    k: int,
) -> float:
    """
    [AUDIT-086] F1@K: Top-K 推荐的 F1 分数.

    精确率 P@K = |predicted[:K] ∩ actual| / K
    召回率 R@K = |predicted[:K] ∩ actual| / |actual|
    F1@K = 2*P@K*R@K / (P@K + R@K)

    Args:
        predicted: 预测排序列表.
        actual:    真实正样本集合.
        k:         Top-K.

    Returns:
        F1@K ∈ [0, 1].

    Examples:
        >>> f1_at_k(["a", "b", "c"], ["a", "c"], k=2)
        0.5
    """
    if k <= 0:
        raise ValueError(f"f1_at_k: k 必须 > 0")

    predicted = list(predicted)
    actual_set = set(actual)

    if not actual_set:
        return 0.0

    top_k = predicted[:k]
    hits = sum(1 for item in top_k if item in actual_set)

    precision_at_k = hits / k if k > 0 else 0.0
    recall_at_k = hits / len(actual_set)

    if precision_at_k + recall_at_k == 0:
        return 0.0

    return 2 * precision_at_k * recall_at_k / (precision_at_k + recall_at_k)


# ---------------------------------------------------------------------------
# 汇总评估
# ---------------------------------------------------------------------------

def evaluate_recommendations(
    y_true: Sequence[Union[int, float]],
    y_score: Sequence[float],
    predicted_ids: Sequence | None = None,
    actual_ids: Sequence | None = None,
    k: int = 10,
) -> dict:
    """
    [AUDIT-086] 综合评估: Brier + AUPRC + Hit Rate@K + F1@K.

    Args:
        y_true:        真实标签 (0/1).
        y_score:       预测分数.
        predicted_ids: 预测排序 ID 列表 (可选, 用于 Hit Rate/F1).
        actual_ids:    真实正样本 ID 集合 (可选).
        k:             Top-K 评估.

    Returns:
        dict: {brier_score, auprc, hit_rate_at_k, f1_at_k} (可用时).
    """
    result: dict = {}

    try:
        result["brier_score"] = brier_score(y_true, y_score)
    except Exception as e:
        result["brier_score_error"] = str(e)

    try:
        result["auprc"] = auprc(y_true, y_score)
    except Exception as e:
        result["auprc_error"] = str(e)

    if predicted_ids is not None and actual_ids is not None:
        try:
            result["hit_rate_at_k"] = hit_rate_at_k(predicted_ids, actual_ids, k)
        except Exception as e:
            result["hit_rate_error"] = str(e)
        try:
            result["f1_at_k"] = f1_at_k(predicted_ids, actual_ids, k)
        except Exception as e:
            result["f1_at_k_error"] = str(e)

    result["k"] = k
    return result
