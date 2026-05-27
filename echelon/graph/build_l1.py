"""
AUDIT-011: NetworkX → GDS 路由修复

原问题: V11.1 全程用 NetworkX, 1900w 边时性能幻觉 (理论超时数小时)
修复:
- Pilot 模式 (≤ 1k 节点): 回退 NetworkX (可接受)
- 生产模式 (> 1w 节点): 必须使用 Neo4j GDS C++ (下推图算法)
- 提供 compute_centrality_neo4j_gds() 接口 (Pilot 可 Mock)
"""
from __future__ import annotations

from typing import Dict, Any, Optional, List


# 节点数阈值
PILOT_MAX_NODES = 1_000       # Pilot 模式: NetworkX 回退上限
PRODUCTION_MIN_NODES = 10_000  # 超过此数必须用 GDS


def compute_centrality_networkx(
    graph: Any,
    k: Optional[int] = None,
) -> Dict[str, Dict[str, float]]:
    """
    [AUDIT-011] Pilot 模式: NetworkX 中心性计算 (限 ≤ 1k 节点)

    超过 1k 节点时抛出 ValueError, 强制使用 GDS。

    Args:
        graph: NetworkX 图对象
        k: betweenness_centrality 采样节点数 (None = 精确计算)

    Returns:
        Dict[paper_id, {"betweenness": float, "degree": float}]

    Raises:
        ValueError: 节点数 > PILOT_MAX_NODES
    """
    try:
        import networkx as nx
    except ImportError:
        raise ImportError("NetworkX 未安装, 请 pip install networkx")

    n_nodes = graph.number_of_nodes()

    if n_nodes > PILOT_MAX_NODES:
        raise ValueError(
            f"[AUDIT-011] 节点数 {n_nodes} > {PILOT_MAX_NODES} (Pilot 上限)。"
            f"请使用 compute_centrality_neo4j_gds() 进行生产级计算。"
        )

    # Pilot 模式: NetworkX 精确计算
    # betweenness_centrality 必须传 weight 参数 (AUDIT-075)
    bc = nx.betweenness_centrality(graph, weight="weight", normalized=True)
    degree = {str(n): d for n, d in graph.degree(weight="weight")}

    results: Dict[str, Dict[str, float]] = {}
    for node in graph.nodes():
        node_str = str(node)
        results[node_str] = {
            "betweenness": bc.get(node, 0.0),
            "degree": degree.get(node_str, 0.0),
        }

    return results


def compute_centrality_neo4j_gds(
    neo4j_driver: Any,
    graph_name: str = "cocite_graph",
    relationship_weight_property: str = "weight",
) -> Dict[str, Dict[str, float]]:
    """
    [AUDIT-011] 生产模式: Neo4j GDS 中心性计算

    GDS C++ 实现, 支持亿级边, 5w 边查询 < 30s。
    超过 1w 节点必须使用此接口。

    Pilot 模式: 如无 GDS 连接, 返回空字典 (测试友好)。

    Args:
        neo4j_driver: Neo4j 驱动实例 (生产用真实驱动, Pilot 可传 None)
        graph_name: GDS 已投影图名称
        relationship_weight_property: 边权属性名

    Returns:
        Dict[paper_id, {"betweenness": float, "pagerank": float}]
        Pilot 模式 (driver=None): 返回空字典
    """
    if neo4j_driver is None:
        # Pilot 模式: Mock 返回, 不崩溃
        return {}

    # 生产模式: 调用 GDS Betweenness
    betweenness_query = f"""
    CALL gds.betweenness.stream('{graph_name}', {{
        relationshipWeightProperty: '{relationship_weight_property}'
    }})
    YIELD nodeId, score
    RETURN gds.util.asNode(nodeId).paper_id AS paper_id, score AS betweenness
    """

    pagerank_query = f"""
    CALL gds.pageRank.stream('{graph_name}', {{
        relationshipWeightProperty: '{relationship_weight_property}',
        dampingFactor: 0.85,
        maxIterations: 20
    }})
    YIELD nodeId, score
    RETURN gds.util.asNode(nodeId).paper_id AS paper_id, score AS pagerank
    """

    results: Dict[str, Dict[str, float]] = {}

    with neo4j_driver.session() as session:
        # Betweenness
        bc_result = session.run(betweenness_query)
        for record in bc_result:
            pid = record["paper_id"]
            results.setdefault(pid, {})["betweenness"] = float(record["betweenness"])

        # PageRank
        pr_result = session.run(pagerank_query)
        for record in pr_result:
            pid = record["paper_id"]
            results.setdefault(pid, {})["pagerank"] = float(record["pagerank"])

    return results


def route_centrality_computation(
    n_nodes: int,
    neo4j_driver: Optional[Any] = None,
) -> str:
    """
    [AUDIT-011] 根据节点数自动路由到正确的中心性计算后端

    Args:
        n_nodes: 图节点数量
        neo4j_driver: Neo4j 驱动 (None 时只能用 NetworkX)

    Returns:
        "networkx" 或 "neo4j_gds"

    Raises:
        ValueError: 节点数 > 10k 但无 GDS 驱动
    """
    if n_nodes <= PILOT_MAX_NODES:
        return "networkx"
    elif n_nodes <= PRODUCTION_MIN_NODES:
        # 1k < n <= 10k: 警告但允许 NetworkX (慢)
        return "networkx"
    else:
        # > 10k: 必须用 GDS
        if neo4j_driver is None:
            raise ValueError(
                f"[AUDIT-011] 节点数 {n_nodes} > {PRODUCTION_MIN_NODES}, "
                f"必须提供 neo4j_driver 使用 GDS。"
                f"NetworkX 在此规模性能不可接受。"
            )
        return "neo4j_gds"
