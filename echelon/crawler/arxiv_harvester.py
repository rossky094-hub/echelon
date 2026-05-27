"""
echelon.crawler.arxiv_harvester
================================
arXiv OAI-PMH 爬虫 — V14 核心 Harvester。

协议: OAI-PMH (Open Archives Initiative Protocol for Metadata Harvesting)
端点: https://export.arxiv.org/oai2

优势:
- resumptionToken 自动分页,无 10000 cap
- 增量摄入只需 from=last_run_date
- arXiv 官方推荐用于大批量摄入

速率限制:
- arXiv 推荐 OAI-PMH 请求间隔 ≥ 3 秒
- 遇 503/429 时指数退避: 30/60/120/300 秒
- 处理 Retry-After header

Fallback / 全量覆盖:
- OAI set `physics:physics:optics` 仅 ~1.3 万篇 (主分类归档)
- 搜索 `cat:physics.optics` 含交叉分类, 约 5.6 万+ 篇 → 全量请用 search 模式
"""
from __future__ import annotations

import asyncio
import calendar
import json
import logging
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import AsyncIterator, List, Optional, Tuple
from xml.etree import ElementTree as ET

import httpx
from lxml import etree

from echelon.crawler.base import BaseHarvester
from echelon.library.schema import Author, OpenAccessInfo, Paper
from echelon.core.ulid_utils import ulid_new

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

OAI_PMH_BASE = "https://oaipmh.arxiv.org/oai"
# OAI setSpec 使用冒号层级: physics:physics:optics (非 categories 里的 physics.optics)
OAI_SET_PHYSICS_OPTICS = "physics:physics:optics"
ARXIV_CATEGORY_PHYSICS_OPTICS = "physics.optics"
SEARCH_API_BASE = "https://export.arxiv.org/search/"
ARXIV_API_QUERY = "https://export.arxiv.org/api/query"
# arXiv API 单查询最多翻页到 start=10000; 按月切窗避免触顶
ARXIV_API_PAGE_SIZE = 2000
ARXIV_API_MAX_START = 10000

# arXiv OAI-PMH 请求间隔(秒)
REQUEST_DELAY = 3.0

# 重试退避序列(秒)
BACKOFF_SCHEDULE = [30, 60, 120, 300, 600]
MAX_RETRIES = 5

# OAI-PMH XML 命名空间
NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "arxiv": "http://arxiv.org/OAI/arXiv/",
    "arXiv": "http://arxiv.org/OAI/arXiv/",
}
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

_USER_AGENT = "Echelon-V14/1.0 (mailto:team@echelon.ai; arXiv harvester)"


# ---------------------------------------------------------------------------
# ArxivHarvester
# ---------------------------------------------------------------------------

def normalize_arxiv_set_spec(set_spec: str) -> str:
    """将常见写法 physics:physics.optics 映射为 OAI 合法 setSpec。"""
    s = (set_spec or "").strip()
    if s in ("physics:physics.optics", "physics.optics"):
        return OAI_SET_PHYSICS_OPTICS
    return s or OAI_SET_PHYSICS_OPTICS


def category_from_set_spec(set_spec: str) -> str:
    """OAI set / 别名 → arXiv search API 分类名。"""
    s = (set_spec or "").strip()
    if s in ("physics:physics:optics", "physics:physics.optics", "physics.optics"):
        return ARXIV_CATEGORY_PHYSICS_OPTICS
    if ":" in s:
        return s.split(":")[-1]
    return s or ARXIV_CATEGORY_PHYSICS_OPTICS


def _atom_text(parent: ET.Element, tag: str) -> Optional[str]:
    el = parent.find(f"atom:{tag}", ATOM_NS)
    if el is not None and el.text:
        return el.text.strip()
    return None




