"""
AUDIT-002 + AUDIT-069: MMR (Maximal Marginal Relevance) 多样性精排
原问题 1 (AUDIT-002): DPP 惩罚项无上界, 可超过 1.0
原问题 2 (AUDIT-069): list.remove 遇到 dict 含 numpy array 报 ValueError

修复:
- 实现标准 MMR: score = λ·relevance - (1-λ)·max_similarity_to_selected
- 惩罚项 max(cos) ∈ [0, 1] → 有上界
- 用 selected_ids: set[str] 跟踪已选, 避免 list.remove 崩溃
"""
from __future__ import annotations

import math
from typing import List, Dict, Any, Optional, Set


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """计算两个向量的余弦相似度, 返回 [0, 1] (假设向量已归一化或手动计算)"""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0

    raw = dot / (norm_a * norm_b)
    # 余弦相似度值域 [-1, 1], clip 到 [0, 1] 使惩罚项有上界
    return max(0.0, min(1.0, raw))


def mmr_marginal_score(
    candidate: Dict[str, Any],
    selected: List[Dict[str, Any]],
    lam: float,
    embedding_key: str = "embedding",
    score_key: str = "score",
) -> float:
    """
    [AUDIT-002] 标准 MMR 边际分数:
        MMR(p) = λ · relevance(p) - (1-λ) · max_{s ∈ selected} cos(p, s)

    惩罚项 max(cos) ∈ [0, 1] → 有上界, 永不超界。
    当 selected 为空时, 惩罚项 = 0, 直接按 relevance 排序。

    Args:
        candidate: 候选论文 dict, 含 score_key 和 embedding_key
        selected: 已选论文列表
        lam: λ ∈ [0,1], 越大越偏重相关性, 越小越偏重多样性
        embedding_key: 向量字段名
        score_key: 相关性分数字段名

    Returns:
        MMR 边际分数 ∈ [-1, 1]
    """
    relevance = float(candidate.get(score_key, 0.0))
    cand_emb = candidate.get(embedding_key, [])

    if not selected:
        max_sim = 0.0
    else:
        max_sim = max(
            cosine_similarity(cand_emb, s.get(embedding_key, []))
            for s in selected
        )
        # 确保惩罚项 ∈ [0, 1]
        max_sim = max(0.0, min(1.0, max_sim))

    return lam * relevance - (1.0 - lam) * max_sim


def mmr_select(
    candidates: List[Dict[str, Any]],
    k: int,
    lam: float = 0.5,
    embedding_key: str = "embedding",
    score_key: str = "score",
    id_key: str = "paper_id",
) -> List[Dict[str, Any]]:
    """
    [AUDIT-002 + AUDIT-069] MMR 多样性精排, 选出 k 篇多样性最优论文

    修复要点:
    1. 惩罚项 max(cos) ∈ [0, 1] 有上界 (AUDIT-002)
    2. 用 selected_ids: set[str] 跟踪已选, 避免 list.remove(dict) 引发 ValueError (AUDIT-069)

    Args:
        candidates: 候选论文列表, 每篇含 id_key, score_key, embedding_key
        k: 目标选取数量
        lam: λ ∈ [0,1], 多样性-相关性权衡系数
        embedding_key: 向量字段名 (支持 numpy array 或 list)
        score_key: 相关性分数字段名
        id_key: 论文 ID 字段名

    Returns:
        selected: 选出的 k 篇论文 (按 MMR 选取顺序)

    Raises:
        ValueError: 如果 k 超过候选数量
    """
    if k <= 0:
        return []
    if k > len(candidates):
        k = len(candidates)

    selected: List[Dict[str, Any]] = []
    selected_ids: Set[str] = set()  # [AUDIT-069] 用 set 跟踪, 避免 list.remove 崩溃

    for _ in range(k):
        # 从未选候选中找 MMR 分数最高的
        best_paper: Optional[Dict[str, Any]] = None
        best_score = float("-inf")

        for cand in candidates:
            cand_id = cand.get(id_key, "")
            if cand_id in selected_ids:
                continue  # 跳过已选, 无需 list.remove

            # 将 embedding 转为 list (支持 numpy array)
            emb = cand.get(embedding_key, [])
            if hasattr(emb, "tolist"):
                emb = emb.tolist()

            # 临时构建用于计算的候选 dict (避免修改原始数据)
            cand_for_score = dict(cand)
            cand_for_score[embedding_key] = emb

            score = mmr_marginal_score(
                cand_for_score, selected, lam, embedding_key, score_key
            )

            if score > best_score:
                best_score = score
                best_paper = cand

        if best_paper is None:
            break

        selected.append(best_paper)
        selected_ids.add(best_paper.get(id_key, ""))

    return selected


