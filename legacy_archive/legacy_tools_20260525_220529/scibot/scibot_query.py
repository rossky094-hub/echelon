#!/usr/bin/env python3
"""
scibot_query.py - [V12.5] Sci-Bot RAG 检索引擎

原创能力(严格保留):
  1. section_type 优先 limitations 检索过滤 (should_filter_by_limitation)
  2. 第一性原理 5 项追问范式 -> 由 first_principles_analysis.py 调用本模块
  3. V11.5 双门筛选上游 -> double_gate_loader.py 提供候选 paper_id

V12.5 新增:
  use_paperqa_rerank=True: cosine top-30 -> pplx LLM 二次评分 -> top-8
  use_paperqa_rerank=False: cosine top-k (原行为,默认兼容)
"""

import sys
import json
import logging
import os
import subprocess
from typing import Optional

import chromadb
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

CHROMA_DIR = '/home/user/workspace/echelon_mvp0a/scibot/chroma_db'
MODEL_NAME = 'all-MiniLM-L6-v2'

# Keywords that trigger priority-section filtering
LIMITATION_KEYWORDS = {
    'limitation', 'challenge', 'bottleneck', 'problem', 'failure', 'difficult',
    'cannot', 'unable', 'constraint', 'barrier', 'restrict', 'weakness',
    'fail', 'fails', 'failed',  # [V12.5] 补充 fail 变体
    '卡点', '限制', '挑战', '问题', '瓶颈', '失败', '困难', 'future', 'direction',
}

PRIORITY_SECTIONS = {'limitations', 'discussion', 'future_work', 'conclusion'}


def _load_model_and_client():
    """Lazy-load the embedding model and ChromaDB client."""
    model = SentenceTransformer(MODEL_NAME)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_collection("scibot_papers")
    return model, collection


_model = None
_collection = None


def _get_resources():
    global _model, _collection
    if _model is None:
        _model, _collection = _load_model_and_client()
    return _model, _collection


def should_filter_by_limitation(question: str) -> bool:
    """Check if the question is about limitations/challenges."""
    q_lower = question.lower()
    return any(kw in q_lower for kw in LIMITATION_KEYWORDS)


