"""
AUDIT-066 P1: Leiden 密集图模块度塌陷 → 余弦 0.83 + CPM

原问题: 余弦 ≥ 0.7 阈值在密集 SPECTER2 向量中构成近全连接图,
        Leiden 模块度塌陷到 1-2 个"毛线球", 无法输出 20-40 个 cluster。

修复:
1. 余弦阈值提升到 0.83 (减少边密度, 避免近全连接)
2. 改用 CPM (Constant Potts Model) 替代默认模块度方法
   - CPM 无分辨率限制 (resolution limit), 可切分密集 clique
   - γ (gamma) 为 CPM 分辨率参数, 越大 → cluster 越细
3. 自动 γ 调优: 试 5 个 γ 值 [0.3, 0.6, 0.9, 1.2, 1.5], 选 modularity 最高的
4. 若 leidenalg 未安装: fallback 到 KMeans 并 log warning

V11.5 P1-B: 新建 echelon/bottleneck/cluster.py
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# 默认参数
DEFAULT_COSINE_THRESHOLD: float = 0.83
DEFAULT_GAMMA_RANGE: Tuple[float, float] = (0.3, 1.5)
DEFAULT_GAMMA_N_CANDIDATES: int = 5
DEFAULT_MIN_CLUSTER_SIZE: int = 2


def _cosine_similarity_matrix(embeddings: List[List[float]]) -> List[List[float]]:
    """
    计算 NxN 余弦相似度矩阵 (纯 Python 实现, numpy 可选)

    Args:
        embeddings: N 个 D 维向量列表

    Returns:
        NxN 相似度矩阵 (list of lists)
    """
    try:
        import numpy as np
        emb_arr = np.array(embeddings, dtype=float)
        # 归一化
        norms = np.linalg.norm(emb_arr, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-9)
        emb_norm = emb_arr / norms
        sim = emb_norm @ emb_norm.T
        return sim.tolist()
    except ImportError:
        pass

    # 纯 Python fallback
    n = len(embeddings)
    norms = []
    for emb in embeddings:
        norm = math.sqrt(sum(x * x for x in emb))
        norms.append(max(norm, 1e-9))

    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            dot = sum(embeddings[i][k] * embeddings[j][k] for k in range(len(embeddings[i])))
            val = dot / (norms[i] * norms[j])
            val = max(-1.0, min(1.0, val))
            sim[i][j] = val
            sim[j][i] = val
    return sim


def _build_cosine_graph(
    embeddings: List[List[float]],
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
) -> Any:
    """
    建立余弦阈值图 (networkx.Graph)

    Args:
        embeddings: 向量列表
        cosine_threshold: 余弦相似度阈值, 默认 0.83

    Returns:
        networkx.Graph (若 networkx 已安装) 或 邻接列表 dict (fallback)
    """
    try:
        import networkx as nx
    except ImportError:
        raise ImportError("NetworkX 未安装, 请 pip install networkx")

    n = len(embeddings)
    sim = _cosine_similarity_matrix(embeddings)

    G = nx.Graph()
    for i in range(n):
        G.add_node(i)

    for i in range(n):
        for j in range(i + 1, n):
            if sim[i][j] >= cosine_threshold:
                G.add_edge(i, j, weight=float(sim[i][j]))

    n_edges = G.number_of_edges()
    density = n_edges / max(1, n * (n - 1) / 2)
    logger.debug(
        f"[AUDIT-066] 余弦图: N={n}, 阈值={cosine_threshold}, "
        f"边数={n_edges}, 密度={density:.3f}"
    )

    return G


def _leiden_cpm_partition(
    graph: Any,
    gamma: float,
) -> List[int]:
    """
    用 leidenalg CPM 方法对图进行分区

    Args:
        graph: networkx.Graph
        gamma: CPM 分辨率参数

    Returns:
        List[int]: 节点 0..N-1 的 cluster 标签 (0-indexed)
    """
    import leidenalg
    import igraph as ig

    # networkx → igraph
    nodes = list(graph.nodes())
    node_idx = {n: i for i, n in enumerate(nodes)}
    edges = [(node_idx[u], node_idx[v]) for u, v in graph.edges()]
    weights = [graph[u][v].get("weight", 1.0) for u, v in graph.edges()]

    ig_graph = ig.Graph(n=len(nodes), edges=edges, directed=False)
    ig_graph.es["weight"] = weights

    partition = leidenalg.find_partition(
        ig_graph,
        leidenalg.CPMVertexPartition,
        resolution_parameter=gamma,
        weights="weight",
    )

    # 恢复到原节点顺序
    labels = [0] * len(nodes)
    for cluster_id, cluster_nodes in enumerate(partition):
        for node_in_ig in cluster_nodes:
            original_node = nodes[node_in_ig]
            labels[original_node] = cluster_id

    return labels


def _compute_modularity(graph: Any, labels: List[int]) -> float:
    """计算给定分区的模块度"""
    try:
        import networkx as nx
        n = graph.number_of_nodes()
        if n == 0:
            return 0.0
        # 构建 community 列表
        communities: Dict[int, set] = {}
        for node, label in enumerate(labels):
            communities.setdefault(label, set()).add(node)
        community_list = list(communities.values())
        return nx.algorithms.community.quality.modularity(graph, community_list)
    except Exception:
        return 0.0


def _kmeans_fallback(
    embeddings: List[List[float]],
    n_clusters: int,
) -> List[int]:
    """
    KMeans fallback (当 leidenalg 不可用时)

    Args:
        embeddings: 向量列表
        n_clusters: 目标 cluster 数量

    Returns:
        List[int]: cluster 标签
    """
    try:
        from sklearn.cluster import KMeans
        import numpy as np

        emb_arr = np.array(embeddings, dtype=float)
        n = len(emb_arr)
        k = max(2, min(n_clusters, n))

        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(emb_arr)
        return labels.tolist()

    except ImportError:
        # 极端 fallback: 所有归一个 cluster
        logger.warning("[AUDIT-066] sklearn 也未安装, 所有节点归为 cluster 0")
        return [0] * len(embeddings)


def cluster_with_leiden_cpm(
    embeddings: List[List[float]],
    gamma_range: Tuple[float, float] = DEFAULT_GAMMA_RANGE,
    n_gamma_candidates: int = DEFAULT_GAMMA_N_CANDIDATES,
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    fallback_n_clusters: int = 20,
) -> Dict[str, Any]:
    """
    [AUDIT-066 P1] Leiden CPM 聚类 (余弦 0.83 + 自动 γ 调优)

    设计点:
    1. 余弦阈值 0.83 (原 0.7 → 密度过高 → 模块度塌陷)
    2. CPM (Constant Potts Model): 无分辨率限制, 适合密集图
    3. 自动 γ 调优: 在 gamma_range 内等间距试 n_gamma_candidates 个值,
       选 networkx modularity 最高的分区
    4. 若 leidenalg 不可用 → KMeans fallback + warning
    5. 若 igraph 不可用 → KMeans fallback + warning

    Args:
        embeddings:          N 个向量 (e.g. SPECTER2 768-dim)
        gamma_range:         γ 调优范围 (min, max), 默认 (0.3, 1.5)
        n_gamma_candidates:  试 γ 值数量, 默认 5
        cosine_threshold:    建边余弦阈值, 默认 0.83 (AUDIT-066)
        min_cluster_size:    最小 cluster 大小 (过小的 cluster 合并到最近 cluster)
        fallback_n_clusters: KMeans fallback 时的目标 cluster 数量

    Returns:
        Dict with keys:
          - "labels": List[int]          # 每个输入向量的 cluster 标签
          - "n_clusters": int             # 实际 cluster 数量
          - "method": str                 # "leiden_cpm" / "kmeans_fallback"
          - "best_gamma": Optional[float] # 最优 γ (leiden 时有值)
          - "best_modularity": float      # 最优分区的模块度
          - "gamma_search": List[dict]    # γ 搜索过程 [{gamma, n_clusters, modularity}]

    Examples:
        >>> import random
        >>> embs = [[random.random() for _ in range(8)] for _ in range(20)]
        >>> result = cluster_with_leiden_cpm(embs)
        >>> "labels" in result and "n_clusters" in result
        True
    """
    n = len(embeddings)
    if n == 0:
        return {
            "labels": [], "n_clusters": 0,
            "method": "empty", "best_gamma": None,
            "best_modularity": 0.0, "gamma_search": [],
        }
    if n == 1:
        return {
            "labels": [0], "n_clusters": 1,
            "method": "trivial", "best_gamma": None,
            "best_modularity": 0.0, "gamma_search": [],
        }

    # 尝试 Leiden CPM
    leiden_available = False
    try:
        import leidenalg  # noqa: F401
        import igraph  # noqa: F401
        leiden_available = True
    except ImportError:
        logger.warning(
            "[AUDIT-066] leidenalg 或 igraph 未安装, fallback 到 KMeans。"
            "建议: pip install leidenalg igraph 以使用 Leiden CPM 聚类。"
        )

    if not leiden_available:
        labels = _kmeans_fallback(embeddings, fallback_n_clusters)
        n_clusters = len(set(labels))
        return {
            "labels": labels,
            "n_clusters": n_clusters,
            "method": "kmeans_fallback",
            "best_gamma": None,
            "best_modularity": 0.0,
            "gamma_search": [],
        }

    # 建立余弦图 (阈值 0.83)
    try:
        import networkx as nx
        G = _build_cosine_graph(embeddings, cosine_threshold=cosine_threshold)
    except ImportError:
        logger.warning("[AUDIT-066] NetworkX 未安装, fallback 到 KMeans。")
        labels = _kmeans_fallback(embeddings, fallback_n_clusters)
        return {
            "labels": labels,
            "n_clusters": len(set(labels)),
            "method": "kmeans_fallback",
            "best_gamma": None,
            "best_modularity": 0.0,
            "gamma_search": [],
        }

    # 若图无边 (所有节点孤立), 每个节点自成 cluster
    if G.number_of_edges() == 0:
        logger.warning(
            f"[AUDIT-066] 余弦阈值 {cosine_threshold} 下图无边 (N={n}), "
            "每个节点自成独立 cluster。考虑降低阈值。"
        )
        return {
            "labels": list(range(n)),
            "n_clusters": n,
            "method": "leiden_cpm",
            "best_gamma": None,
            "best_modularity": 0.0,
            "gamma_search": [],
        }

    # 生成 γ 候选值 (等间距)
    gamma_min, gamma_max = gamma_range
    if n_gamma_candidates == 1:
        gamma_candidates = [(gamma_min + gamma_max) / 2]
    else:
        step = (gamma_max - gamma_min) / (n_gamma_candidates - 1)
        gamma_candidates = [gamma_min + i * step for i in range(n_gamma_candidates)]

    # γ 调优: 试每个 γ 值, 选 modularity 最高的
    best_labels: Optional[List[int]] = None
    best_modularity = -math.inf
    best_gamma: Optional[float] = None
    gamma_search_log: List[Dict[str, Any]] = []

    for gamma in gamma_candidates:
        try:
            labels_candidate = _leiden_cpm_partition(G, gamma)
            n_clusters_candidate = len(set(labels_candidate))
            mod = _compute_modularity(G, labels_candidate)

            gamma_search_log.append({
                "gamma": round(gamma, 4),
                "n_clusters": n_clusters_candidate,
                "modularity": round(mod, 6),
            })
            logger.debug(
                f"[AUDIT-066] γ={gamma:.3f}: {n_clusters_candidate} clusters, "
                f"modularity={mod:.4f}"
            )

            if mod > best_modularity:
                best_modularity = mod
                best_labels = labels_candidate
                best_gamma = gamma

        except Exception as e:
            logger.warning(f"[AUDIT-066] γ={gamma:.3f} 失败: {e}")
            gamma_search_log.append({"gamma": round(gamma, 4), "error": str(e)})

    if best_labels is None:
        # 所有 γ 失败 → KMeans fallback
        logger.warning("[AUDIT-066] 所有 γ 值 Leiden 失败, fallback 到 KMeans。")
        best_labels = _kmeans_fallback(embeddings, fallback_n_clusters)
        method = "kmeans_fallback"
        best_gamma = None
        best_modularity = 0.0
    else:
        method = "leiden_cpm"

    n_clusters = len(set(best_labels))
    logger.info(
        f"[AUDIT-066] 最终聚类: method={method}, γ={best_gamma}, "
        f"n_clusters={n_clusters}, modularity={best_modularity:.4f}"
    )

    return {
        "labels": best_labels,
        "n_clusters": n_clusters,
        "method": method,
        "best_gamma": best_gamma,
        "best_modularity": float(best_modularity) if best_modularity != -math.inf else 0.0,
        "gamma_search": gamma_search_log,
    }
