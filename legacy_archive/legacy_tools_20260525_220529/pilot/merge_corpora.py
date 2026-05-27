"""
V11.4 步骤1: 合并 raw + raw_v2 → 2000篇语料

读 data/raw/papers_*.jsonl (1000篇 2024-2026) +
   data/raw_v2/papers_*_v2.jsonl (1000篇 2022-2023)
合并到 data/raw_merged/papers_merged.jsonl (2000行)
验证零重叠(用 openalex_id 去重)
给每篇打标签 corpus_origin: "v1"|"v2"
输出 stats
按 topic 拆 4 个 merged 文件
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
RAW_DIR = ROOT / "data" / "raw"
RAW_V2_DIR = ROOT / "data" / "raw_v2"
MERGED_DIR = ROOT / "data" / "raw_merged"
MERGED_DIR.mkdir(exist_ok=True)

TOPIC_FILE_MAP_V1 = {
    "T10245": "papers_metasurfaces.jsonl",
    "T10653": "papers_robot_manipulation.jsonl",
    "T11714": "papers_multimodal_ml.jsonl",
    "T10462": "papers_rl_robotics.jsonl",
}

TOPIC_FILE_MAP_V2 = {
    "T10245": "papers_metasurfaces_v2.jsonl",
    "T10653": "papers_robot_manipulation_v2.jsonl",
    "T11714": "papers_multimodal_ml_v2.jsonl",
    "T10462": "papers_rl_robotics_v2.jsonl",
}

TOPIC_NAMES = {
    "T10245": "Metamaterials and Metasurfaces Applications",
    "T10653": "Robot Manipulation and Learning",
    "T11714": "Multimodal Machine Learning Applications",
    "T10462": "Reinforcement Learning in Robotics",
}


def load_jsonl(fpath: Path, topic_id: str, corpus_origin: str):
    """Load a JSONL file, yielding enriched records."""
    records = []
    skipped = 0
    if not fpath.exists():
        print(f"  !! 文件不存在: {fpath}")
        return records, skipped
    with open(fpath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            # skip retracted/paratext
            if str(rec.get("is_retracted", "False")).lower() == "true":
                skipped += 1
                continue
            if str(rec.get("is_paratext", "False")).lower() == "true":
                skipped += 1
                continue
            # skip no abstract
            if not (rec.get("abstract", "") or "").strip():
                skipped += 1
                continue
            rec["primary_topic_id"] = topic_id
            rec["primary_topic_name"] = TOPIC_NAMES.get(topic_id, "")
            rec["corpus_origin"] = corpus_origin
            records.append(rec)
    return records, skipped


def main():
    print("=== V11.4 步骤1: 合并语料 ===")

    all_records = []
    seen_oa_ids = set()
    duplicates = 0
    by_topic_v1 = defaultdict(int)
    by_topic_v2 = defaultdict(int)
    total_skipped = 0

    # Load V1 (2024-2026)
    print("\n[V1] 加载 raw/ (2024-2026)...")
    for topic_id, fname in TOPIC_FILE_MAP_V1.items():
        fpath = RAW_DIR / fname
        records, skipped = load_jsonl(fpath, topic_id, "v1")
        total_skipped += skipped
        print(f"  {fname}: {len(records)} 篇 (skipped={skipped})")
        for rec in records:
            oa_id = rec.get("openalex_id", "") or ""
            if "openalex.org/" in oa_id:
                oa_id_short = oa_id.split("openalex.org/")[-1]
            else:
                oa_id_short = oa_id
            if oa_id_short and oa_id_short in seen_oa_ids:
                duplicates += 1
                continue
            if oa_id_short:
                seen_oa_ids.add(oa_id_short)
            all_records.append(rec)
            by_topic_v1[topic_id] += 1

    # Load V2 (2022-2023)
    print("\n[V2] 加载 raw_v2/ (2022-2023)...")
    for topic_id, fname in TOPIC_FILE_MAP_V2.items():
        fpath = RAW_V2_DIR / fname
        records, skipped = load_jsonl(fpath, topic_id, "v2")
        total_skipped += skipped
        print(f"  {fname}: {len(records)} 篇 (skipped={skipped})")
        for rec in records:
            oa_id = rec.get("openalex_id", "") or ""
            if "openalex.org/" in oa_id:
                oa_id_short = oa_id.split("openalex.org/")[-1]
            else:
                oa_id_short = oa_id
            if oa_id_short and oa_id_short in seen_oa_ids:
                duplicates += 1
                continue
            if oa_id_short:
                seen_oa_ids.add(oa_id_short)
            all_records.append(rec)
            by_topic_v2[topic_id] += 1

    total = len(all_records)
    print(f"\n合并结果: {total} 篇 (duplicates去除={duplicates}, total_skipped={total_skipped})")

    # 验证零重叠
    v1_oas = set()
    v2_oas = set()
    for rec in all_records:
        oa_id = rec.get("openalex_id", "") or ""
        if "openalex.org/" in oa_id:
            oa_id_short = oa_id.split("openalex.org/")[-1]
        else:
            oa_id_short = oa_id
        if rec["corpus_origin"] == "v1":
            v1_oas.add(oa_id_short)
        else:
            v2_oas.add(oa_id_short)
    overlap = v1_oas & v2_oas
    print(f"零重叠验证: v1={len(v1_oas)}, v2={len(v2_oas)}, overlap={len(overlap)}")

    # 按 topic 分组统计
    by_topic_total = defaultdict(int)
    for rec in all_records:
        by_topic_total[rec["primary_topic_id"]] += 1

    stats = {
        "total": total,
        "v1_count": sum(by_topic_v1.values()),
        "v2_count": sum(by_topic_v2.values()),
        "duplicates_removed": duplicates,
        "total_skipped": total_skipped,
        "overlap_count": len(overlap),
        "by_topic_v1": dict(by_topic_v1),
        "by_topic_v2": dict(by_topic_v2),
        "by_topic_total": dict(by_topic_total),
        "zero_overlap_verified": len(overlap) == 0,
    }

    print(f"\nTopic 分布:")
    for tid, cnt in by_topic_total.items():
        v1c = by_topic_v1.get(tid, 0)
        v2c = by_topic_v2.get(tid, 0)
        print(f"  {tid}: total={cnt} (v1={v1c}, v2={v2c})")

    # 写入合并后的 merged.jsonl
    merged_path = MERGED_DIR / "papers_merged.jsonl"
    with open(merged_path, "w") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\n写入 {merged_path}: {total} 行")

    # 按 topic 拆分
    topic_file_names = {
        "T10245": "papers_metasurfaces_merged.jsonl",
        "T10653": "papers_robot_manipulation_merged.jsonl",
        "T11714": "papers_multimodal_ml_merged.jsonl",
        "T10462": "papers_rl_robotics_merged.jsonl",
    }
    topic_records = defaultdict(list)
    for rec in all_records:
        topic_records[rec["primary_topic_id"]].append(rec)

    for topic_id, fname in topic_file_names.items():
        fpath = MERGED_DIR / fname
        with open(fpath, "w") as f:
            for rec in topic_records[topic_id]:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"  {fname}: {len(topic_records[topic_id])} 行")

    # 写 stats
    stats_path = MERGED_DIR / "merge_stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"\n统计写入 {stats_path}")

    print("\n=== 合并完成 ===")
    print(f"  总计: {total} 篇")
    print(f"  V1 (2024-2026): {sum(by_topic_v1.values())} 篇")
    print(f"  V2 (2022-2023): {sum(by_topic_v2.values())} 篇")
    print(f"  零重叠验证: {'PASS' if len(overlap)==0 else 'FAIL'}")

    return stats


if __name__ == "__main__":
    main()
