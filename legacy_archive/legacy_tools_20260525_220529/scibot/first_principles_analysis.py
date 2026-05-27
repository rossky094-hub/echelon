#!/usr/bin/env python3
"""
first_principles_analysis.py - Step 5: 17-theme first-principles deep dive
Uses RAG + pplx llm extract to produce structured 5-part analyses.
"""

import json
import os
import re
import subprocess
import sys
import logging
from pathlib import Path

# Add parent dir to path for scibot imports
sys.path.insert(0, '/home/user/workspace/echelon_mvp0a')

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

from scibot.scibot_query import query_for_theme, format_context_for_llm

REPORTS_DIR = '/home/user/workspace/echelon_mvp0a/reports'
SCIBOT_DIR = '/home/user/workspace/echelon_mvp0a/scibot'
OUTPUT_FILE = os.path.join(SCIBOT_DIR, 'first_principles_results.json')

# 17 themes from V11.5+ report with paper IDs from seeds
THEMES = [
    {
        "theme_id": "T12",
        "theme_title": "工业级精密物理系统的强化学习控制",
        "query": "reinforcement learning precision physical systems tokamak limitations failure challenges",
    },
    {
        "theme_id": "T01",
        "theme_title": "超构光学器件的微分优化与自动设计",
        "query": "metasurface meta-optics differentiable optimization inverse design limitations computational cost",
    },
    {
        "theme_id": "T02",
        "theme_title": "宽谱段多维光信息解耦与片上集成",
        "query": "broadband multidimensional photodetector metasurface polarization wavelength decoupling limitations",
    },
    {
        "theme_id": "T04",
        "theme_title": "具身智能中的物理一致性拓扑建模",
        "query": "robot manipulation physical consistency topology kinematic constraint cable routing limitations",
    },
    {
        "theme_id": "T08",
        "theme_title": "视觉语言模型的物理常识与逻辑落地",
        "query": "vision language model VLM physical grounding robot navigation material fragility limitations failure",
    },
    {
        "theme_id": "T03",
        "theme_title": "灵巧手高精度触觉反馈与空间感知",
        "query": "dexterous hand tactile feedback high resolution grasp spatial perception limitations",
    },
    {
        "theme_id": "T05",
        "theme_title": "跨场景机器人运动控制的零样本泛化",
        "query": "robot locomotion control zero-shot generalization sim-to-real transfer domain gap limitations",
    },
    {
        "theme_id": "T07",
        "theme_title": "复杂极端环境下的视觉鲁棒感知",
        "query": "visual perception robustness extreme environment noise adversarial domain shift limitations failure",
    },
    {
        "theme_id": "T14",
        "theme_title": "多智能体协同的学习稳定性与安全性",
        "query": "multi-agent reinforcement learning stability safety coordination convergence limitations failure",
    },
    {
        "theme_id": "T15",
        "theme_title": "离线与跨域强化学习的分布漂移修正",
        "query": "offline reinforcement learning distribution shift out-of-distribution generalization limitations",
    },
    {
        "theme_id": "T10",
        "theme_title": "3D视觉语言模型的统一表征与对齐",
        "query": "3D vision language model unified representation alignment multimodal limitations failure",
    },
    {
        "theme_id": "T13",
        "theme_title": "稀疏奖励下的强化学习采样效率优化",
        "query": "sparse reward reinforcement learning sample efficiency exploration limitations challenge",
    },
    {
        "theme_id": "T16",
        "theme_title": "高维任务空间的强化学习算法架构优化",
        "query": "high dimensional action space reinforcement learning algorithm scalability limitations",
    },
    {
        "theme_id": "T06",
        "theme_title": "开放场景下的物体示能性与几何关联",
        "query": "affordance detection open world object geometry spatial reasoning limitations failure",
    },
    {
        "theme_id": "T17",
        "theme_title": "具身智能实时的端侧部署与推理优化",
        "query": "embodied AI real-time edge deployment inference optimization latency limitations",
    },
    {
        "theme_id": "T09",
        "theme_title": "多模态大模型的高效表征与时序压缩",
        "query": "multimodal large model efficient representation temporal compression video understanding limitations",
    },
    {
        "theme_id": "T11",
        "theme_title": "增强型跨模态知识检索与推理偏差修正",
        "query": "cross-modal retrieval augmented generation knowledge bias correction multimodal limitations",
    },
]


