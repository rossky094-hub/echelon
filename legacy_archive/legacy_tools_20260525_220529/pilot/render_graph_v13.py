"""
pilot/render_graph_v13.py
V13 可视化集成入口

读 V12.5 现有产物 + 应用 V13 着色和布局 → 输出 HTML + PNG

用法:
    python pilot/render_graph_v13.py
    python pilot/render_graph_v13.py --dpi 300 --out-dir reports/v13
"""

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

# 确保 echelon_mvp0a 在路径中
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from echelon.graph.discipline_colors import build_color_map_for_papers
from echelon.graph.radial_layout import (
    compute_novelty_score,
    radial_force_layout,
    get_node_radius_px,
)
from echelon.graph.landmark_detection import detect_landmarks, generate_landmark_labels
from scibot.visualization.render_d3 import render_interactive_html
from scibot.visualization.render_png import render_static_png

# ── 路径常量 ──────────────────────────────────────────────────────────────────
DATA_DIR   = _ROOT / "data" / "raw_merged"
REPORTS_V5 = _ROOT / "reports" / "v5"
SCIBOT_DIR = _ROOT / "scibot"

PAPERS_PATH      = DATA_DIR / "papers_merged.jsonl"
SEEDS_PATH       = REPORTS_V5 / "l2_seeds_v5.json"
BOTTLENECKS_PATH = REPORTS_V5 / "l3_bottlenecks_v5.json"
META_PATH        = SCIBOT_DIR / "meta_principles_v12_5.json"


def load_papers(path: Path) -> list[dict]:
    """加载论文数据 (.jsonl)"""
    papers = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                papers.append(json.loads(line))
    print(f"  [load] papers: {len(papers)}")
    return papers


def load_json(path: Path) -> dict | list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_paper_index(papers: list[dict]) -> dict[str, dict]:
    """构建 paper_id → paper dict 索引"""
    idx = {}
    for p in papers:
        pid = p.get("openalex_id") or p.get("paper_id") or p.get("id", "")
        idx[pid] = p
    return idx


def extract_seeds_set(seeds_data: dict) -> set[str]:
    """从 l2_seeds 数据中提取金种子 paper_id 集合"""
    top10 = seeds_data.get("top10_seeds", [])
    seeds_by_topic = seeds_data.get("seeds_by_topic", {})
    ids = set()
    for s in top10:
        ids.add(s.get("paper_id", ""))
    for topic_seeds in seeds_by_topic.values():
        if isinstance(topic_seeds, list):
            for s in topic_seeds:
                if isinstance(s, dict):
                    ids.add(s.get("paper_id", ""))
    ids.discard("")
    return ids


def build_fused_edges_simple(papers: list[dict]) -> dict:
    """
    简单版 fused_edges: 基于 referenced_works 共引关系构建
    (完整版需要 echelon/graph/fused_edge.py, 这里用轻量代替)
    返回 {(src_id, dst_id): weight}
    """
    # 构建 paper_id 集合
    paper_ids = set()
    for p in papers:
        pid = p.get("openalex_id") or ""
        paper_ids.add(pid)

    # 统计共引
    cocite: dict[tuple, int] = {}
    # 对每篇论文, 取其 referenced_works 中同属语料的论文对
    for p in papers:
        refs = p.get("referenced_works", []) or []
        refs_in_corpus = [r for r in refs if r in paper_ids][:20]  # 最多 20 条防慢
        for i in range(len(refs_in_corpus)):
            for j in range(i + 1, len(refs_in_corpus)):
                pair = (refs_in_corpus[i], refs_in_corpus[j])
                cocite[pair] = cocite.get(pair, 0) + 1

    # 归一化权重
    max_count = max(cocite.values(), default=1)
    edges = {pair: count / max_count for pair, count in cocite.items() if count >= 2}
    print(f"  [edges] fused edges (co-cite >= 2): {len(edges)}")
    return edges


