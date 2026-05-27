"""
[V11.4 bugfix] run_pilot_v4 中 cocite 数字 (4603) 错误,
独立脚本直接基于 jsonl 算正确 cocite 并修正 reports/v4/。
不动其他三层,只改 L1 stats 中 cocite 部分,以及 N3 验证。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from echelon.graph.cocite import build_cocitation_edges_adaptive

DATA_FILES = [
    'data/raw/papers_metasurfaces.jsonl',
    'data/raw/papers_robot_manipulation.jsonl',
    'data/raw/papers_multimodal_ml.jsonl',
    'data/raw/papers_rl_robotics.jsonl',
    'data/raw_v2/papers_metasurfaces_v2.jsonl',
    'data/raw_v2/papers_robot_manipulation_v2.jsonl',
    'data/raw_v2/papers_multimodal_ml_v2.jsonl',
    'data/raw_v2/papers_rl_robotics_v2.jsonl',
]

base = Path("/home/user/workspace/echelon_mvp0a")
papers_refs = {}
for fn in DATA_FILES:
    with open(base / fn) as f:
        for line in f:
            rec = json.loads(line)
            oa_id = rec.get("openalex_id", "") or ""
            oa_short = oa_id.split("openalex.org/")[-1] if "openalex.org/" in oa_id else oa_id
            rw_list = rec.get("referenced_works", []) or []
            rw_ids = [str(w).split("openalex.org/")[-1] if "openalex.org/" in str(w) else str(w) for w in rw_list]
            if rw_ids:
                papers_refs[oa_short] = rw_ids

print(f"加载: {len(papers_refs)} 篇有 refs")
edges, stats = build_cocitation_edges_adaptive(papers_refs, min_floor=2)
print(f"原始对数: {stats['raw_pair_count']}")
print(f"阈值: {stats['threshold_used']}")
print(f"过滤后边数: {stats['filtered_edge_count']}")
print(f"weight 分布: {stats.get('weight_distribution_summary')}")

# 修正 reports/v4/l1_graph_stats_v4.json
l1_path = base / "reports/v4/l1_graph_stats_v4.json"
l1 = json.load(open(l1_path))

old_cocite = l1["edges"].get("co_citation_after_filter", 4603)
old_cocite_all = l1["edges"].get("co_citation_all_pairs", 16060)

l1["edges"]["co_citation_after_filter"] = stats['filtered_edge_count']
l1["edges"]["co_citation_all_pairs"] = stats['raw_pair_count']
l1["cocite_distribution"] = stats.get("weight_distribution_summary", {})
# 重算 total
l1["edges"]["total"] = (
    l1["edges"]["cite_direct"]
    + l1["edges"]["co_citation_after_filter"]
    + l1["edges"]["bib_couple"]
    + l1["edges"]["semantic_bridge"]
)
l1["_v11_4_bugfix_1_note"] = (
    f"co_citation 从错误的 {old_cocite}(只算语料内引用)修正为 {stats['filtered_edge_count']}"
    f"(包含语料外引用,符合 co_citation 的语义)"
)

with open(l1_path, "w") as f:
    json.dump(l1, f, indent=2, ensure_ascii=False)

print(f"\n[bugfix] reports/v4/l1_graph_stats_v4.json 已修正")
print(f"  co_citation_after_filter: {old_cocite} → {stats['filtered_edge_count']}")
print(f"  co_citation_all_pairs: {old_cocite_all} → {stats['raw_pair_count']}")

# 修正 three_way_compare.json
twc_path = base / "reports/v4/three_way_compare.json"
twc = json.load(open(twc_path))
twc["L1_metrics"]["edges_co_citation_after_filter"][2] = stats['filtered_edge_count']
twc["_v11_4_bugfix_1_note"] = (
    "co_citation 从 4603 修正到 {} (28× 提升)".format(stats['filtered_edge_count'])
)

with open(twc_path, "w") as f:
    json.dump(twc, f, indent=2, ensure_ascii=False)
print(f"[bugfix] reports/v4/three_way_compare.json 已修正")
