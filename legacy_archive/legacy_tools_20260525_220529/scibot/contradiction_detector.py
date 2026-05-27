#!/usr/bin/env python3
"""
contradiction_detector.py - Sci-Bot V12.5 独有能力 #1
AI4Science 领域定制版跨论文矛盾检测

检测同一卡点主题下多篇论文间的三类矛盾：
  - numeric:   数值矛盾（同一任务/指标，不同数据）
  - mechanism: 机制矛盾（X 的成因，论文间相互否定）
  - boundary:  边界条件矛盾（同一方法在同条件下结论相反）

与 paper-qa 的差异化：
  - paper-qa 做通用矛盾检测（任何主题）
  - 本模块专注 AI4Science 卡点（优先 limitations/discussion sections）
  - 输出带 severity (low/mid/high) + paper_ids 的结构化列表

Usage:
    python -m scibot.contradiction_detector --theme T01
    python -m scibot.contradiction_detector --theme T12 --top-k 8
"""

import json
import logging
import os
import subprocess
import sys
from typing import Optional

sys.path.insert(0, '/home/user/workspace/echelon_mvp0a')

from scibot.scibot_query import query_for_theme, format_context_for_llm

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

FIRST_PRINCIPLES_FILE = '/home/user/workspace/echelon_mvp0a/scibot/first_principles_results.json'
SCIBOT_DIR = '/home/user/workspace/echelon_mvp0a/scibot'

# Theme ID -> query mapping (from first_principles_analysis.py)
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

THEME_TITLES = {
    "T01": "超构光学器件的微分优化与自动设计",
    "T02": "宽谱段多维光信息解耦与片上集成",
    "T03": "灵巧手高精度触觉反馈与空间感知",
    "T04": "具身智能中的物理一致性拓扑建模",
    "T05": "跨场景机器人运动控制的零样本泛化",
    "T06": "开放场景下的物体示能性与几何关联",
    "T07": "复杂极端环境下的视觉鲁棒感知",
    "T08": "视觉语言模型的物理常识与逻辑落地",
    "T09": "多模态大模型的高效表征与时序压缩",
    "T10": "3D视觉语言模型的统一表征与对齐",
    "T11": "增强型跨模态知识检索与推理偏差修正",
    "T12": "工业级精密物理系统的强化学习控制",
    "T13": "稀疏奖励下的强化学习采样效率优化",
    "T14": "多智能体协同的学习稳定性与安全性",
    "T15": "离线与跨域强化学习的分布漂移修正",
    "T16": "高维任务空间的强化学习算法架构优化",
    "T17": "具身智能实时的端侧部署与推理优化",
}

CONTRADICTION_SCHEMA = {
    "type": "object",
    "properties": {
        "contradictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["numeric", "mechanism", "boundary"]},
                    "severity": {"type": "string", "enum": ["low", "mid", "high"]},
                    "claim_a": {
                        "type": "object",
                        "properties": {
                            "paper_id": {"type": "string"},
                            "text": {"type": "string"}
                        },
                        "required": ["paper_id", "text"]
                    },
                    "claim_b": {
                        "type": "object",
                        "properties": {
                            "paper_id": {"type": "string"},
                            "text": {"type": "string"}
                        },
                        "required": ["paper_id", "text"]
                    },
                    "explanation": {"type": "string"}
                },
                "required": ["type", "severity", "claim_a", "claim_b", "explanation"]
            }
        },
        "summary": {"type": "string"},
        "total_chunks_analyzed": {"type": "integer"}
    },
    "required": ["contradictions", "summary", "total_chunks_analyzed"]
}