def build_novelty_scores(papers: list[dict]) -> dict[str, float]:
    """
    使用 V12.5 可用信号计算 novelty_score。
    未实施信号传 None (权重自动转移)。
    """
    scores = {}
    for p in papers:
        pid = p.get("openalex_id") or p.get("paper_id") or p.get("id", "")

        # 从 paper 数据中提取可用信号
        cited = float(p.get("cited_by_count", 0) or 0)

        # c_recency: 根据 publication_date 估算
        pub_date = p.get("publication_date", "")
        recency = 0.5  # 默认中性
        if pub_date:
            try:
                import datetime
                pub = datetime.datetime.strptime(str(pub_date)[:10], "%Y-%m-%d")
                days_old = (datetime.datetime.now() - pub).days
                # 新论文 (< 180 天) → recency ≈ 1.0; 老论文 (> 3 年) → recency ≈ 0.0
                recency = max(0.0, min(1.0, 1.0 - days_old / (3 * 365)))
            except Exception:
                pass

        # c_semantic_outlier: 用 cited_by_count 的对数分位作为 proxy
        # (真实实现需要 Isolation Forest on embeddings)
        semantic_outlier = None  # 未实施 → 权重转移

        # c_breakthrough_lang: 无 LLM → None
        breakthrough_lang = None

        # c_bridging_centrality: 用引用多样性作为 proxy
        refs = p.get("referenced_works", []) or []
        bridging = min(math.log(1 + len(refs)) / 5.0, 1.0) if refs else 0.3

        # c_cd_subdomain: 未实施 → None
        cd_subdomain = None

        # c_team_disrupt: 未实施 → None
        team_disrupt = None

        signals = {
            "c_cd_subdomain":        cd_subdomain,
            "c_bridging_centrality": bridging,
            "c_team_disrupt":        team_disrupt,
            "c_semantic_outlier":    semantic_outlier,
            "c_recency":             recency,
            "c_breakthrough_lang":   breakthrough_lang,
        }
        scores[pid] = compute_novelty_score(p, signals)

    return scores


def build_bottleneck_halos(
    bottlenecks: list[dict],
    positions: dict[str, tuple],
    paper_index: dict[str, dict],
) -> list[dict]:
    """
    为每个 bottleneck cluster 计算辉光晕中心和半径。
    """
    halo_colors = [
        "#ffaa00", "#ff6b6b", "#6bceff", "#aeff6b", "#d4a0ff",
        "#ff8c42", "#00d4aa", "#ffd166", "#ef476f", "#06d6a0",
        "#118ab2", "#073b4c", "#ff595e", "#ffca3a", "#6a4c93",
    ]

    halos = []
    for i, bn in enumerate(bottlenecks):
        sp = bn.get("supporting_papers", [])
        coords = []
        for pid in sp:
            if pid in positions:
                coords.append(positions[pid])

        if not coords:
            # 若无位置信息, 随机分布在圆环上
            angle = i * 2 * math.pi / len(bottlenecks)
            cx = 800 + math.cos(angle) * 400
            cy = 800 + math.sin(angle) * 400
            r = 60
        else:
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            # 半径 = 最大到中心距离 × 1.3
            r = max(
                max((x - cx)**2 + (y - cy)**2 for x, y in coords) ** 0.5 * 1.3,
                40,
            )

        halos.append({
            "bottleneck_id": bn.get("bottleneck_id", f"BN{i}"),
            "label":         bn.get("label", ""),
            "cx":            round(cx, 2),
            "cy":            round(cy, 2),
            "r":             round(min(r, 200), 2),  # 最大 200px
            "color":         halo_colors[i % len(halo_colors)],
            "paper_count":   len(sp),
        })

    return halos


def build_meta_principle_bands(meta_principles: list[dict]) -> list[dict]:
    """
    为 4 个元规律构建虹光带数据。
    """
    band_colors = ["#00ffcc", "#ff6b9d", "#ffd700", "#7b9fff"]
    bands = []
    for i, mp in enumerate(meta_principles):
        bands.append({
            "id":           i,
            "name":         mp.get("principle", f"MetaPrinciple {i+1}")[:30],
            "color":        band_colors[i % len(band_colors)],
            "covered_themes": mp.get("covered_themes", []),
        })
    return bands


