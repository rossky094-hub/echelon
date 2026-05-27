#!/usr/bin/env python3
"""
first_principles_v125.py - 5项追问第一性原理分析
For each theme, query Chroma for relevant chunks, then call LLM with 5 questions:
  1. What (现象描述)
  2. How (机制分析)  
  3. Why (第一性原理追问)
  4. Where (进展前沿)
  5. Predict (未来预测)
"""

import json
import os
import subprocess
import chromadb
from sentence_transformers import SentenceTransformer
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

CHROMA_DIR = '/home/user/workspace/echelon_mvp0a/scibot/chroma_db'
THEMES_FILE = '/home/user/workspace/echelon_mvp0a/scibot/themes_v125.json'
OUTPUT_FILE = '/home/user/workspace/echelon_mvp0a/scibot/first_principles_results_v12_5.json'

# Query keywords for each theme
THEME_QUERIES = {
    'T1': 'inverse design interpretability physical mechanism neural network metasurface',
    'T2': 'broadband achromatic metasurface dispersion phase compensation wideband',
    'T3': 'optoelectronic integration photonic chip fabrication coupling efficiency',
    'T4': 'fabrication tolerance manufacturing error sim-to-real metasurface robust',
    'T5': 'multimodal generalization robot manipulation transfer learning cross-modal',
    'T6': 'sample efficiency robot learning imitation learning few-shot data efficiency',
    'T7': 'unstructured scene grasping object detection pose estimation cluttered',
    'T8': 'semantic understanding language grounding manipulation instruction following',
    'T9': 'reward function sparse reward reinforcement learning reward shaping',
    'T10': 'sim-to-real transfer deployment safety real-world reinforcement learning',
    'T11': 'hallucination visual language model factual error grounding',
    'T12': 'out-of-distribution generalization cross-modal retrieval domain shift',
    'T13': 'computational efficiency inference large model optimization lightweight',
    'T14': 'world model long-horizon prediction error accumulation temporal',
    'T15': 'optical neural network training stability gradient noise convergence',
}


def get_theme_context(collection, model, theme_id: str, n_results: int = 8) -> str:
    """Get relevant text chunks for a theme from Chroma."""
    query_text = THEME_QUERIES.get(theme_id, '')
    if not query_text:
        return ""
    
    q_embed = model.encode(query_text, normalize_embeddings=True).tolist()
    
    # First try priority sections
    try:
        results = collection.query(
            query_embeddings=[q_embed],
            n_results=min(n_results, collection.count()),
            where={"is_priority": 1},
            include=["documents", "metadatas"]
        )
        priority_docs = results['documents'][0]
        priority_metas = results['metadatas'][0]
    except Exception:
        priority_docs = []
        priority_metas = []
    
    # Also get general results
    try:
        general_results = collection.query(
            query_embeddings=[q_embed],
            n_results=min(n_results, collection.count()),
            include=["documents", "metadatas"]
        )
        general_docs = general_results['documents'][0]
        general_metas = general_results['metadatas'][0]
    except Exception:
        general_docs = []
        general_metas = []
    
    # Combine, dedup, prioritize
    seen = set()
    context_parts = []
    
    # Priority first
    for doc, meta in zip(priority_docs, priority_metas):
        doc_id = f"{meta['paper_id']}_{meta['section_type']}_{meta['chunk_idx']}"
        if doc_id not in seen:
            seen.add(doc_id)
            context_parts.append(f"[{meta['section_type'].upper()}] {doc[:400]}")
    
    # General
    for doc, meta in zip(general_docs, general_metas):
        doc_id = f"{meta['paper_id']}_{meta['section_type']}_{meta['chunk_idx']}"
        if doc_id not in seen and len(context_parts) < 6:
            seen.add(doc_id)
            context_parts.append(f"[{meta['section_type'].upper()}] {doc[:300]}")
    
    return '\n\n'.join(context_parts[:6])


def call_llm_5questions(theme: dict, context: str) -> dict:
    """Call LLM for 5-question first principles analysis."""
    
    input_obj = {
        'theme_name': theme['name'],
        'domain': theme['domain'],
        'core_challenge': theme['challenge'],
        'literature_context': context[:2000] if context else '无直接文献摘录'
    }
    
    instruction = """你是第一性原理科研分析专家。基于给定主题和文献上下文,回答5项追问:
1. what_is: 该瓶颈的现象描述(2-3句,包含关键数据/指标)
2. how_mechanism: 底层机制分析(从物理/数学角度解释为何存在此瓶颈)
3. why_first_principle: 第一性原理追问(追溯到最底层的物理/信息论/数学约束,如信息容量极限、维度灾难、热力学约束等)
4. where_frontier: 当前进展前沿(已有哪些尝试,进展到哪一步,最近关键突破)
5. predict_3yr: 3年内突破预测(具体可验证的里程碑预测,含成功概率估计)
每项回答控制在100字以内。用中文回答,保留关键英文术语。"""

    schema = {
        "type": "object",
        "properties": {
            "what_is": {"type": "string"},
            "how_mechanism": {"type": "string"},
            "why_first_principle": {"type": "string"},
            "where_frontier": {"type": "string"},
            "predict_3yr": {"type": "string"}
        },
        "required": ["what_is", "how_mechanism", "why_first_principle", "where_frontier", "predict_3yr"]
    }
    
    cmd = [
        'pplx', 'llm', 'extract',
        '--instruction', instruction,
        '--output-schema', json.dumps(schema)
    ]
    
    input_line = json.dumps(input_obj)
    
    try:
        result = subprocess.run(
            cmd,
            input=input_line,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, 'PPLX_API_KEY': os.environ.get('PPLX_API_KEY', '')}
        )
        output = result.stdout.strip()
        if not output:
            return {'error': 'No output', 'stderr': result.stderr[:200]}
        
        data = json.loads(output)
        if data.get('results') and data['results'][0].get('result'):
            return data['results'][0]['result']
        else:
            error = data.get('results', [{}])[0].get('error', {})
            return {'error': str(error)}
    except subprocess.TimeoutExpired:
        return {'error': 'LLM timeout'}
    except Exception as e:
        return {'error': str(e)}


def main():
    # Load themes
    with open(THEMES_FILE) as f:
        themes = json.load(f)
    
    # Init Chroma
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_collection("papers_v125")
    
    # Load embedding model
    logger.info("Loading sentence transformer...")
    embed_model = SentenceTransformer('all-MiniLM-L6-v2')
    
    results = []
    total_cost = 0.0
    
    for i, theme in enumerate(themes):
        tid = theme['id']
        logger.info(f"\n[{i+1}/{len(themes)}] Processing theme: {tid} - {theme['name']}")
        
        # Get Chroma context
        context = get_theme_context(collection, embed_model, tid)
        logger.info(f"  Context length: {len(context)} chars")
        
        # Call LLM
        analysis = call_llm_5questions(theme, context)
        
        if 'error' in analysis:
            logger.warning(f"  LLM error: {analysis['error']}")
        else:
            logger.info(f"  5 questions answered successfully")
        
        result = {
            'theme_id': tid,
            'theme_name': theme['name'],
            'domain': theme['domain'],
            'core_challenge': theme['challenge'],
            'context_used': len(context),
            'analysis': analysis
        }
        results.append(result)
    
    # Save results
    output = {
        'total_themes': len(results),
        'total_llm_calls': len(results),
        'results': results
    }
    
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\n=== COMPLETE ===")
    logger.info(f"Themes analyzed: {len(results)}")
    logger.info(f"Saved to: {OUTPUT_FILE}")
    
    return output


if __name__ == '__main__':
    main()
