"""
AUDIT-008: bridging_centrality 增量数学冲突修复

原问题: bridging_centrality 需要全图拓扑才能正确计算,
        增量更新时只有局部子图 → 数值严重失真

修复:
- bridging_centrality 标记为 monthly_full (只做月度全量计算)
- 增量场景用 sb_count (semantic_bridge count) 作代理指标
- sb_count 是局部可增量的: 新论文加入时只需统计其跨领域语义边数

AUDIT-049: 升级为双重门控
- 通过门: z_score >= 0 AND bc >= 5e-5 (绝对阈值)
- 防止小语料 z-score 通胀 (小图中任意节点 z-score 可能 >= 0)
- BC_ABSOLUTE_THRESHOLD = 5e-5
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Any


class CentralityMode(str, Enum):
    """中心性计算模式"""
    MONTHLY_FULL = "monthly_full"       # 月度全量重算 (bridging_centrality)
    INCREMENTAL_PROXY = "incremental"   # 增量代理 (sb_count)


@dataclass
class BridgingCentralityResult:
    """月度全量 bridging_centrality 计算结果"""
    paper_id: str
    bridging_centrality: float
    global_z_score: float           # 全局 z-score
    global_z_normalized: float      # z-score 归一化到 [0, 1]
    mode: CentralityMode = CentralityMode.MONTHLY_FULL
    computed_at_snapshot_id: Optional[str] = None


@dataclass
class SbCountProxy:
    """
    [AUDIT-008] 增量场景代理指标: semantic_bridge count
    
    semantic_bridge_count = 该论文的跨子领域语义边数量
    - 增量可计算: 新论文加入时只需查询其跨域相似邻居
    - 不需要全图拓扑 (不像 bridging_centrality)
    - 与 bridging_centrality 正相关, 可作为增量代理
    """
    paper_id: str
    sb_count: int                   # 跨子领域语义边数
    sb_count_normalized: float      # sb_count / max_sb_count, [0, 1]
    mode: CentralityMode = CentralityMode.INCREMENTAL_PROXY


# AUDIT-008: 月度全量计算标记
BRIDGING_CENTRALITY_SCHEDULE = {
    "mode": CentralityMode.MONTHLY_FULL,
    "note": (
        "bridging_centrality 必须在全图上计算 (依赖全局拓扑)。"
        "增量摄入时用 sb_count 代理。"
        "月度全量重算时更新所有论文的 bridging_centrality。"
    ),
    "incremental_proxy": "sb_count",
}


def compute_bridging_centrality_monthly(
    graph: Any,
    snapshot_id: str,
    global_mu: Optional[float] = None,
    global_sigma: Optional[float] = None,
) -> Dict[str, BridgingCentralityResult]:
    """
    [AUDIT-008] 月度全量 bridging_centrality 计算

    此函数标记为 monthly_full: 必须在完整图上运行, 不做增量。
    增量摄入场景请使用 compute_sb_count_proxy()。

    Args:
        graph: NetworkX 图对象 (Pilot 模式, < 1k 节点)
               或 Neo4j GDS 图 (生产模式, > 1w 节点)
        snapshot_id: 快照 ID, 记录本次全量计算的时间点
        global_mu: 全局均值 (None 时自动计算)
        global_sigma: 全局标准差 (None 时自动计算)

    Returns:
        Dict[paper_id, BridgingCentralityResult]

    Notes:
        AUDIT-008: bridging_centrality 不做增量 (monthly_full 标记)
        增量用 sb_count 代理 (见 compute_sb_count_proxy)
    """
    try:
        import networkx as nx
    except ImportError:
        raise ImportError("NetworkX 未安装, 请 pip install networkx")

    if not isinstance(graph, (nx.Graph, nx.DiGraph)):
        raise TypeError(f"期望 NetworkX 图, 收到 {type(graph)}")

    n_nodes = graph.number_of_nodes()

    # Pilot 模式: NetworkX (≤ 1000 节点)
    # 生产模式: 应使用 Neo4j GDS (见 build_l1.py)
    if n_nodes > 10000:
        raise ValueError(
            f"图节点数 {n_nodes} > 10000, 必须使用 Neo4j GDS (见 compute_centrality_neo4j_gds)。"
            f"NetworkX 在此规模会严重超时。"
        )

    # 计算 betweenness centrality (带权重)
    bc_dict = nx.betweenness_centrality(graph, weight="weight", normalized=True)

    # 全局均值和标准差 (月度全量时更新)
    values = list(bc_dict.values())
    if len(values) == 0:
        return {}

    if global_mu is None:
        global_mu = sum(values) / len(values)
    if global_sigma is None:
        variance = sum((v - global_mu) ** 2 for v in values) / len(values)
        global_sigma = variance ** 0.5

    results = {}
    for paper_id, bc in bc_dict.items():
        z = (bc - global_mu) / (global_sigma + 1e-9)
        # z-score 归一化到 [0, 1]: clip(-3, 3) → (z+3)/6
        z_norm = max(0.0, min(1.0, (z + 3.0) / 6.0))
        results[str(paper_id)] = BridgingCentralityResult(
            paper_id=str(paper_id),
            bridging_centrality=bc,
            global_z_score=z,
            global_z_normalized=z_norm,
            mode=CentralityMode.MONTHLY_FULL,
            computed_at_snapshot_id=snapshot_id,
        )

    return results


# AUDIT-049: 绝对阈值,防止小语料 z-score 通胀
BC_ABSOLUTE_THRESHOLD: float = 5e-5


def is_bridging_node(
    result: BridgingCentralityResult,
    z_score_min: float = 0.0,
    bc_absolute_min: float = BC_ABSOLUTE_THRESHOLD,
) -> bool:
    """
    [AUDIT-049] 双重门控判断是否为 bridging 节点。

    通过门: z_score >= z_score_min AND bc >= bc_absolute_min

    小语料场景下,任意节点的 z-score 可能 >= 0 (均值附近都 >= 0),
    导致大量假阳性。绝对阈值 5e-5 确保 bridging_centrality
    具有实际物理意义(在该图规模下的最小桥接权重)。

    Args:
        result:         BridgingCentralityResult 对象
        z_score_min:    z-score 最小门槛 (默认 0.0, 即高于均值)
        bc_absolute_min: 绝对 BC 阈值 (默认 5e-5)

    Returns:
        True 当且仅当 z_score >= z_score_min AND bc >= bc_absolute_min
    """
    return (
        result.global_z_score >= z_score_min
        and result.bridging_centrality >= bc_absolute_min
    )


def filter_bridging_nodes(
    results: Dict[str, BridgingCentralityResult],
    z_score_min: float = 0.0,
    bc_absolute_min: float = BC_ABSOLUTE_THRESHOLD,
) -> Dict[str, BridgingCentralityResult]:
    """
    [AUDIT-049] 从全量 BridgingCentralityResult 中筛选真正的 bridging 节点。

    双重门: z_score >= z_score_min AND bc >= bc_absolute_min

    Args:
        results:         compute_bridging_centrality_monthly() 返回值
        z_score_min:     z-score 门槛 (默认 0.0)
        bc_absolute_min: 绝对 BC 阈值 (默认 5e-5 = BC_ABSOLUTE_THRESHOLD)

    Returns:
        满足双重门控的 paper_id → BridgingCentralityResult 子集
    """
    return {
        pid: r
        for pid, r in results.items()
        if is_bridging_node(r, z_score_min=z_score_min, bc_absolute_min=bc_absolute_min)
    }


def compute_sb_count_proxy(
    paper_id: str,
    neighbor_topic_ids: List[str],
    own_topic_id: str,
    max_sb_count: int = 20,
) -> SbCountProxy:
    """
    [AUDIT-008] 增量场景代理: semantic_bridge count

    新论文加入时, 统计其跨子领域语义边数 (不需要全图重算)。

    Args:
        paper_id: 论文 ID
        neighbor_topic_ids: 语义近邻论文的 topic_id 列表
        own_topic_id: 该论文自身的 topic_id
        max_sb_count: 归一化用的最大值 (默认 20)

    Returns:
        SbCountProxy with sb_count and normalized value
    """
    # semantic_bridge count = 跨越不同 topic 的语义边数
    sb_count = sum(1 for tid in neighbor_topic_ids if tid != own_topic_id)
    sb_norm = min(1.0, sb_count / max(1, max_sb_count))

    return SbCountProxy(
        paper_id=paper_id,
        sb_count=sb_count,
        sb_count_normalized=sb_norm,
        mode=CentralityMode.INCREMENTAL_PROXY,
    )


# ---------------------------------------------------------------------------
# AUDIT-012 P1: 无向图 PageRank 禁用 → cocite 只用 degree + betweenness
# ---------------------------------------------------------------------------

def compute_cocite_centrality(
    cocite_graph: Any,
    pagerank_disabled: bool = True,
) -> Dict[str, Dict[str, float]]:
    """
    [AUDIT-012 P1] 共被引网络 (cocite) 中心性计算

    设计点:
    - 共被引网络是**无向图** (A和B共被引是对称关系)
    - 无向图的 PageRank 在数学上退化为 degree centrality
      (因为 PageRank 在无向图上稳态分布 ∝ degree — 见 Bollobás 2001)
    - 因此在 cocite 子图中:
        ✓ degree centrality    (有效: 衡量共被引频次)
        ✓ betweenness centrality (有效: 衡量桥接位置)
        ✗ PageRank             (无向图退化, 禁用)
    - PageRank 保留给 cite_direct 有向引用图 (见 compute_direct_cite_pagerank)

    Args:
        cocite_graph:       NetworkX 无向图 (共被引网络)
        pagerank_disabled:  是否禁用 PageRank (默认 True, AUDIT-012 要求)

    Returns:
        Dict[paper_id, {degree_centrality, betweenness_centrality}]

    Raises:
        ImportError: 若 networkx 未安装
        TypeError:   若图不是 networkx.Graph (无向图)
        ValueError:  若传入 pagerank_disabled=False (不允许在无向图运行 PageRank)
    """
    try:
        import networkx as nx
    except ImportError:
        raise ImportError("NetworkX 未安装, 请 pip install networkx")

    # AUDIT-012: cocite 图必须是无向图
    # 注意: nx.DiGraph 继承自 nx.Graph, 需用 isinstance(G, nx.DiGraph) 区分
    if isinstance(cocite_graph, nx.DiGraph):
        raise TypeError(
            "[AUDIT-012] cocite 图必须是无向图 (nx.Graph), 不能是 DiGraph。"
            "有向引用图请使用 compute_direct_cite_pagerank()。"
        )

    if not pagerank_disabled:
        raise ValueError(
            "[AUDIT-012] cocite 无向图禁止运行 PageRank "
            "(无向图 PageRank ∝ degree, 退化无意义)。"
            "如确需 PageRank, 请使用有向引用图 compute_direct_cite_pagerank()。"
        )

    n_nodes = cocite_graph.number_of_nodes()
    if n_nodes == 0:
        return {}

    # Degree centrality (归一化)
    degree_cent = nx.degree_centrality(cocite_graph)

    # Betweenness centrality (带权重, 归一化)
    # 注意: N>1000 时较慢, 建议采样近似
    if n_nodes <= 1000:
        betweenness_cent = nx.betweenness_centrality(
            cocite_graph, weight="weight", normalized=True
        )
    else:
        # 采样近似 (k=500 采样节点)
        k = min(500, n_nodes)
        betweenness_cent = nx.betweenness_centrality(
            cocite_graph, k=k, weight="weight", normalized=True
        )

    result = {}
    for node in cocite_graph.nodes():
        pid = str(node)
        result[pid] = {
            "degree_centrality": degree_cent.get(node, 0.0),
            "betweenness_centrality": betweenness_cent.get(node, 0.0),
            # AUDIT-012: pagerank 明确禁用
            "pagerank": None,
            "pagerank_disabled_reason": "cocite 无向图 PageRank ∝ degree, 见 AUDIT-012",
        }

    return result


def compute_direct_cite_pagerank(
    cite_graph: Any,
    damping: float = 0.85,
    max_iter: int = 100,
    weight: str = "weight",
) -> Dict[str, float]:
    """
    [AUDIT-012 P1] 有向引用图 (cite_direct) PageRank

    PageRank 在有向图上有意义 (不退化)。
    cocite 无向图不应使用此函数 (请用 compute_cocite_centrality)。

    Args:
        cite_graph: NetworkX 有向图 (DiGraph), 表示 paper_a → paper_b 的引用关系
        damping:    阻尼系数, 默认 0.85
        max_iter:   最大迭代次数
        weight:     边权重字段名

    Returns:
        Dict[paper_id, pagerank_score]

    Raises:
        TypeError: 若传入无向图
    """
    try:
        import networkx as nx
    except ImportError:
        raise ImportError("NetworkX 未安装, 请 pip install networkx")

    if not isinstance(cite_graph, nx.DiGraph):
        raise TypeError(
            "[AUDIT-012] PageRank 只用于有向引用图 (DiGraph)。"
            "共被引无向图请使用 compute_cocite_centrality()。"
        )

    if cite_graph.number_of_nodes() == 0:
        return {}

    pr = nx.pagerank(cite_graph, alpha=damping, max_iter=max_iter, weight=weight)
    return {str(k): float(v) for k, v in pr.items()}
