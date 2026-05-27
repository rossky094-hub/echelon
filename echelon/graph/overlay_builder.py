"""
V13: overlay_builder.py — Graph Overlay Builder

把 V12 的 4 个孤立报告映射回 2000 个图谱节点:
  - 15 个 L3 卡点  (l3_bottlenecks_v5.json)
  - V12 主题       (themes_enriched.json 17 个, 或 first_principles_results_v12_5.json 15 个)
  - 4 个元规律     (meta_principles_v12_5.json)

输出 graph_overlay_v13.json, 驱动前端卡点辉光晕 + 元规律虹光带渲染。

颜色方案:
  15 卡点 → BOTTLENECK_PALETTE (15 色)
  4 元规律 → META_PRINCIPLE_PALETTE (4 色)
"""

from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Set, Tuple


# ─────────────────────────────────────────────
# 调色板
# ─────────────────────────────────────────────

# 15 色卡点调色板 (distinct, hue-spread)
BOTTLENECK_PALETTE: List[str] = [
    "#FF6B6B",  # B0  - 珊瑚红
    "#FF9F43",  # B1  - 橙色
    "#FECA57",  # B2  - 金黄
    "#54A0FF",  # B3  - 天蓝
    "#5F27CD",  # B4  - 深紫
    "#00D2D3",  # B5  - 青绿
    "#48DBFB",  # B6  - 浅蓝
    "#FF9FF3",  # B7  - 粉紫
    "#1DD1A1",  # B8  - 薄荷绿
    "#F368E0",  # B9  - 品红
    "#EE5A24",  # B10 - 暗橙
    "#009432",  # B11 - 翠绿
    "#833471",  # B12 - 深玫红
    "#006266",  # B13 - 深青
    "#D980FA",  # B14 - 淡紫
]

# 4 色元规律调色板 (醒目, 对比强)
META_PRINCIPLE_PALETTE: List[str] = [
    "#FF4757",  # MP1 - 维度灾难  (红)
    "#2ED573",  # MP2 - 信息熵耗散 (绿)
    "#1E90FF",  # MP3 - 因果机制  (蓝)
    "#FFA502",  # MP4 - 物理场约束 (橙)
]


# ─────────────────────────────────────────────
# 内部工具
# ─────────────────────────────────────────────

def _build_paper_to_bottleneck(bottlenecks: List[Dict]) -> Dict[str, str]:
    """
    从 l3_bottlenecks_v5 的 supporting_papers 反查 paper_id → bottleneck 短 ID。

    短 ID 格式: "B{cluster_id}" (e.g. "B0", "B5")
    """
    mapping: Dict[str, str] = {}
    for b in bottlenecks:
        cluster_id = b.get("cluster_id")
        short_id = f"B{cluster_id}"
        for pid in b.get("supporting_papers", []):
            # 若一篇论文出现在多个 cluster, 取最先出现 (cluster_id 较小)
            if pid not in mapping:
                mapping[pid] = short_id
    return mapping


def _build_paper_to_theme(themes: List[Dict]) -> Dict[str, str]:
    """
    从主题的 paper_ids 字段反查 paper_id → theme_id。

    支持两种主题格式:
      - themes_enriched: {"theme_id": "T01", "paper_ids": [...]}
      - first_principles_results: {"theme_id": "T1", "paper_ids": [...]}  (若存在)

    若 paper_ids 不存在则跳过该主题。
    """
    mapping: Dict[str, str] = {}
    for t in themes:
        tid = t.get("theme_id") or t.get("id") or ""
        paper_ids = t.get("paper_ids", [])
        for pid in paper_ids:
            if pid not in mapping:
                mapping[pid] = tid
    return mapping


def _build_theme_to_meta_principles(meta_principles: List[Dict]) -> Dict[str, List[str]]:
    """
    从元规律的 covered_themes 正查 theme_id → [meta_principle_id, ...]。

    元规律 ID 格式: "MP1", "MP2", "MP3", "MP4" (按列表顺序编号)。
    """
    mapping: Dict[str, List[str]] = {}
    for i, mp in enumerate(meta_principles):
        mp_id = f"MP{i + 1}"
        for tid in mp.get("covered_themes", []):
            mapping.setdefault(tid, []).append(mp_id)
    return mapping