def query(
    question: str,
    top_k: int = 8,
    filter_section: Optional[str] = None,
    filter_paper_ids: Optional[list[str]] = None,
    use_paperqa_rerank: bool = False,
) -> list[dict]:
    """
    [V12.5] Query the RAG system.

    Args:
        question: The query text
        top_k: Number of results to return
        filter_section: If set, only return chunks from this section type
        filter_paper_ids: If set, only return chunks from these paper IDs
        use_paperqa_rerank: [V12.5] True=先 cosine top-30,再用 pplx LLM 二次评分选 top-k
                            False=cosine top-k 直接返回 (原行为)

    Returns:
        List of chunk dicts with: text, paper_id, paper_title, section_type, chunk_idx, distance
    """
    model, collection = _get_resources()

    # Embed the query
    q_embedding = model.encode([question], normalize_embeddings=True)[0].tolist()

    # [Sci-Bot 原创 #1] 确定是否启用 section_type 优先过滤
    use_priority_filter = filter_section is not None or should_filter_by_limitation(question)

    # Build where clause
    where = None
    if filter_section:
        where = {"section_type": {"$eq": filter_section}}
    elif filter_paper_ids:
        where = {"paper_id": {"$in": filter_paper_ids}}

    # [V12.5] rerank 需要更多候选:cosine top-30
    candidate_k = 30 if use_paperqa_rerank else top_k * 2

    # Strategy: try priority sections first, then fall back to all
    results = None
    if use_priority_filter and filter_section is None:
        # Try fetching from priority sections
        priority_where = {
            "$and": [
                {"is_priority_section": {"$eq": True}},
            ]
        }
        if filter_paper_ids:
            priority_where["$and"].append({"paper_id": {"$in": filter_paper_ids}})

        try:
            results = collection.query(
                query_embeddings=[q_embedding],
                n_results=min(candidate_k, collection.count()),
                where=priority_where if priority_where["$and"] else None,
                include=["documents", "metadatas", "distances"],
            )
            if not results["documents"][0]:
                results = None
        except Exception:
            results = None

    # Fallback or normal query
    if results is None or not results["documents"][0]:
        try:
            n_results = min(candidate_k, collection.count())
            results = collection.query(
                query_embeddings=[q_embedding],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    # Format results
    chunks = []
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    for doc, meta, dist in zip(docs, metas, distances):
        chunks.append({
            "text": doc,
            "paper_id": meta.get("paper_id", ""),
            "paper_title": meta.get("paper_title", ""),
            "topic_name": meta.get("topic_name", ""),
            "section_type": meta.get("section_type", ""),
            "chunk_idx": meta.get("chunk_idx", 0),
            "is_priority_section": meta.get("is_priority_section", False),
            "distance": dist,
        })

    # Sort: priority sections first, then by distance (Sci-Bot 原创 #1)
    chunks.sort(key=lambda x: (not x["is_priority_section"], x["distance"]))

    # [V12.5] pplx LLM 二次 rerank
    if use_paperqa_rerank and len(chunks) > top_k:
        chunks = _pplx_rerank(question, chunks, top_k=top_k)
    else:
        chunks = chunks[:top_k]

    return chunks


def query_for_theme(
    theme_title: str,
    paper_ids: list[str],
    top_k: int = 10,
) -> list[dict]:
    """
    Query specifically for a theme, focusing on limitations/discussion/future_work sections
    from the papers relevant to that theme.
    """
    model, collection = _get_resources()
    q_embedding = model.encode([theme_title], normalize_embeddings=True)[0].tolist()

    results_list = []

    # First: query priority sections from theme papers
    if paper_ids:
        try:
            where = {
                "$and": [
                    {"is_priority_section": {"$eq": True}},
                    {"paper_id": {"$in": paper_ids}},
                ]
            }
            n = min(top_k, collection.count())
            results = collection.query(
                query_embeddings=[q_embedding],
                n_results=n,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            if results["documents"][0]:
                for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
                    results_list.append({
                        "text": doc,
                        "paper_id": meta.get("paper_id", ""),
                        "paper_title": meta.get("paper_title", ""),
                        "topic_name": meta.get("topic_name", ""),
                        "section_type": meta.get("section_type", ""),
                        "chunk_idx": meta.get("chunk_idx", 0),
                        "is_priority_section": True,
                        "distance": dist,
                    })
        except Exception as e:
            logger.warning(f"Priority query failed: {e}")

    # Second: global priority sections query (across all papers)
    try:
        where2 = {"is_priority_section": {"$eq": True}}
        n2 = min(top_k + 5, collection.count())
        results2 = collection.query(
            query_embeddings=[q_embedding],
            n_results=n2,
            where=where2,
            include=["documents", "metadatas", "distances"],
        )
        if results2["documents"][0]:
            seen_ids = {r["paper_id"] + str(r["chunk_idx"]) for r in results_list}
            for doc, meta, dist in zip(results2["documents"][0], results2["metadatas"][0], results2["distances"][0]):
                key = meta.get("paper_id", "") + str(meta.get("chunk_idx", ""))
                if key not in seen_ids:
                    results_list.append({
                        "text": doc,
                        "paper_id": meta.get("paper_id", ""),
                        "paper_title": meta.get("paper_title", ""),
                        "topic_name": meta.get("topic_name", ""),
                        "section_type": meta.get("section_type", ""),
                        "chunk_idx": meta.get("chunk_idx", 0),
                        "is_priority_section": True,
                        "distance": dist,
                    })
                    seen_ids.add(key)
    except Exception as e:
        logger.warning(f"Global priority query failed: {e}")

    # Sort by distance and return top_k
    results_list.sort(key=lambda x: x["distance"])
    return results_list[:top_k]


# --------------------------------------------------------------------------
# [V12.5] pplx LLM 二次 rerank
# --------------------------------------------------------------------------

_RERANK_SCHEMA = {
    "type": "object",
    "properties": {
        "ranked_indices": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "0-based indices of top-8 most relevant chunks, best first",
        }
    },
    "required": ["ranked_indices"]
}

_RERANK_INSTRUCTION_TMPL = (
    "你是科学文献相关性评分专家。根据给定问题,从候选文本块中选出最相关的 {n} 个,按相关度从高到低排列其下标(0-based)。\n\n"
    "评分标准:\n"
    "  1. 文本块是否直接回答了问题(卡点/限制/原因/机制)?\n"
    "  2. 文本块来自 limitations / discussion / future_work 章节优先\n"
    "  3. 文本块包含具体实验数据/定量描述优先\n\n"
    "输出格式: JSON 对象,含 ranked_indices 字段 (整数数组)"
)


def _pplx_rerank(
    question: str,
    chunks: list[dict],
    top_k: int = 8,
    max_tokens: int = 200,
) -> list[dict]:
    """
    [V12.5] 用 pplx llm extract 对 cosine top-30 结果做二次评分,选 top-k。
    全程走 pplx CLI,不使用第三方 LLM API。
    若 pplx 调用失败,自动 fallback 到 cosine 排序。
    """
    if not chunks:
        return chunks

    n_select = min(top_k, len(chunks))
    instruction = _RERANK_INSTRUCTION_TMPL.format(n=n_select)

    # 构造输入:问题 + 候选文本块摘要
    candidates = []
    for i, c in enumerate(chunks):
        snippet = c['text'][:300].replace('\n', ' ')
        candidates.append({
            "idx": i,
            "section": c.get('section_type', ''),
            "snippet": snippet,
        })

    input_data = {
        "question": question,
        "candidates": candidates,
    }

    input_json = json.dumps(input_data, ensure_ascii=False)
    schema_json = json.dumps(_RERANK_SCHEMA)

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
            timeout=60,
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            logger.warning(f"[V12.5] pplx rerank 失败: {result.stderr[:200]}, fallback 到 cosine")
            return chunks[:top_k]

        # Parse JSONL output
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if 'results' in obj and obj['results']:
                    res = obj['results'][0]
                    if 'result' in res:
                        indices = res['result'].get('ranked_indices', [])
                        # 验证下标合法性
                        valid_indices = [i for i in indices if 0 <= i < len(chunks)]
                        if valid_indices:
                            reranked = [chunks[i] for i in valid_indices[:top_k]]
                            logger.debug(f"[V12.5] pplx rerank 成功,选出 {len(reranked)} 个")
                            return reranked
            except (json.JSONDecodeError, KeyError):
                continue

        logger.warning("[V12.5] pplx rerank 解析失败, fallback 到 cosine")
        return chunks[:top_k]

    except subprocess.TimeoutExpired:
        logger.warning("[V12.5] pplx rerank 超时, fallback 到 cosine")
        return chunks[:top_k]
    except Exception as e:
        logger.warning(f"[V12.5] pplx rerank 异常: {e}, fallback 到 cosine")
        return chunks[:top_k]


# --------------------------------------------------------------------------
# 原有辅助函数
# --------------------------------------------------------------------------

def format_context_for_llm(chunks: list[dict], max_chars: int = 6000) -> str:
    """Format retrieved chunks into a LLM-ready context string."""
    parts = []
    total = 0
    for chunk in chunks:
        header = f"[论文: {chunk['paper_title'][:80]} | 章节: {chunk['section_type']} | paper_id: {chunk['paper_id']}]"
        text = chunk['text']
        entry = f"{header}\n{text}\n"
        if total + len(entry) > max_chars:
            break
        parts.append(entry)
        total += len(entry)
    return '\n---\n'.join(parts)


def main():
    """CLI interface: python -m scibot.scibot_query "your question" """
    if len(sys.argv) < 2:
        print("Usage: python scibot_query.py <question> [top_k]")
        sys.exit(1)

    question = sys.argv[1]
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 8

    print(f"Query: {question}")
    print(f"Top-K: {top_k}")
    print(f"Will filter priority sections: {should_filter_by_limitation(question)}")
    print()

    chunks = query(question, top_k=top_k)
    for i, chunk in enumerate(chunks):
        print(f"[{i+1}] {chunk['paper_title'][:60]} | {chunk['section_type']} | dist={chunk['distance']:.3f}")
        print(f"    {chunk['text'][:200]}...")
        print()


if __name__ == '__main__':
    main()
