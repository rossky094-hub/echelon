#!/usr/bin/env python3
"""
[V12.5] double_gate_loader.py — V11.5 双门筛选上游接入

目的:
  把 V11.5 的双门筛选结果作为 Sci-Bot V12.5 的**显式上游**,
  确保 fetch_pdfs / build_index 使用的是经过严格验证的金种子论文。

双门定义 (V11.5 P1 验证标准):
  门1: is_outlier = 0 (非离群值)
  门2: validation_type IN ('experiment', 'simulation')  (有实验/仿真验证)
        + review_subtype = 'non_review' OR review_subtype IN ('roadmap', 'systematic')
  (即排除纯综述、无实验验证、被标记为离群的论文)

数据源:
  - 主要: db/pilot_v5.db (paper_identity 表, 2000 篇候选)
  - 金种子: reports/v5/llm_seeds_with_resources.json (71 篇已 LLM 验证)
  - 原始数据: data/raw_merged/*.jsonl

API:
  load_v11_5_seeds() -> list[dict]        # 71 金种子 (有 OA URL + abstract)
  load_double_gate_papers() -> list[dict] # 从 DB 按双门条件过滤
  get_seed_paper_ids() -> list[str]       # 71 paper_id 列表
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# 路径常量
# --------------------------------------------------------------------------

DB_PATH = '/home/user/workspace/echelon_mvp0a/db/pilot_v5.db'
SEEDS_JSON = '/home/user/workspace/echelon_mvp0a/reports/v5/llm_seeds_with_resources.json'
RAW_MERGED_DIR = '/home/user/workspace/echelon_mvp0a/data/raw_merged'

# 双门 SQL 过滤条件
_DOUBLE_GATE_SQL = """
SELECT
    id,
    openalex_id,
    title,
    abstract,
    publication_date,
    primary_topic_id,
    primary_topic_name,
    field_name,
    subfield_name,
    cited_by_count,
    language,
    is_retracted,
    corpus_origin,
    validation_type,
    review_subtype,
    is_outlier
FROM paper_identity
WHERE
    is_outlier = 0
    AND is_retracted = 0
    AND validation_type IN ('experiment', 'simulation')
    AND language IN ('en', '')
