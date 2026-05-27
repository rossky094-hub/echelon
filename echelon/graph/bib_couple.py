"""
AUDIT-009: entity_overlap OOM 修复 - TF-IDF 截断高频实体 + 跳过 doc_freq > 100
AUDIT-010: entity_overlap 不对称吸血修复 - 改为 Jaccard |shared|/|union|

原问题 AUDIT-009:
  全组合 O(n²) × 实体数量 → OOM
  高频实体 (如 "photon", "silicon") 几乎在每篇论文中出现,
  加入 overlap 计算带来噪音且消耗大量内存

原问题 AUDIT-010:
  原公式: overlap = |shared| / min(|A|, |B|)
  不对称: 小集合对大集合有 "吸血" 效应 (小论文实体全包含于大论文 → overlap=1)
  修复: Jaccard = |shared| / |union| (满足三角不等式, 对称)
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Set, Tuple, Optional


def compute_entity_idf(
    all_papers_entities: List[List[str]],
    max_doc_freq: int = 100,
) -> Dict[str, float]:
    """
    [AUDIT-009] 计算实体 IDF, 并过滤高频实体 (doc_freq > max_doc_freq)

    高频实体 (如 "photon", "result", "method") 在大量论文中出现,
    对 bib-coupling 没有区分度, 且会导致 OOM。
    过滤标准: 在超过 max_doc_freq 篇论文中出现的实体不参与计算。

    Args:
        all_papers_entities: 每篇论文的实体列表
        max_doc_freq: 最大文档频率阈值, 超过则跳过 (AUDIT-009)

    Returns:
        Dict[entity, idf_score], 已过滤高频实体
    """
    n_docs = len(all_papers_entities)
    if n_docs == 0:
        return {}

    doc_freq: Dict[str, int] = Counter()
    for entities in all_papers_entities:
        for ent in set(entities):  # 每篇论文每个实体只计一次
            doc_freq[ent] += 1

    idf: Dict[str, float] = {}
    for ent, df in doc_freq.items():
        # [AUDIT-009] 跳过 doc_freq > max_doc_freq 的高频实体
        if df > max_doc_freq:
            continue
        # IDF = log(N / df) + 1 (平滑)
        idf[ent] = math.log(n_docs / df) + 1.0

    return idf


def entity_overlap_jaccard(
    entities_a: List[str],
    entities_b: List[str],
    idf: Optional[Dict[str, float]] = None,
) -> float:
    """
    [AUDIT-010] Jaccard 实体重叠度 |shared| / |union|

    修复原来的不对称公式 |shared| / min(|A|, |B|):
    - 原公式: 小集合对大集合有吸血效应 (不对称)
    - Jaccard: 满足三角不等式, 对称性好, 是标准相似度度量

    可选 IDF 加权: 对高 IDF 实体 (稀有实体) 赋予更高权重。

    Args:
        entities_a: 论文 A 的实体集合
        entities_b: 论文 B 的实体集合
        idf: 实体 IDF 权重字典 (None 时等权重)

    Returns:
        Jaccard 相似度 ∈ [0, 1], 对称 (swap A,B 结果相同)
    """
    set_a: Set[str] = set(entities_a)
    set_b: Set[str] = set(entities_b)

    if idf is not None:
        # IDF 加权 Jaccard (过滤掉高频实体, 即 idf 中不存在的实体)
        # 只保留 idf 字典中存在的实体 (已过滤高频)
        set_a = {e for e in set_a if e in idf}
        set_b = {e for e in set_b if e in idf}

        shared = set_a & set_b
        union = set_a | set_b

        if not union:
            return 0.0

        # IDF 加权: sum(idf[e] for e in shared) / sum(idf[e] for e in union)
        weight_shared = sum(idf.get(e, 0.0) for e in shared)
        weight_union = sum(idf.get(e, 0.0) for e in union)

        return weight_shared / (weight_union + 1e-9)
    else:
        # 标准 Jaccard (等权重)
        shared = set_a & set_b
        union = set_a | set_b

        if not union:
            return 0.0

        return len(shared) / len(union)


def build_bib_coupling_edges(
    papers: List[Dict],
    entity_field: str = "entities",
    paper_id_field: str = "paper_id",
    similarity_threshold: float = 0.1,
    max_doc_freq: int = 100,
    max_pairs: int = 500_000,
) -> List[Tuple[str, str, float]]:
    """
    [AUDIT-009 + AUDIT-010] 批量构建 bib-coupling 实体重叠边

    AUDIT-009 修复: TF-IDF 截断高频实体 (doc_freq > max_doc_freq 跳过)
    AUDIT-010 修复: 使用 Jaccard |shared|/|union| (对称公式)

    内存安全措施:
    - 高频实体过滤减少有效实体数量
    - max_pairs 限制最大边数防 OOM
    - 只存储超过 similarity_threshold 的边

    Args:
        papers: 论文列表, 每篇含 paper_id_field 和 entity_field
        entity_field: 实体列表字段名
        paper_id_field: 论文 ID 字段名
        similarity_threshold: 最小相似度阈值 (低于此值不建边)
        max_doc_freq: 跳过文档频率超过此值的实体 (AUDIT-009)
        max_pairs: 最大返回边数 (OOM 保护)

    Returns:
        List of (paper_id_a, paper_id_b, jaccard_similarity) tuples
    """
    if not papers:
        return []

    # 提取所有论文的实体列表
    all_entities = [p.get(entity_field, []) for p in papers]
    paper_ids = [p.get(paper_id_field, str(i)) for i, p in enumerate(papers)]

    # [AUDIT-009] 计算 IDF, 过滤高频实体
    idf = compute_entity_idf(all_entities, max_doc_freq=max_doc_freq)

    edges: List[Tuple[str, str, float]] = []
    n = len(papers)

    for i in range(n):
        for j in range(i + 1, n):
            if len(edges) >= max_pairs:
                break  # OOM 保护

            sim = entity_overlap_jaccard(
                all_entities[i],
                all_entities[j],
                idf=idf,
            )

            if sim >= similarity_threshold:
                edges.append((paper_ids[i], paper_ids[j], sim))

        if len(edges) >= max_pairs:
            break

    return edges