def _write_harvest_cursor(year: int, month: int) -> None:
    """Persist last completed month for search-mode resume."""
    if month == 12:
        ny, nm = year + 1, 1
    else:
        ny, nm = year, month + 1
    today = date.today()
    next_month_start = date(ny, nm, 1)
    date_crawl_complete = next_month_start > today
    backfill_mode = date_crawl_complete
    if date_crawl_complete:
        # 日历月已扫完; resume_from 勿指向未来月份 (会导致 from>to 空跑)
        resume_from = today.isoformat()
    else:
        resume_from = next_month_start.isoformat()
    path = Path(__file__).resolve().parents[2] / "logs" / "v14b" / "arxiv_harvest_cursor.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_completed": f"{year:04d}-{month:02d}",
        "resume_from": resume_from,
        "year": year,
        "month": month,
        "date_crawl_complete": date_crawl_complete,
        "backfill_mode": backfill_mode,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

def _iter_month_windows(from_date: date, to_date: date) -> List[Tuple[int, int]]:
    """[(year, month), ...] 覆盖 [from_date, to_date]。"""
    windows: List[Tuple[int, int]] = []
    y, m = from_date.year, from_date.month
    end_y, end_m = to_date.year, to_date.month
    while (y, m) <= (end_y, end_m):
        windows.append((y, m))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return windows


