#!/usr/bin/env python3
"""
principle_to_papers.py - Sci-Bot V12.5 独有能力 #3
元规律 → 论文反查：从数学本源找最严重的论文证据

V12 已有 4 元规律（MP1-MP4），本模块实现反向查询：
  给定一个元规律 ID（如 "MP1"），找出哪些具体论文最能体现这个数学本源，
  并按"本源严重度"排序输出。

与 paper-qa 的差异化：
  - paper-qa 只能回答用户问的问题
  - 本模块主动从元规律出发，系统性地挖掘论文证据
  - 这是 Echelon 独有的"元认知"层：不只知道论文说了什么，
    还知道它们共同揭示了哪个更深层的数学本源

Usage:
    python -m scibot.principle_to_papers --principle MP1
    python -m scibot.principle_to_papers --principle MP3 --top-n 5
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, '/home/user/workspace/echelon_mvp0a')

from scibot.scibot_query import query_for_theme, format_context_for_llm

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

META_PRINCIPLES_FILE = Path('/home/user/workspace/echelon_mvp0a/scibot/meta_principles.json')
FIRST_PRINCIPLES_FILE = Path('/home/user/workspace/echelon_mvp0a/scibot/first_principles_results.json')

# 元规律 ID 映射（MP1-MP4，按 meta_principles.json 顺序）
MP_ID_MAP = {
    "MP1": 0,  # 维度灾难与非凸地形搜索瓶颈
    "MP2": 1,  # 流形假设失真与表达能力上限瓶颈
    "MP3": 2,  # 互信息耗散与Shannon信道容量限制
    "MP4": 3,  # 非平稳动力学的收敛性与不确定性瓶颈
}

THEME_QUERIES = {
    "T01": "metasurface meta-optics differentiable optimization inverse design limitations computational cost",
    "T02": "broadband multidimensional photodetector metasurface polarization wavelength decoupling limitations",
    "T03": "dexterous hand tactile feedback high resolution grasp spatial perception limitations",
    "T04": "robot manipulation physical consistency topology kinematic constraint cable routing limitations",
    "T05": "robot locomotion control zero-shot generalization sim-to-real transfer domain gap limitations",
    "T06": "affordance detection open world object geometry spatial reasoning limitations failure",
    "T07": "visual perception robustness extreme environment noise adversarial domain shift limitations failure",
    "T08": "vision language model VLM physical grounding robot navigation material fragility limitations failure",
    "T09": "multimodal large model efficient representation temporal compression video understanding limitations",
    "T10": "3D vision language model unified representation alignment multimodal limitations failure",
    "T11": "cross-modal retrieval augmented generation knowledge bias correction multimodal limitations",
    "T12": "reinforcement learning precision physical systems tokamak limitations failure challenges",
    "T13": "sparse reward reinforcement learning sample efficiency exploration limitations challenge",
    "T14": "multi-agent reinforcement learning stability safety coordination convergence limitations failure",
    "T15": "offline reinforcement learning distribution shift out-of-distribution generalization limitations",
    "T16": "high dimensional action space reinforcement learning algorithm scalability limitations",
    "T17": "embodied AI real-time edge deployment inference optimization latency limitations",
}

SEVERITY_SCHEMA = {
    "type": "object",
    "properties": {
        "papers_ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string"},
                    "paper_title": {"type": "string"},
                    "severity_score": {
                        "type": "number",
                        "description": "0.0-1.0，1.0 表示该论文最严重地体现了这个元规律的限制"
                    },
                    "evidence": {
                        "type": "string",
                        "description": "从该论文中摘录最能体现元规律的原句或关键段落（英文保留原文），50-120字"
                    },
                    "how_principle_manifests": {
                        "type": "string",
                        "description": "用中文解释这个元规律在该论文中如何体现（80-150字）"
                    }
                },
                "required": ["paper_id", "paper_title", "severity_score", "evidence", "how_principle_manifests"]
            }
        },
        "principle_analysis": {
            "type": "string",
            "description": "对该元规律在所有涉及论文中普遍体现方式的综合分析（150-250字中文）"
        }
    },
    "required": ["papers_ranked", "principle_analysis"]
}


def _load_meta_principles() -> list[dict]:
    """加载元规律数据。"""
    with open(META_PRINCIPLES_FILE) as f:
        data = json.load(f)
    return data.get('meta_principles', [])


def _load_first_principles_results() -> list[dict]:
    """加载第一性原理分析结果。"""
    if not FIRST_PRINCIPLES_FILE.exists():
        return []
    with open(FIRST_PRINCIPLES_FILE) as f:
        return json.load(f)


def _run_llm_extract(input_data: dict, instruction: str, output_schema: dict,
                     max_tokens: int = 2000) -> dict | None:
    """Run pplx llm extract."""
    cmd = [
        'pplx', 'llm', 'extract',
        '--instruction', instruction,
        '--output-schema', json.dumps(output_schema),
        '--max-tokens', str(max_tokens),
    ]
    try:
        result = subprocess.run(
            cmd,
            input=json.dumps(input_data, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=120,
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            logger.error(f"LLM extract failed: {result.stderr[:200]}")
            return None
        for line in result.stdout.strip().split('\n'):
            try:
                obj = json.loads(line.strip())
                if 'results' in obj and obj['results']:
                    res = obj['results'][0]
                    if 'result' in res:
                        return res['result']
            except json.JSONDecodeError:
                continue
        return None
    except Exception as e:
        logger.error(f"LLM extract error: {e}")
        return None


async def query_principle_in_papers(principle_id: str, top_n: int = 5) -> dict:
    """
    元规律 → 论文反查主函数。

    Args:
        principle_id: 元规律 ID，如 "MP1"、"MP2"、"MP3"、"MP4"
        top_n: 返回最多论文数

    Returns:
        {
          "principle_id": "MP1",
          "principle": "维度灾难与非凸地形搜索瓶颈",
          "covered_themes": ["T01", "T02", ...],
          "papers_ranked_by_severity": [
            {"paper_id": "...", "severity": 0.92, "evidence": "..."},
            ...
          ],
          "principle_analysis": "...",
        }
    """
    return query_principle_in_papers_sync(principle_id, top_n)


def query_principle_in_papers_sync(principle_id: str, top_n: int = 5) -> dict:
    """同步版本的元规律→论文反查。"""
    if principle_id not in MP_ID_MAP:
        valid = list(MP_ID_MAP.keys())
        return {"error": f"Unknown principle_id: {principle_id}. Valid: {valid}"}

    # 1. 加载元规律数据
    meta_principles = _load_meta_principles()
    mp_index = MP_ID_MAP[principle_id]

    if mp_index >= len(meta_principles):
        return {"error": f"Meta principles data only has {len(meta_principles)} entries"}

    principle_data = meta_principles[mp_index]
    principle_name = principle_data.get('principle', f'MetaPrinciple {principle_id}')
    covered_themes = principle_data.get('covered_themes', [])
    principle_explanation = principle_data.get('explanation', '')

    logger.info(f"Querying {principle_id}: {principle_name}")
    logger.info(f"Covered themes: {covered_themes}")

    # 2. 对每个 theme，从 ChromaDB 拉相关 chunks（优先 limitations 节）
    all_chunks = []
    theme_paper_ids: dict[str, list[str]] = {}

    first_principles_results = _load_first_principles_results()
    fp_by_theme = {r['theme_id']: r for r in first_principles_results}

    for theme_id in covered_themes:
        query_text = THEME_QUERIES.get(theme_id, theme_id)
        chunks = query_for_theme(
            theme_title=query_text,
            paper_ids=[],
            top_k=6,
        )
        theme_paper_ids[theme_id] = list({c['paper_id'] for c in chunks})

        # 优先取 limitations/discussion 节的 chunks
        priority_chunks = [c for c in chunks
                           if c.get('section_type') in ('limitations', 'discussion', 'future_work')]
        all_chunks.extend(priority_chunks[:3])

    # 去重（同一 chunk 不重复）
    seen_keys = set()
    unique_chunks = []
    for chunk in all_chunks:
        key = chunk['paper_id'] + str(chunk.get('chunk_idx', ''))
        if key not in seen_keys:
            unique_chunks.append(chunk)
            seen_keys.add(key)

    # 3. 构建 LLM 上下文
    context = format_context_for_llm(unique_chunks[:12], max_chars=5500)

    # 包含 first_principles 结果中已有的分析
    theme_analyses = []
    for theme_id in covered_themes:
        fp = fp_by_theme.get(theme_id)
        if fp and fp.get('why_first_principle'):
            theme_analyses.append(
                f"[{theme_id}] {fp.get('theme_title', '')}:\n"
                f"  第一性原理分析: {fp['why_first_principle'][:300]}"
            )

    theme_analysis_text = '\n\n'.join(theme_analyses)

    instruction = f"""你是 AI4Science 第一性原理分析专家。

