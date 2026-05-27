"""
AUDIT-050 P1: LOF → Isolation Forest + kNN-distance 双检测

原问题: LOF 在各向异性向量空间崩塌 (sentence-transformer 嵌入高度各向异性),
        导致假阳性/假阴性严重 (Ethayarajh 2019)。

修复:
- Isolation Forest (sklearn): 对各向异性向量空间鲁棒
- kNN-distance (K=10): 经典局部密度度量,与 IF 互补
- AND 逻辑: 两者都判异常才标记, 降低假阳性
- 可选 whitening_transform: 预处理消除各向异性

References:
    Ethayarajh 2019: https://arxiv.org/abs/1909.00512
    Isolation Forest: Liu et al. 2008 (sklearn IsolationForest)
"""
from __future__ import annotations

import logging
from typing import Set

import numpy as np

logger = logging.getLogger(__name__)

# 默认 kNN 邻居数
KNN_K: int = 10


def whitening_transform(embeddings: np.ndarray) -> np.ndarray:
    """
    [AUDIT-050] 白化变换 (可选预处理), 消除各向异性。

    对嵌入矩阵做 ZCA 白化:
      1. 中心化
      2. 计算协方差矩阵
      3. 对角化 + 白化: X_w = X @ W, 使 Cov(X_w) ≈ I

    白化后向量空间更接近各向同性, 有利于 kNN-distance 计算。
    对于 Isolation Forest 白化效果有限 (树方法天然不受各向异性影响)。

    Args:
        embeddings: shape (n, d) 的嵌入矩阵, float64/float32.

    Returns:
        shape (n, d) 的白化后矩阵, float64.

    Notes:
        - 若 n <= d (样本数 ≤ 维度), 协方差矩阵奇异,
          自动退化为 L2 归一化 (安全回退)。
        - 数值稳定性: 特征值 < 1e-10 的分量设为 0。
    """
    emb = np.array(embeddings, dtype=np.float64)
    n, d = emb.shape

    if n <= 1:
        return emb

    # 中心化
    mean = emb.mean(axis=0)
    centered = emb - mean

    if n <= d:
        # 样本不足: 协方差矩阵奇异 → 退化为 L2 归一化
        logger.warning(
            "whitening_transform: n=%d <= d=%d, falling back to L2 normalization", n, d
        )
        norms = np.linalg.norm(centered, axis=1, keepdims=True)
        norms = np.where(norms < 1e-10, 1.0, norms)
        return centered / norms

    # 协方差矩阵 (d, d)
    cov = (centered.T @ centered) / (n - 1)

    # 特征值分解
    eigvals, eigvecs = np.linalg.eigh(cov)

    # 数值稳定: 忽略近零特征值
    eps = 1e-10
    inv_sqrt_eigvals = np.where(eigvals > eps, 1.0 / np.sqrt(eigvals), 0.0)

    # ZCA 白化矩阵: W = V @ diag(1/sqrt(λ)) @ V^T
    W = eigvecs @ np.diag(inv_sqrt_eigvals) @ eigvecs.T

    return centered @ W


def _compute_knn_distances(embeddings: np.ndarray, k: int = KNN_K) -> np.ndarray:
    """
    计算每个样本到其第 K 近邻的距离。

    Args:
        embeddings: shape (n, d)
        k:          近邻数

    Returns:
        shape (n,) 的 kNN 距离数组 (欧氏距离)
    """
    n = embeddings.shape[0]
    k = min(k, n - 1)  # 防止 k >= n

    if k <= 0:
        return np.zeros(n)

    # L2 距离矩阵 (避免 scipy 依赖)
    # ||a - b||^2 = ||a||^2 + ||b||^2 - 2 a·b
    sq_norms = (embeddings ** 2).sum(axis=1)
    dist_sq = sq_norms[:, None] + sq_norms[None, :] - 2.0 * (embeddings @ embeddings.T)
    # 数值稳定: 消除负数 (浮点误差)
    dist_sq = np.clip(dist_sq, 0.0, None)
    np.fill_diagonal(dist_sq, np.inf)  # 排除自身

    # 取第 k 小的距离
    partitioned = np.partition(dist_sq, k - 1, axis=1)
    knn_dist_sq = partitioned[:, k - 1]
    return np.sqrt(knn_dist_sq)


def detect_outliers(
    embeddings: np.ndarray,
    contamination: float = 0.05,
    knn_k: int = KNN_K,
    random_state: int = 42,
) -> Set[int]:
    """
    [AUDIT-050] Isolation Forest + kNN-distance 双检测异常点。

    两者都判异常 (AND 逻辑) 才标记为异常, 降低假阳性率。

    Algorithm:
        1. Isolation Forest (sklearn): 树方法, 对各向异性鲁棒
           - contamination 参数控制预期异常比例
           - predict = -1 → 异常候选
        2. kNN-distance (K=knn_k): 第 K 近邻欧氏距离
           - 距离 > threshold (均值 + 2σ) → 异常候选
        3. AND: 两方法同时判异常才输出

    Args:
        embeddings:     shape (n, d) 嵌入矩阵。
        contamination:  预期异常比例, 传给 IsolationForest。
                        取值范围 (0, 0.5], 默认 0.05。
        knn_k:          kNN 邻居数, 默认 10。
        random_state:   IsolationForest 随机种子, 默认 42 (可复现)。

    Returns:
        异常点的下标集合 set[int]。空集合表示未检测到异常。

    Raises:
        ImportError: 若 sklearn 未安装。
        ValueError:  若 embeddings 为空或维度不对。
    """
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        raise ImportError(
            "scikit-learn 未安装, 请 pip install scikit-learn"
        )

    emb = np.array(embeddings, dtype=np.float64)
    if emb.ndim != 2:
        raise ValueError(f"embeddings 必须是 2D 数组, 收到 shape={emb.shape}")

    n = emb.shape[0]
    if n == 0:
        return set()

    if n == 1:
        # 单个样本无法判断异常
        logger.warning("detect_outliers: 只有 1 个样本, 无法检测异常, 返回空集")
        return set()

    # --- Step 1: Isolation Forest ---
    # contamination 可能超过有效范围, 做安全 clip
    safe_contamination = float(np.clip(contamination, 1e-4, 0.5))
    iso = IsolationForest(
        contamination=safe_contamination,
        random_state=random_state,
        n_estimators=100,
    )
    iso_labels = iso.fit_predict(emb)  # 1=正常, -1=异常
    iso_outliers: Set[int] = {i for i, lbl in enumerate(iso_labels) if lbl == -1}

    logger.debug("IsolationForest: %d / %d 异常", len(iso_outliers), n)

    # --- Step 2: kNN-distance ---
    knn_dists = _compute_knn_distances(emb, k=knn_k)
    knn_mean = knn_dists.mean()
    knn_std = knn_dists.std()
    knn_threshold = knn_mean + 2.0 * knn_std
    knn_outliers: Set[int] = {i for i, d in enumerate(knn_dists) if d > knn_threshold}

    logger.debug(
        "kNN-distance (k=%d): %d / %d 异常 (threshold=%.4f)",
        knn_k,
        len(knn_outliers),
        n,
        knn_threshold,
    )

    # --- Step 3: AND 两者均异常才输出 ---
    outliers = iso_outliers & knn_outliers

    logger.info(
        "detect_outliers: IF=%d, kNN=%d, AND=%d (n=%d, contamination=%.3f)",
        len(iso_outliers),
        len(knn_outliers),
        len(outliers),
        n,
        safe_contamination,
    )

    return outliers
