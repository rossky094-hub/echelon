#!/usr/bin/env python3
"""
incremental_analysis.py - Sci-Bot V12.5 独有能力 #4
新论文增量分析：将新 arXiv 论文与 V12 知识体系连接

当用户读到一篇新 arXiv 论文，本模块自动：
  1. 解析 PDF（若有 arXiv URL，自动下载）
  2. 抽取 abstract + limitations + methods 摘要
  3. 与 V12 17 主题做语义匹配（top-3 相似主题）
  4. 与 4 元规律做匹配（识别最相关的 MP）
  5. 调 LLM 5 项追问深挖（沿用 first_principles 范式）
  6. 输出：主题对齐、元规律映射、5项追问、与知识体系的关系

与 paper-qa 的差异化：
  - paper-qa 只能对已索引论文做 QA
  - 本模块处理全新、未知的论文，将其接入 V12 知识图谱
  - 输出结构化的"知识增量"报告，不只是 QA 答案

Usage:
    python -m scibot.incremental_analysis --arxiv https://arxiv.org/abs/2401.xxxxx
    python -m scibot.incremental_analysis --pdf /path/to/paper.pdf
"""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

sys.path.insert(0, '/home/user/workspace/echelon_mvp0a')

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SCIBOT_DIR = Path('/home/user/workspace/echelon_mvp0a/scibot')
FIRST_PRINCIPLES_FILE = SCIBOT_DIR / 'first_principles_results.json'
META_PRINCIPLES_FILE = SCIBOT_DIR / 'meta_principles.json'

# 17 主题
THEMES = [
    {"theme_id": "T01", "theme_title": "超构光学器件的微分优化与自动设计",
     "keywords": "metasurface meta-optics differentiable optimization inverse design"},
    {"theme_id": "T02", "theme_title": "宽谱段多维光信息解耦与片上集成",
     "keywords": "broadband multidimensional photodetector polarization wavelength decoupling"},
    {"theme_id": "T03", "theme_title": "灵巧手高精度触觉反馈与空间感知",
     "keywords": "dexterous hand tactile feedback grasp spatial perception"},
    {"theme_id": "T04", "theme_title": "具身智能中的物理一致性拓扑建模",
     "keywords": "robot manipulation physical consistency topology kinematic constraint"},
    {"theme_id": "T05", "theme_title": "跨场景机器人运动控制的零样本泛化",
     "keywords": "robot locomotion zero-shot generalization sim-to-real transfer domain gap"},
    {"theme_id": "T06", "theme_title": "开放场景下的物体示能性与几何关联",
     "keywords": "affordance detection open world object geometry spatial reasoning"},
    {"theme_id": "T07", "theme_title": "复杂极端环境下的视觉鲁棒感知",
     "keywords": "visual perception robustness extreme environment noise adversarial"},
    {"theme_id": "T08", "theme_title": "视觉语言模型的物理常识与逻辑落地",
     "keywords": "vision language model VLM physical grounding robot navigation"},
    {"theme_id": "T09", "theme_title": "多模态大模型的高效表征与时序压缩",
     "keywords": "multimodal large model efficient representation temporal compression video"},
    {"theme_id": "T10", "theme_title": "3D视觉语言模型的统一表征与对齐",
     "keywords": "3D vision language model unified representation alignment multimodal"},
    {"theme_id": "T11", "theme_title": "增强型跨模态知识检索与推理偏差修正",
     "keywords": "cross-modal retrieval augmented generation knowledge bias correction"},
    {"theme_id": "T12", "theme_title": "工业级精密物理系统的强化学习控制",
     "keywords": "reinforcement learning precision physical systems tokamak control"},
    {"theme_id": "T13", "theme_title": "稀疏奖励下的强化学习采样效率优化",
     "keywords": "sparse reward reinforcement learning sample efficiency exploration"},
    {"theme_id": "T14", "theme_title": "多智能体协同的学习稳定性与安全性",
     "keywords": "multi-agent reinforcement learning stability safety coordination convergence"},
    {"theme_id": "T15", "theme_title": "离线与跨域强化学习的分布漂移修正",
     "keywords": "offline reinforcement learning distribution shift out-of-distribution"},
    {"theme_id": "T16", "theme_title": "高维任务空间的强化学习算法架构优化",
     "keywords": "high dimensional action space reinforcement learning algorithm scalability"},
    {"theme_id": "T17", "theme_title": "具身智能实时的端侧部署与推理优化",
     "keywords": "embodied AI real-time edge deployment inference optimization latency"},
]

