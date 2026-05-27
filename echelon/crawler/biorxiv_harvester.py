"""
echelon.crawler.biorxiv_harvester
====================================
BioRxiv Harvester — V15 vertical: bio (占位)。

当前状态: 骨架实现,MVP1 (V15) 启用。

TODO (V15):
- 实现 bioRxiv API (https://api.biorxiv.org/details/biorxiv/{from}/{to})
- 支持 medRxiv (https://api.biorxiv.org/details/medrxiv/{from}/{to})
- 速率限制: 1 req/s
- 分类过滤: neuroscience / cell-biology / genomics 等
"""
from __future__ import annotations

from datetime import date
from typing import AsyncIterator, Optional

from echelon.crawler.base import BaseHarvester
from echelon.library.schema import Paper


class BioRxivHarvester(BaseHarvester):
    """
    bioRxiv / medRxiv 预印本爬虫。

    **V15 vertical: bio — 当前未实现**

    参考 API:
    - https://api.biorxiv.org/details/biorxiv/{from}/{to}/{cursor}
    - https://api.biorxiv.org/details/medrxiv/{from}/{to}/{cursor}

    JSON 格式:
    {
      "messages": [{"cursor": "...", "count": 100, "total": 5000}],
      "collection": [
        {
          "doi": "10.1101/...",
          "title": "...",
          "authors": "...",
          "author_corresponding": "...",
          "date": "YYYY-MM-DD",
          "category": "neuroscience",
          "abstract": "...",
          "published": "NA" | "DOI"  # NA = 仅预印本
        }, ...
      ]
    }
    """

    provider_name = "biorxiv"

    async def fetch_by_topic(
        self,
        topic_id: str,
        from_date: date,
        to_date: date,
        max_results: Optional[int] = None,
    ) -> AsyncIterator[Paper]:
        """V15 vertical: bio — 未实现"""
        raise NotImplementedError("V15 vertical: bio")
        yield  # make it a generator

    async def fetch_by_id(self, external_id: str) -> Optional[Paper]:
        """V15 vertical: bio — 未实现"""
        raise NotImplementedError("V15 vertical: bio")

    async def fetch_by_doi(self, doi: str) -> Optional[Paper]:
        """V15 vertical: bio — 未实现"""
        raise NotImplementedError("V15 vertical: bio")