**元规律 {principle_id}**: {principle_name}

**元规律解释**: {principle_explanation}

**该元规律覆盖的主题**: {', '.join(covered_themes)}

以下是各主题论文的 Limitations/Discussion 摘录，以及已有的第一性原理分析。

**任务**: 从这些论文中，找出最能体现"{principle_name}"这一数学本源的论文，并按"本源严重度"排序。

**严重度定义**:
- 0.9-1.0: 论文的核心失败直接由该元规律的数学约束导致，且有明确原句支撑
- 0.7-0.89: 论文的主要瓶颈与该元规律高度相关，有间接证据
- 0.5-0.69: 论文涉及该元规律，但不是核心限制因素
- <0.5: 该元规律仅边缘相关

每篇论文：
1. paper_id 必须使用原文方括号中的 ID
2. evidence 引用论文原句（30-100字英文）
3. how_principle_manifests 中文解释（80-150字）
4. 最多输出 {top_n} 篇，仅输出确有证据支持的论文

**已有主题分析**:
{theme_analysis_text}"""

    llm_input = {
        "principle_id": principle_id,
        "principle_name": principle_name,
        "paper_chunks": context,
    }

    result = _run_llm_extract(llm_input, instruction, SEVERITY_SCHEMA, max_tokens=8000)

    papers_ranked = []
    principle_analysis = ""

    if result:
        raw_ranked = result.get('papers_ranked', [])
        # 整理格式：将 severity_score 映射到 severity
        for item in raw_ranked:
            papers_ranked.append({
                "paper_id": item.get('paper_id', ''),
                "paper_title": item.get('paper_title', ''),
                "severity": round(float(item.get('severity_score', 0.5)), 2),
                "evidence": item.get('evidence', ''),
                "how_principle_manifests": item.get('how_principle_manifests', ''),
            })
        principle_analysis = result.get('principle_analysis', '')
    else:
        # LLM 失败时，用 first_principles_results 做简单排序
        for theme_id in covered_themes:
            fp = fp_by_theme.get(theme_id)
            if fp:
                source_papers = fp.get('source_papers', [])
                for sp in source_papers[:2]:
                    papers_ranked.append({
                        "paper_id": sp['paper_id'],
                        "paper_title": sp['paper_title'],
                        "severity": round(0.5 + (1.0 - sp['distance']) * 0.5, 2),
                        "evidence": f"From {fp['theme_title']} analysis",
                        "how_principle_manifests": fp.get('why_first_principle', '')[:200],
                    })
        principle_analysis = f"LLM 调用失败，使用第一性原理结果直接填充。{principle_explanation[:200]}"

    # 去重并排序
    seen_ids = set()
    deduped = []
    for p in papers_ranked:
        if p['paper_id'] not in seen_ids:
            deduped.append(p)
            seen_ids.add(p['paper_id'])
    deduped.sort(key=lambda x: -x['severity'])

    return {
        "principle_id": principle_id,
        "principle": principle_name,
        "principle_explanation": principle_explanation,
        "covered_themes": covered_themes,
        "is_solvable_in_3_years": principle_data.get('is_solvable_in_3_years', None),
        "solvability_reason": principle_data.get('solvability_reason', ''),
        "papers_ranked_by_severity": deduped[:top_n],
        "principle_analysis": principle_analysis,
        "total_chunks_analyzed": len(unique_chunks),
    }


def main():
    """CLI: python -m scibot.principle_to_papers --principle MP1"""
    import argparse
    parser = argparse.ArgumentParser(description="Sci-Bot V12.5: 元规律→论文反查")
    parser.add_argument('--principle', required=True, help='元规律 ID: MP1, MP2, MP3, MP4')
    parser.add_argument('--top-n', type=int, default=5, help='返回最多论文数 (default: 5)')
    parser.add_argument('--output', help='输出 JSON 文件路径（可选）')
    args = parser.parse_args()

    print(f"\n=== Sci-Bot V12.5: 元规律 → 论文反查 ===")
    print(f"元规律: {args.principle} | top_n={args.top_n}")
    print()

    result = query_principle_in_papers_sync(args.principle, top_n=args.top_n)

    if 'error' in result:
        print(f"错误: {result['error']}")
        return

    print(f"元规律 {result['principle_id']}: {result['principle']}")
    print(f"覆盖主题: {', '.join(result['covered_themes'])}")
    print(f"3年内可解决: {result.get('is_solvable_in_3_years')}")
    print(f"分析 chunks 数: {result['total_chunks_analyzed']}")
    print()

    print("按本源严重度排序的论文:")
    for i, paper in enumerate(result['papers_ranked_by_severity'], 1):
        print(f"  [{i}] 严重度={paper['severity']:.2f} | {paper['paper_title'][:60]}")
        print(f"      paper_id: {paper['paper_id']}")
        print(f"      证据: {paper['evidence'][:120]}...")
        print(f"      体现方式: {paper['how_principle_manifests'][:150]}...")
        print()

    print(f"综合分析: {result['principle_analysis'][:300]}...")

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {args.output}")

    return result


if __name__ == '__main__':
    main()
