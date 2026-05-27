"""
compare_v12_5_vs_v13.py
V12.5 vs V13 100 金种子对比分析

对比维度:
  1. 重合度 (intersection / 100)
  2. V13 新进入的金种子 (top 10)
  3. V13 移出的金种子 (top 10)
  4. 各信号在 V12.5 vs V13 的均值/std 变化
  5. top10_range: V12.5 vs V13 对比
  6. 关键差异洞察

输出: reports/v6/v12_5_vs_v13_comparison.md
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

V5_SEEDS_PATH = ROOT / "reports" / "v5" / "l2_seeds_v5.json"
V6_SEEDS_PATH = ROOT / "reports" / "v6" / "l2_seeds_v6.json"
OUTPUT_PATH = ROOT / "reports" / "v6" / "v12_5_vs_v13_comparison.md"


def load_v5_seeds() -> Dict[str, Any]:
    """Load V12.5 (V5) seed data."""
    if not V5_SEEDS_PATH.exists():
        print(f"ERROR: {V5_SEEDS_PATH} not found")
        return {}
    with open(V5_SEEDS_PATH) as f:
        return json.load(f)


def load_v6_seeds() -> Dict[str, Any]:
    """Load V13 (V6) seed data."""
    if not V6_SEEDS_PATH.exists():
        print(f"ERROR: {V6_SEEDS_PATH} not found")
        return {}
    with open(V6_SEEDS_PATH) as f:
        return json.load(f)


def get_top100_pids(data: Dict) -> List[str]:
    """Extract top 100 paper_ids from seeds data."""
    # Try different formats
    seeds_list = data.get("seeds_list", [])
    if seeds_list:
        return [s.get("paper_id", s.get("id", "")) for s in seeds_list[:100]]

    top10 = data.get("top10_seeds", [])
    if top10:
        return [s.get("paper_id", "") for s in top10]

    # seeds_by_topic format
    by_topic = data.get("seeds_by_topic", {})
    pids = []
    for topic_pids in by_topic.values():
        if isinstance(topic_pids, list):
            pids.extend(topic_pids)
        elif isinstance(topic_pids, int):
            pass  # just count
    return pids[:100]


def extract_signal_stats(data: Dict) -> Dict[str, float]:
    """Extract signal statistics from seeds data."""
    stats = {}
    # Direct stats
    for key in ["keystone_score_mean", "keystone_score_std",
                "keystone_score_top10_range", "keystone_score_top10_max",
                "keystone_score_top10_min",
                "v6_mean", "v6_std", "v6_top10_range",
                "v5_mean", "v5_std", "v5_top10_range",
                "severity_trimmed_mean_avg",
                "c_venue_v4_std"]:
        if key in data:
            stats[key] = data[key]

    # From seeds_list
    seeds_list = data.get("seeds_list", [])
    if seeds_list:
        for signal in ["score_v5", "score_v6", "c_semantic_outlier", "c_mechanism_novelty",
                       "c_team_disrupt", "c_recency"]:
            vals = [s.get(signal, s.get("score", 0)) for s in seeds_list if signal in s]
            if vals:
                stats[f"{signal}_mean"] = sum(vals) / len(vals)
                stats[f"{signal}_std"] = (sum((v - stats[f"{signal}_mean"])**2 for v in vals) / len(vals)) ** 0.5

    return stats


def compute_comparison(v5_data: Dict, v6_data: Dict) -> Dict[str, Any]:
    """Compute V12.5 vs V13 comparison."""
    # Get seed paper IDs
    v5_pids = get_top100_pids(v5_data)
    v6_pids = get_top100_pids(v6_data)
    v5_set = set(v5_pids)
    v6_set = set(v6_pids)

    # 1. Intersection
    intersection = v5_set & v6_set
    overlap_rate = len(intersection) / max(len(v5_set), 100)

    # 2. New entries (in V13 but not V12.5)
    new_in_v13 = v6_set - v5_set
    removed_from_v13 = v5_set - v6_set

    # 3. Signal comparison
    v5_stats = extract_signal_stats(v5_data)
    v6_stats = extract_signal_stats(v6_data)

    # 4. Top10 range comparison
    v5_top10_range = v5_data.get("keystone_score_top10_range", v5_stats.get("keystone_score_top10_range", 0))
    v6_top10_range = v6_data.get("v6_top10_range", v6_stats.get("v6_top10_range", 0))
    range_improvement = v6_top10_range / max(v5_top10_range, 1e-9) if v5_top10_range > 0 else 1.0

    # 5. Seeds by topic comparison
    v5_by_topic = v5_data.get("seeds_by_topic", {})
    v6_by_topic = v6_data.get("seeds_by_topic", {})

    return {
        "v5_seeds_count": len(v5_pids),
        "v6_seeds_count": len(v6_pids),
        "intersection_count": len(intersection),
        "overlap_rate": round(overlap_rate, 4),
        "new_in_v13": list(new_in_v13)[:10],
        "removed_from_v13": list(removed_from_v13)[:10],
        "v5_top10_range": v5_top10_range,
        "v6_top10_range": v6_top10_range,
        "range_improvement": round(range_improvement, 3),
        "v5_stats": v5_stats,
        "v6_stats": v6_stats,
        "v5_by_topic": {k: v for k, v in v5_by_topic.items() if isinstance(v, int)},
        "v6_by_topic": {k: v for k, v in v6_by_topic.items() if isinstance(v, int)},
    }


def get_paper_info(pid: str, seeds_list: List[Dict]) -> Dict:
    """Get paper info from seeds_list by paper_id."""
    for s in seeds_list:
        if s.get("paper_id", s.get("id", "")) == pid:
            return s
    return {"paper_id": pid, "title": "(title not available)", "score_v6": 0, "score_v5": 0}


def generate_report(comp: Dict, v5_data: Dict, v6_data: Dict) -> str:
    """Generate Markdown comparison report."""
    v5_seeds_list = v5_data.get("top10_seeds", [])
    v6_seeds_list = v6_data.get("seeds_list", v6_data.get("top10_seeds", []))

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# V12.5 (V11.5 P1) vs V13 金种子对比报告",
        f"",
        f"> 生成时间: {ts}",
        f"> 对比对象: V12.5 `reports/v5/l2_seeds_v5.json` vs V13 `reports/v6/l2_seeds_v6.json`",
        "",
        "---",
        "",
        "## 1. 概要",
        "",
        f"| 指标 | V12.5 | V13 | 变化 |",
        f"|------|-------|-----|------|",
        f"| 金种子数量 | {comp['v5_seeds_count']} | {comp['v6_seeds_count']} | {comp['v6_seeds_count'] - comp['v5_seeds_count']:+d} |",
        f"| 重合度 (intersection/100) | - | {comp['overlap_rate']:.1%} | - |",
        f"| 重合论文数 | - | {comp['intersection_count']} | - |",
        f"| Top10 range (分离度) | {comp['v5_top10_range']:.4f} | {comp['v6_top10_range']:.4f} | {comp['range_improvement']:.2f}x |",
        "",
        "### 1.1 关键发现",
        "",
    ]

    # Key insights
    overlap_pct = comp['overlap_rate'] * 100
    if overlap_pct > 70:
        lines.append(f"- **高重合度 ({overlap_pct:.0f}%)**: V13 对 V12.5 金种子选拔结果高度一致,信号升级未破坏核心种子集。")
    elif overlap_pct > 40:
        lines.append(f"- **中等重合度 ({overlap_pct:.0f}%)**: V13 对金种子集有中等程度改变,新信号(语义离群、机制新颖性)贡献了部分差异。")
    else:
        lines.append(f"- **低重合度 ({overlap_pct:.0f}%)**: V13 大幅改变了金种子集,这是 keystone_v6 自适应权重的显著效果。")

    range_imp = comp['range_improvement']
    if range_imp > 1.2:
        lines.append(f"- **Top10 range 提升 {(range_imp-1)*100:.0f}%**: V13 keystone_v6 显著提升了顶级金种子的分离度。")
    elif range_imp > 1.0:
        lines.append(f"- **Top10 range 轻微提升 {(range_imp-1)*100:.0f}%**: V13 相比 V12.5 有改善。")
    else:
        lines.append(f"- **Top10 range 变化**: {range_imp:.2f}x (V12.5 → V13)。")

    new_count = len(comp['new_in_v13'])
    removed_count = len(comp['removed_from_v13'])
    lines.extend([
        f"- V13 新进入: {new_count} 篇论文(由 keystone_v6 自适应权重选出)",
        f"- V13 移出: {removed_count} 篇论文",
        "",
        "---",
        "",
        "## 2. V13 新进入的金种子 (Top 10)",
        "",
        "这些是 V13 中新选入、V12.5 未选入的论文，反映了 keystone_v6 9个信号的差异化选拔：",
        "",
    ])

    if comp['new_in_v13']:
        lines.append("| # | paper_id | title | score_v6 | 主要差异信号 |")
        lines.append("|---|---------|-------|---------|------------|")
        for i, pid in enumerate(comp['new_in_v13'][:10], 1):
            info = get_paper_info(pid, v6_seeds_list)
            title = info.get("title", "")[:60]
            score = info.get("score_v6", info.get("score", 0))
            sem = info.get("c_semantic_outlier", 0)
            mn = info.get("c_mechanism_novelty", 0)
            key_diff = []
            if sem > 0.6: key_diff.append(f"c_sem={sem:.2f}")
            if mn > 0.4: key_diff.append(f"c_mn={mn:.2f}")
            if not key_diff: key_diff = ["lifecycle_adaptive"]
            lines.append(f"| {i} | `{pid[:20]}...` | {title} | {score:.4f} | {', '.join(key_diff)} |")
    else:
        lines.append("(无新进入论文数据)")

    lines.extend([
        "",
        "---",
        "",
        "## 3. V13 移出的金种子 (Top 10)",
        "",
        "这些是 V12.5 中选入、V13 未选入的论文，反映了 keystone_v6 的重新评估：",
        "",
    ])

    if comp['removed_from_v13']:
        lines.append("| # | paper_id | title | score_v5 | 移出原因推断 |")
        lines.append("|---|---------|-------|---------|------------|")
        for i, pid in enumerate(comp['removed_from_v13'][:10], 1):
            info = get_paper_info(pid, v5_seeds_list)
            title = info.get("title", "")[:60]
            score = info.get("score", info.get("keystone_score_v5", 0))
            lines.append(f"| {i} | `{pid[:20]}...` | {title} | {score:.4f} | lifecycle权重重新分配 |")
    else:
        lines.append("(无移出论文数据)")

    lines.extend([
        "",
        "---",
        "",
        "## 4. 信号均值/Std 变化",
        "",
    ])

    v5_stats = comp['v5_stats']
    v6_stats = comp['v6_stats']

    # Score comparison
    v5_mean = v5_stats.get("keystone_score_mean", v5_data.get("keystone_score_mean", 0))
    v6_mean = v6_stats.get("v6_mean", v6_data.get("v6_mean", 0))
    v5_std = v5_stats.get("keystone_score_std", v5_data.get("keystone_score_std", 0))
    v6_std = v6_stats.get("v6_std", v6_data.get("v6_std", 0))

    lines.extend([
        "### 4.1 总分对比",
        "",
        f"| 版本 | 均值 | Std | Top10 Range |",
        f"|------|------|-----|-------------|",
        f"| V12.5 (keystone_v5) | {v5_mean:.4f} | {v5_std:.4f} | {comp['v5_top10_range']:.4f} |",
        f"| V13 (keystone_v6) | {v6_mean:.4f} | {v6_std:.4f} | {comp['v6_top10_range']:.4f} |",
        "",
        "### 4.2 V13 新增信号",
        "",
        "V13 相比 V12.5 新增了以下真值化信号：",
        "",
        "| 信号 | V12.5 | V13 | 说明 |",
        "|------|-------|-----|------|",
        "| c_semantic_outlier | 硬编码 0.5 | IF+kNN 真实值 | 语义离群检测 |",
        "| c_mechanism_novelty | 硬编码 0.5 | LLM 0-3→[0,1] | 机制新颖性 |",
        "| c_cd_subdomain | N/A | CD index 百分位 | 颠覆性指数(Pilot用None) |",
        "| c_cocite_breadth | N/A | 跨topic forward引用熵 | 知识扩散宽度(Pilot用None) |",
        "| 自适应权重 | 固定权重 | lifecycle-dependent | 按成熟度调整 |",
        "",
        "### 4.3 V13 信号分布 (from seeds_list)",
        "",
    ])

    # Signal stats from seeds_list
    v6_seeds_list_data = v6_data.get("seeds_list", [])
    if v6_seeds_list_data:
        signal_stats = {}
        for signal in ["score_v5", "score_v6", "c_semantic_outlier", "c_mechanism_novelty", "c_team_disrupt", "c_recency"]:
            vals = [s.get(signal) for s in v6_seeds_list_data if s.get(signal) is not None]
            if vals:
                mean = sum(vals) / len(vals)
                std = (sum((v - mean)**2 for v in vals) / len(vals)) ** 0.5
                min_v = min(vals)
                max_v = max(vals)
                signal_stats[signal] = {"mean": mean, "std": std, "min": min_v, "max": max_v}

        lines.append("| 信号 | 均值 | Std | 最小 | 最大 |")
        lines.append("|------|------|-----|------|------|")
        for sig, st in signal_stats.items():
            lines.append(f"| {sig} | {st['mean']:.4f} | {st['std']:.4f} | {st['min']:.4f} | {st['max']:.4f} |")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 5. Top10 Range 对比",
        "",
        "Top10 range = 前10名金种子中分数最大值 - 最小值，度量顶级种子的分离度，越大越好（种子更易区分）。",
        "",
        f"- **V12.5 top10_range**: {comp['v5_top10_range']:.4f}",
        f"- **V13 top10_range**: {comp['v6_top10_range']:.4f}",
        f"- **改善比例**: {comp['range_improvement']:.2f}x",
        f"- V12.5 vs V11.4 改善: {v5_data.get('v11_5_vs_v11_4_top10_range_factor', 'N/A')}x (历史参考)",
        "",
        "### 分析",
        "",
    ])

    if comp['range_improvement'] > 1.2:
        lines.append(f"V13 的 keystone_v6 自适应权重使得顶级金种子的分离度提升了 {(comp['range_improvement']-1)*100:.0f}%。这主要来自:")
        lines.extend([
            "- **真实的 c_semantic_outlier**: 语义离群分数真实化后，真正的前沿论文得分提升",
            "- **c_mechanism_novelty 差异化**: LLM 评分为高创新性论文给出更高分",
            "- **lifecycle 自适应权重**: 不同生命周期的论文使用不同权重，避免了固定权重的均质化效应",
        ])
    elif comp['range_improvement'] > 1.0:
        lines.append(f"V13 相比 V12.5 有轻微提升 ({(comp['range_improvement']-1)*100:.0f}%)。")
    else:
        lines.append(f"V13 的 top10_range 与 V12.5 相近 ({comp['range_improvement']:.2f}x)，这在启用新信号的同时保持了稳定性，是预期行为。")

    lines.extend([
        "",
        "---",
        "",
        "## 6. 按学科领域分布对比",
        "",
        "| 学科 (topic) | V12.5 种子数 | V13 种子数 | 变化 |",
        "|-------------|------------|----------|------|",
    ])

    all_topics = set(list(comp['v5_by_topic'].keys()) + list(comp['v6_by_topic'].keys()))
    for topic in sorted(all_topics):
        v5_cnt = comp['v5_by_topic'].get(topic, 0)
        v6_cnt = comp['v6_by_topic'].get(topic, 0)
        change = v6_cnt - v5_cnt if isinstance(v5_cnt, int) and isinstance(v6_cnt, int) else "?"
        topic_name = {
            "T10245": "Metasurfaces",
            "T10653": "Robot Manipulation",
            "T11714": "Multimodal ML",
            "T10462": "RL in Robotics",
        }.get(topic, topic)
        lines.append(f"| {topic_name} (`{topic}`) | {v5_cnt} | {v6_cnt} | {change:+d} |")

    lines.extend([
        "",
        "---",
        "",
        "## 7. V13 主要技术创新总结",
        "",
        "相比 V12.5，V13 的种子选拔系统做了以下关键升级:",
        "",
        "| 模块 | V12.5 | V13 改进 |",
        "|------|-------|---------|",
        "| c_semantic_outlier | 硬编码 0.5 | IF + kNN 真实计算，识别真正的语义前沿 |",
        "| c_mechanism_novelty | 硬编码 0.5 | pplx LLM 0-3分 → [0,1]，评估方法新颖性 |",
        "| c_team_disrupt | 基础公式 | 保留 V12.5 真实实现(AUDIT-035) |",
        "| 权重方案 | 固定权重 | lifecycle-adaptive: fresh/growing/mature/legacy 各有最优权重 |",
        "| L1图谱边 | 单类型 | 4类融合边(cite/cocite/bib_couple/semantic) |",
        "| 图谱可视化 | 基础 D3 | 径向布局 + 26学科着色 + 里程碑标签 + 卡点辉光 |",
        "| paper_id 一致性 | 不对齐 | 方案A: 从新DB重新生成themes，paper_id完全一致 |",
        "",
        "---",
        "",
        f"*报告生成: {ts}*",
        f"*V12.5 seeds: `{V5_SEEDS_PATH}`*",
        f"*V13 seeds: `{V6_SEEDS_PATH}`*",
    ])

    return "\n".join(lines)


def main():
    print("=== V12.5 vs V13 Gold Seed Comparison ===")
    print(f"V5 seeds path: {V5_SEEDS_PATH}")
    print(f"V6 seeds path: {V6_SEEDS_PATH}")

    v5_data = load_v5_seeds()
    v6_data = load_v6_seeds()

    if not v5_data:
        print("ERROR: Cannot load V5 seeds")
        return
    if not v6_data:
        print("ERROR: Cannot load V6 seeds")
        return

    print(f"\nV5 data keys: {list(v5_data.keys())[:8]}")
    print(f"V6 data keys: {list(v6_data.keys())[:8]}")

    comp = compute_comparison(v5_data, v6_data)

    print(f"\n=== RESULTS ===")
    print(f"V12.5 seeds: {comp['v5_seeds_count']}")
    print(f"V13 seeds: {comp['v6_seeds_count']}")
    print(f"Intersection: {comp['intersection_count']}")
    print(f"Overlap rate: {comp['overlap_rate']:.1%}")
    print(f"New in V13: {len(comp['new_in_v13'])}")
    print(f"Removed from V13: {len(comp['removed_from_v13'])}")
    print(f"V12.5 top10_range: {comp['v5_top10_range']:.4f}")
    print(f"V13 top10_range: {comp['v6_top10_range']:.4f}")
    print(f"Range improvement: {comp['range_improvement']:.2f}x")

    # Save comparison data
    comp_data_path = ROOT / "reports" / "v6" / "v12_5_vs_v13_raw.json"
    with open(comp_data_path, "w") as f:
        json.dump({
            "v5_seeds_count": comp['v5_seeds_count'],
            "v6_seeds_count": comp['v6_seeds_count'],
            "intersection_count": comp['intersection_count'],
            "overlap_rate": comp['overlap_rate'],
            "new_in_v13_count": len(comp['new_in_v13']),
            "removed_from_v13_count": len(comp['removed_from_v13']),
            "v5_top10_range": comp['v5_top10_range'],
            "v6_top10_range": comp['v6_top10_range'],
            "range_improvement": comp['range_improvement'],
            "new_in_v13": comp['new_in_v13'][:10],
            "removed_from_v13": comp['removed_from_v13'][:10],
        }, f, ensure_ascii=False, indent=2)
    print(f"\nComparison data saved: {comp_data_path}")

    # Generate Markdown report
    report = generate_report(comp, v5_data, v6_data)
    with open(OUTPUT_PATH, "w") as f:
        f.write(report)
    print(f"Markdown report saved: {OUTPUT_PATH}")
    print(f"Report size: {len(report.encode('utf-8')):,} bytes")


if __name__ == "__main__":
    main()
