#!/usr/bin/env python3
"""
citation_chain.py - Sci-Bot V12.5 独有能力 #2
多跳引用追踪：发现论文思想起源

paper-qa 不做引用链追踪，本模块专注：
  1. 从论文 A 的 reference 区域提取被引文献
  2. 检查被引文献是否在 V12 数据库（25 篇语料）
  3. 递归至深度 2（共同祖先检测）
  4. 图算法找"共同祖先"：被多条引用链共同指向的奠基性工作

与 paper-qa 的差异化：
  - paper-qa 无引用追踪功能
  - 本模块输出 citation tree + 共同祖先 + 在库检测
  - 专注 AI4Science 关键论文的思想谱系

Usage:
    python -m scibot.citation_chain --paper 01KR7T0VQ0VWCDTX5SN9B4BEVH
    python -m scibot.citation_chain --paper 01KR7T0X48ESGCZC6KF1M5RW90 --depth 2
"""

import json
import logging
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

sys.path.insert(0, '/home/user/workspace/echelon_mvp0a')

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PARSED_DIR = Path('/home/user/workspace/echelon_mvp0a/scibot/parsed')
SCIBOT_DIR = Path('/home/user/workspace/echelon_mvp0a/scibot')

# 最大递归深度
MAX_DEPTH = 2
# 每篇论文提取的最多引用条目
TOP_K_REFS = 5


def _load_all_papers() -> dict[str, dict]:
    """
    加载所有已解析的论文元数据。
    Returns: {paper_id: {title, doi, topic_name, ...}}
    """
    papers = {}
    for f in PARSED_DIR.glob('*.json'):
        if f.name.startswith('_'):
            continue
        try:
            with open(f) as fh:
                data = json.load(fh)
            pid = data.get('paper_id', f.stem)
            papers[pid] = {
                'paper_id': pid,
                'title': data.get('title', data.get('seed_title', '')),
                'doi': data.get('doi', ''),
                'topic_name': data.get('topic_name', ''),
                'sections': list(data.get('sections', {}).keys()),
                'raw_text_snippet': data.get('raw_text', '')[:500],
            }
        except Exception as e:
            logger.warning(f"Could not load {f}: {e}")
    return papers


def _extract_references_from_text(paper_data: dict) -> list[str]:
    """
    从论文原文提取参考文献列表。
    策略：从 raw_text 的末尾找参考文献块，提取论文标题/DOI
    Returns: 参考文献条目列表（原始文本）
    """
    raw = paper_data.get('raw_text', '')
    sections = paper_data.get('sections', {})

    # 尝试从 references section 提取
    ref_text = sections.get('references', '')
    if not ref_text or len(ref_text) < 50:
        # 尝试从 raw_text 末尾找参考文献区域
        # 典型格式："References\n[1] Author et al..."
        ref_match = re.search(
            r'(?:References|REFERENCES|Bibliography)\s*\n(.+)$',
            raw, re.DOTALL
        )
        if ref_match:
            ref_text = ref_match.group(1)
        else:
            # 取 raw_text 最后 3000 字符作为参考区域
            ref_text = raw[-3000:] if len(raw) > 3000 else raw

    if not ref_text:
        return []

    # 策略1: 合并续行（适用于 [N] 格式，跨行的条目）
    lines = ref_text.split('\n')
    merged_entries = []
    current = ''
    for line in lines:
        stripped = line.strip()
        if re.match(r'\[\d+\]', stripped):
            if current:
                merged_entries.append(current)
            current = stripped
        elif current and stripped:
            current += ' ' + stripped
    if current:
        merged_entries.append(current)

    if merged_entries:
        return merged_entries[:20]

    # 策略2: 数字. Author 格式
    entries = re.findall(r'\d+\.\s+[A-Z][^\n]{30,300}', ref_text)
    if entries:
        return entries[:20]

    # 策略3: 按行（取含大写字母开头的长行）
    long_lines = [l.strip() for l in ref_text.split('\n') if len(l.strip()) > 40]
    entries = [l for l in long_lines if re.match(r'[A-Z]', l) or re.match(r'\d+[.\)]', l)]
    return entries[:20]


