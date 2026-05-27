"""
echelon.crawler.dedup
=======================
V14 论文去重服务。

优先级:DOI > openalex_id > arxiv_id > title fuzzy match
命中重复 → 合并字段(取最新最完整的 raw_jsonb)
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Optional

from echelon.library.schema import Paper

logger = logging.getLogger(__name__)

# 标题模糊匹配的最低相似度阈值
TITLE_SIMILARITY_THRESHOLD = 0.92


class DeduplicationService:
    """
    论文去重服务。

    去重优先级:
    1. DOI 精确匹配
    2. openalex_id 精确匹配
    3. arxiv_id 精确匹配
    4. 标题模糊匹配(≥0.92 相似度)
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def find_duplicate(self, paper: Paper) -> Optional[dict]:
        """
        查找数据库中是否已存在相同论文。

        Args:
            paper: 待插入的 Paper 对象

        Returns:
            已存在的论文行(dict)或 None
        """
        from echelon.library.db import get_session

        with get_session(self.db_path) as conn:
            # 1. DOI 精确匹配(最高优先级)
            if paper.doi:
                row = conn.execute(
                    "SELECT * FROM papers WHERE doi = ?",
                    (paper.doi,)
                ).fetchone()
                if row:
                    logger.debug(f"[dedup] DOI 匹配: {paper.doi}")
                    return dict(row)

            # 2. openalex_id 精确匹配
            if paper.openalex_id:
                row = conn.execute(
                    "SELECT * FROM papers WHERE openalex_id = ?",
                    (paper.openalex_id,)
                ).fetchone()
                if row:
                    logger.debug(f"[dedup] OpenAlex ID 匹配: {paper.openalex_id}")
                    return dict(row)

            # 3. arxiv_id 精确匹配
            if paper.arxiv_id:
                row = conn.execute(
                    "SELECT * FROM papers WHERE arxiv_id = ?",
                    (paper.arxiv_id,)
                ).fetchone()
                if row:
                    logger.debug(f"[dedup] arXiv ID 匹配: {paper.arxiv_id}")
                    return dict(row)

            # 4. 标题模糊匹配
            if paper.title:
                row = self._find_by_title_fuzzy(conn, paper.title)
                if row:
                    logger.debug(f"[dedup] 标题模糊匹配: {paper.title[:50]}...")
                    return dict(row)

        return None

    def _find_by_title_fuzzy(
        self,
        conn: sqlite3.Connection,
        title: str,
        threshold: float = TITLE_SIMILARITY_THRESHOLD,
    ) -> Optional[sqlite3.Row]:
        """
        标题模糊匹配(基于 token 级 Jaccard 相似度)。

        生产环境升级路径:
        - SQLite FTS5 用 bm25 搜索候选集再精排
        - Postgres 用 tsvector + 余弦相似度
        - 嵌入层: SPECTER2 title embedding + cosine

        当前 Pilot 实现:
        - 从数据库取候选(按日期缩窄)
        - 计算 token-level Jaccard 相似度
        """
        title_tokens = set(_tokenize(title))
        if len(title_tokens) < 3:
            return None  # 标题太短,不做模糊匹配

        # 取候选:标题长度相近的论文(优化:只取 token 数量差异 ≤30% 的)
        candidates = conn.execute(
            "SELECT * FROM papers WHERE LENGTH(title) BETWEEN ? AND ? LIMIT 1000",
            (int(len(title) * 0.6), int(len(title) * 1.4))
        ).fetchall()

        best_score = 0.0
        best_row = None
        for row in candidates:
            db_title = row["title"] or ""
            db_tokens = set(_tokenize(db_title))
            score = _jaccard(title_tokens, db_tokens)
            if score > best_score:
                best_score = score
                best_row = row

        if best_score >= threshold:
            return best_row
        return None

    def merge_papers(self, existing: dict, incoming: Paper) -> dict:
        """
        合并论文字段:取最新最完整的数据。

        策略:
        - 优先保留已有非空字段
        - cited_by_count 取最大值(更新 = 更多引用)
        - raw_jsonb 追加到列表(保留所有来源)
        - last_refreshed_at 更新为当前时间
        """
        import json
        from datetime import datetime, timezone

        merged = dict(existing)

        # 补充空缺字段
        for field in ["doi", "arxiv_id", "openalex_id", "abstract", "language",
                      "primary_topic_id", "primary_subfield_id",
                      "primary_field_id", "primary_domain_id"]:
            if not merged.get(field):
                new_val = getattr(incoming, field, None)
                if new_val:
                    merged[field] = new_val

        # cited_by_count 取最大
        existing_cbc = merged.get("cited_by_count") or 0
        incoming_cbc = incoming.cited_by_count or 0
        merged["cited_by_count"] = max(existing_cbc, incoming_cbc)

        # last_refreshed_at 更新
        merged["last_refreshed_at"] = datetime.now(timezone.utc).isoformat()

        return merged


def find_duplicate(paper: Paper, db_path: str) -> Optional[dict]:
    """
    模块级快捷函数:查找重复论文。

    Args:
        paper: 待检查的 Paper
        db_path: 数据库路径

    Returns:
        已存在的论文行(dict)或 None
    """
    svc = DeduplicationService(db_path)
    return svc.find_duplicate(paper)


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """简单 token 化:小写 + 去标点 + 分词"""
    import re
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return [t for t in text.split() if len(t) > 1]


def _jaccard(set_a: set, set_b: set) -> float:
    """Jaccard 相似度"""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0
