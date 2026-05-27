"""
echelon.crawler.crossref_harvester
=====================================
Crossref Harvester — DOI 元数据 fallback。

功能:
- 给定 DOI → 拿完整 metadata
- 给定 arxiv_id → 用 arXiv API 查 DOI,再查 Crossref
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import AsyncIterator, Optional

import httpx

from echelon.crawler.base import BaseHarvester
from echelon.library.schema import Paper
from echelon.core.ulid_utils import ulid_new

logger = logging.getLogger(__name__)

_CROSSREF_BASE = "https://api.crossref.org/works"
_USER_AGENT = "Echelon-V14/1.0 (mailto:team@echelon.ai)"
_REQUEST_DELAY = 0.5  # Crossref polite pool


class CrossrefHarvester(BaseHarvester):
    """
    Crossref DOI 元数据 fallback 爬虫。

    主要用途:补充 DOI、期刊信息、发表年份等。
    不用于大批量摄入(Crossref API 速率限制较严)。
    """

    provider_name = "crossref"

    def __init__(
        self,
        *,
        mailto: str = "team@echelon.ai",
        request_delay: float = _REQUEST_DELAY,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.mailto = mailto
        self.request_delay = request_delay
        self._client = http_client

    # ------------------------------------------------------------------
    # BaseHarvester 接口
    # ------------------------------------------------------------------

    async def fetch_by_topic(
        self,
        topic_id: str,
        from_date: date,
        to_date: date,
        max_results: Optional[int] = None,
    ) -> AsyncIterator[Paper]:
        """Crossref 不支持按 topic 大批量拉取,此处仅为接口兼容"""
        logger.warning("[CrossrefHarvester] fetch_by_topic 不支持,Crossref 为 DOI fallback")
        return
        yield  # 使成为 generator

    async def fetch_by_id(self, external_id: str) -> Optional[Paper]:
        """按 Crossref work ID 或 DOI 拉取"""
        return await self.fetch_by_doi(external_id)

    async def fetch_by_doi(self, doi: str) -> Optional[Paper]:
        """
        按 DOI 查询 Crossref 完整元数据。

        Args:
            doi: DOI 字符串(可带或不带 https://doi.org/ 前缀)

        Returns:
            Paper 或 None
        """
        # 规范化 DOI
        clean_doi = doi.strip()
        for prefix in ("https://doi.org/", "http://dx.doi.org/", "doi:"):
            if clean_doi.lower().startswith(prefix.lower()):
                clean_doi = clean_doi[len(prefix):]

        await asyncio.sleep(self.request_delay)
        try:
            msg = await self._get_crossref_work(clean_doi)
            if msg:
                return self._normalize_crossref(msg)
        except Exception as e:
            logger.error(f"[CrossrefHarvester] fetch_by_doi 失败: {doi}: {e}")
        return None

    async def fetch_by_arxiv_id(self, arxiv_id: str) -> Optional[Paper]:
        """
        用 arXiv ID 查找 DOI,再用 Crossref 拉元数据。

        步骤:
        1. 调 arXiv API 查 arxiv_id 的 DOI
        2. 用获得的 DOI 查 Crossref
        """
        doi = await self._get_doi_from_arxiv(arxiv_id)
        if not doi:
            logger.debug(f"[CrossrefHarvester] 无法从 arXiv 获取 DOI: {arxiv_id}")
            return None
        return await self.fetch_by_doi(doi)

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    async def _get_crossref_work(self, doi: str) -> Optional[dict]:
        """调 Crossref API 获取 work metadata"""
        url = f"{_CROSSREF_BASE}/{doi}"
        try:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            should_close = self._client is None
            try:
                resp = await client.get(
                    url,
                    params={"mailto": self.mailto},
                    headers={"User-Agent": _USER_AGENT},
                )
            finally:
                if should_close:
                    await client.aclose()

            if resp.status_code == 200:
                data = resp.json()
                return data.get("message")
            elif resp.status_code == 404:
                logger.debug(f"[CrossrefHarvester] DOI 不存在: {doi}")
            else:
                logger.warning(f"[CrossrefHarvester] Crossref 返回 {resp.status_code}: {doi}")
        except Exception as e:
            logger.error(f"[CrossrefHarvester] _get_crossref_work 异常: {e}")
        return None

    async def _get_doi_from_arxiv(self, arxiv_id: str) -> Optional[str]:
        """从 arXiv API 获取 DOI"""
        import re
        await asyncio.sleep(self.request_delay)
        try:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            should_close = self._client is None
            try:
                resp = await client.get(
                    "https://export.arxiv.org/abs/" + arxiv_id,
                    headers={"User-Agent": _USER_AGENT},
                )
            finally:
                if should_close:
                    await client.aclose()

            if resp.status_code == 200:
                # 从 HTML 中提取 DOI
                content = resp.text
                doi_match = re.search(r'doi\.org/([^"\s<>]+)', content)
                if doi_match:
                    return doi_match.group(1)
        except Exception as e:
            logger.error(f"[CrossrefHarvester] _get_doi_from_arxiv 异常: {e}")
        return None

    def _normalize_crossref(self, msg: dict) -> Optional[Paper]:
        """将 Crossref message JSON 归一化为 Paper"""
        from echelon.crawler.normalizer import normalize_crossref_msg
        return normalize_crossref_msg(msg)