META_PRINCIPLES = [
    {"id": "MP1", "principle": "维度灾难与非凸地形搜索瓶颈",
     "keywords": "high dimensional curse dimensionality non-convex optimization search space"},
    {"id": "MP2", "principle": "流形假设失真与表达能力上限瓶颈",
     "keywords": "manifold hypothesis representation capacity topology expressiveness"},
    {"id": "MP3", "principle": "互信息耗散与Shannon信道容量限制",
     "keywords": "mutual information Shannon channel capacity information loss compression"},
    {"id": "MP4", "principle": "非平稳动力学的收敛性与不确定性瓶颈",
     "keywords": "non-stationary dynamics convergence uncertainty temporal difference RL"},
]

INCREMENTAL_SCHEMA = {
    "type": "object",
    "properties": {
        "paper_summary": {"type": "string", "description": "100-200字中文摘要，聚焦核心方法和主张"},
        "top_theme_id": {"type": "string", "description": "最贴近的主题 ID (T01-T17)"},
        "top_theme_title": {"type": "string"},
        "theme_alignment_score": {"type": "number", "description": "0-1，语义对齐程度"},
        "theme_alignment_reason": {"type": "string", "description": "100字中文，为什么匹配这个主题"},
        "top_mp_id": {"type": "string", "description": "最相关的元规律 ID (MP1-MP4)"},
        "top_mp_name": {"type": "string"},
        "mp_severity": {"type": "number", "description": "0-1，元规律在此论文中的严重程度"},
        "mp_evidence": {"type": "string", "description": "论文中体现该元规律的原句（英文，30-100字）"},
        "what_phenomenon": {"type": "string", "description": "现象层：论文具体卡点（100-200字中文）"},
        "how_mechanism": {"type": "string", "description": "机制层：失败机制因果链（100-200字中文）"},
        "why_first_principle": {"type": "string", "description": "第一性原理：数学/物理/信息论本源（100-200字中文）"},
        "where_cross_domain": {"type": "string", "description": "跨领域桥点（100-200字中文）"},
        "predict_falsifiable": {"type": "string", "description": "可证伪预测（100-200字中文）"},
        "knowledge_relation": {
            "type": "string",
            "enum": ["reinforces", "counterexample", "new_direction", "unclear"],
            "description": "与现有 V12 知识体系的关系"
        },
        "knowledge_relation_detail": {"type": "string", "description": "150字中文，解释与现有知识体系的关系"}
    },
    "required": [
        "paper_summary", "top_theme_id", "top_theme_title", "theme_alignment_score",
        "theme_alignment_reason", "top_mp_id", "top_mp_name", "mp_severity", "mp_evidence",
        "what_phenomenon", "how_mechanism", "why_first_principle", "where_cross_domain",
        "predict_falsifiable", "knowledge_relation", "knowledge_relation_detail"
    ]
}


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
            timeout=150,
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


