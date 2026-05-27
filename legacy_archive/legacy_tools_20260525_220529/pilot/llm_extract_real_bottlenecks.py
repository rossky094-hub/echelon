"""
[V11.5+ 真 LLM 卡点抽取]
用 pplx llm extract 从 71 篇 V11.5 金种子的真实 abstract 中抽取 AI4Science 卡点。
这是项目最初目标的真正交付:跨领域+物理深度+非显然的卡点。
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

BASE = Path("/home/user/workspace/echelon_mvp0a")

# Step 1: 从 l3 bottlenecks 拿到 71 篇支持论文 id
l3 = json.load(open(BASE / "reports/v5/l3_bottlenecks_v5.json"))
paper_ids = set()
for b in l3["bottlenecks"]:
    for p in b.get("supporting_papers", []):
        if isinstance(p, dict):
            pid = p.get("paper_id") or p.get("id")
        else:
            pid = p
        if pid:
            paper_ids.add(pid)

print(f"[1] V11.5 金种子(L3 支持论文): {len(paper_ids)} 篇")

# Step 2: 从 db 拉论文完整数据
conn = sqlite3.connect(BASE / "db/pilot_v5.db")
ids_list = list(paper_ids)
placeholders = ",".join("?" * len(ids_list))
cur = conn.execute(
    f"""SELECT id, title, abstract, primary_topic_name, field_name, cited_by_count, validation_type
    FROM paper_identity WHERE id IN ({placeholders}) AND abstract IS NOT NULL""",
    ids_list,
)
papers = []
for row in cur.fetchall():
    papers.append({
        "paper_id": row[0],
        "title": row[1],
        "abstract": row[2],
        "topic_name": row[3],
        "field_name": row[4],
        "cited_by_count": row[5],
        "validation_type": row[6],
    })
print(f"[2] DB 抽取成功: {len(papers)} 篇")

# Step 3: 写入 jsonl 准备喂给 pplx llm extract
input_jsonl = BASE / "reports/v5/llm_input_71seeds.jsonl"
with open(input_jsonl, "w") as f:
    for p in papers:
        f.write(json.dumps(p, ensure_ascii=False) + "\n")
print(f"[3] JSONL 输入文件: {input_jsonl}")

# Step 4: 写抽取 prompt + schema
INSTRUCTION = """You are an expert AI4Science researcher analyzing a paper for unsolved research bottlenecks.

Given the paper's title, abstract, topic, and field, extract ONE primary research bottleneck following these strict criteria:

1. **Bottleneck statement** (中文,1-2 sentences): The specific unresolved technical/scientific problem the paper acknowledges or implies. NOT a general challenge — must be concrete (e.g. "逆向设计 metasurface 缺乏物理可解释性的具体机制" not "AI is hard").

2. **Cross-domain signal**: Does this bottleneck require crossing field/topic boundaries to solve? (true/false)
   - true: bridges optics+ML, robotics+VLM, physics+world-models, etc.
   - false: stays within one domain

3. **Physical depth signal** (中文): The specific physical mechanism, quantitative metric, or mathematical relationship the bottleneck binds to. If purely algorithmic with no physics, write "无物理深度信号 (纯算法)".

4. **Non-obviousness score** (1-5):
   - 1 = trivial/well-known (everyone in field knows)
   - 3 = moderate (some experts know)
   - 5 = subtle/buried (only careful reading reveals)

5. **Bottleneck category** (one of):
   - "interpretability" / "scalability" / "generalization" / "sample_efficiency" / "physical_grounding"
   - "robustness" / "compute_efficiency" / "hardware_constraint" / "data_quality" / "evaluation_gap"

6. **Evidence quote** (English, verbatim): Direct quote from the abstract that supports the bottleneck claim. Must be a substring of the input.

If the abstract is too generic to extract a real bottleneck, set bottleneck="无明确卡点" and non_obviousness=1.
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "bottleneck": {"type": "string", "description": "Specific unresolved bottleneck (Chinese, 1-2 sentences)"},
        "is_cross_domain": {"type": "boolean"},
        "physical_depth_signal": {"type": "string", "description": "Physical mechanism or quantitative signal (Chinese)"},
        "non_obviousness": {"type": "integer", "minimum": 1, "maximum": 5},
        "bottleneck_category": {
            "type": "string",
            "enum": ["interpretability", "scalability", "generalization", "sample_efficiency",
                    "physical_grounding", "robustness", "compute_efficiency",
                    "hardware_constraint", "data_quality", "evaluation_gap", "未明确"],
        },
        "evidence_quote": {"type": "string", "description": "Verbatim quote from abstract"},
    },
    "required": ["bottleneck", "is_cross_domain", "physical_depth_signal",
                 "non_obviousness", "bottleneck_category", "evidence_quote"],
}

# Step 5: 调 pplx llm extract
print(f"\n[4] 调用 pplx llm extract,模型默认...")
output_path = BASE / "reports/v5/llm_extracted_bottlenecks.jsonl"

cmd = [
    "pplx", "llm", "extract",
    "--instruction", INSTRUCTION,
    "--output-schema", json.dumps(OUTPUT_SCHEMA),
    "--max-tokens", "1500",
]
import os
env = os.environ.copy()
env.update({"PPLX_USE_SDK": "1"})

with open(input_jsonl) as fin, open(output_path, "w") as fout:
    proc = subprocess.run(cmd, stdin=fin, stdout=fout, stderr=subprocess.PIPE, env=env)
print(f"  exit code: {proc.returncode}")
if proc.stderr:
    print(f"  stderr: {proc.stderr.decode()[:500]}")

# Step 6: 读取结果
results = []
total_cost = 0.0
with open(output_path) as f:
    for line in f:
        if not line.strip():
            continue
        rec = json.loads(line)
        if "warnings" in rec and "results" not in rec:
            continue  # leading compat record
        results.append(rec)
        total_cost += rec.get("cost_usd", 0)

print(f"\n[5] LLM 抽取完成: {len(results)} 条结果")
print(f"  总成本: ${total_cost:.4f}")
print(f"  输出: {output_path}")

# 简单展示前 3 条
print(f"\n[6] 前 3 条结果预览:\n")
for i, r in enumerate(results[:3]):
    inp = r.get("input", {})
    res = r.get("results", [{}])[0].get("result", {})
    err = r.get("results", [{}])[0].get("error")
    print(f"--- [{i+1}] {inp.get('title', '?')[:80]} ---")
    if err:
        print(f"  错误: {err}")
    else:
        print(f"  卡点: {res.get('bottleneck', '?')}")
        print(f"  跨领域: {res.get('is_cross_domain')}")
        print(f"  物理深度: {res.get('physical_depth_signal', '?')[:100]}")
        print(f"  非显然: {res.get('non_obviousness')}/5 | 类别: {res.get('bottleneck_category')}")
        print(f"  证据: {res.get('evidence_quote', '?')[:120]}")
    print()
