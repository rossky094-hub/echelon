"""
AUDIT-076 P1: 局部 PageRank 概率质量黑洞 → 虚拟 sink 节点

原问题:
    局部 PageRank 中, seed 节点集合的外部邻居 (dst 不在子图内) 会把
    概率质量永久带走 (概率黑洞), 导致子图内总质量 << 1.0,
    局部重要性评分系统性偏低。

修复:
    引入虚拟 sink 节点 `_external_sink`:
    - 所有指向子图外部的出边 (外部边) 改为指向 sink
    - 在扩展子图上运行标准 NetworkX PageRank (保证质量守恒)
    - 返回时去掉 sink, 仅返回原始节点的 PageRank 分布
    - 去掉 sink 后做归一化 (sum → 1.0), 便于下游使用

    质量守恒验证:
    - 包含 sink 的总质量 ≈ 1.0 (NetworkX PageRank 保证)
    - 去掉 sink 后的子图质量 = 1 - pr[sink]

References:
    Page et al. 1999: The PageRank Citation Ranking: Bringing Order to the Web
    AUDIT-076 修订点: Echelon V11.2 修订摘要 §6.5.2
"""
from __future__ import annotations

import logging
from typing import Any, Collection, Dict, Optional

logger = logging.getLogger(__name__)

# 虚拟 sink 节点标识符 (保证不与真实节点冲突)
EXTERNAL_SINK_ID = "_external_sink"


def compute_local_pagerank_with_sink(
    graph: Any,
    seed_nodes: Collection[Any],
    alpha: float = 0.85,
    weight: Optional[str] = "weight",
    normalize: bool = True,
) -> Dict[Any, float]:
    """
    [AUDIT-076] 带虚拟 sink 节点的局部 PageRank, 解决概率质量黑洞。

    Algorithm:
        1. 提取由 seed_nodes 诱导的子图 (子图包含 seed_nodes 的所有直接邻居)
        2. 识别外部边: src 在子图内, dst 在子图外的边
        3. 将外部边的 dst 替换为虚拟 sink `_external_sink`
        4. 在扩展子图 (含 sink) 上运行 NetworkX PageRank
        5. 删除 sink 的 PageRank 值, 返回子图节点分布
        6. 若 normalize=True, 对返回值归一化使 sum=1.0

    Args:
        graph:       NetworkX 图对象 (DiGraph 或 Graph)。
                     若为无向图, 自动转换为有向图。
        seed_nodes:  种子节点集合 (必须是图中实际存在的节点)。
        alpha:       阻尼系数, 默认 0.85。
        weight:      边权重属性名, None 表示无权重。
        normalize:   是否对返回的子图质量归一化 (sum=1.0)。
                     默认 True。若 False 则保留原始 PageRank 值
                     (sum = 1 - pr[_external_sink])。

    Returns:
        Dict[node_id, pagerank_score] (不含 sink 节点)。
        若 seed_nodes 为空或全不在图中, 返回空字典。

    Raises:
        ImportError: 若 networkx 未安装。
        TypeError:   若 graph 不是 NetworkX 图对象。

    Notes:
        - 子图定义: seed_nodes ∪ {v | (u, v) ∈ E, u ∈ seed_nodes}
          即 seed 节点及其所有 1 跳邻居
        - sink 节点接收所有外部概率质量, 自身无出边 (dangling node),
          NetworkX 处理 dangling 时均匀分配给所有节点, 保持总质量 = 1.0
    """
    try:
        import networkx as nx
    except ImportError:
        raise ImportError("NetworkX 未安装, 请 pip install networkx")

    if not isinstance(graph, (nx.Graph, nx.DiGraph, nx.MultiGraph, nx.MultiDiGraph)):
        raise TypeError(f"期望 NetworkX 图, 收到 {type(graph)}")

    # 统一转换为有向图 (PageRank 基于有向图)
    if not isinstance(graph, (nx.DiGraph, nx.MultiDiGraph)):
        digraph: nx.DiGraph = nx.DiGraph(graph)
    else:
        digraph = graph  # type: ignore[assignment]

    # --- Step 1: 确定子图节点 ---
    # 过滤不存在于图中的 seed 节点
    valid_seeds = {n for n in seed_nodes if digraph.has_node(n)}
    if not valid_seeds:
        logger.warning("compute_local_pagerank_with_sink: 无有效 seed 节点, 返回空字典")
        return {}

    # 子图 = seeds + 所有 1 跳邻居
    subgraph_nodes: set = set(valid_seeds)
    for seed in valid_seeds:
        # 出邻居
        subgraph_nodes.update(digraph.successors(seed))
        # 入邻居 (保留: 让入边信息进入子图)
        subgraph_nodes.update(digraph.predecessors(seed))

    # 确保 sink 不与任何真实节点重名
    sink = EXTERNAL_SINK_ID
    if sink in subgraph_nodes:
        # 极罕见: 真实节点名与 sink 冲突, 加后缀规避
        sink = f"{EXTERNAL_SINK_ID}__{hash(tuple(sorted(str(n) for n in subgraph_nodes)))}"
        logger.warning("sink 名称冲突, 改用: %s", sink)

    # --- Step 2: 构建扩展子图 ---
    extended = nx.DiGraph()
    extended.add_nodes_from(subgraph_nodes)
    extended.add_node(sink)  # 虚拟 sink

    external_edge_count = 0
    for u in subgraph_nodes:
        for v in digraph.successors(u):
            if v in subgraph_nodes:
                # 内部边: 直接复制
                edge_data = digraph.get_edge_data(u, v) or {}
                extended.add_edge(u, v, **edge_data)
            else:
                # 外部边: 重定向到 sink
                if weight and (edge_attrs := digraph.get_edge_data(u, v)):
                    w = edge_attrs.get(weight, 1.0)
                    # 累加 (若已有边到 sink)
                    if extended.has_edge(u, sink):
                        extended[u][sink][weight] = extended[u][sink].get(weight, 0) + w
                    else:
                        extended.add_edge(u, sink, **{weight: w})
                else:
                    if not extended.has_edge(u, sink):
                        extended.add_edge(u, sink)
                external_edge_count += 1

    logger.debug(
        "local_pagerank: subgraph=%d nodes, external_edges=%d → sink",
        len(subgraph_nodes),
        external_edge_count,
    )

    # --- Step 3: 运行 NetworkX PageRank ---
    try:
        pr = nx.pagerank(extended, alpha=alpha, weight=weight)
    except nx.exception.PowerIterationFailedConvergence:
        logger.warning(
            "PageRank 未收敛 (nodes=%d), 尝试增加迭代次数", extended.number_of_nodes()
        )
        pr = nx.pagerank(extended, alpha=alpha, weight=weight, max_iter=1000)

    # --- Step 4: 去掉 sink, 返回子图节点分布 ---
    pr_without_sink = {node: score for node, score in pr.items() if node != sink}

    sink_mass = pr.get(sink, 0.0)
    logger.debug(
        "local_pagerank: sink_mass=%.4f, subgraph_mass=%.4f",
        sink_mass,
        sum(pr_without_sink.values()),
    )

    # --- Step 5: 可选归一化 ---
    if normalize:
        total = sum(pr_without_sink.values())
        if total > 1e-12:
            pr_without_sink = {node: score / total for node, score in pr_without_sink.items()}

    return pr_without_sink