CONTRADICTION_INSTRUCTION = """你是 AI4Science 领域的跨论文矛盾分析专家。以下是多篇论文的 Limitations/Discussion 章节摘录，所有论文均来自同一研究主题。

请仔细对比论文间的论断，检测以下三类矛盾（**仅基于原文，不引入外部知识**）：

1. **numeric（数值矛盾）**：论文A报告了某指标/精度/性能 X%，论文B在同一任务/同一指标下报告了截然不同的数值 Y%，两者互相矛盾（须明确说明是同一指标）。

2. **mechanism（机制矛盾）**：论文A声称"现象P是因为机制M引起的"，论文B声称"现象P不是M引起的"或"M根本不是原因"，两者对因果链存在直接否定关系。

3. **boundary（边界条件矛盾）**：论文A在条件C下得出结论Z成立，论文B在相同或相似条件C下得出结论Z不成立。

**严重程度评估（severity）**：
- high：两篇核心论文对同一具体指标/机制直接对立，影响领域方向判断
- mid：两篇论文在方法有效性或条件上存在明显分歧，但可能源于不同实验设置
- low：论文间在边缘结论或次要指标上存在不一致，影响较小

**格式要求**：
- claim_a.paper_id 和 claim_b.paper_id 必须使用原文中方括号内的 paper_id
- claim_a.text 和 claim_b.text 引用论文原句（英文保留原文，50-100字）
- explanation 用中文解释矛盾的性质和可能原因（80-150字）
- 如果没有检测到任何矛盾，返回空 contradictions 列表并在 summary 中说明原因
- summary 用中文概括所有矛盾的整体模式（100-200字）"""


def run_llm_extract(input_data: dict, instruction: str, output_schema: dict,
                    max_tokens: int = 2000) -> dict | None:
    """Run pplx llm extract via subprocess."""
    input_json = json.dumps(input_data, ensure_ascii=False)
    schema_json = json.dumps(output_schema)

    cmd = [
        'pplx', 'llm', 'extract',
        '--instruction', instruction,
        '--output-schema', schema_json,
        '--max-tokens', str(max_tokens),
    ]

    try:
        result = subprocess.run(
            cmd,
            input=input_json,
            capture_output=True,
            text=True,
            timeout=120,
            env=os.environ.copy(),
        )

        if result.returncode != 0:
            logger.error(f"LLM extract failed: {result.stderr[:300]}")
            return None

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

        return None

    except subprocess.TimeoutExpired:
        logger.error("LLM extract timed out")
        return None
    except Exception as e:
        logger.error(f"LLM extract exception: {e}")
        return None


async def detect_contradictions(chunks: list[dict]) -> list[dict]:
    """
    AI4Science 定制版跨论文矛盾检测。

    Args:
        chunks: 来自 scibot_query 的 chunk 列表，每个 chunk 含
                {text, paper_id, paper_title, section_type, ...}

    Returns:
        contradiction list: [{
          "type": "numeric|mechanism|boundary",
          "severity": "low|mid|high",
          "claim_a": {"paper_id": "...", "text": "..."},
          "claim_b": {"paper_id": "...", "text": "..."},
          "explanation": "..."
        }]
    """
    if not chunks:
        return []

    # 去重：只保留每个 paper 的前2个 chunk
    paper_chunk_count: dict[str, int] = {}
    filtered_chunks = []
    for chunk in chunks:
        pid = chunk.get('paper_id', '')
        if paper_chunk_count.get(pid, 0) < 2:
            filtered_chunks.append(chunk)
            paper_chunk_count[pid] = paper_chunk_count.get(pid, 0) + 1

    # 最多使用 10 个 chunks
    filtered_chunks = filtered_chunks[:10]

    # 格式化为 LLM 输入
    context = format_context_for_llm(filtered_chunks, max_chars=3000)

    llm_input = {
        "chunks_count": len(filtered_chunks),
        "unique_papers": len(paper_chunk_count),
        "context": context,
    }

    result = run_llm_extract(llm_input, CONTRADICTION_INSTRUCTION, CONTRADICTION_SCHEMA,
                             max_tokens=8000)

    if result is None:
        return []

    return result.get('contradictions', [])