FIRST_PRINCIPLES_INSTRUCTION = """你是 AI4Science 资深学者。以下是来自多篇论文的 Limitations / Discussion / Conclusion 章节摘录，关于卡点主题。

请依据**仅限以下原文片段**进行分析，不能引入论文外知识。完成 5 项追问并输出 JSON。

1. **what_phenomenon (现象层)**：论文具体说了什么卡点？用 1-2 句话概括（中文，引用 paper_id）。

2. **how_mechanism (机制层)**：论文给出的失败/受限机制是什么？必须从论文 Discussion/Limitations 中找原句佐证，说明物理或算法层面的因果链。

3. **why_first_principle (第一性原理)**：这个失败机制的数学/物理/信息论本源是什么？必须指名道姓说出哪个本源（从以下选一个或多个）：
   - 数学：Lipschitz 连续性、收敛性、唯一性、可微性、维度灾难、表达能力上限
   - 物理：能量守恒、热力学第二定律、不确定性原理、因果性、衍射极限
   - 信息论：Shannon 信道容量、互信息、压缩率、Kolmogorov 复杂度
   - 几何：流形假设、内蕴维度、曲率
   - 优化：鞍点、非凸地形、梯度消失/爆炸、模式坍塌
   不能笼统说"复杂度高"。

4. **where_cross_domain (跨领域桥点)**：这个第一性原理在哪些领域有相通对偶？提供 2-3 个跨学科对偶，标明哪些是论文真讨论过、哪些是你基于本源推断。

5. **predict_falsifiable (可证伪预测)**：基于这个第一性原理，未来 3-5 年内能否被解决？给出可证伪的预测：如果 X 技术成熟到 Y 程度，卡点 Z 应能突破。提供阻断条件：什么会让突破失败？

每项 100-200 字中文。"""


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "what_phenomenon": {"type": "string"},
        "how_mechanism": {"type": "string"},
        "why_first_principle": {"type": "string"},
        "where_cross_domain": {"type": "string"},
        "predict_falsifiable": {"type": "string"},
    },
    "required": ["what_phenomenon", "how_mechanism", "why_first_principle", "where_cross_domain", "predict_falsifiable"]
}


def run_llm_extract(input_data: dict, instruction: str, output_schema: dict, max_tokens: int = 3000) -> dict | None:
    """Run pplx llm extract via subprocess."""
    input_json = json.dumps(input_data, ensure_ascii=False)
    schema_json = json.dumps(output_schema)

    cmd = [
        'pplx', 'llm', 'extract',
        '--instruction', instruction,
        '--output-schema', schema_json,
        '--max-tokens', str(max_tokens),
    ]

    env = os.environ.copy()

    try:
        result = subprocess.run(
            cmd,
            input=input_json,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )

        if result.returncode != 0:
            logger.error(f"LLM extract failed: {result.stderr[:500]}")
            return None

        # Parse output (JSONL)
        lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
        for line in lines:
            try:
                obj = json.loads(line)
                if 'results' in obj and obj['results']:
                    res = obj['results'][0]
                    if 'result' in res:
                        return res['result']
                    elif 'error' in res:
                        logger.error(f"LLM result error: {res['error']}")
            except json.JSONDecodeError:
                continue

        logger.error(f"Could not parse LLM output: {result.stdout[:200]}")
        return None

    except subprocess.TimeoutExpired:
        logger.error("LLM extract timed out")
        return None
    except Exception as e:
        logger.error(f"LLM extract exception: {e}")
        return None


def analyze_theme(theme: dict) -> dict:
    """Analyze a single theme with RAG + LLM."""
    theme_id = theme['theme_id']
    theme_title = theme['theme_title']
    query_text = theme['query']

    logger.info(f"\nAnalyzing {theme_id}: {theme_title}")

    # RAG retrieval
    chunks = query_for_theme(
        theme_title=query_text,
        paper_ids=[],  # search globally
        top_k=10,
    )

    logger.info(f"  Retrieved {len(chunks)} chunks")
    for c in chunks[:3]:
        logger.info(f"    - {c['paper_title'][:50]} | {c['section_type']} | dist={c['distance']:.3f}")

    if not chunks:
        logger.warning(f"  No chunks found for {theme_id}, using abstract fallback")
        # Fallback: use abstract from seeds
        return {
            "theme_id": theme_id,
            "theme_title": theme_title,
            "chunks_used": 0,
            "what_phenomenon": "RAG检索无结果，无法从论文原文分析。",
            "how_mechanism": "无论文原文支持。",
            "why_first_principle": "无论文原文支持。",
            "where_cross_domain": "无论文原文支持。",
            "predict_falsifiable": "无论文原文支持。",
            "source_papers": [],
        }

    # Format context
    context = format_context_for_llm(chunks, max_chars=6000)

    # Build input for LLM
    llm_input = {
        "theme_title": theme_title,
        "context": context,
    }

    # Build instruction with theme
    full_instruction = f'卡点主题："{theme_title}"\n\n以下是论文摘录：\n\n' + FIRST_PRINCIPLES_INSTRUCTION

    # Run LLM
    logger.info(f"  Running LLM extract...")
    result = run_llm_extract(llm_input, full_instruction, OUTPUT_SCHEMA, max_tokens=3000)

    if result is None:
        logger.error(f"  LLM failed for {theme_id}")
        result = {
            "what_phenomenon": "LLM调用失败。",
            "how_mechanism": "LLM调用失败。",
            "why_first_principle": "LLM调用失败。",
            "where_cross_domain": "LLM调用失败。",
            "predict_falsifiable": "LLM调用失败。",
        }

    # Collect source paper info
    source_papers = []
    seen_papers = set()
    for c in chunks:
        if c['paper_id'] not in seen_papers:
            source_papers.append({
                'paper_id': c['paper_id'],
                'paper_title': c['paper_title'],
                'section_type': c['section_type'],
                'distance': c['distance'],
            })
            seen_papers.add(c['paper_id'])

    return {
        "theme_id": theme_id,
        "theme_title": theme_title,
        "chunks_used": len(chunks),
        "source_papers": source_papers,
        **result,
    }


