"""
scibot/visualization/render_png.py
V13 高清 PNG 渲染器 (matplotlib)

输出: 300 DPI, 16×16 英寸 = 4800×4800 像素 (实际大小受内存限制可调低)
黑色背景 + 径向布局 + 卡点辉光 + 里程碑标签 + 图例
"""

import math
import os
from typing import Optional

try:
    import matplotlib
    matplotlib.use("Agg")   # 无显示器环境
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.patheffects as pe
    from matplotlib.collections import LineCollection
    from matplotlib.colors import to_rgba
    import numpy as np
    _MPL_AVAILABLE = True
except ImportError:
    _MPL_AVAILABLE = False


def _marker_for_shape(shape: str) -> str:
    """D3 shape → matplotlib marker"""
    return {
        "circle":   "o",
        "square":   "s",
        "triangle": "^",
        "diamond":  "D",
    }.get(shape, "o")


def render_static_png(
    nodes: list[dict],
    edges: list[dict],
    overlays: dict,
    landmarks: list[dict],
    output_path: str,
    dpi: int = 150,
    size: tuple = (16, 16),
) -> str:
    """
    高清 PNG (黑色背景 + 径向布局 + 卡点辉光 + 里程碑标签 + 图例)

    Parameters
    ----------
    nodes       : list of {id, x, y, color, shape, size, label,
                            field, subfield, domain, topic, cited_by_count, novelty}
    edges       : list of {src, dst, fused_weight, opacity}
    overlays    : {bottleneck_halos: [...], meta_principle_bands: [...]}
    landmarks   : list of {paper_id, x, y, short_label_zh, title}
    output_path : 输出文件路径
    dpi         : 分辨率 (300 → 4800×4800px @ 16in)
    size        : figure 尺寸 (英寸)

    Returns
    -------
    output_path
    """
    if not _MPL_AVAILABLE:
        raise ImportError("matplotlib is required: pip install matplotlib")

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    W, H = size
    fig, ax = plt.subplots(figsize=(W, H), dpi=dpi)
    fig.patch.set_facecolor("#080810")
    ax.set_facecolor("#080810")
    ax.set_aspect("equal")
    ax.axis("off")

    # 画布坐标范围 (原始坐标系 1600×1600, 中心 800×800)
    ORIG_W, ORIG_H = 1600, 1600
    margin = 80
    ax.set_xlim(-margin, ORIG_W + margin)
    ax.set_ylim(-margin, ORIG_H + margin)
    ax.invert_yaxis()   # y 轴翻转以匹配 SVG 坐标系

    node_index = {n["id"]: n for n in nodes}

    # ── 渲染: 边 ────────────────────────────────────────────────────────────────
    if edges:
        lines = []
        line_colors = []
        for e in edges:
            src = node_index.get(e.get("src", ""))
            dst = node_index.get(e.get("dst", ""))
            if src and dst:
                lines.append([(src["x"], src["y"]), (dst["x"], dst["y"])])
                alpha = float(e.get("opacity", 0.2))
                w = float(e.get("fused_weight", 0.3))
                line_colors.append((0.2, 0.2, 0.35, alpha * 0.6))

        if lines:
            lc = LineCollection(
                lines,
                colors=line_colors,
                linewidths=0.3,
                antialiaseds=True,
                zorder=1,
            )
            ax.add_collection(lc)

    # ── 渲染: 卡点辉光晕 ─────────────────────────────────────────────────────────
    bottleneck_halos = overlays.get("bottleneck_halos", [])
    for halo in bottleneck_halos:
        cx = float(halo.get("cx", 800))
        cy = float(halo.get("cy", 800))
        r  = float(halo.get("r", 60))
        color = halo.get("color", "#ffaa00")

        # 多层渐变辉光 (由外向内, 透明度递增)
        for layer_r, alpha in [(r * 2.0, 0.03), (r * 1.4, 0.07), (r, 0.12)]:
            circle = plt.Circle(
                (cx, cy), layer_r,
                color=color, alpha=alpha, zorder=2, linewidth=0,
            )
            ax.add_patch(circle)

        # 辉光轮廓
        ring = plt.Circle(
            (cx, cy), r,
            fill=False, edgecolor=color, linewidth=1.2,
            alpha=0.5, zorder=3,
        )
        ax.add_patch(ring)

        # 卡点标签
        label = halo.get("label", "")
        if label:
            ax.text(
                cx, cy - r - 12, label[:25],
                fontsize=7, color="#ffaa88", ha="center", va="bottom",
                alpha=0.7, zorder=4,
            )

    # ── 渲染: 元规律虹光带 ───────────────────────────────────────────────────────
    meta_bands = overlays.get("meta_principle_bands", [])
    meta_colors = ["#00ffcc", "#ff6b9d", "#ffd700", "#7b9fff"]
    CX, CY = ORIG_W / 2, ORIG_H / 2
    for i, band in enumerate(meta_bands):
        color = band.get("color", meta_colors[i % len(meta_colors)])
        name  = band.get("name", f"MetaPrinciple {i+1}")
        angle_offset = i * math.pi / 2

        # 绘制椭圆弧覆盖带
        ellipse = mpatches.Ellipse(
            (CX + math.cos(angle_offset) * 250,
             CY + math.sin(angle_offset) * 250),
            width=700, height=400,
            angle=math.degrees(angle_offset),
            fill=False, edgecolor=color,
            linewidth=2.0, alpha=0.25,
            linestyle="--", zorder=3,
        )
        ax.add_patch(ellipse)

        # 元规律标签
        lx = CX + math.cos(angle_offset) * 450
        ly = CY + math.sin(angle_offset) * 450
        ax.text(
            lx, ly, name[:20],
            fontsize=8, color=color, alpha=0.6,
            ha="center", va="center", zorder=5,
            fontweight="bold",
        )

    # ── 渲染: 节点 ───────────────────────────────────────────────────────────────
    # 按 field 分组批量绘制 (同 field 用相同颜色, 提升渲染效率)
    field_groups: dict[str, list[dict]] = {}
    for n in nodes:
        fn = n.get("field", "Unknown")
        field_groups.setdefault(fn, []).append(n)

    for fn, fnodes in field_groups.items():
        for n in fnodes:
            x = float(n.get("x", 800))
            y = float(n.get("y", 800))
            color = n.get("color", "#7f7f7f")
            shape = n.get("shape", "circle")
            size_val = float(n.get("size", 5))
            marker_size = max(2, min(15, size_val)) ** 2  # scatter 用面积

            ax.scatter(
                [x], [y],
                s=marker_size,
                c=[color],
                marker=_marker_for_shape(shape),
                alpha=0.85,
                linewidths=0,
                zorder=5,
            )

    # ── 渲染: 里程碑标签 ─────────────────────────────────────────────────────────
    for lm in landmarks:
        x = float(lm.get("x", 800))
        y = float(lm.get("y", 800))
        label = lm.get("short_label_zh", "")
        if not label:
            continue

        # 标签文字 (带辉光描边效果)
        ax.text(
            x + 18, y,
            label,
            fontsize=11,
            color="#ffe066",
            fontweight="bold",
            va="center",
            ha="left",
            zorder=8,
            path_effects=[
                pe.withStroke(linewidth=3, foreground="#ffe06640"),
                pe.Normal(),
            ],
            fontfamily=["PingFang SC", "Microsoft YaHei", "DejaVu Sans"],
        )

        # 里程碑节点外圆
        ring = plt.Circle(
            (x, y), 14,
            fill=False, edgecolor="#ffe066",
            linewidth=1.2, alpha=0.8, zorder=7,
        )
        ax.add_patch(ring)

    # ── 图例 ─────────────────────────────────────────────────────────────────────
    legend_handles = []
    fields_seen = {}
    for n in nodes:
        fn = n.get("field", "")
        if fn and fn not in fields_seen:
            fields_seen[fn] = n.get("color", "#7f7f7f")
    for fn, color in sorted(fields_seen.items()):
        h = mpatches.Patch(color=color, label=fn, alpha=0.8)
        legend_handles.append(h)

    if legend_handles:
        legend = ax.legend(
            handles=legend_handles,
            loc="lower left",
            framealpha=0.4,
            facecolor="#0d0d15",
            edgecolor="#333",
            fontsize=8,
            labelcolor="white",
            title="Field (一级学科)",
            title_fontsize=9,
            ncol=2,
        )
        legend.get_title().set_color("#aaa")

    # 标题
    ax.text(
        ORIG_W / 2, -50,
        "Echelon V13 — Nature风格知识图谱",
        fontsize=14, color="#888", ha="center", va="bottom",
        alpha=0.8, zorder=9,
    )
    ax.text(
        ORIG_W / 2, -25,
        f"N={len(nodes)} papers  |  Radial layout  |  Colored by Field+Subfield",
        fontsize=9, color="#555", ha="center", va="bottom",
        alpha=0.7, zorder=9,
    )

    plt.tight_layout(pad=0.5)
    plt.savefig(output_path, dpi=dpi, bbox_inches="tight",
                facecolor="#080810", edgecolor="none")
    plt.close(fig)

    return output_path