class ArxivHarvester(BaseHarvester):
    """
    arXiv 爬虫,优先用 OAI-PMH 协议做全量/增量摄入。

    Fallback: OAI-PMH 失败时降级到 search API。
    """

    provider_name = "arxiv"

    def __init__(
        self,
        *,
        request_delay: float = REQUEST_DELAY,
        max_retries: int = MAX_RETRIES,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.request_delay = request_delay
        self.max_retries = max_retries
        self._client = http_client  # 注入用于测试 mock

    # ------------------------------------------------------------------
    # 公共接口 (BaseHarvester 实现)
    # ------------------------------------------------------------------

    async def fetch_by_topic(
        self,
        topic_id: str,
        from_date: Optional[date],
        to_date: Optional[date],
        max_results: Optional[int] = None,
    ) -> AsyncIterator[Paper]:
        """
        按 arXiv set 拉取论文(OAI-PMH)。

        topic_id 格式:
        - "physics:physics:optics" → OAI-PMH setSpec (categories 显示为 physics.optics)
        - "cs.AI" → 转换为 "cs"
        """
        set_spec = normalize_arxiv_set_spec(topic_id)
        async for paper in self.fetch_full_set(
            set_spec=set_spec,
            from_date=from_date,
            to_date=to_date,
            max_results=max_results,
        ):
            yield paper

    async def fetch_by_id(self, external_id: str) -> Optional[Paper]:
        """按 arXiv ID 拉取单篇论文(使用 OAI-PMH GetRecord)"""
        return await self._fetch_single_by_arxiv_id(external_id)

    async def fetch_by_doi(self, doi: str) -> Optional[Paper]:
        """按 DOI 查询 arXiv 论文(使用 search API,不支持 OAI-PMH 按 DOI 查)"""
        return await self._search_by_doi(doi)

    # ------------------------------------------------------------------
    # arXiv API 按分类全量 (cat:physics.optics, ~5.6 万篇)
    # ------------------------------------------------------------------

    async def fetch_by_category_search(
        self,
        category: str = ARXIV_CATEGORY_PHYSICS_OPTICS,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        max_results: Optional[int] = None,
    ) -> AsyncIterator[Paper]:
        """
        用 export.arxiv.org/api/query 按 cat: 拉取, 覆盖交叉分类论文。

        按月切 submittedDate 窗口, 避免单查询 10000 条翻页上限。
        """
        start = from_date or date(1991, 1, 1)
        end = to_date or date.today()
        if start > end:
            logger.warning(
                "[ArxivHarvester] from=%s > until=%s, 日期窗口为空; "
                "请使用 backfill 或修正 cursor",
                start, end,
            )
            return
        count = 0
        logger.info(
            "[ArxivHarvester] 开始 API 分类拉取: cat:%s from=%s until=%s (预期 ~5.6 万篇)",
            category, start, end,
        )

        for year, month in _iter_month_windows(start, end):
            last_day = calendar.monthrange(year, month)[1]
            q_start = f"{year}{month:02d}010000"
            q_end = f"{year}{month:02d}{last_day:02d}2359"
            search_query = f"cat:{category} AND submittedDate:[{q_start} TO {q_end}]"
            window_count = 0

            async for paper in self._fetch_api_query_pages(search_query):
                count += 1
                window_count += 1
                yield paper
                if max_results and count >= max_results:
                    logger.info(
                        "[ArxivHarvester] 达到 max_results=%s, 停止", max_results
                    )
                    return

            if window_count:
                logger.info(
                    "[ArxivHarvester] 月份 %04d-%02d 完成: %s 篇 (累计 %s)",
                    year, month, window_count, count,
                )
                _write_harvest_cursor(year, month)

        logger.info("[ArxivHarvester] API 分类拉取完成, 共 %s 篇", count)

    async def fetch_by_category_backfill(
        self,
        category: str = ARXIV_CATEGORY_PHYSICS_OPTICS,
        max_results: Optional[int] = None,
    ) -> AsyncIterator[Paper]:
        """
        cat: 查询, 无 submittedDate 过滤; 用于日期 crawl 完成后补缺 (~56k 目标)。
        重复 arxiv_id 由 worker refresh/skip 处理。
        """
        search_query = f"cat:{category}"
        count = 0
        logger.info(
            "[ArxivHarvester] 开始 backfill: %s (无日期过滤)",
            search_query,
        )
        async for paper in self._fetch_api_query_pages(search_query):
            count += 1
            yield paper
            if max_results and count >= max_results:
                logger.info(
                    "[ArxivHarvester] backfill 达到 max_results=%s, 停止", max_results
                )
                return
        logger.info("[ArxivHarvester] backfill 完成, 共遍历 %s 篇", count)

    async def _fetch_api_query_pages(self, search_query: str) -> AsyncIterator[Paper]:
        """单条 search_query 分页直到耗尽或触达 API start 上限。"""
        start_index = 0
        while start_index <= ARXIV_API_MAX_START:
            await asyncio.sleep(self.request_delay)
            params = {
                "search_query": search_query,
                "start": start_index,
                "max_results": ARXIV_API_PAGE_SIZE,
                "sortBy": "submittedDate",
                "sortOrder": "ascending",
            }
            content = await self._request_with_retry(ARXIV_API_QUERY, params)
            if not content:
                return

            entries, total = self._parse_api_atom_feed(content)
            if not entries:
                return

            for entry in entries:
                paper = self._parse_atom_entry(entry)
                if paper:
                    yield paper

            start_index += len(entries)
            if start_index >= total or len(entries) < ARXIV_API_PAGE_SIZE:
                return

            if start_index > ARXIV_API_MAX_START:
                logger.warning(
                    "[ArxivHarvester] 查询触达 API 翻页上限 start=%s, query=%s",
                    start_index, search_query,
                )
                return

    def _parse_api_atom_feed(self, content: bytes) -> Tuple[List[ET.Element], int]:
        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            logger.error("[ArxivHarvester] Atom 解析失败: %s", e)
            return [], 0
        total_el = root.find("opensearch:totalResults", ATOM_NS)
        total = int(total_el.text) if total_el is not None and total_el.text else 0
        entries = root.findall("atom:entry", ATOM_NS)
        return entries, total

    def _parse_atom_entry(self, entry_el: ET.Element) -> Optional[Paper]:
        """解析 arXiv API Atom entry → Paper。"""
        try:
            id_url = _atom_text(entry_el, "id")
            if not id_url:
                return None
            m = re.search(r"arxiv\.org/abs/([^/\s]+)", id_url)
            if not m:
                return None
            arxiv_id = re.sub(r"v\d+$", "", m.group(1))

            title = (_atom_text(entry_el, "title") or "").strip()
            title = re.sub(r"\s+", " ", title)
            abstract = _atom_text(entry_el, "summary")
            if abstract:
                abstract = re.sub(r"\s+", " ", abstract).strip()

            published = _atom_text(entry_el, "published") or _atom_text(entry_el, "updated")
            try:
                pub_date = date.fromisoformat((published or "1900-01-01")[:10])
            except ValueError:
                pub_date = date(1900, 1, 1)

            categories: List[str] = []
            primary = entry_el.find("arxiv:primary_category", ATOM_NS)
            if primary is not None and primary.get("term"):
                categories.append(primary.get("term"))
            for cat_el in entry_el.findall("atom:category", ATOM_NS):
                term = cat_el.get("term")
                if term and term not in categories:
                    categories.append(term)

            doi_el = entry_el.find("arxiv:doi", ATOM_NS)
            doi = (doi_el.text or "").strip() if doi_el is not None and doi_el.text else None

            authors: List[Author] = []
            for author_el in entry_el.findall("atom:author", ATOM_NS):
                name = _atom_text(author_el, "name")
                if name:
                    authors.append(Author(id=ulid_new(), display_name=name.strip()))

            raw_jsonb = {
                "arxiv_id": arxiv_id,
                "title": title,
                "abstract": abstract,
                "doi": doi,
                "created": published,
                "categories": categories,
                "authors": [a.display_name for a in authors],
                "source": "arxiv_api_query",
            }

            return Paper(
                id=ulid_new(),
                arxiv_id=arxiv_id,
                doi=doi,
                title=title,
                abstract=abstract,
                publication_date=pub_date,
                n_authors=len(authors),
                primary_topic_id=categories[0] if categories else ARXIV_CATEGORY_PHYSICS_OPTICS,
                language="en",
                open_access=OpenAccessInfo(
                    is_oa=True,
                    oa_status="green",
                    oa_url=f"https://arxiv.org/abs/{arxiv_id}",
                ),
                raw_jsonb=raw_jsonb,
                source_provider="arxiv",
                first_ingested_at=datetime.now(timezone.utc),
                authors=authors,
                references_external=[],
            )
        except Exception as e:
            logger.error("[ArxivHarvester] Atom entry 解析异常: %s", e)
            return None

    # ------------------------------------------------------------------
    # OAI-PMH 全量/增量拉取
    # ------------------------------------------------------------------

    async def fetch_full_set(
        self,
        set_spec: str = OAI_SET_PHYSICS_OPTICS,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        max_results: Optional[int] = None,
    ) -> AsyncIterator[Paper]:
        """
        OAI-PMH ListRecords 全量拉取。

        处理 resumptionToken 分页循环:
        1. 第一次请求携带 set/from/until/metadataPrefix 参数
        2. 后续请求只携带 resumptionToken
        3. 直到 resumptionToken 为空或缺失
        """
        count = 0
        set_spec = normalize_arxiv_set_spec(set_spec)
        # arXiv OAI 拒绝过早的 from (如 1991); 全量用 set + resumptionToken 无日期过滤
        if from_date and from_date < date(2007, 1, 1):
            logger.warning(
                "[ArxivHarvester] OAI 不支持 from=%s (过早), 改为按 set 全量分页拉取",
                from_date,
            )
            from_date = None
            to_date = None

        params: dict = {
            "verb": "ListRecords",
            "metadataPrefix": "arXiv",
        }
        if set_spec:
            params["set"] = set_spec
        if from_date:
            params["from"] = from_date.isoformat()
        if to_date:
            params["until"] = to_date.isoformat()

        logger.info(
            f"[ArxivHarvester] 开始 OAI-PMH 全量拉取: set={set_spec} "
            f"from={from_date} until={to_date} max={max_results}"
        )

        use_token = False  # 是否已切换到 resumptionToken 模式

        while True:
            # 速率限制
            await asyncio.sleep(self.request_delay)

            # 发起请求(带重试)
            xml_content = await self._request_with_retry(
                OAI_PMH_BASE, params=params
            )
            if xml_content is None:
                logger.error("[ArxivHarvester] OAI-PMH 请求失败,停止摄入")
                return

            # 解析 XML
            try:
                root = etree.fromstring(xml_content.encode() if isinstance(xml_content, str) else xml_content)
            except etree.XMLSyntaxError as e:
                logger.error(f"[ArxivHarvester] XML 解析失败: {e}")
                return

            err_el = root.find(".//oai:error", NS)
            if err_el is not None:
                err_msg = (err_el.text or "").strip()
                logger.error(
                    "[ArxivHarvester] OAI 错误 code=%s: %s",
                    err_el.get("code"), err_msg,
                )
                if "start date too early" in err_msg and ("from" in params or "until" in params):
                    logger.warning("[ArxivHarvester] 重试: 去掉日期参数,按 set 全量分页")
                    params = {"verb": "ListRecords", "metadataPrefix": "arXiv", "set": set_spec}
                    continue
                return

            # 提取 records
            records = root.findall(".//oai:record", NS)
            logger.debug(f"[ArxivHarvester] 本批次获取 {len(records)} 条记录")

            for record in records:
                paper = self._parse_oai_record(record)
                if paper is None:
                    continue
                count += 1
                yield paper
                if max_results and count >= max_results:
                    logger.info(f"[ArxivHarvester] 达到 max_results={max_results},停止")
                    return

            # 检查 resumptionToken
            token_el = root.find(".//oai:resumptionToken", NS)
            if token_el is not None and token_el.text and token_el.text.strip():
                token = token_el.text.strip()
                # 记录总数(如果有)
                total = token_el.get("completeListSize")
                cursor = token_el.get("cursor")
                logger.info(
                    f"[ArxivHarvester] resumptionToken 已获取, cursor={cursor}, "
                    f"total={total}, 已拉取={count}"
                )
                # 切换到 token 模式:下次只传 verb + resumptionToken
                params = {"verb": "ListRecords", "resumptionToken": token}
                use_token = True
            else:
                # 无更多数据
                logger.info(
                    f"[ArxivHarvester] OAI-PMH 摄入完成,共拉取 {count} 篇"
                )
                return

    async def fetch_incremental(
        self,
        since: date,
        set_spec: str = OAI_SET_PHYSICS_OPTICS,
        max_results: Optional[int] = None,
    ) -> AsyncIterator[Paper]:
        """
        增量摄入(从 HWM 起,from=since)。

        等同于 fetch_full_set 带 from_date,此处封装更明确的语义。
        """
        async for paper in self.fetch_full_set(
            set_spec=set_spec,
            from_date=since,
            to_date=date.today(),
            max_results=max_results,
        ):
            yield paper

    # ------------------------------------------------------------------
    # 单篇操作
    # ------------------------------------------------------------------

    async def _fetch_single_by_arxiv_id(self, arxiv_id: str) -> Optional[Paper]:
        """OAI-PMH GetRecord 获取单篇"""
        # OAI-PMH 使用 oai:arxiv.org:arxiv_id 格式的 identifier
        # arxiv_id 可能含版本后缀,先去掉
        clean_id = re.sub(r"v\d+$", "", arxiv_id.strip())
        identifier = f"oai:arXiv.org:{clean_id}"

        await asyncio.sleep(self.request_delay)
        xml_content = await self._request_with_retry(
            OAI_PMH_BASE,
            params={
                "verb": "GetRecord",
                "identifier": identifier,
                "metadataPrefix": "arXiv",
            }
        )
        if not xml_content:
            return None
        try:
            root = etree.fromstring(xml_content.encode() if isinstance(xml_content, str) else xml_content)
            record = root.find(".//oai:record", NS)
            if record is None:
                return None
            return self._parse_oai_record(record)
        except Exception as e:
            logger.error(f"[ArxivHarvester] GetRecord 解析失败 {arxiv_id}: {e}")
            return None

    async def _search_by_doi(self, doi: str) -> Optional[Paper]:
        """通过 arXiv search API 按 DOI 查询(有限支持)"""
        await asyncio.sleep(self.request_delay)
        # arXiv search API 不直接支持 DOI 查询,尝试用 ti + all 组合
        xml_content = await self._request_with_retry(
            "https://export.arxiv.org/find/all/1/ti:+AND+doi:{}/0/1/0/all/0/1".format(
                doi.replace("/", "")
            ),
            params={}
        )
        # 若无结果直接返回 None
        return None

    # ------------------------------------------------------------------
    # OAI-PMH XML 解析
    # ------------------------------------------------------------------

    def _parse_oai_record(self, record_el) -> Optional[Paper]:
        """
        解析单条 OAI-PMH record XML 为 Paper 对象。

        arXiv OAI-PMH arXiv 格式字段:
        - identifier → arxiv_id
        - datestamp → 入库日期(不是发表日期)
        - title / abstract / authors / categories / doi / journal-ref / created / updated
        """
        try:
            # -- header --
            header = record_el.find("oai:header", NS)
            if header is None:
                return None

            # 检查是否已删除
            status = header.get("status")
            if status == "deleted":
                return None

            identifier_el = header.find("oai:identifier", NS)
            if identifier_el is None or not identifier_el.text:
                return None

            # 提取 arxiv_id: "oai:arXiv.org:2401.12345" -> "2401.12345"
            raw_identifier = identifier_el.text.strip()
            arxiv_id = raw_identifier.replace("oai:arXiv.org:", "").strip()

            datestamp_el = header.find("oai:datestamp", NS)
            datestamp = datestamp_el.text.strip() if datestamp_el is not None and datestamp_el.text else None

            # -- metadata --
            metadata = record_el.find("oai:metadata", NS)
            if metadata is None:
                return None

            # arXiv 格式的 metadata
            arxiv_meta = metadata.find("arXiv:arXiv", NS)
            if arxiv_meta is None:
                # 尝试不带命名空间
                arxiv_meta = metadata.find("{http://arxiv.org/OAI/arXiv/}arXiv")
            if arxiv_meta is None:
                logger.debug(f"[ArxivHarvester] 找不到 arXiv metadata: {arxiv_id}")
                return None

            def _text(el, tag, ns="arXiv"):
                child = el.find(f"{ns}:{tag}", NS)
                if child is None:
                    child = el.find(f"{{http://arxiv.org/OAI/arXiv/}}{tag}")
                return child.text.strip() if child is not None and child.text else None

            title = _text(arxiv_meta, "title") or ""
            abstract = _text(arxiv_meta, "abstract")
            doi = _text(arxiv_meta, "doi")
            journal_ref = _text(arxiv_meta, "journal-ref")
            created = _text(arxiv_meta, "created")    # YYYY-MM-DD
            updated = _text(arxiv_meta, "updated")    # YYYY-MM-DD
            license_text = _text(arxiv_meta, "license")
            comments = _text(arxiv_meta, "comments")
            report_no = _text(arxiv_meta, "report-no")

            # 发表日期优先用 created,其次 datestamp
            pub_date_str = created or datestamp or "1900-01-01"
            try:
                pub_date = date.fromisoformat(pub_date_str[:10])
            except ValueError:
                pub_date = date(1900, 1, 1)

            # 分类(categories)
            categories_el = arxiv_meta.find("arXiv:categories", NS)
            if categories_el is None:
                categories_el = arxiv_meta.find("{http://arxiv.org/OAI/arXiv/}categories")
            categories = []
            if categories_el is not None and categories_el.text:
                categories = categories_el.text.strip().split()

            # 主要 topic(用第一个分类)
            primary_topic_id = categories[0] if categories else None

            # 作者列表
            authors = []
            authors_el = arxiv_meta.find("arXiv:authors", NS)
            if authors_el is None:
                authors_el = arxiv_meta.find("{http://arxiv.org/OAI/arXiv/}authors")
            if authors_el is not None:
                for i, author_el in enumerate(authors_el.findall("arXiv:author", NS) or
                                               authors_el.findall("{http://arxiv.org/OAI/arXiv/}author")):
                    keyname = _text(author_el, "keyname")
                    forenames = _text(author_el, "forenames")
                    if keyname:
                        name = f"{forenames} {keyname}".strip() if forenames else keyname
                    else:
                        name = forenames or ""
                    if name:
                        authors.append(Author(
                            id=ulid_new(),
                            display_name=name,
                        ))

            # 清理 abstract 格式
            if abstract:
                abstract = re.sub(r"\s+", " ", abstract).strip()

            # OA 信息(arXiv 全部 OA)
            oa_url = f"https://arxiv.org/abs/{arxiv_id}"
            open_access = OpenAccessInfo(
                is_oa=True,
                oa_status="green",
                oa_url=oa_url,
                license=license_text,
            )

            # 构建原始 JSON 审计
            raw_jsonb = {
                "arxiv_id": arxiv_id,
                "title": title,
                "abstract": abstract,
                "doi": doi,
                "journal_ref": journal_ref,
                "created": created,
                "updated": updated,
                "categories": categories,
                "license": license_text,
                "comments": comments,
                "report_no": report_no,
                "datestamp": datestamp,
                "authors": [a.display_name for a in authors],
            }

            paper = Paper(
                id=ulid_new(),
                arxiv_id=arxiv_id,
                doi=doi,
                title=title,
                abstract=abstract,
                publication_date=pub_date,
                n_authors=len(authors),
                primary_topic_id=primary_topic_id,
                language="en",
                open_access=open_access,
                raw_jsonb=raw_jsonb,
                source_provider="arxiv",
                first_ingested_at=datetime.now(timezone.utc),
            )
            paper.authors = authors
            paper.references_external = []  # arXiv OAI-PMH 不含引用列表

            return paper

        except Exception as e:
            logger.error(f"[ArxivHarvester] 解析 record 异常: {e}")
            return None

    # ------------------------------------------------------------------
    # HTTP 请求(带重试退避)
    # ------------------------------------------------------------------

    async def _request_with_retry(
        self,
        url: str,
        params: dict,
    ) -> Optional[bytes]:
        """
        发起 HTTP GET 请求,带指数退避重试。

        遇到 503/429 时:
        1. 优先读取 Retry-After header
        2. 否则按 BACKOFF_SCHEDULE 退避
        """
        headers = {"User-Agent": _USER_AGENT}

        for attempt in range(self.max_retries + 1):
            try:
                if self._client:
                    # 注入的 mock client
                    response = await self._client.get(url, params=params, headers=headers)
                else:
                    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                        response = await client.get(url, params=params, headers=headers)

                if response.status_code == 200:
                    return response.content

                elif response.status_code in (429, 503):
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait = float(retry_after)
                        except ValueError:
                            wait = BACKOFF_SCHEDULE[min(attempt, len(BACKOFF_SCHEDULE) - 1)]
                    else:
                        wait = BACKOFF_SCHEDULE[min(attempt, len(BACKOFF_SCHEDULE) - 1)]

                    logger.warning(
                        f"[ArxivHarvester] {response.status_code} 限速, "
                        f"等待 {wait}s (attempt {attempt + 1}/{self.max_retries + 1})"
                    )
                    await asyncio.sleep(wait)
                    continue

                elif response.status_code == 404:
                    logger.warning(f"[ArxivHarvester] 404 Not Found: {url}")
                    return None

                else:
                    logger.warning(
                        f"[ArxivHarvester] 非预期状态码 {response.status_code}, "
                        f"url={url}, attempt={attempt + 1}"
                    )
                    if attempt < self.max_retries:
                        wait = BACKOFF_SCHEDULE[min(attempt, len(BACKOFF_SCHEDULE) - 1)]
                        await asyncio.sleep(wait)
                        continue
                    return None

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                logger.warning(
                    f"[ArxivHarvester] 网络错误: {e}, attempt={attempt + 1}"
                )
                if attempt < self.max_retries:
                    wait = BACKOFF_SCHEDULE[min(attempt, len(BACKOFF_SCHEDULE) - 1)]
                    await asyncio.sleep(wait)
                    continue
                return None

        logger.error(f"[ArxivHarvester] 达到最大重试次数 {self.max_retries}, url={url}")
        return None