def _extract_ref_titles(entries: list[str]) -> list[str]:
    """从参考文献条目中提取可能的论文标题。"""
    titles = []
    for entry in entries:
        # 移除编号前缀 [N] or N. or N)
        cleaned = re.sub(r'^\[\d+\]\s*', '', entry)
        cleaned = re.sub(r'^\d+[.\)]\s*', '', cleaned)

        # 策略1: 提取双引号中的标题（IEEE/ACM 格式：[N] Author, "Title," or "Title."）
        # 匹配 "..." 其中内容可含逗号，允许结尾有 ," 或 ." 或 ;"
        quoted = re.findall(r'[“"]([^”"]{10,300})[”"][,\.;]?', cleaned)
        if quoted:
            # 清理：去除末尾逗号（有时标题被截断并包含尾部逗号）
            clean_titles = [q.rstrip('.,; ') for q in quoted if len(q.rstrip('.,; ')) > 10]
            if clean_titles:
                titles.extend(clean_titles)
                continue

        # 策略2: 移除作者列表后再提取标题
        no_authors = re.sub(r'^(?:[A-Z][^,]{0,20},\s*(?:[A-Z]\.\s*)+,?\s*)+(?:and\s+|&\s+)?', '', cleaned)
        no_authors = re.sub(r'^(?:[A-Z][a-z]+\s+[A-Z][^,]*,?\s+)+', '', no_authors)

        quoted2 = re.findall(r'[“"]([^”"]{10,300})[”"][,\.;]?', no_authors)
        if quoted2:
            clean_titles2 = [q.rstrip('.,; ') for q in quoted2 if len(q.rstrip('.,; ')) > 10]
            if clean_titles2:
                titles.extend(clean_titles2)
                continue

        # 策略3: 取第一个完整句子
        first_sent = no_authors.split('.')[0].strip() if '.' in no_authors else no_authors.strip()
        if len(first_sent) > 20 and not re.match(r'^\d{4}$', first_sent):
            titles.append(first_sent)

    return [t for t in titles if len(t) > 15][:TOP_K_REFS]


def _find_in_corpus(ref_title: str, all_papers: dict[str, dict]) -> Optional[dict]:
    """
    在已有语料库中查找与参考文献标题最匹配的论文。
    使用简单的词级重叠匹配（不依赖 embedding 避免额外开销）。
    """
    if not ref_title:
        return None

    ref_words = set(re.findall(r'\b[a-z]{3,}\b', ref_title.lower()))
    if len(ref_words) < 3:
        return None

    best_match = None
    best_score = 0.0

    for pid, meta in all_papers.items():
        corpus_title = meta.get('title', '')
        corpus_words = set(re.findall(r'\b[a-z]{3,}\b', corpus_title.lower()))
        if not corpus_words:
            continue

        # Jaccard similarity
        intersection = ref_words & corpus_words
        union = ref_words | corpus_words
        score = len(intersection) / len(union) if union else 0.0

        if score > best_score and score > 0.25:  # 25% 重叠阈值
            best_score = score
            best_match = {**meta, 'match_score': round(score, 3)}

    return best_match


def _use_llm_to_extract_refs(paper_id: str, raw_text_snippet: str,
                              all_paper_titles: list[str]) -> list[str]:
    """
    用 LLM 从论文原文中提取最重要的 K=5 篇引用标题。
    """
    instruction = f"""你是科学文献分析专家。从以下论文片段中，找出最核心的 {TOP_K_REFS} 篇被引文献的标题。

要求：
1. 只输出论文标题，不含作者/年份/期刊信息
2. 优先选择论文方法/技术的奠基性引用（经常被介绍和对比的论文）
3. 每个标题单独一行
4. 如果文本不包含明显的参考文献，返回 "NO_REFS"

以下是数据库中已有论文标题供参考（可以匹配这些，但不强制）：
{chr(10).join(all_paper_titles[:10])}"""

    input_data = {
        "paper_id": paper_id,
        "text_snippet": raw_text_snippet[:2000],
    }

    schema = {
        "type": "object",
        "properties": {
            "reference_titles": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["reference_titles"]
    }

    result = _run_llm_extract(input_data, instruction, schema, max_tokens=5000)
    if result and result.get('reference_titles'):
        return result['reference_titles'][:TOP_K_REFS]
    return []


def _run_llm_extract(input_data: dict, instruction: str, output_schema: dict,
                     max_tokens: int = 1000) -> dict | None:
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
            timeout=90,
            env=os.environ.copy(),
        )
        if result.returncode != 0:
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