def _build_paper_to_meta_principles(
    paper_to_theme: Dict[str, str],
    theme_to_mp: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """paper_id → [MP1, MP3, ...] (通过主题间接关联)"""
    mapping: Dict[str, List[str]] = {}
    for pid, tid in paper_to_theme.items():
        mps = theme_to_mp.get(tid, [])
        if mps:
            mapping[pid] = mps
    return mapping


def _bottleneck_short_id_to_full(bottleneck: Dict) -> Tuple[str, str]:
    """返回 (short_id='B5', full_id=bottleneck_id)"""
    cluster_id = bottleneck.get("cluster_id")
    return f"B{cluster_id}", bottleneck.get("bottleneck_id", "")


# ─────────────────────────────────────────────
# 主 API
# ─────────────────────────────────────────────

def build_overlay(
    papers: List[Dict],
    bottlenecks: List[Dict],
    themes: List[Dict],
    meta_principles: List[Dict],
) -> Dict:
    """
    构建图谱 Overlay 数据, 把 4 个孤立报告映射到图谱节点上。

    Args:
        papers:          2000 篇 paper_identity 记录 (含 paper_id / id 字段)
        bottlenecks:     l3_bottlenecks_v5.json 的 "bottlenecks" 列表
        themes:          主题列表 (含 theme_id + paper_ids 字段)
        meta_principles: meta_principles_v12_5.json 的 "meta_principles" 列表

    Returns:
        {
          "node_overlays":        [...],   # 每篇论文的 overlay 信息
          "bottleneck_halos":     [...],   # 15 卡点光晕
          "meta_principle_bands": [...],   # 4 元规律虹光带
          "summary": {
              "papers_covered_by_bottleneck": int,
              "papers_covered_by_theme":      int,
              "papers_in_meta_principle":     int,
          }
        }
    """
    # ── 构建反查映射 ──────────────────────────────────────────────────────────
    paper_to_bn: Dict[str, str] = _build_paper_to_bottleneck(bottlenecks)
    paper_to_theme: Dict[str, str] = _build_paper_to_theme(themes)
    theme_to_mp: Dict[str, List[str]] = _build_theme_to_meta_principles(meta_principles)
    paper_to_mp: Dict[str, List[str]] = _build_paper_to_meta_principles(paper_to_theme, theme_to_mp)

    # cluster_id → color 映射
    cluster_to_color: Dict[int, str] = {}
    cluster_to_bottleneck: Dict[int, Dict] = {}
    for b in bottlenecks:
        cid = b.get("cluster_id", 0)
        cluster_to_bottleneck[cid] = b
        cluster_to_color[cid] = BOTTLENECK_PALETTE[cid % len(BOTTLENECK_PALETTE)]

    # ── node_overlays ─────────────────────────────────────────────────────────
    node_overlays = []
    # 收集各统计数
    papers_with_bn: Set[str] = set()
    papers_with_theme: Set[str] = set()
    papers_with_mp: Set[str] = set()

    for paper in papers:
        pid = paper.get("paper_id") or paper.get("id") or ""
        if not pid:
            continue

        bn_id = paper_to_bn.get(pid)          # "B5" | None
        theme_id = paper_to_theme.get(pid)    # "T01" | None
        mp_ids = paper_to_mp.get(pid, [])     # ["MP1", "MP3"] | []

        # 是否里程碑 (属于某个卡点)
        is_landmark = bn_id is not None

        # 辉光颜色 (从 cluster_id 映射)
        halo_color: Optional[str] = None
        if bn_id is not None:
            cluster_id = int(bn_id[1:])  # "B5" → 5
            halo_color = cluster_to_color.get(cluster_id)

        # 元规律虹光带颜色
        principle_band_colors: List[str] = []
        for mp_id in mp_ids:
            mp_idx = int(mp_id[2:]) - 1  # "MP1" → 0
            if 0 <= mp_idx < len(META_PRINCIPLE_PALETTE):
                principle_band_colors.append(META_PRINCIPLE_PALETTE[mp_idx])

        node_overlays.append({
            "paper_id": pid,
            "bottleneck_id": bn_id,
            "theme_id": theme_id,
            "meta_principles": mp_ids,
            "is_landmark": is_landmark,
            "halo_color": halo_color,
            "principle_band_colors": principle_band_colors,
        })

        if bn_id is not None:
            papers_with_bn.add(pid)
        if theme_id is not None:
            papers_with_theme.add(pid)
        if mp_ids:
            papers_with_mp.add(pid)

    # ── bottleneck_halos ──────────────────────────────────────────────────────
    bottleneck_halos = []
    for b in bottlenecks:
        cid = b.get("cluster_id", 0)
        short_id = f"B{cid}"
        color = cluster_to_color.get(cid, "#888888")
        supporting = b.get("supporting_papers", [])

        # 质心坐标: 以 paper 索引顺序为代理坐标 (真实坐标需由前端覆盖)
        paper_indices = []
        for i, p in enumerate(papers):
            pid = p.get("paper_id") or p.get("id") or ""
            if pid in supporting:
                paper_indices.append(i)

        if paper_indices:
            centroid_x = float(sum(paper_indices) / len(paper_indices))
            centroid_y = float(cid * 10)  # y 轴用 cluster_id × 10 作为占位
        else:
            centroid_x, centroid_y = 0.0, 0.0

        # 半径: 随支撑论文数量增长
        radius = max(1.0, math.sqrt(len(supporting)) * 5.0)

        bottleneck_halos.append({
            "cluster_id": short_id,
            "bottleneck_id": b.get("bottleneck_id", ""),
            "label": b.get("label", ""),
            "supporting_paper_ids": supporting,
            "halo_color": color,
            "centroid_x_y": [round(centroid_x, 2), round(centroid_y, 2)],
            "radius": round(radius, 2),
            "is_cross_topic": b.get("is_cross_topic", False),
        })

    # ── meta_principle_bands ──────────────────────────────────────────────────
    meta_principle_bands = []
    for i, mp in enumerate(meta_principles):
        mp_id = f"MP{i + 1}"
        color = META_PRINCIPLE_PALETTE[i % len(META_PRINCIPLE_PALETTE)]
        covered_themes = mp.get("covered_themes", [])

        # 找所有属于这些主题的论文
        covered_papers: List[str] = []
        for pid, tid in paper_to_theme.items():
            if tid in covered_themes:
                covered_papers.append(pid)

        meta_principle_bands.append({
            "principle_id": mp_id,
            "principle_name": mp.get("principle", ""),
            "explanation": mp.get("explanation", ""),
            "covered_theme_ids": covered_themes,
            "covered_paper_ids": covered_papers,
            "band_color": color,
            "is_solvable_in_3_years": bool(mp.get("is_solvable_in_3_years", False)),
            "solvability_reason": mp.get("solvability_reason", ""),
        })

    # ── summary ───────────────────────────────────────────────────────────────
    summary = {
        "papers_covered_by_bottleneck": len(papers_with_bn),
        "papers_covered_by_theme": len(papers_with_theme),
        "papers_in_meta_principle": len(papers_with_mp),
        "total_papers": len(papers),
        "bottleneck_count": len(bottlenecks),
        "theme_count": len(themes),
        "meta_principle_count": len(meta_principles),
    }

    return {
        "node_overlays": node_overlays,
        "bottleneck_halos": bottleneck_halos,
        "meta_principle_bands": meta_principle_bands,
        "summary": summary,
    }


# ─────────────────────────────────────────────
# 便捷加载函数 (供 pilot 调用)
# ─────────────────────────────────────────────

def load_overlay_inputs_from_files(
    bottlenecks_path: str,
    themes_path: str,
    meta_principles_path: str,
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    从文件路径加载 overlay 所需的 3 个输入数据集。

    Args:
        bottlenecks_path:     l3_bottlenecks_v5.json 路径
        themes_path:          themes_enriched.json 路径 (含 paper_ids)
        meta_principles_path: meta_principles_v12_5.json 路径

    Returns:
        (bottlenecks, themes, meta_principles) — 均为 List[Dict]
    """
    with open(bottlenecks_path, encoding="utf-8") as f:
        bn_data = json.load(f)
    bottlenecks = bn_data.get("bottlenecks", bn_data) if isinstance(bn_data, dict) else bn_data

    with open(themes_path, encoding="utf-8") as f:
        themes_data = json.load(f)
    if isinstance(themes_data, dict):
        themes = themes_data.get("themes", list(themes_data.values())[0] if themes_data else [])
    else:
        themes = themes_data

    with open(meta_principles_path, encoding="utf-8") as f:
        mp_data = json.load(f)
    meta_principles = mp_data.get("meta_principles", mp_data) if isinstance(mp_data, dict) else mp_data

    return bottlenecks, themes, meta_principles



