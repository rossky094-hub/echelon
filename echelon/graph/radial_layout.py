"""
echelon/graph/radial_layout.py
V13 Novelty Score 计算 + 径向 Force-Directed 布局

Novelty Score 公式:
  novelty = 0.30 * c_cd_subdomain
           + 0.20 * c_bridging_centrality
           + 0.15 * c_team_disrupt
           + 0.15 * c_semantic_outlier
           + 0.10 * c_recency
           + 0.10 * c_breakthrough_lang

若某信号 = None,其权重转移到其他有效信号(归一化)。

径向布局:
  - 中心: KeystoneScore 高 + 引用多 + novelty 低 → 已知核心
  - 外圈: novelty 高 + 跨界桥 + cited_by 中等 → 颠覆性前沿
  - 角度: 按 primary_topic_id 分配(同 topic 在同一角度区,平滑过渡)
"""

import math
import random
from typing import Optional

try:
    import networkx as nx
    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False

# 默认 Novelty 信号权重
_DEFAULT_NOVELTY_WEIGHTS: dict[str, float] = {
    "c_cd_subdomain":        0.30,
    "c_bridging_centrality": 0.20,
    "c_team_disrupt":        0.15,
    "c_semantic_outlier":    0.15,
    "c_recency":             0.10,
    "c_breakthrough_lang":   0.10,
}

CANVAS_SIZE = (1600, 1600)
R_MAX = 700    # 最大径向距离 (像素)
R_MIN = 80     # 最小径向距离 (像素, 核心区)


def compute_novelty_score(paper: dict, signals: dict) -> float:
    """
    V13 颠覆性分数 ∈ [0, 1]

    signals 中 None 值信号权重会等比例转移到其他有效信号。
    paper 参数保留以便未来从 paper dict 直接读取信号。

    Parameters
    ----------
    paper  : 论文 dict (含 paper_id / title 等基本信息)
    signals: {signal_name: value_or_None}  ∈ [0, 1] 或 None
    """
    weights = _DEFAULT_NOVELTY_WEIGHTS.copy()

    # 过滤有效信号 (非 None)
    valid: dict[str, float] = {}
    for k, w in weights.items():
        v = signals.get(k)
        if v is not None:
            try:
                v_float = float(v)
            except (TypeError, ValueError):
                continue
            valid[k] = max(0.0, min(1.0, v_float))

    if not valid:
        return 0.5  # 无信号时返回中性分

    # 归一化权重 (缺失信号权重等比例转移)
    total_w = sum(weights[k] for k in valid)
    if total_w <= 0:
        return 0.5

    score = sum((weights[k] / total_w) * valid[k] for k in valid)
    return max(0.0, min(1.0, score))


def _assign_topic_angles(
    papers: list[dict],
) -> dict[str, float]:
    """
    为每个 primary_topic_id 分配基准角度区间,
    同一 topic 的论文集中在同一扇区。
    返回 {paper_id: base_angle_rad}
    """
    # 收集所有 topic
    topic_counts: dict[str, int] = {}
    for p in papers:
        tid = p.get("primary_topic_id", "unknown")
        topic_counts[tid] = topic_counts.get(tid, 0) + 1

    topics_sorted = sorted(topic_counts.keys())
    n_topics = len(topics_sorted)
    sector_size = 2 * math.pi / max(n_topics, 1)

    # 给每个 topic 一个起始角度
    topic_base_angle: dict[str, float] = {
        t: i * sector_size for i, t in enumerate(topics_sorted)
    }

    # 给每篇论文分配角度 (在 sector 内按引用数量排序, 轻微随机扰动)
    # 按 topic 分组
    topic_papers: dict[str, list[dict]] = {}
    for p in papers:
        tid = p.get("primary_topic_id", "unknown")
        topic_papers.setdefault(tid, []).append(p)

    paper_angles: dict[str, float] = {}
    rng = random.Random(42)

    for tid, tpapers in topic_papers.items():
        base = topic_base_angle.get(tid, 0.0)
        n = len(tpapers)
        # 在 sector 内均匀分配, 加小随机扰动
        for i, p in enumerate(tpapers):
            pid = p.get("openalex_id") or p.get("paper_id") or p.get("id", "")
            offset = (i / max(n, 1)) * sector_size * 0.85  # 留 15% 缓冲
            jitter = rng.gauss(0, sector_size * 0.02)
            paper_angles[pid] = base + offset + jitter

    return paper_angles


def _safe_log(x: float, base: float = 10.0) -> float:
    return math.log(max(x, 1.0), base)