def build_citation_tree(paper_id: str, all_papers: dict[str, dict],
                         depth: int = 0, max_depth: int = MAX_DEPTH,
                         visited: set = None) -> dict:
    """
    递归构建引用树。

    Args:
        paper_id: 根论文 ID
        all_papers: 所有语料论文的元数据字典
        depth: 当前递归深度
        max_depth: 最大递归深度
        visited: 已访问的 paper_id 集合（防止环）

    Returns:
        {
          "paper_id": ...,
          "title": ...,
          "in_corpus": bool,
          "depth": int,
          "references": [  # 找到的被引文献（在库的）
            { 同结构, ... }
          ],
          "ref_titles_extracted": [...]
        }
    """
    if visited is None:
        visited = set()

    if paper_id in visited:
        return {"paper_id": paper_id, "title": all_papers.get(paper_id, {}).get('title', ''), 
                "in_corpus": paper_id in all_papers, "depth": depth, "references": [], 
                "cycle": True}

    visited.add(paper_id)
    paper_meta = all_papers.get(paper_id, {})
    in_corpus = paper_id in all_papers

    node = {
        "paper_id": paper_id,
        "title": paper_meta.get('title', 'Unknown'),
        "in_corpus": in_corpus,
        "depth": depth,
        "references": [],
        "ref_titles_extracted": [],
    }

    if not in_corpus or depth >= max_depth:
        return node

    # 加载论文详细数据
    parsed_path = PARSED_DIR / f"{paper_id}.json"
    if not parsed_path.exists():
        return node

    try:
        with open(parsed_path) as f:
            paper_data = json.load(f)
    except Exception:
        return node

    # 提取参考文献
    ref_entries = _extract_references_from_text(paper_data)
    ref_titles = _extract_ref_titles(ref_entries)

    # 如果正则提取失败，用 LLM 兜底（仅在深度 0 时调用，节约 token）
    if not ref_titles and depth == 0:
        all_corpus_titles = [m['title'] for m in all_papers.values()]
        ref_titles = _use_llm_to_extract_refs(
            paper_id,
            paper_data.get('raw_text', '')[-3000:],
            all_corpus_titles
        )

    node['ref_titles_extracted'] = ref_titles

    # 在语料库中查找被引文献
    for ref_title in ref_titles[:TOP_K_REFS]:
        match = _find_in_corpus(ref_title, all_papers)
        if match and match['paper_id'] not in visited:
            child_node = build_citation_tree(
                match['paper_id'], all_papers,
                depth=depth + 1,
                max_depth=max_depth,
                visited=visited.copy()
            )
            child_node['ref_title_matched'] = ref_title
            child_node['match_score'] = match.get('match_score', 0.0)
            node['references'].append(child_node)

    return node


def find_common_ancestors(citation_tree: dict) -> list[dict]:
    """
    从引用树中找共同祖先：被多个引用路径共同指向的论文。

    Returns:
        [{"paper_id": ..., "title": ..., "referenced_count": int, "paths": [...]}]
    """
    reference_count: dict[str, int] = defaultdict(int)
    reference_meta: dict[str, dict] = {}

    def traverse(node: dict, path: list[str]):
        if not node.get('in_corpus'):
            return
        pid = node['paper_id']
        for child in node.get('references', []):
            cpid = child['paper_id']
            reference_count[cpid] += 1
            reference_meta[cpid] = {
                'paper_id': cpid,
                'title': child.get('title', ''),
                'in_corpus': child.get('in_corpus', False),
            }
            traverse(child, path + [pid])

    traverse(citation_tree, [])

    # 找被引次数 >= 2 的论文
    ancestors = []
    for pid, count in reference_count.items():
        if count >= 2 and pid != citation_tree['paper_id']:
            ancestors.append({
                **reference_meta[pid],
                'referenced_count': count,
            })

    ancestors.sort(key=lambda x: -x['referenced_count'])
    return ancestors