# ---------------------------------------------------------------------------
# AUDIT-043 P1: DPP/MMR 保底 bucket 前余弦距离硬下界
# ---------------------------------------------------------------------------

def cosine_distance(vec_a: List[float], vec_b: List[float]) -> float:
    """
    余弦距离 = 1 - cosine_similarity ∈ [0, 2]
    (clip 后实际 ∈ [0, 1] 因为 cosine_similarity 被 clip 到 [0,1])
    """
    return 1.0 - cosine_similarity(vec_a, vec_b)


def mmr_select_with_cosine_floor(
    candidates: List[Dict[str, Any]],
    k: int,
    lam: float = 0.5,
    embedding_key: str = "embedding",
    score_key: str = "score",
    id_key: str = "paper_id",
    cosine_distance_floor: float = 0.20,
    fallback_k: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    [AUDIT-043 P1] MMR 精排 + fallback bucket 余弦距离硬下界

    在 fallback bucket (MMR 已选 k 篇不足时的兜底选取) 加余弦距离硬下界:
    fallback 候选必须与所有已选论文的余弦距离 ≥ cosine_distance_floor (默认 0.20)

    设计点:
    - 主路径 (前 k 篇): 标准 MMR 选取 (同 mmr_select)
    - fallback bucket: 当 MMR 选不够时, 从剩余候选中按相关性降序选取,
      但加余弦距离硬下界过滤 (cosine_distance ≥ 0.20)
    - 若 fallback 仍不足 (全部被过滤), 放宽下界到 0.0 (取任意论文)

    Args:
        candidates:            候选论文列表
        k:                     目标选取数量
        lam:                   MMR λ 系数
        embedding_key:         向量字段名
        score_key:             相关性分数字段名
        id_key:                论文 ID 字段名
        cosine_distance_floor: fallback bucket 余弦距离硬下界, 默认 0.20
        fallback_k:            fallback 最多补充篇数 (None = k)

    Returns:
        selected: 最多 k 篇论文

    Examples:
        >>> cands = [
        ...     {"paper_id": "A", "score": 0.9, "embedding": [1,0,0]},
        ...     {"paper_id": "B", "score": 0.8, "embedding": [1,0,0]},  # 与 A 完全相同
        ...     {"paper_id": "C", "score": 0.7, "embedding": [0,1,0]},  # 与 A 正交
        ... ]
        >>> sel = mmr_select_with_cosine_floor(cands, k=2, cosine_distance_floor=0.20)
        >>> # B 与 A 余弦距离 = 0 < 0.20, 在 fallback 时被过滤
        >>> set(p["paper_id"] for p in sel) == {"A", "C"}
        True
    """
    if k <= 0:
        return []
    if k > len(candidates):
        k = len(candidates)
    if fallback_k is None:
        fallback_k = k

    # 第一步: 标准 MMR 选取
    selected = mmr_select(
        candidates, k, lam=lam,
        embedding_key=embedding_key,
        score_key=score_key,
        id_key=id_key,
    )

    # 若已选够, 直接返回
    if len(selected) >= k:
        return selected

    # 第二步: fallback bucket — 不足时补充
    selected_ids: Set[str] = {p.get(id_key, "") for p in selected}

    def _emb(p: Dict[str, Any]) -> List[float]:
        emb = p.get(embedding_key, [])
        if hasattr(emb, "tolist"):
            emb = emb.tolist()
        return emb

    def _min_dist_to_selected(cand: Dict[str, Any]) -> float:
        """候选与所有已选论文的最小余弦距离"""
        cand_emb = _emb(cand)
        if not selected:
            return 1.0
        dists = [cosine_distance(cand_emb, _emb(s)) for s in selected]
        return min(dists)

    # 按相关性降序排列 fallback 候选
    fallback_pool = [
        c for c in candidates
        if c.get(id_key, "") not in selected_ids
    ]
    fallback_pool_sorted = sorted(
        fallback_pool,
        key=lambda p: float(p.get(score_key, 0.0)),
        reverse=True,
    )

    # 先尝试带硬下界的 fallback
    added = 0
    rejected_by_floor: List[Dict[str, Any]] = []

    for cand in fallback_pool_sorted:
        if len(selected) >= k or added >= fallback_k:
            break
        dist = _min_dist_to_selected(cand)
        if dist >= cosine_distance_floor:
            selected.append(cand)
            selected_ids.add(cand.get(id_key, ""))
            added += 1
        else:
            rejected_by_floor.append(cand)

    # 若仍不足, 放宽 floor (取被拒候选, 按相关性降序)
    if len(selected) < k:
        for cand in rejected_by_floor:
            if len(selected) >= k:
                break
            cand_id = cand.get(id_key, "")
            if cand_id not in selected_ids:
                selected.append(cand)
                selected_ids.add(cand_id)

    return selected
