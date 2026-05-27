#!/usr/bin/env python3
"""
build_index.py - [V12.5] Chunk + Embedding + Chroma index

双引擎 PDF 解析:
  Primary:  paper-qa readers.py (更鲁棒,处理多列/旋转/嵌入字体)
  Fallback: pymupdf (scibot/parse_pdf.py) 用于兜底 + 章节边界标注

设计决策:
  1. paper-qa 给原始文本(更干净)
  2. pymupdf 给已解析的 sections JSON(从 parsed/ 目录读)
  3. 融合:优先用 paper-qa 的 section 分割;若 paper-qa 失败,退用 pymupdf parsed JSON
  4. ChromaDB + sentence-transformers 完整保留 (Sci-Bot 原创 #1 依赖的向量库)
  5. metadata 新增 paperqa_doc_id 字段
"""

import json
import os
import logging
import asyncio
from pathlib import Path
from typing import Optional

import tiktoken
import chromadb
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PARSED_DIR = '/home/user/workspace/echelon_mvp0a/scibot/parsed'
PDF_DIR = '/home/user/workspace/echelon_mvp0a/scibot/pdfs'
CHROMA_DIR = '/home/user/workspace/echelon_mvp0a/scibot/chroma_db'

CHUNK_SIZE = 400     # target tokens per chunk
CHUNK_OVERLAP = 50   # overlap tokens

# Section priority for limitation-aware retrieval (Sci-Bot 原创 #1)
PRIORITY_SECTIONS = {'limitations', 'discussion', 'future_work', 'conclusion'}
SKIP_SECTIONS = {'references', 'acknowledgments', 'appendix'}