def trace_citation_chain(paper_id: str, depth: int = MAX_DEPTH) -> dict:
    """
    多跳引用追踪主函数。

    Args:
        paper_id: 起始论文的 ID
        depth: 追踪深度（默认 2）

    Returns:
        {
            "root_paper_id": ...,
            "root_title": ...,
            "in_corpus": bool,
            "citation_tree": {...},
            "common_ancestors": [...],
            "corpus_papers_found": int,
            "total_refs_extracted": int,
        }
    """
    all_papers = _load_all_papers()

    if paper_id not in all_papers:
        return {
            "error": f"paper_id {paper_id} 不在语料库中",
            "available_papers": list(all_papers.keys()),
        }

    citation_tree = build_citation_tree(
        paper_id, all_papers,
        depth=0, max_depth=depth,
        visited=set()
    )

    common_ancestors = find_common_ancestors(citation_tree)

    # 统计在库论文数
    def count_in_corpus(node: dict) -> int:
        cnt = 1 if node.get('in_corpus') else 0
        for child in node.get('references', []):
            cnt += count_in_corpus(child)
        return cnt

    def count_refs(node: dict) -> int:
        cnt = len(node.get('ref_titles_extracted', []))
        for child in node.get('references', []):
            cnt += count_refs(child)
        return cnt

    corpus_found = count_in_corpus(citation_tree) - 1  # 减去根节点自身
    total_refs = count_refs(citation_tree)

    return {
        "root_paper_id": paper_id,
        "root_title": all_papers[paper_id]['title'],
        "in_corpus": True,
        "max_depth": depth,
        "citation_tree": citation_tree,
        "common_ancestors": common_ancestors,
        "corpus_papers_found_in_chain": corpus_found,
        "total_refs_extracted": total_refs,
    }


def main():
    """CLI: python -m scibot.citation_chain --paper 01KR7T0VQ0VWCDTX5SN9B4BEVH"""
    import argparse
    parser = argparse.ArgumentParser(description="Sci-Bot V12.5: 多跳引用追踪")
    parser.add_argument('--paper', required=True, help='起始论文 paper_id')
    parser.add_argument('--depth', type=int, default=2, help='追踪深度 (default: 2)')
    parser.add_argument('--output', help='输出 JSON 文件路径（可选）')
    args = parser.parse_args()

    print(f"\n=== Sci-Bot V12.5: 多跳引用追踪 ===")
    print(f"起始论文: {args.paper} | depth={args.depth}")
    print()

    result = trace_citation_chain(args.paper, depth=args.depth)

    if 'error' in result:
        print(f"错误: {result['error']}")
        print(f"可用 paper_id: {result.get('available_papers', [])}")
        return

    print(f"根论文: {result['root_title'][:80]}")
    print(f"最大深度: {result['max_depth']}")
    print(f"提取引用总数: {result['total_refs_extracted']}")
    print(f"在库论文追踪到: {result['corpus_papers_found_in_chain']} 篇")
    print()

    # 打印引用树（简化版）
    def print_tree(node: dict, indent: int = 0):
        prefix = "  " * indent
        in_corpus_mark = "✓" if node.get('in_corpus') else "✗"
        title = node.get('title', '')[:60]
        score = f" [match={node.get('match_score', ''):.2f}]" if 'match_score' in node else ""
        print(f"{prefix}[{in_corpus_mark}] {title}{score}")
        for child in node.get('references', []):
            print_tree(child, indent + 1)

    print("引用树 (✓=在库, ✗=不在库):")
    print_tree(result['citation_tree'])
    print()

    if result['common_ancestors']:
        print("共同祖先论文（被多路径引用）:")
        for anc in result['common_ancestors']:
            mark = "✓" if anc.get('in_corpus') else "✗"
            print(f"  [{mark}] [{anc['referenced_count']}次引用] {anc['title'][:70]}")
    else:
        print("(未发现共同祖先论文)")

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {args.output}")

    return result


if __name__ == '__main__':
    main()