def build_nodes_list(
    papers: list[dict],
    positions: dict[str, tuple],
    color_map: dict[str, dict],
    novelty_scores: dict[str, float],
    seeds_set: set[str],
) -> list[dict]:
    """组装节点列表 (含坐标、颜色、形状、大小)"""
    nodes = []
    for p in papers:
        pid = p.get("openalex_id") or p.get("paper_id") or p.get("id", "")
        if pid not in positions:
            continue

        x, y = positions[pid]
        cm = color_map.get(pid, {})
        cited = float(p.get("cited_by_count", 0) or 0)
        novelty = novelty_scores.get(pid, 0.5)
        size = get_node_radius_px(p, novelty)

        nodes.append({
            "id":              pid,
            "x":               round(x, 2),
            "y":               round(y, 2),
            "color":           cm.get("color", "#7f7f7f"),
            "shape":           cm.get("shape", "circle"),
            "size":            round(size, 2),
            "label":           (p.get("title", "") or "")[:80],
            "field":           cm.get("field", ""),
            "subfield":        cm.get("subfield", ""),
            "domain":          cm.get("domain", ""),
            "topic":           p.get("primary_topic_name", ""),
            "cited_by_count":  cited,
            "novelty":         round(novelty, 4),
            "is_seed":         pid in seeds_set,
        })
    return nodes


def build_edges_list(
    fused_edges: dict,
    max_edges: int = 3000,
) -> list[dict]:
    """转换 fused_edges 为渲染用列表 (限制数量)"""
    # 按权重降序取 top max_edges
    sorted_edges = sorted(fused_edges.items(), key=lambda x: x[1], reverse=True)
    edges = []
    for (src, dst), w in sorted_edges[:max_edges]:
        edges.append({
            "src":          src,
            "dst":          dst,
            "fused_weight": round(float(w), 4),
            "opacity":      round(min(float(w) * 0.8, 0.6), 3),
        })
    return edges


