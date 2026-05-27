"""
echelon.crawler.base
====================
V14 统一爬虫基类接口。

所有 Harvester 实现此抽象接口,保证可互换。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import AsyncIterator, Optional

from echelon.library.schema import Paper


class BaseHarvester(ABC):
    """
    统一爬虫抽象接口。

    子类需实现:
    - fetch_by_topic: 按 topic/set 拉取论文列表
    - fetch_by_id: 按外部 ID 拉取单篇
    - fetch_by_doi: 按 DOI 拉取单篇
    """

    provider_name: str = "unknown"

    @abstractmethod
    async def fetch_by_topic(
        self,
        topic_id: str,
        from_date: date,
        to_date: date,
        max_results: Optional[int] = None,
    ) -> AsyncIterator[Paper]:
        """按 topic/set 拉取论文(异步生成器)"""
        ...  # pragma: no cover

    @abstractmethod
    async def fetch_by_id(self, external_id: str) -> Optional[Paper]:
        """按外部 ID 拉取单篇论文"""
        ...  # pragma: no cover

    @abstractmethod
    async def fetch_by_doi(self, doi: str) -> Optional[Paper]:
        """按 DOI 拉取单篇论文"""
        ...  # pragma: no cover