def _download_arxiv_pdf(arxiv_url: str, dest_dir: str) -> Optional[str]:
    """
    从 arXiv URL 下载 PDF。
    支持格式：
      - https://arxiv.org/abs/XXXX.XXXXX
      - https://arxiv.org/pdf/XXXX.XXXXX
    """
    # 提取 arxiv ID
    match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)', arxiv_url)
    if not match:
        logger.error(f"Cannot extract arXiv ID from URL: {arxiv_url}")
        return None

    arxiv_id = match.group(1)
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    dest_path = os.path.join(dest_dir, f"{arxiv_id}.pdf")

    logger.info(f"Downloading {pdf_url} -> {dest_path}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; Sci-Bot/1.0)'}
        req = urllib.request.Request(pdf_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read()
        with open(dest_path, 'wb') as f:
            f.write(content)
        logger.info(f"Downloaded {len(content)} bytes")
        return dest_path
    except Exception as e:
        logger.error(f"Download failed: {e}")
        return None


def _parse_pdf_simple(pdf_path: str) -> dict:
    """
    简单 PDF 解析：提取 abstract + limitations + methods 区域。
    使用 pdfminer/pymupdf 如果可用，否则回退到 subprocess pdftotext。
    """
    text = ""

    # 方法1: pymupdf (fitz)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        for page in doc[:20]:  # 最多读 20 页
            text += page.get_text()
        doc.close()
    except ImportError:
        pass

    # 方法2: pdftotext (CLI)
    if not text:
        try:
            result = subprocess.run(
                ['pdftotext', pdf_path, '-'],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                text = result.stdout
        except Exception:
            pass

    if not text:
        return {"error": f"Cannot parse PDF: {pdf_path}", "raw_text": ""}

    # 提取各节
    sections = {}

    # Abstract
    abs_match = re.search(
        r'(?:Abstract|ABSTRACT)\s*\n(.+?)(?:\n\s*(?:1\.|Introduction|INTRODUCTION))',
        text, re.DOTALL
    )
    if abs_match:
        sections['abstract'] = abs_match.group(1).strip()[:1500]
    else:
        # 取前 500 字作为 abstract 替代
        sections['abstract'] = text[:500].strip()

    # Limitations
    lim_match = re.search(
        r'(?:Limitations?|LIMITATIONS?|Future Work|Conclusion)[^\n]*\n(.+?)(?:\n\s*(?:\d+\.|References|REFERENCES|Acknowledgments?))',
        text, re.DOTALL | re.IGNORECASE
    )
    if lim_match:
        sections['limitations'] = lim_match.group(1).strip()[:2000]
    else:
        # 正则查找限制句
        limitation_sentences = re.findall(
            r'[^.]*(?:limitation|cannot|unable|fail|challenge|drawback|constraint|future work)[^.]{20,200}\.',
            text, re.IGNORECASE
        )
        sections['limitations'] = ' '.join(limitation_sentences[:10])[:2000]

    # Methods / Approach
    method_match = re.search(
        r'(?:Method(?:ology)?|Approach|Framework|Model)[^\n]*\n(.+?)(?:\n\s*(?:\d+\.|Results?|Experiment))',
        text, re.DOTALL | re.IGNORECASE
    )
    if method_match:
        sections['methods'] = method_match.group(1).strip()[:1500]

    return {
        "raw_text": text[:8000],  # 前 8000 字
        "sections": sections,
        "page_count": text.count('\x0c') + 1,
    }


def _semantic_match_themes(paper_text: str) -> list[dict]:
    """
    将论文文本与 17 主题做简单词级语义匹配。
    Returns: sorted list of {theme_id, theme_title, score}
    """
    paper_words = set(re.findall(r'\b[a-z]{3,}\b', paper_text.lower()))

    scores = []
    for theme in THEMES:
        theme_words = set(re.findall(r'\b[a-z]{3,}\b', theme['keywords'].lower()))
        if not theme_words:
            continue
        intersection = paper_words & theme_words
        score = len(intersection) / len(theme_words)
        scores.append({
            'theme_id': theme['theme_id'],
            'theme_title': theme['theme_title'],
            'score': round(score, 3),
            'matched_keywords': list(intersection)[:8],
        })

    scores.sort(key=lambda x: -x['score'])
    return scores[:3]


def _semantic_match_principles(paper_text: str) -> list[dict]:
    """将论文文本与 4 元规律做简单词级匹配。"""
    paper_words = set(re.findall(r'\b[a-z]{3,}\b', paper_text.lower()))

    scores = []
    for mp in META_PRINCIPLES:
        mp_words = set(re.findall(r'\b[a-z]{3,}\b', mp['keywords'].lower()))
        if not mp_words:
            continue
        intersection = paper_words & mp_words
        score = len(intersection) / len(mp_words)
        scores.append({
            'mp_id': mp['id'],
            'mp_name': mp['principle'],
            'score': round(score, 3),
        })

    scores.sort(key=lambda x: -x['score'])
    return scores


def _load_v12_knowledge_summary() -> str:
    """加载 V12 知识体系摘要，供 LLM 判断关系用。"""
    try:
        with open(FIRST_PRINCIPLES_FILE) as f:
            results = json.load(f)
        summaries = []
        for r in results[:5]:  # 取前5个主题的 why_first_principle
            summaries.append(
                f"[{r['theme_id']}] {r['theme_title']}: {r.get('why_first_principle', '')[:200]}"
            )
        return '\n'.join(summaries)
    except Exception:
        return "V12 知识体系数据暂不可用"


async def analyze_new_paper(arxiv_url_or_pdf: str) -> dict:
    """整合 5 项追问 + 主题匹配 + 元规律映射（async 接口）。"""
    return analyze_new_paper_sync(arxiv_url_or_pdf)


def analyze_new_paper_sync(arxiv_url_or_pdf: str) -> dict:
    """
    新论文增量分析主函数。

    Args:
        arxiv_url_or_pdf: arXiv URL (https://arxiv.org/abs/XXXX.XXXXX)
                          或本地 PDF 路径

    Returns:
        {
          "source": ...,
          "paper_summary": ...,
          "top_theme": {theme_id, theme_title, score, reason},
          "top_3_themes": [...],
          "top_mp": {mp_id, name, severity, evidence},
          "five_questions": {what, how, why, where, predict},
          "knowledge_relation": "reinforces|counterexample|new_direction|unclear",
          "knowledge_relation_detail": ...,
        }
    """
    source = arxiv_url_or_pdf
    pdf_path = None
    tmp_dir = None

    # 1. 获取 PDF
    if arxiv_url_or_pdf.startswith('http'):
        tmp_dir = tempfile.mkdtemp()
        pdf_path = _download_arxiv_pdf(arxiv_url_or_pdf, tmp_dir)
        if not pdf_path:
            return {
                "error": f"无法下载 arXiv PDF: {arxiv_url_or_pdf}",
                "source": source,
            }
    else:
        pdf_path = arxiv_url_or_pdf
        if not os.path.exists(pdf_path):
            return {
                "error": f"PDF 文件不存在: {pdf_path}",
                "source": source,
            }

    # 2. 解析 PDF
    logger.info(f"Parsing PDF: {pdf_path}")
    parsed = _parse_pdf_simple(pdf_path)
    if 'error' in parsed:
        return {"error": parsed['error'], "source": source}

    sections = parsed.get('sections', {})
    abstract = sections.get('abstract', '')
    limitations = sections.get('limitations', '')
    methods = sections.get('methods', '')
    raw_text = parsed.get('raw_text', '')

    # 用于匹配的文本
    match_text = f"{abstract} {limitations} {methods}"

    # 3. 语义匹配 17 主题（词级快速匹配）
    top_3_themes = _semantic_match_themes(match_text)
    top_mp_list = _semantic_match_principles(match_text)

    # 4. 调 LLM 做完整分析（5 项追问 + 匹配校正）
    v12_knowledge = _load_v12_knowledge_summary()

    themes_text = '\n'.join([
        f"  - {t['theme_id']}: {t['theme_title']} (词级匹配分: {t['score']:.2f}, 关键词: {t['matched_keywords'][:5]})"
        for t in top_3_themes
    ])

    mp_text = '\n'.join([
        f"  - {m['mp_id']}: {m['mp_name']} (词级匹配分: {m['score']:.2f})"
        for m in top_mp_list[:4]
    ])

    instruction = f"""你是 AI4Science 第一性原理分析专家（Sci-Bot V12.5）。

以下是一篇新论文的内容，请完成完整的增量分析报告。

**V12 已有 17 主题**（基于词级匹配的候选，可以更换为更准确的主题）:
{themes_text}

**V12 已有 4 元规律**（词级匹配候选）:
{mp_text}

**V12 现有知识体系摘要**（用于判断新论文与现有知识的关系）:
{v12_knowledge}

**分析任务**：
1. 用 100-200 字概括论文核心（paper_summary）
2. 选最贴近的 V12 主题（top_theme_id），给出对齐分和理由
3. 选最相关的元规律（top_mp_id），给出严重度分数和论文原句证据
4. 完成 5 项追问（what/how/why/where/predict，各 100-200 字中文）
5. 判断新论文与 V12 现有知识的关系：
   - reinforces: 强化现有某个主题/元规律的结论
   - counterexample: 提供了反例，挑战现有某个结论
   - new_direction: 开辟了现有 17 主题未覆盖的新方向
   - unclear: 关系不明确

**第一性原理追问框架（why_first_principle）要求**：
必须从以下本源中指名道姓选一个：
维度灾难、非凸地形、收敛性、流形假设、表达能力上限、Shannon信道容量、互信息耗散、Kolmogorov复杂度、能量守恒、衍射极限、不确定性原理、梯度消失/爆炸

paper_id 字段请填写 "NEW_PAPER"（新论文尚未在数据库中）。"""

    llm_input = {
        "abstract": abstract[:1000],
        "limitations": limitations[:1500],
        "methods": methods[:800],
        "raw_text_tail": raw_text[-1000:],  # 论文尾部通常含 conclusions
    }

    result = _run_llm_extract(llm_input, instruction, INCREMENTAL_SCHEMA, max_tokens=8000)

    if result:
        return {
            "source": source,
            "pdf_path": pdf_path,
            "page_count": parsed.get('page_count', 0),
            "sections_found": list(sections.keys()),
            "top_3_themes_prelim": top_3_themes,
            "top_4_mp_prelim": top_mp_list[:4],
            # LLM 分析结果
            "paper_summary": result.get('paper_summary', ''),
            "top_theme": {
                "theme_id": result.get('top_theme_id', ''),
                "theme_title": result.get('top_theme_title', ''),
                "alignment_score": result.get('theme_alignment_score', 0.0),
                "alignment_reason": result.get('theme_alignment_reason', ''),
            },
            "top_mp": {
                "mp_id": result.get('top_mp_id', ''),
                "mp_name": result.get('top_mp_name', ''),
                "severity": result.get('mp_severity', 0.0),
                "evidence": result.get('mp_evidence', ''),
            },
            "five_questions": {
                "what_phenomenon": result.get('what_phenomenon', ''),
                "how_mechanism": result.get('how_mechanism', ''),
                "why_first_principle": result.get('why_first_principle', ''),
                "where_cross_domain": result.get('where_cross_domain', ''),
                "predict_falsifiable": result.get('predict_falsifiable', ''),
            },
            "knowledge_relation": result.get('knowledge_relation', 'unclear'),
            "knowledge_relation_detail": result.get('knowledge_relation_detail', ''),
        }
    else:
        # LLM 失败时，返回基于词级匹配的基础结果
        top_theme = top_3_themes[0] if top_3_themes else {}
        top_mp = top_mp_list[0] if top_mp_list else {}
        return {
            "source": source,
            "error": "LLM 分析失败，仅提供词级匹配结果",
            "paper_summary": abstract[:300],
            "top_theme": {
                "theme_id": top_theme.get('theme_id', ''),
                "theme_title": top_theme.get('theme_title', ''),
                "alignment_score": top_theme.get('score', 0.0),
                "alignment_reason": f"基于词级匹配，关键词重叠: {top_theme.get('matched_keywords', [])}",
            },
            "top_mp": {
                "mp_id": top_mp.get('mp_id', ''),
                "mp_name": top_mp.get('mp_name', ''),
                "severity": top_mp.get('score', 0.0),
                "evidence": "",
            },
            "five_questions": {
                "what_phenomenon": "LLM 调用失败",
                "how_mechanism": "LLM 调用失败",
                "why_first_principle": "LLM 调用失败",
                "where_cross_domain": "LLM 调用失败",
                "predict_falsifiable": "LLM 调用失败",
            },
            "knowledge_relation": "unclear",
            "knowledge_relation_detail": "LLM 分析失败，无法判断关系",
        }


def main():
    """CLI: python -m scibot.incremental_analysis --arxiv https://arxiv.org/abs/2401.xxxxx"""
    import argparse
    parser = argparse.ArgumentParser(description="Sci-Bot V12.5: 新论文增量分析")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--arxiv', help='arXiv URL (https://arxiv.org/abs/XXXX.XXXXX)')
    group.add_argument('--pdf', help='本地 PDF 路径')
    parser.add_argument('--output', help='输出 JSON 文件路径（可选）')
    args = parser.parse_args()

    source = args.arxiv or args.pdf
    print(f"\n=== Sci-Bot V12.5: 新论文增量分析 ===")
    print(f"来源: {source}")
    print()

    result = analyze_new_paper_sync(source)

    if 'error' in result and 'five_questions' not in result:
        print(f"错误: {result['error']}")
        return

    print(f"论文摘要: {result.get('paper_summary', '')[:200]}...")
    print()
    print(f"最贴近主题: {result['top_theme'].get('theme_id')} {result['top_theme'].get('theme_title')}")
    print(f"  对齐分: {result['top_theme'].get('alignment_score', 0):.2f}")
    print(f"  理由: {result['top_theme'].get('alignment_reason', '')[:150]}")
    print()
    print(f"最严重元规律: {result['top_mp'].get('mp_id')} {result['top_mp'].get('mp_name')}")
    print(f"  严重度: {result['top_mp'].get('severity', 0):.2f}")
    print(f"  证据: {result['top_mp'].get('evidence', '')[:120]}...")
    print()
    print(f"与现有知识体系关系: {result.get('knowledge_relation')} — {result.get('knowledge_relation_detail', '')[:200]}")
    print()
    print("5 项追问:")
    fq = result.get('five_questions', {})
    for key, label in [
        ('what_phenomenon', '现象层'),
        ('how_mechanism', '机制层'),
        ('why_first_principle', '第一性原理'),
        ('where_cross_domain', '跨领域桥点'),
        ('predict_falsifiable', '可证伪预测'),
    ]:
        text = fq.get(key, '')
        print(f"  [{label}]: {text[:200]}...")
        print()

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"结果已保存到: {args.output}")

    return result


if __name__ == '__main__':
    main()