# Tokenizer
enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(enc.encode(text))


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping token-aware chunks."""
    if not text or not text.strip():
        return []

    tokens = enc.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_str = enc.decode(chunk_tokens)
        if chunk_str.strip():
            chunks.append(chunk_str.strip())
        if end >= len(tokens):
            break
        start += chunk_size - overlap

    return chunks


# --------------------------------------------------------------------------
# 双引擎 PDF 解析
# --------------------------------------------------------------------------

def _load_pymupdf_parsed(paper_id: str) -> Optional[dict]:
    """从 parsed/ 目录读已解析的 pymupdf JSON。"""
    path = Path(PARSED_DIR) / f"{paper_id}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


async def _parse_with_paperqa(pdf_path: str, paper_id: str, seed_meta: dict) -> Optional[dict]:
    """
    用 paper-qa 解析 PDF。
    返回 None 表示失败 (由 pymupdf 兜底)。
    """
    try:
        from scibot.paperqa_integration import EchelonPaperQA
        pqa = EchelonPaperQA()
        result = await pqa.parse_pdf_async(pdf_path, paper_id, metadata=seed_meta)
        if 'error' in result:
            return None
        return result
    except Exception as e:
        logger.warning(f"[V12.5] paper-qa 解析异常 {paper_id}: {e}")
        return None


def _merge_sections(pqa_result: Optional[dict], pymupdf_parsed: Optional[dict]) -> dict:
    """
    双引擎融合逻辑:
      1. 优先用 paper-qa 的章节 (文本质量更好)
      2. 若 paper-qa 章节为空,用 pymupdf 章节填充
      3. pymupdf 的 section_stats 用于验证
    """
    # 取 paper-qa sections
    if pqa_result and pqa_result.get('sections'):
        sections = pqa_result['sections']
        source = 'paperqa'
    elif pymupdf_parsed and pymupdf_parsed.get('sections'):
        sections = pymupdf_parsed['sections']
        source = 'pymupdf'
    else:
        sections = {}
        source = 'none'

    # 如果 paper-qa 有 sections 但 limitations 为空,尝试从 pymupdf 补充
    if (source == 'paperqa' and
            len(sections.get('limitations', '')) < 50 and
            pymupdf_parsed and
            len(pymupdf_parsed.get('sections', {}).get('limitations', '')) > 50):
        sections['limitations'] = pymupdf_parsed['sections']['limitations']
        logger.debug(f"[V12.5] limitations 由 pymupdf 补充")

    sections['_source'] = source
    return sections


def get_sections_for_paper(
    paper_id: str,
    seed_meta: Optional[dict] = None,
    force_paperqa: bool = True,
) -> dict:
    """
    获取论文章节。双引擎策略:
      1. 若有 PDF 且 force_paperqa=True: 先用 paper-qa 解析
      2. 从 parsed/ 目录读 pymupdf 结果作为兜底/补充
      3. 融合两者,返回最佳 sections dict

    Args:
        paper_id: 论文 ULID
        seed_meta: 种子元数据 (title, doi, etc.)
        force_paperqa: 是否尝试 paper-qa 解析

    Returns:
        dict: section_type -> text
    """
    seed_meta = seed_meta or {}
    pymupdf_parsed = _load_pymupdf_parsed(paper_id)

    pqa_result = None
    if force_paperqa:
        pdf_path = Path(PDF_DIR) / f"{paper_id}.pdf"
        if pdf_path.exists():
            try:
                pqa_result = asyncio.run(
                    _parse_with_paperqa(str(pdf_path), paper_id, seed_meta)
                )
            except RuntimeError:
                # 已有 event loop (如 Jupyter),用 nest_asyncio 或直接 pymupdf
                logger.debug(f"[V12.5] asyncio.run 无法在现有 event loop 中运行,使用 pymupdf")
                pqa_result = None
        else:
            logger.debug(f"[V12.5] PDF 不存在: {pdf_path}")

    return _merge_sections(pqa_result, pymupdf_parsed)


# --------------------------------------------------------------------------
# 主索引构建
# --------------------------------------------------------------------------

def build_index(use_paperqa: bool = True):
    """
    [V12.5] 构建 ChromaDB 向量索引。

    Args:
        use_paperqa: True=双引擎(paper-qa主 + pymupdf兜底), False=仅 pymupdf(原行为)
    """

    # Load embedding model
    logger.info("[V12.5] 加载 sentence-transformers 模型...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    logger.info("模型加载完成。")

    # Setup ChromaDB
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    # Delete existing collection if it exists
    try:
        client.delete_collection("scibot_papers")
        logger.info("已删除旧集合。")
    except Exception:
        pass

    collection = client.create_collection(
        name="scibot_papers",
        metadata={"hnsw:space": "cosine"},
    )

    # Load seeds for metadata
    seeds_file = '/home/user/workspace/echelon_mvp0a/reports/v5/llm_seeds_with_resources.json'
    with open(seeds_file) as f:
        seeds = json.load(f)
    seeds_map = {s['paper_id']: s for s in seeds}

    # Process each parsed file
    parsed_files = list(Path(PARSED_DIR).glob('*.json'))
    parsed_files = [p for p in parsed_files if not p.stem.startswith('_')]

    total_chunks = 0
    all_docs = []
    all_embeddings = []
    all_metadatas = []
    all_ids = []

    engine_stats = {'paperqa': 0, 'pymupdf': 0, 'none': 0}

    for pf in parsed_files:
        with open(pf) as f:
            pymupdf_data = json.load(f)

        paper_id = pymupdf_data.get('paper_id', pf.stem)
        title = pymupdf_data.get('seed_title') or pymupdf_data.get('title', '')
        topic = pymupdf_data.get('topic_name', '')
        seed = seeds_map.get(paper_id, {})

        logger.info(f"[V12.5] 处理 {paper_id}: {title[:60]}")

        # 双引擎获取 sections
        if use_paperqa:
            sections = get_sections_for_paper(
                paper_id,
                seed_meta={
                    'title': title,
                    'doi': pymupdf_data.get('doi', ''),
                    'citation': f"{title} ({topic})",
                },
                force_paperqa=True,
            )
        else:
            sections = pymupdf_data.get('sections', {})
            sections['_source'] = 'pymupdf'

        engine = sections.get('_source', 'none')
        engine_stats[engine] = engine_stats.get(engine, 0) + 1
        logger.info(f"  解析引擎: {engine}")

        for section_type, section_text in sections.items():
            if section_type.startswith('_'):
                continue
            if not section_text or len(section_text.strip()) < 50:
                continue
            if section_type in SKIP_SECTIONS:
                continue

            chunks = chunk_text(section_text)
            chunk_count_before = len(all_docs)

            for chunk_idx, chunk in enumerate(chunks):
                chunk_id = f"{paper_id}_{section_type}_{chunk_idx}"
                all_docs.append(chunk)
                all_metadatas.append({
                    'paper_id': paper_id,
                    'paper_title': title[:200],
                    'topic_name': topic,
                    'section_type': section_type,
                    'chunk_idx': chunk_idx,
                    'is_priority_section': section_type in PRIORITY_SECTIONS,
                    'doi': pymupdf_data.get('doi', ''),
                    # [V12.5] 新增: 引用追踪用的 paperqa_doc_id
                    'paperqa_doc_id': paper_id,
                    'parse_engine': engine,
                })
                all_ids.append(chunk_id)

        new_chunks = len(all_docs) - total_chunks
        logger.info(f"  生成 {new_chunks} 个 chunks")
        total_chunks = len(all_docs)

    logger.info(f"\n[V12.5] 总 chunks: {total_chunks}")
    logger.info(f"解析引擎统计: {engine_stats}")

    # Embed in batches
    BATCH_SIZE = 64
    all_embeddings = []
    for i in range(0, len(all_docs), BATCH_SIZE):
        batch = all_docs[i:i+BATCH_SIZE]
        embeddings = model.encode(batch, show_progress_bar=False, normalize_embeddings=True)
        all_embeddings.extend(embeddings.tolist())
        if i % 256 == 0:
            logger.info(f"  Embedded {i+len(batch)}/{total_chunks} chunks")

    logger.info("Embedding 完成,写入 ChromaDB...")

    # Add to collection in batches
    ADD_BATCH = 500
    for i in range(0, len(all_docs), ADD_BATCH):
        collection.add(
            documents=all_docs[i:i+ADD_BATCH],
            embeddings=all_embeddings[i:i+ADD_BATCH],
            metadatas=all_metadatas[i:i+ADD_BATCH],
            ids=all_ids[i:i+ADD_BATCH],
        )
        logger.info(f"  已写入 {min(i+ADD_BATCH, total_chunks)}/{total_chunks}")

    logger.info(f"\n=== [V12.5] 索引构建完成 ===")
    logger.info(f"总文档数: {collection.count()}")
    logger.info(f"ChromaDB 路径: {CHROMA_DIR}")

    # Save index stats
    stats = {
        'total_chunks': total_chunks,
        'papers_indexed': len(parsed_files),
        'chroma_path': CHROMA_DIR,
        'model': 'all-MiniLM-L6-v2',
        'chunk_size': CHUNK_SIZE,
        'chunk_overlap': CHUNK_OVERLAP,
        'version': 'V12.5',
        'dual_engine': use_paperqa,
        'engine_stats': engine_stats,
    }
    with open(os.path.join(CHROMA_DIR, '_index_stats.json'), 'w') as f:
        json.dump(stats, f, indent=2)

    return stats


if __name__ == '__main__':
    build_index(use_paperqa=True)


# ─────────────────────────────────────────────
# V13 Importable interface (不破坏 __main__)
# ─────────────────────────────────────────────

def build_chroma_index(
    parsed_dir: str = PARSED_DIR,
    pdf_dir: str = PDF_DIR,
    chroma_dir: str = CHROMA_DIR,
    use_paperqa: bool = False,
) -> dict:
    """
    V13 pilot interface: build ChromaDB index from parsed PDFs.

    Args:
        parsed_dir:  directory with parsed JSON files
        pdf_dir:     directory with PDF files
        chroma_dir:  ChromaDB output directory
        use_paperqa: use paper-qa for better parsing (requires extra deps)

    Returns:
        dict with 'chunks', 'papers_indexed', 'chroma_path'
    """
    global PARSED_DIR, PDF_DIR, CHROMA_DIR
    old_parsed = PARSED_DIR
    old_pdf = PDF_DIR
    old_chroma = CHROMA_DIR

    PARSED_DIR = parsed_dir
    PDF_DIR = pdf_dir
    CHROMA_DIR = chroma_dir

    try:
        stats = build_index(use_paperqa=use_paperqa)
        return stats
    finally:
        PARSED_DIR = old_parsed
        PDF_DIR = old_pdf
        CHROMA_DIR = old_chroma


def build_chroma_for_pilot(bottleneck_paper_ids: list = None) -> dict:
    """
    V13 pilot convenience: build index from all existing parsed files.
    If chroma_db already has content, returns stats without rebuilding.
    """
    try:
        import chromadb as _chromadb
        client = _chromadb.PersistentClient(path=CHROMA_DIR)
        try:
            collection = client.get_collection("scibot_papers")
            n = collection.count()
            if n > 0:
                logger.info(f"[build_chroma_for_pilot] ChromaDB already has {n} chunks, skip rebuild")
                return {"chunks": n, "papers_indexed": 0, "chroma_path": CHROMA_DIR, "skipped": True}
        except Exception:
            pass
    except Exception:
        pass

    return build_index(use_paperqa=False)