def run_all_themes():
    """Analyze all 17 themes."""
    results = []

    # Load existing results if any
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)
        done_ids = {r['theme_id'] for r in existing}
        results = existing
        logger.info(f"Loaded {len(results)} existing results, resuming...")
    else:
        done_ids = set()

    for theme in THEMES:
        if theme['theme_id'] in done_ids:
            logger.info(f"SKIP {theme['theme_id']} (already done)")
            continue

        result = analyze_theme(theme)
        results.append(result)
        done_ids.add(theme['theme_id'])

        # Save after each theme
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"  Saved progress: {len(results)}/17")

    logger.info(f"\n=== ANALYSIS COMPLETE ===")
    logger.info(f"Analyzed: {len(results)}/17 themes")
    success_count = sum(1 for r in results if r.get('what_phenomenon') and 'LLM调用失败' not in r['what_phenomenon'])
    logger.info(f"LLM success: {success_count}/{len(results)}")

    return results


if __name__ == '__main__':
    run_all_themes()


# ─────────────────────────────────────────────
# V13 Importable interface (不破坏 __main__)
# ─────────────────────────────────────────────

def analyze_themes(
    themes: list,
    output_file: str = None,
    max_themes: int = 17,
) -> list:
    """
    V13 pilot interface: analyze a list of themes using RAG + LLM.

    Args:
        themes:      list of dicts with 'theme_id', 'theme_title', 'query', 'paper_ids'
        output_file: optional path to save results JSON
        max_themes:  maximum number of themes to analyze

    Returns:
        list of analysis result dicts
    """
    if output_file is None:
        output_file = OUTPUT_FILE

    results = []
    if os.path.exists(output_file):
        with open(output_file) as f:
            results = json.load(f)
    done_ids = {r["theme_id"] for r in results}

    themes_to_run = []
    for t in themes[:max_themes]:
        # Normalize theme format
        theme_id = t.get("theme_id", t.get("id", ""))
        theme_title = t.get("theme_title", t.get("title", t.get("name", "")))
        query = t.get("query", theme_title + " limitations failure challenges")
        themes_to_run.append({
            "theme_id": theme_id,
            "theme_title": theme_title,
            "query": query,
        })

    for theme in themes_to_run:
        if theme["theme_id"] in done_ids:
            logger.info(f"SKIP {theme['theme_id']} (already done)")
            continue

        try:
            result = analyze_theme(theme)
            results.append(result)
            done_ids.add(theme["theme_id"])
            with open(output_file, "w") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to analyze {theme['theme_id']}: {e}")
            results.append({
                "theme_id": theme["theme_id"],
                "theme_title": theme.get("theme_title", ""),
                "chunks_used": 0,
                "what_phenomenon": f"分析失败: {str(e)[:100]}",
                "how_mechanism": "N/A",
                "why_first_principle": "N/A",
                "where_cross_domain": "N/A",
                "predict_falsifiable": "N/A",
                "source_papers": [],
            })

    logger.info(f"[analyze_themes] Done: {len(results)}/{len(themes_to_run)}")
    return results


def analyze_single_theme(
    theme_id: str,
    theme_title: str,
    query: str = None,
    paper_ids: list = None,
) -> dict:
    """
    V13 pilot interface: analyze a single theme.

    Returns analysis result dict with 5-part first-principles breakdown.
    """
    theme = {
        "theme_id": theme_id,
        "theme_title": theme_title,
        "query": query or (theme_title + " limitations failure challenges"),
    }
    return analyze_theme(theme)