def detect_contradictions_for_theme(theme_id: str, top_k: int = 10) -> dict:
    """
    检测指定主题下的论文矛盾。

    Args:
        theme_id: 主题 ID（如 "T01"）
        top_k: 检索的 chunk 数

    Returns:
        {
            "theme_id": ...,
            "theme_title": ...,
            "contradictions": [...],
            "summary": ...,
            "chunks_analyzed": ...,
            "papers_involved": [...]
        }
    """
    if theme_id not in THEME_QUERIES:
        raise ValueError(f"Unknown theme_id: {theme_id}. Valid: {list(THEME_QUERIES.keys())}")

    query_text = THEME_QUERIES[theme_id]
    theme_title = THEME_TITLES[theme_id]

    logger.info(f"Detecting contradictions for {theme_id}: {theme_title}")

    # 1. 从 ChromaDB 检索相关 chunks（优先 limitations/discussion）
    chunks = query_for_theme(
        theme_title=query_text,
        paper_ids=[],
        top_k=top_k,
    )

    if not chunks:
        return {
            "theme_id": theme_id,
            "theme_title": theme_title,
            "contradictions": [],
            "summary": "RAG 检索无结果，无法检测矛盾。",
            "chunks_analyzed": 0,
            "papers_involved": [],
        }

    # 2. 跑 LLM 矛盾检测（同步路径）
    contradictions = _sync_detect(chunks)

    # 3. 收集涉及论文列表
    involved_papers = []
    seen = set()
    for chunk in chunks:
        pid = chunk['paper_id']
        if pid not in seen:
            involved_papers.append({
                "paper_id": pid,
                "paper_title": chunk['paper_title'],
                "section_type": chunk['section_type'],
            })
            seen.add(pid)

    # 4. 也运行同步路径获取 summary
    context = format_context_for_llm(chunks[:10], max_chars=3000)
    llm_input = {
        "chunks_count": len(chunks),
        "unique_papers": len(seen),
        "context": context,
    }
    full_result = run_llm_extract(llm_input, CONTRADICTION_INSTRUCTION, CONTRADICTION_SCHEMA,
                                  max_tokens=8000)

    if full_result:
        contradictions = full_result.get('contradictions', [])
        summary = full_result.get('summary', '')
    else:
        summary = "LLM 调用失败，矛盾检测结果不可用。"

    return {
        "theme_id": theme_id,
        "theme_title": theme_title,
        "contradictions": contradictions,
        "summary": summary,
        "chunks_analyzed": len(chunks),
        "papers_involved": involved_papers,
    }


def _sync_detect(chunks: list[dict]) -> list[dict]:
    """Synchronous wrapper for detect_contradictions."""
    context = format_context_for_llm(chunks[:10], max_chars=3000)
    paper_chunk_count: dict[str, int] = {}
    filtered_chunks = []
    for chunk in chunks:
        pid = chunk.get('paper_id', '')
        if paper_chunk_count.get(pid, 0) < 2:
            filtered_chunks.append(chunk)
            paper_chunk_count[pid] = paper_chunk_count.get(pid, 0) + 1

    llm_input = {
        "chunks_count": len(filtered_chunks),
        "unique_papers": len(paper_chunk_count),
        "context": context,
    }
    result = run_llm_extract(llm_input, CONTRADICTION_INSTRUCTION, CONTRADICTION_SCHEMA,
                             max_tokens=8000)
    if result:
        return result.get('contradictions', [])
    return []


def main():
    """CLI: python -m scibot.contradiction_detector --theme T01"""
    import argparse
    parser = argparse.ArgumentParser(description="Sci-Bot V12.5: 跨论文矛盾检测")
    parser.add_argument('--theme', required=True, help='主题 ID，如 T01, T12')
    parser.add_argument('--top-k', type=int, default=10, help='检索 chunk 数 (default: 10)')
    parser.add_argument('--output', help='输出 JSON 文件路径（可选）')
    args = parser.parse_args()

    print(f"\n=== Sci-Bot V12.5: 跨论文矛盾检测 ===")
    print(f"主题: {args.theme} | top_k={args.top_k}")
    print()

    result = detect_contradictions_for_theme(args.theme, top_k=args.top_k)

    print(f"主题标题: {result['theme_title']}")
    print(f"分析 chunks: {result['chunks_analyzed']}")
    print(f"涉及论文: {len(result['papers_involved'])} 篇")
    print(f"检测到矛盾: {len(result['contradictions'])} 条")
    print()

    if result['contradictions']:
        for i, c in enumerate(result['contradictions'], 1):
            print(f"[矛盾 {i}] type={c['type']} | severity={c['severity']}")
            print(f"  论文A ({c['claim_a']['paper_id']}): {c['claim_a']['text'][:120]}...")
            print(f"  论文B ({c['claim_b']['paper_id']}): {c['claim_b']['text'][:120]}...")
            print(f"  解释: {c['explanation'][:200]}")
            print()
    else:
        print("(未检测到明显矛盾)")

    print(f"综合摘要: {result['summary']}")

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {args.output}")

    return result


if __name__ == '__main__':
    main()