ORDER BY cited_by_count DESC
"""

# 金种子查询 (从 DB 拿原始字段)
_SEED_IDS_SQL = "SELECT id FROM paper_identity WHERE is_outlier = 0 ORDER BY id"


# --------------------------------------------------------------------------
# 公开 API
# --------------------------------------------------------------------------

def load_v11_5_seeds() -> list[dict]:
    """
    [Sci-Bot 原创 #3] 加载 V11.5 金种子论文列表。

    数据来源: reports/v5/llm_seeds_with_resources.json
    (71 篇经 V11.5 P1 双门验证 + LLM 二次筛选的核心论文)

    Returns:
        list[dict], 每个 dict 含:
          paper_id, title, topic_name, openalex_id, doi,
          arxiv_id, oa_url, abstract
    """
    seeds_path = Path(SEEDS_JSON)
    if not seeds_path.exists():
        logger.error(f"金种子文件不存在: {SEEDS_JSON}")
        return []

    with open(seeds_path, encoding='utf-8') as f:
        seeds = json.load(f)

    logger.info(f"[V12.5] 加载 V11.5 金种子: {len(seeds)} 篇")
    return seeds


def get_seed_paper_ids() -> list[str]:
    """返回 71 个金种子 paper_id 列表。"""
    seeds = load_v11_5_seeds()
    return [s['paper_id'] for s in seeds]


def load_double_gate_papers(
    db_path: str = DB_PATH,
    extra_filter: Optional[str] = None,
) -> list[dict]:
    """
    [V12.5] 从 pilot_v5.db 按双门条件加载候选论文。

    双门:
      门1: is_outlier = 0
      门2: validation_type IN ('experiment', 'simulation')
           + is_retracted = 0
           + language = 'en'

    Args:
        db_path: SQLite 数据库路径
        extra_filter: 额外 SQL WHERE 子句 (可选,如 "corpus_origin='v1'")

    Returns:
        list[dict], 每个 dict 含 paper_identity 全部字段
    """
    sql = _DOUBLE_GATE_SQL
    if extra_filter:
        sql = sql.rstrip() + f" AND ({extra_filter})"

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"[V12.5] double_gate DB 查询失败: {e}")
        return []

    papers = [dict(row) for row in rows]
    logger.info(f"[V12.5] 双门筛选: {len(papers)} 篇论文通过")
    return papers


def load_raw_merged_data(
    paper_ids: Optional[list[str]] = None,
    raw_dir: str = RAW_MERGED_DIR,
    max_files: int = 10,
) -> list[dict]:
    """
    从 data/raw_merged/*.jsonl 读原始数据。

    Args:
        paper_ids: 若指定,只返回这些 paper_id 的记录
        raw_dir: raw_merged 目录路径
        max_files: 最多读取文件数 (避免内存爆炸)

    Returns:
        list[dict]
    """
    raw_path = Path(raw_dir)
    if not raw_path.exists():
        logger.warning(f"[V12.5] raw_merged 目录不存在: {raw_dir}")
        return []

    paper_id_set = set(paper_ids) if paper_ids else None
    results = []
    file_count = 0

    for jsonl_file in sorted(raw_path.glob('*.jsonl')):
        if file_count >= max_files:
            break
        try:
            with open(jsonl_file, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        pid = rec.get('id', rec.get('paper_id', ''))
                        if paper_id_set is None or pid in paper_id_set:
                            results.append(rec)
                    except json.JSONDecodeError:
                        continue
            file_count += 1
        except Exception as e:
            logger.warning(f"[V12.5] 读取 {jsonl_file} 失败: {e}")

    logger.info(f"[V12.5] raw_merged 加载: {len(results)} 条记录")
    return results


def get_seeds_for_fetch(
    with_oa_url: bool = True,
) -> list[dict]:
    """
    为 fetch_pdfs.py 提供候选论文列表。

    Args:
        with_oa_url: True=只返回有 oa_url 的种子 (有 PDF 下载链接)

    Returns:
        list[dict] 适合传给 fetch_pdfs.py 的格式
    """
    seeds = load_v11_5_seeds()
    if with_oa_url:
        seeds = [s for s in seeds if s.get('oa_url')]
        logger.info(f"[V12.5] 有 OA URL 的种子: {len(seeds)} 篇")
    return seeds


def get_double_gate_stats() -> dict:
    """
    返回双门筛选的统计摘要。用于验证和报告。

    Returns:
        dict: {
            'total_in_db': int,
            'passed_double_gate': int,
            'seed_count': int,
            'seed_ids': list[str],
        }
    """
    # DB 总数
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM paper_identity")
        total = cur.fetchone()[0]
        conn.close()
    except Exception:
        total = 0

    gate_papers = load_double_gate_papers()
    seeds = load_v11_5_seeds()

    return {
        'total_in_db': total,
        'passed_double_gate': len(gate_papers),
        'seed_count': len(seeds),
        'seed_ids': [s['paper_id'] for s in seeds],
    }


# --------------------------------------------------------------------------
# CLI 入口
# --------------------------------------------------------------------------

if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    cmd = sys.argv[1] if len(sys.argv) > 1 else 'stats'

    if cmd == 'seeds':
        seeds = load_v11_5_seeds()
        print(f"V11.5 金种子: {len(seeds)} 篇")
        for s in seeds[:5]:
            print(f"  {s['paper_id']}: {s['title'][:60]}")

    elif cmd == 'gate':
        papers = load_double_gate_papers()
        print(f"双门通过: {len(papers)} 篇")

    elif cmd == 'stats':
        stats = get_double_gate_stats()
        print(json.dumps(stats, indent=2, ensure_ascii=False))

    else:
        print(f"Usage: python double_gate_loader.py [seeds|gate|stats]")
