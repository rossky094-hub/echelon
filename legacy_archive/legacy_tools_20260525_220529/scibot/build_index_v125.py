#!/usr/bin/env python3
"""
build_index_v125.py - Chunk + Embedding + Chroma index for V12.5
Uses parsed JSON from parsed/ dir, builds ChromaDB with priority section metadata
"""

import json
import os
import logging
from pathlib import Path

import tiktoken
import chromadb
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PARSED_DIR = '/home/user/workspace/echelon_mvp0a/scibot/parsed'
CHROMA_DIR = '/home/user/workspace/echelon_mvp0a/scibot/chroma_db'
SEEDS_FILE = '/home/user/workspace/echelon_mvp0a/reports/v5/llm_seeds_with_resources_v12_5.json'

CHUNK_SIZE = 400      # tokens
CHUNK_OVERLAP = 50

PRIORITY_SECTIONS = {'limitations', 'discussion', 'future_work', 'conclusion'}
SKIP_SECTIONS = {'references', 'acknowledgments', 'appendix', '_method'}

enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(enc.encode(text))


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
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


def build_index():
    # Load seeds for metadata
    with open(SEEDS_FILE) as f:
        seeds = json.load(f)
    seeds_by_id = {s['paper_id']: s for s in seeds}
    
    # Init ChromaDB
    os.makedirs(CHROMA_DIR, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    
    # Delete existing collection if any
    try:
        client.delete_collection("papers_v125")
        logger.info("Deleted existing papers_v125 collection")
    except Exception:
        pass
    
    collection = client.create_collection(
        name="papers_v125",
        metadata={"hnsw:space": "cosine"}
    )
    
    # Load sentence transformer
    logger.info("Loading sentence transformer model...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Parse all files
    parsed_files = [f for f in os.listdir(PARSED_DIR) 
                    if f.endswith('.json') and not f.startswith('_')]
    logger.info(f"Processing {len(parsed_files)} parsed papers")
    
    total_chunks = 0
    paper_count = 0
    section_dist = {}
    priority_chunk_count = 0
    
    batch_ids = []
    batch_docs = []
    batch_embeds = []
    batch_metas = []
    BATCH_SIZE = 100
    
    def flush_batch():
        nonlocal total_chunks
        if batch_ids:
            collection.add(
                ids=batch_ids,
                documents=batch_docs,
                embeddings=batch_embeds,
                metadatas=batch_metas
            )
            total_chunks += len(batch_ids)
            batch_ids.clear()
            batch_docs.clear()
            batch_embeds.clear()
            batch_metas.clear()
    
    for fname in parsed_files:
        paper_id = fname.replace('.json', '')
        
        with open(os.path.join(PARSED_DIR, fname)) as f:
            data = json.load(f)
        
        sections = data.get('sections', {})
        seed_meta = seeds_by_id.get(paper_id, {})
        
        paper_chunks = 0
        
        for sec_name, sec_text in sections.items():
            if sec_name in SKIP_SECTIONS:
                continue
            if not sec_text or len(sec_text.strip()) < 50:
                continue
            
            # Track section distribution
            section_dist[sec_name] = section_dist.get(sec_name, 0)
            
            chunks = chunk_text(sec_text)
            is_priority = sec_name in PRIORITY_SECTIONS
            
            for chunk_idx, chunk in enumerate(chunks):
                chunk_id = f"{paper_id}_{sec_name}_{chunk_idx}"
                
                # Encode
                embedding = model.encode(chunk, normalize_embeddings=True).tolist()
                
                meta = {
                    'paper_id': paper_id,
                    'section_type': sec_name,
                    'chunk_idx': chunk_idx,
                    'is_priority': int(is_priority),
                    'title': seed_meta.get('title', '')[:200],
                    'topic': seed_meta.get('primary_topic_name', '')[:100],
                    'token_count': count_tokens(chunk)
                }
                
                batch_ids.append(chunk_id)
                batch_docs.append(chunk)
                batch_embeds.append(embedding)
                batch_metas.append(meta)
                
                section_dist[sec_name] = section_dist.get(sec_name, 0) + 1
                paper_chunks += 1
                if is_priority:
                    priority_chunk_count += 1
                
                if len(batch_ids) >= BATCH_SIZE:
                    flush_batch()
        
        if paper_chunks > 0:
            paper_count += 1
            logger.info(f"  {paper_id}: {paper_chunks} chunks")
    
    flush_batch()
    
    logger.info(f"\n=== INDEX STATS ===")
    logger.info(f"Papers indexed: {paper_count}")
    logger.info(f"Total chunks: {total_chunks}")
    logger.info(f"Priority chunks: {priority_chunk_count}")
    
    stats = {
        'papers_indexed': paper_count,
        'total_chunks': total_chunks,
        'priority_chunks': priority_chunk_count,
        'section_distribution': section_dist,
        'model': 'all-MiniLM-L6-v2',
        'chunk_size': CHUNK_SIZE,
        'chunk_overlap': CHUNK_OVERLAP
    }
    
    with open(os.path.join(CHROMA_DIR, '_index_stats.json'), 'w') as f:
        json.dump(stats, f, indent=2)
    
    logger.info(f"\nSection distribution:")
    for sec, cnt in sorted(section_dist.items(), key=lambda x: -x[1]):
        logger.info(f"  {sec}: {cnt}")
    
    return stats


if __name__ == '__main__':
    build_index()
