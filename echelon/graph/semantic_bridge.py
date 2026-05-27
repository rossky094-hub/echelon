"""
V11.3-R4: Semantic bridge edge builder.

Replaces TF-IDF+SVD 256D with sentence-transformers/all-MiniLM-L6-v2 (90MB local).
Falls back to TF-IDF+SVD if sentence-transformers is unavailable.

Changes from V11.2 pilot:
  - Embedding: sentence-transformers/all-MiniLM-L6-v2 preferred (768D → 384D)
  - Cosine threshold: 0.70 (sentence-transformers) or 0.65 (TF-IDF fallback)
  - Bridge keyword forcing: papers with bridge keywords get automatic edges (weight=0.5)
  - Cross-topic only (AUDIT-063: same-topic pairs excluded)

This resolves R4: Pilot 1k produced only 7 semantic_bridge edges total,
with only 1 Optics ↔ ML bridge. Target: ≥ 10 cross-topic bridges.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

# Threshold when using sentence-transformers (dense semantic space)
COSINE_THRESHOLD_DENSE = 0.70

# Threshold when using TF-IDF+SVD fallback (sparse/reduced space)
COSINE_THRESHOLD_TFIDF = 0.65

# Forced bridge edge weight (bridge keyword match)
BRIDGE_KEYWORD_WEIGHT = 0.5


def _build_tfidf_embeddings(
    abstracts: List[str],
    n_components: int = 256,
) -> Any:
    """
    Fallback: TF-IDF + SVD (TruncatedSVD) embeddings, L2-normalized.

    Args:
        abstracts:    List of abstract strings.
        n_components: SVD dimensions (default 256).

    Returns:
        numpy array of shape (n_papers, n_components), L2-normalized.
    """
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.decomposition import TruncatedSVD
    from sklearn.preprocessing import normalize

    vectorizer = TfidfVectorizer(max_features=5000, min_df=2, stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(abstracts)

    n_comp = min(n_components, tfidf_matrix.shape[1] - 1, len(abstracts) - 1)
    if n_comp < 1:
        n_comp = 1

    svd = TruncatedSVD(n_components=n_comp, random_state=42)
    reduced = svd.fit_transform(tfidf_matrix)

    return normalize(reduced, norm="l2")


def _build_sentence_transformer_embeddings(
    abstracts: List[str],
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> Tuple[Any, bool]:
    """
    Build embeddings using sentence-transformers (preferred, ~90MB model).

    Args:
        abstracts:  List of abstract strings.
        model_name: HuggingFace model identifier.

    Returns:
        (embeddings_array, success_flag)
        success_flag=False means fallback should be used.
    """
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
        from sklearn.preprocessing import normalize

        model = SentenceTransformer(model_name)
        embeddings = model.encode(
            abstracts,
            batch_size=64,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,  # L2 normalize in-place
        )
        return embeddings, True

    except ImportError:
        logger.warning(
            "sentence-transformers not available; falling back to TF-IDF+SVD. "
            "Install with: pip install sentence-transformers"
        )
        return None, False
    except Exception as exc:
        logger.warning(
            f"sentence-transformers encoding failed ({exc}); falling back to TF-IDF+SVD"
        )
        return None, False


def build_semantic_bridge_edges(
    papers: List[Dict],
    paper_id_field: str = "paper_id",
    abstract_field: str = "abstract",
    topic_id_field: str = "primary_topic_id",
    author_field: str = "author_names",
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    cosine_threshold_dense: float = COSINE_THRESHOLD_DENSE,
    cosine_threshold_tfidf: float = COSINE_THRESHOLD_TFIDF,
    use_bridge_keywords: bool = True,
    bridge_keyword_weight: float = BRIDGE_KEYWORD_WEIGHT,
    max_edges: int = 50_000,
) -> List[Tuple[str, str, float, str]]:
    """
    [V11.3-R4] Build semantic bridge edges for cross-topic paper pairs.

    Two papers from different topics get a semantic_bridge edge if:
    1. Their cosine similarity >= threshold (dense: 0.70, TF-IDF: 0.65), OR
    2. Either paper's abstract contains a bridge keyword (forced edge, weight=0.5)

    Same-author pairs are excluded (AUDIT-063).

    Args:
        papers:                   List of paper dicts.
        paper_id_field:           Key for paper ID.
        abstract_field:           Key for abstract text.
        topic_id_field:           Key for topic identifier.
        author_field:             Key for author names (list or set).
        model_name:               HuggingFace model for dense embeddings.
        cosine_threshold_dense:   Cosine threshold for sentence-transformers.
        cosine_threshold_tfidf:   Cosine threshold for TF-IDF fallback.
        use_bridge_keywords:      Whether to add bridge keyword edges.
        bridge_keyword_weight:    Weight for bridge-keyword-forced edges.
        max_edges:                Maximum number of edges to return.

    Returns:
        List of (paper_id_a, paper_id_b, weight, edge_source) tuples.
        edge_source is "cosine" or "bridge_keyword".
    """
    import numpy as np
    from collections import defaultdict

    if not papers:
        return []

    abstracts = [p.get(abstract_field, "") or "" for p in papers]
    paper_ids = [p.get(paper_id_field, str(i)) for i, p in enumerate(papers)]
    topic_ids = [p.get(topic_id_field, "unknown") or "unknown" for p in papers]

    # Build author sets for same-author filtering (AUDIT-063)
    author_sets: List[set] = []
    for p in papers:
        raw = p.get(author_field, []) or []
        if isinstance(raw, (list, set)):
            author_sets.append({str(a).lower() for a in raw})
        else:
            author_sets.append(set())

    # Step 1: Try sentence-transformers
    embeddings, use_dense = _build_sentence_transformer_embeddings(abstracts, model_name)
    threshold = cosine_threshold_dense if use_dense else cosine_threshold_tfidf

    if not use_dense:
        logger.info("Using TF-IDF+SVD fallback for semantic bridge (threshold=%.2f)", threshold)
        try:
            embeddings = _build_tfidf_embeddings(abstracts)
        except Exception as exc:
            logger.error(f"TF-IDF fallback also failed: {exc}")
            embeddings = None

    # Step 2: Build topic buckets
    topic_buckets: Dict[str, List[int]] = defaultdict(list)
    for i, tid in enumerate(topic_ids):
        topic_buckets[tid].append(i)

    topics = list(topic_buckets.keys())

    edges: List[Tuple[str, str, float, str]] = []
    edge_set: set = set()

    def _add_edge(pid_a: str, pid_b: str, weight: float, source: str) -> None:
        pair = tuple(sorted([pid_a, pid_b]))
        if pair not in edge_set and len(edges) < max_edges:
            edge_set.add(pair)
            edges.append((*pair, weight, source))

    # Step 3: Cosine-threshold edges (cross-topic)
    if embeddings is not None:
        emb_array = np.array(embeddings)
        for t1_idx in range(len(topics)):
            for t2_idx in range(t1_idx + 1, len(topics)):
                idx1_list = topic_buckets[topics[t1_idx]]
                idx2_list = topic_buckets[topics[t2_idx]]

                emb1 = emb_array[idx1_list]
                emb2 = emb_array[idx2_list]

                # L2-normalized: cosine = dot product
                cos_matrix = emb1 @ emb2.T  # (n1, n2)

                high_pairs = np.argwhere(cos_matrix >= threshold)
                for pair in high_pairs:
                    li, lj = pair[0], pair[1]
                    gi = idx1_list[li]
                    gj = idx2_list[lj]

                    pid_a = paper_ids[gi]
                    pid_b = paper_ids[gj]

                    # AUDIT-063: filter same-author pairs
                    if author_sets[gi] & author_sets[gj]:
                        continue

                    cos_val = float(cos_matrix[li, lj])
                    _add_edge(pid_a, pid_b, cos_val, "cosine")

    # Step 4: Bridge keyword forced edges (cross-topic)
    if use_bridge_keywords:
        from echelon.graph.bridge_keywords import contains_bridge_keyword

        bridge_indices = [i for i, abs_text in enumerate(abstracts)
                          if contains_bridge_keyword(abs_text)]

        for bi in bridge_indices:
            bridge_topic = topic_ids[bi]
            bridge_pid = paper_ids[bi]

            for other_i, other_tid in enumerate(topic_ids):
                if other_tid == bridge_topic:
                    continue  # cross-topic only
                if other_i == bi:
                    continue

                other_pid = paper_ids[other_i]

                # AUDIT-063: filter same-author
                if author_sets[bi] & author_sets[other_i]:
                    continue

                _add_edge(bridge_pid, other_pid, bridge_keyword_weight, "bridge_keyword")

                if len(edges) >= max_edges:
                    logger.warning(
                        f"Reached max_edges={max_edges} during bridge keyword expansion"
                    )
                    break

    logger.info(
        "semantic_bridge: %d edges (threshold=%.2f, backend=%s, bridge_kw=%s)",
        len(edges),
        threshold,
        "sentence-transformers" if use_dense else "TF-IDF+SVD",
        use_bridge_keywords,
    )

    return edges


# ---------------------------------------------------------------------------
# AUDIT-077: Payload pre-filter — cross-topic only
# ---------------------------------------------------------------------------

def pre_filter_cross_topic(
    papers: List[Dict],
    candidates: List[Dict],
    query_paper: Dict,
    topic_id_field: str = "primary_topic_id",
) -> List[Dict]:
    """
    [AUDIT-077] Qdrant payload pre-filter: 在向量检索前过滤同 topic 候选。

    问题背景:
        Qdrant 向量空间中同 topic 论文高度聚集, 不加过滤则向量检索
        结果几乎全部来自同一 topic, 导致 semantic_bridge 无法找到
        真正的跨 topic 桥接论文。

    修复:
        在向量检索前, 先按 topic_id ≠ query_paper.topic_id 过滤候选集。
        - 真实 Qdrant 场景: 在 payload filter 中加 `must_not: {key: topic_id, match: value}`
        - Pilot (numpy) 场景: 本函数直接对 Python list 做过滤

    Args:
        papers:         全量论文列表 (完整 corpus, 用于获取 query_paper 的 topic_id)。
                        若 query_paper 已包含 topic_id_field 则不需要。
        candidates:     候选论文列表 (向量检索前的候选池)。
        query_paper:    查询论文 dict, 包含 topic_id_field 字段。
        topic_id_field: topic ID 字段名, 默认 "primary_topic_id"。

    Returns:
        过滤后的候选列表: topic_id ≠ query_paper[topic_id_field] 的论文。
        若 query_paper 无有效 topic_id 则返回原始 candidates (不过滤)。

    Example (Pilot, numpy path)::

        query = {"paper_id": "P1", "primary_topic_id": "optics_001"}
        candidates = [
            {"paper_id": "P2", "primary_topic_id": "optics_001"},  # 同 topic → 过滤
            {"paper_id": "P3", "primary_topic_id": "ml_042"},       # 跨 topic → 保留
        ]
        result = pre_filter_cross_topic([], candidates, query)
        # result == [{"paper_id": "P3", ...}]

    Example (Qdrant production path — pseudo-code)::

        # 在 QdrantClient.search() 中加入 payload filter:
        # query_filter = Filter(
        #     must_not=[
        #         FieldCondition(
        #             key="primary_topic_id",
        #             match=MatchValue(value=query_topic_id)
        #         )
        #     ]
        # )
        # results = client.search(
        #     collection_name="papers",
        #     query_vector=query_embedding,
        #     query_filter=query_filter,
        #     limit=top_k,
        # )
    """
    query_topic = query_paper.get(topic_id_field)

    if not query_topic:
        logger.warning(
            "pre_filter_cross_topic: query_paper 无 %s 字段, 跳过过滤",
            topic_id_field,
        )
        return list(candidates)

    filtered = [
        c for c in candidates
        if c.get(topic_id_field) != query_topic
    ]

    logger.debug(
        "pre_filter_cross_topic: %d → %d candidates (query_topic=%s)",
        len(candidates),
        len(filtered),
        query_topic,
    )

    return filtered


def count_semantic_bridges(
    paper: Dict,
    candidates: List[Dict],
    embeddings: Optional[Any] = None,
    paper_idx: Optional[int] = None,
    candidate_indices: Optional[List[int]] = None,
    cosine_threshold: float = COSINE_THRESHOLD_DENSE,
    topic_id_field: str = "primary_topic_id",
    min_sb_count: int = 1,
) -> int:
    """
    [AUDIT-077] 计算论文的 semantic bridge count (sb_count)。

    AUDIT-077 修订: 阈值从 ≥3 降到 ≥1, 并强制 pre-filter cross-topic。

    Args:
        paper:             查询论文 dict。
        candidates:        候选论文列表 (应已通过 pre_filter_cross_topic 过滤)。
        embeddings:        (可选) 嵌入矩阵 shape (n_all, d), L2 归一化。
        paper_idx:         paper 在 embeddings 中的下标。
        candidate_indices: candidates 在 embeddings 中的下标列表。
        cosine_threshold:  余弦相似度阈值, 默认 0.70。
        topic_id_field:    topic ID 字段名。
        min_sb_count:      最小桥接数 (≥1 为 True), 默认 1。

    Returns:
        int: sb_count (跨 topic 且余弦 >= threshold 的候选数)。
    """
    import numpy as np

    # 先做 cross-topic pre-filter
    cross_topic_candidates = pre_filter_cross_topic([], candidates, paper, topic_id_field)

    if not cross_topic_candidates or embeddings is None:
        return len(cross_topic_candidates)  # 无 embedding 时直接按候选数计

    if paper_idx is None or candidate_indices is None:
        return len(cross_topic_candidates)

    # 计算余弦相似度 (L2 归一化后 = 内积)
    emb_array = np.array(embeddings)
    query_emb = emb_array[paper_idx]
    sb_count = 0

    for c, c_idx in zip(cross_topic_candidates, candidate_indices):
        cand_emb = emb_array[c_idx]
        cosine = float(np.dot(query_emb, cand_emb))
        if cosine >= cosine_threshold:
            sb_count += 1

    return sb_count