def main():
    parser = argparse.ArgumentParser(description="V13 知识图谱渲染器")
    parser.add_argument("--dpi",     type=int,   default=150, help="PNG DPI (默认 150)")
    parser.add_argument("--out-dir", type=str,   default="reports/v13", help="输出目录")
    parser.add_argument("--no-llm",  action="store_true", help="跳过 LLM 标签生成")
    parser.add_argument("--max-edges", type=int, default=2000, help="最大边数 (默认 2000)")
    args = parser.parse_args()

    out_dir = _ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = str(out_dir / "graph.html")
    png_path  = str(out_dir / "graph.png")
    meta_path = str(out_dir / "metadata.json")

    t0 = time.time()
    print("\n[V13] 开始渲染知识图谱...")
    print(f"  输出目录: {out_dir}")

    # ── Step 1: 加载数据 ──────────────────────────────────────────────────────
    print("\n[1/7] 加载数据...")
    papers = load_papers(PAPERS_PATH)
    seeds_data       = load_json(SEEDS_PATH)
    bottlenecks_data = load_json(BOTTLENECKS_PATH)
    meta_data        = load_json(META_PATH)

    bottlenecks   = bottlenecks_data.get("bottlenecks", [])
    meta_principles = meta_data.get("meta_principles", [])
    seeds_set     = extract_seeds_set(seeds_data)
    paper_index   = build_paper_index(papers)
    print(f"  papers={len(papers)}, seeds={len(seeds_set)}, bottlenecks={len(bottlenecks)}")

    # ── Step 2: 构建 fused_edges ──────────────────────────────────────────────
    print("\n[2/7] 构建融合边...")
    fused_edges = build_fused_edges_simple(papers)

    # ── Step 3: 计算 novelty_scores + 径向布局 ────────────────────────────────
    print("\n[3/7] 计算 novelty_scores...")
    novelty_scores = build_novelty_scores(papers)
    n_high_novelty = sum(1 for v in novelty_scores.values() if v > 0.6)
    print(f"  novelty_scores: mean={sum(novelty_scores.values())/len(novelty_scores):.3f}, "
          f"high_novelty(>0.6)={n_high_novelty}")

    print("\n[4/7] 计算径向布局...")
    positions = radial_force_layout(
        papers=papers,
        fused_edges=fused_edges,
        novelty_scores=novelty_scores,
        canvas_size=(1600, 1600),
        n_iterations=30,
    )
    print(f"  positions: {len(positions)} nodes placed")

    # ── Step 4: 学科着色 ──────────────────────────────────────────────────────
    print("\n[5/7] 计算学科着色...")
    color_map = build_color_map_for_papers(papers)
    fields_present = set(v["field"] for v in color_map.values() if v["field"])
    print(f"  fields in corpus: {fields_present}")

    # ── Step 5: 里程碑识别 + 标签 ─────────────────────────────────────────────
    print("\n[6/7] 识别里程碑...")
    landmarks_raw = detect_landmarks(
        papers=papers,
        novelty_scores=novelty_scores,
        weighted_betweenness=None,  # 用 proxy
        top_n=10,
    )
    print(f"  top landmarks: {len(landmarks_raw)}")
    for lm in landmarks_raw[:3]:
        print(f"    - [{lm['composite_score']:.3f}] {lm['title'][:60]}")

    if args.no_llm:
        # 使用回退标签
        from echelon.graph.landmark_detection import _generate_fallback_label
        landmarks = [{**lm, "short_label_zh": _generate_fallback_label(lm)} for lm in landmarks_raw]
    else:
        print("  生成 LLM 中文标签 (若 pplx-tool 不可用则回退)...")
        landmarks = generate_landmark_labels(landmarks_raw)

    for lm in landmarks:
        pid = lm["paper_id"]
        if pid in positions:
            x, y = positions[pid]
            lm["x"] = round(x, 2)
            lm["y"] = round(y, 2)
        else:
            lm["x"] = 800.0
            lm["y"] = 800.0

    print("  里程碑标签:", [lm["short_label_zh"] for lm in landmarks])

    # ── Step 6: 构建渲染数据 ──────────────────────────────────────────────────
    nodes = build_nodes_list(papers, positions, color_map, novelty_scores, seeds_set)
    edges = build_edges_list(fused_edges, max_edges=args.max_edges)

    bottleneck_halos = build_bottleneck_halos(bottlenecks, positions, paper_index)
    meta_bands = build_meta_principle_bands(meta_principles)
    overlays = {
        "bottleneck_halos":       bottleneck_halos,
        "meta_principle_bands":   meta_bands,
    }

    # ── Step 7: 渲染输出 ──────────────────────────────────────────────────────
    print("\n[7/7] 渲染输出...")

    # HTML
    print(f"  渲染 HTML → {html_path}")
    render_interactive_html(nodes, edges, overlays, landmarks, html_path)
    html_bytes = os.path.getsize(html_path)
    print(f"  HTML: {html_bytes:,} bytes ({html_bytes/1024:.1f} KB)")

    # PNG
    print(f"  渲染 PNG → {png_path}")
    render_static_png(nodes, edges, overlays, landmarks, png_path, dpi=args.dpi)
    png_bytes = os.path.getsize(png_path)
    print(f"  PNG: {png_bytes:,} bytes ({png_bytes/1024:.1f} KB)")

    # Metadata
    metadata = {
        "version":            "V13",
        "papers_count":       len(papers),
        "nodes_rendered":     len(nodes),
        "edges_rendered":     len(edges),
        "seeds_count":        len(seeds_set),
        "bottlenecks_count":  len(bottlenecks),
        "landmarks_count":    len(landmarks),
        "fields_present":     sorted(fields_present),
        "novelty_mean":       round(sum(novelty_scores.values()) / max(len(novelty_scores), 1), 4),
        "html_bytes":         html_bytes,
        "png_bytes":          png_bytes,
        "dpi":                args.dpi,
        "elapsed_sec":        round(time.time() - t0, 2),
        "landmarks": [
            {
                "title":          lm["title"][:80],
                "short_label_zh": lm["short_label_zh"],
                "novelty":        lm["novelty"],
                "composite_score": lm["composite_score"],
            }
            for lm in landmarks
        ],
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0
    print(f"\n[V13] 完成! 耗时 {elapsed:.1f}s")
    print(f"  HTML: {html_path}  ({html_bytes/1024:.1f} KB)")
    print(f"  PNG:  {png_path}   ({png_bytes/1024:.1f} KB)")
    print(f"  Meta: {meta_path}")

    # ── 视觉描述 ──────────────────────────────────────────────────────────────
    fields_by_count: dict[str, int] = {}
    for n in nodes:
        fn = n.get("field", "Unknown")
        fields_by_count[fn] = fields_by_count.get(fn, 0) + 1
    dominant_field = max(fields_by_count, key=fields_by_count.get) if fields_by_count else "N/A"

    print("\n[视觉描述]")
    print(f"  黑色背景径向图谱 | 主色: {dominant_field} 系")
    print(f"  卡点辉光数: {len(bottleneck_halos)}")
    print(f"  元规律虹光带: {len(meta_bands)}")
    print(f"  里程碑标注: {[lm['short_label_zh'] for lm in landmarks]}")
    print(f"  外圈(高novelty)颠覆性前沿论文 {n_high_novelty} 篇")


if __name__ == "__main__":
    main()
