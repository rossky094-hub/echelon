"""
echelon.crawler.openalex_harvester
====================================
OpenAlex Harvester — 包装 V13 openalex_client.py 为标准 Harvester 接口。

功能:
- fetch_by_arxiv_id: 用 OpenAlex 给 arXiv 论文补 citation count + topic + referenced_works
- enrich_paper: Pilot 阶段对每篇 arXiv 论文调一次 OpenAlex 补元数据
- fetch_by_topic: 按 OpenAlex topic ID 全量拉取
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import AsyncIterator, Optional

import httpx

from echelon.crawler.base import BaseHarvester
from echelon.core.openalex_client import iter_works_by_topic
from echelon.library.schema import Author, OpenAccessInfo, Paper
from echelon.core.ulid_utils import ulid_new

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.openalex.org"
_USER_AGENT = "Echelon-V14/1.0 (mailto:team@echelon.ai)"
_REQUEST_DELAY = 0.1  # OpenAlex polite pool: 10 req/s


class OpenAlexHarvester(BaseHarvester):
    """
    OpenAlex 数据源爬虫。

    基于 V13 openalex_client.py cursor 分页实现。
    """

    provider_name = "openalex"

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
        """按 OpenAlex topic_id 拉取论文"""
        async for work in iter_works_by_topic(
            topic_id=topic_id,
            since=from_date,
            until=to_date,
            max_results=max_results,
            mailto=self.mailto,
            _http_client=self._client,
        ):
            paper = self._normalize_work(work)
            if paper:
                yield paper

    async def fetch_by_id(self, external_id: str) -> Optional[Paper]:
        """按 OpenAlex work ID 拉取单篇(W4392199370)"""
        work = await self._get_work(external_id)
        if work:
            return self._normalize_work(work)
        return None

    async def fetch_by_doi(self, doi: str) -> Optional[Paper]:
        """按 DOI 查询 OpenAlex"""
        work = await self._get_work_by_doi(doi)
        if work:
            return self._normalize_work(work)
        return None

    # ------------------------------------------------------------------
    # 特有方法
    # ------------------------------------------------------------------

    async def fetch_by_arxiv_id(self, arxiv_id: str) -> Optional[Paper]:
        """
        用 OpenAlex 给 arXiv 论文补 citation count + topic + referenced_works。

        OpenAlex 支持用 arXiv ID 过滤:
        filter=locations.source.id:S2764455111 (arXiv source)
        或 filter=ids.arxiv:2401.12345
        """
        await asyncio.sleep(self.request_delay)
        try:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            should_close = self._client is None
            try:
                resp = await client.get(
                    f"{_BASE_URL}/works",
                    params={
                        "filter": f"ids.arxiv:{arxiv_id}",
                        "select": "id,doi,title,abstract,publication_date,"
                                  "cited_by_count,primary_topic,open_access,"
                                  "referenced_works,authorships,language",
                        "mailto": self.mailto,
                    },
                    headers={"User-Agent": _USER_AGENT},
                )
            finally:
                if should_close:
                    await client.aclose()

            if resp.status_code != 200:
                return None
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return None
            return self._normalize_work(results[0])
        except Exception as e:
            logger.error(f"[OpenAlexHarvester] fetch_by_arxiv_id 失败: {arxiv_id}: {e}")
            return None

    async def enrich_paper(self, paper: Paper) -> Paper:
        """
        用 OpenAlex 补充 arXiv 论文的元数据。

        补充:
        - cited_by_count
        - primary_topic + subfield + field + domain
        - referenced_works (引用列表)
        - openalex_id
        """
        if not paper.arxiv_id and not paper.doi:
            return paper

        oa_paper = None
        if paper.arxiv_id:
            oa_paper = await self.fetch_by_arxiv_id(paper.arxiv_id)
        if oa_paper is None and paper.doi:
            oa_paper = await self.fetch_by_doi(paper.doi)

        if oa_paper is None:
            return paper

        # 补充字段(仅补空缺,不覆盖 arXiv 原有数据)
        if oa_paper.openalex_id:
            paper.openalex_id = oa_paper.openalex_id
        if oa_paper.cited_by_count is not None:
            paper.cited_by_count = oa_paper.cited_by_count
        if oa_paper.primary_topic_id and not paper.primary_topic_id:
            paper.primary_topic_id = oa_paper.primary_topic_id
        if oa_paper.primary_subfield_id and not paper.primary_subfield_id:
            paper.primary_subfield_id = oa_paper.primary_subfield_id
        if oa_paper.primary_field_id and not paper.primary_field_id:
            paper.primary_field_id = oa_paper.primary_field_id
        if oa_paper.primary_domain_id and not paper.primary_domain_id:
            paper.primary_domain_id = oa_paper.primary_domain_id
        if oa_paper.references_external:
            paper.references_external = oa_paper.references_external

        return paper

    # ------------------------------------------------------------------
    # 私有 HTTP 方法
    # ------------------------------------------------------------------

    async def _get_work(self, work_id: str) -> Optional[dict]:
        """按 OpenAlex work ID 获取 JSON"""
        await asyncio.sleep(self.request_delay)
        try:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            should_close = self._client is None
            try:
                resp = await client.get(
                    f"{_BASE_URL}/works/{work_id}",
                    params={"mailto": self.mailto},
                    headers={"User-Agent": _USER_AGENT},
                )
            finally:
                if should_close:
                    await client.aclose()
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"[OpenAlexHarvester] _get_work 失败: {work_id}: {e}")
        return None

    async def _get_work_by_doi(self, doi: str) -> Optional[dict]:
        """按 DOI 获取 OpenAlex work JSON"""
        await asyncio.sleep(self.request_delay)
        encoded_doi = doi.replace("/", "%2F")
        try:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            should_close = self._client is None
            try:
                resp = await client.get(
                    f"{_BASE_URL}/works/https://doi.org/{doi}",
                    params={"mailto": self.mailto},
                    headers={"User-Agent": _USER_AGENT},
                )
            finally:
                if should_close:
                    await client.aclose()
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"[OpenAlexHarvester] _get_work_by_doi 失败: {doi}: {e}")
        return None

    # ------------------------------------------------------------------
    # 归一化
    # ------------------------------------------------------------------

    def _normalize_work(self, work: dict) -> Optional[Paper]:
        """将 OpenAlex Work JSON 归一化为 Paper"""
        from echelon.crawler.normalizer import normalize_openalex_work
        return normalize_openalex_work(work)