def radial_force_layout(
    papers: list[dict],
    fused_edges: Optional[dict] = None,
    novelty_scores: Optional[dict[str, float]] = None,
    canvas_size: tuple = CANVAS_SIZE,
    n_iterations: int = 50,
) -> dict[str, tuple[float, float]]:
    """
    径向 force-directed 布局

    - 中心: KeystoneScore 高 + 引用多 + novelty 低 → 已知核心
    - 外圈: novelty 高 + 跨界桥 + cited_by 中等 → 颠覆性前沿
    - 角度: 按 primary_topic_id 分配

    Parameters
    ----------
    papers        : 论文列表, 每篇含 openalex_id/paper_id, cited_by_count,
                    primary_topic_id, keystone_score (可选)
    fused_edges   : {(src_id, dst_id): weight} 或 None
    novelty_scores: {paper_id: float} 或 None (若 None 则全取 0.5)
    canvas_size   : (width, height) 像素
    n_iterations  : force-directed 微调迭代次数

    Returns
    -------
    {paper_id: (x, y)}  — 坐标以 canvas 中心为原点
    """
    if not papers:
        return {}

    cx = canvas_size[0] / 2.0
    cy = canvas_size[1] / 2.0

    if novelty_scores is None:
        novelty_scores = {}

    # 分配角度
    paper_angles = _assign_topic_angles(papers)

    # 为每篇论文计算初始径向距离
    positions: dict[str, tuple[float, float]] = {}
    paper_map: dict[str, dict] = {}

    for p in papers:
        pid = p.get("openalex_id") or p.get("paper_id") or p.get("id", "")
        paper_map[pid] = p

        novelty = novelty_scores.get(pid, 0.5)
        cited = float(p.get("cited_by_count", 0) or 0)
        keystone = float(p.get("keystone_score", 0.5) or 0.5)

        # radius: novelty 越高 → 越在外圈
        # 综合: (1 - novelty) 拉向中心, cited 多也拉向中心, keystone 高拉向中心
        centrality = (1.0 - novelty) * 0.5 + min(_safe_log(cited + 1) / 4.0, 0.5) * 0.3 + keystone * 0.2
        radius = R_MIN + (R_MAX - R_MIN) * (1.0 - max(0.0, min(1.0, centrality)))

        angle = paper_angles.get(pid, 0.0)
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        positions[pid] = (x, y)

    # Force-directed 微调 (若有 networkx + fused_edges)
    if _NX_AVAILABLE and fused_edges and n_iterations > 0:
        G = nx.Graph()
        G.add_nodes_from(positions.keys())

        # 只加权重 > 0.1 的边
        for (src, dst), w in fused_edges.items():
            if src in positions and dst in positions and w > 0.1:
                G.add_edge(src, dst, weight=float(w))

        if G.number_of_edges() > 0:
            # 用 spring_layout 做相对位移微调
            # pos_init 使用现有坐标 (归一化到 [0,1])
            pos_init = {
                pid: (x / canvas_size[0], y / canvas_size[1])
                for pid, (x, y) in positions.items()
            }
            spring_pos = nx.spring_layout(
                G,
                pos=pos_init,
                iterations=n_iterations,
                weight="weight",
                seed=42,
                k=0.05,  # 小弹簧常数, 防止过度变形
            )

            # 将 spring 位移叠加到径向基础位置 (小权重混合)
            BLEND = 0.15  # spring 位移的混合比例
            for pid, (sx, sy) in spring_pos.items():
                ox, oy = positions[pid]
                nx_coord = ox + BLEND * (sx * canvas_size[0] - ox)
                ny_coord = oy + BLEND * (sy * canvas_size[1] - oy)

                # 保持最小径向距离约束
                dx = nx_coord - cx
                dy = ny_coord - cy
                r = math.sqrt(dx**2 + dy**2)
                if r < R_MIN:
                    scale = R_MIN / max(r, 1e-6)
                    nx_coord = cx + dx * scale
                    ny_coord = cy + dy * scale

                positions[pid] = (nx_coord, ny_coord)

    return positions


def get_node_radius_px(paper: dict, novelty: float = 0.5) -> float:
    """
    节点显示半径 (像素) = log(1 + cited_by_count) * 2 + 3
    最小 3px, 最大 20px
    """
    cited = float(paper.get("cited_by_count", 0) or 0)
    r = math.log(1 + cited) * 2.0 + 3.0
    return max(3.0, min(20.0, r))
