"""
Step 1 多数据源 enrich: Semantic Scholar + Crossref + OpenAlex

Semantic Scholar Graph API (需 API Key):
  GET https://api.semanticscholar.org/graph/v1/paper/{paper_id}
  Header: x-api-key
  限速: 1 request/second (全端点累计, 见 _s2_rate_limit_wait)

无 S2 API Key 且 V14B_SKIP_S2_WITHOUT_KEY=true 时自动跳过 S2。
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional

import httpx

from echelon.crawler.crossref_harvester import CrossrefHarvester
from echelon.library.schema import Paper
from echelon.v14b.config import (
    OPENALEX_EMAIL,
    OPENALEX_MAX_RETRIES,
    OPENALEX_POLITE_DELAY,
    OPENALEX_ENRICH_CONCURRENCY,
    CROSSREF_EMAIL,
    CROSSREF_DELAY,
    SEMANTIC_SCHOLAR_API_KEY,
    S2_DELAY,
    S2_MIN_INTERVAL,
    S2_MAX_RETRIES,
    ENRICH_PROVIDERS,
    SKIP_S2_WITHOUT_KEY,
    USE_OPENALEX,
    ENRICH_PARALLEL_CR_OA,
)
from echelon.v14b.id_normalization import (
    classify_external_id,
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_work_id,
    normalize_s2_paper_id,
)

_OA_SEMAPHORE: Optional[asyncio.Semaphore] = None
_OA_DISABLED_UNTIL: float = 0.0
_OA_429_STREAK: int = 0

# S2 全进程共享限速 (1 req/s, 跨并发 worker 累计)
_S2_RATE_LOCK: Optional[asyncio.Lock] = None
_S2_LAST_REQUEST_MONO: float = 0.0


def _openalex_semaphore() -> asyncio.Semaphore:
    global _OA_SEMAPHORE
    if _OA_SEMAPHORE is None:
        _OA_SEMAPHORE = asyncio.Semaphore(OPENALEX_ENRICH_CONCURRENCY)
    return _OA_SEMAPHORE

logger = logging.getLogger("echelon.v14b.enrich_providers")

_S2_BASE = "https://api.semanticscholar.org/graph/v1"
_S2_FIELDS = (
    "paperId,externalIds,url,title,abstract,year,publicationDate,"
    "authors.authorId,authors.name,openAccessPdf,"
    "citationCount,referenceCount,"
    "fieldsOfStudy,s2FieldsOfStudy,"
    "references.paperId,references.externalIds"
)


def effective_enrich_providers(has_doi: bool = False) -> list[str]:
    """无 S2 Key / OpenAlex 熔断时自动裁剪数据源; 顺序遵循 V14B_ENRICH_PROVIDERS."""
    global _OA_DISABLED_UNTIL
    allowed = {"s2", "crossref", "openalex"}
    providers: list[str] = []
    for p in ENRICH_PROVIDERS:
        name = p.strip().lower()
        if name not in allowed or name in providers:
            continue
        if name == "s2" and SKIP_S2_WITHOUT_KEY and not SEMANTIC_SCHOLAR_API_KEY:
            continue
        providers.append(name)
    oa_ok = USE_OPENALEX and time.time() >= _OA_DISABLED_UNTIL
    if not oa_ok:
        providers = [p for p in providers if p != "openalex"]
    if not providers:
        providers = ["crossref"] if not oa_ok else ["crossref", "openalex"]
    # 纯 arXiv 且无 OpenAlex: 仍可用 S2 / Crossref(arXiv id)
    if not has_doi and not oa_ok:
        fallback = [p for p in providers if p in ("s2", "crossref")]
        return fallback
    return providers


def _note_openalex_429() -> None:
    global _OA_429_STREAK, _OA_DISABLED_UNTIL
    _OA_429_STREAK += 1
    if _OA_429_STREAK >= 3:
        _OA_DISABLED_UNTIL = time.time() + 1800
        logger.warning(
            "OpenAlex 连续 429,暂停 30 分钟; 有 DOI 的篇目仅用 Crossref 加速"
        )


def _clean_doi(doi: Optional[str]) -> Optional[str]:
    return normalize_doi(doi)


def _clean_arxiv(arxiv_id: Optional[str]) -> Optional[str]:
    return normalize_arxiv_id(arxiv_id)


def _ref_external_id(ref: dict) -> Optional[str]:
    ext = ref.get("externalIds") or {}
    if ext.get("DOI"):
        doi = normalize_doi(ext["DOI"])
        return f"DOI:{doi}" if doi else None
    if ext.get("ArXiv"):
        aid = normalize_arxiv_id(ext["ArXiv"])
        return f"ARXIV:{aid}" if aid else None
    pid = ref.get("paperId")
    if pid:
        sid = normalize_s2_paper_id(pid)
        return f"S2:{sid}" if sid else None
    return None


def paper_to_enrich_result(paper_id: str, paper: Paper) -> dict:
    openalex_id = normalize_openalex_work_id(paper.openalex_id)
    references = [
        {
            "citing_paper_id": paper_id,
            "cited_paper_id_external": ref_id,
            "cited_paper_id_provider": classify_external_id(ref_id)[0],
            "cited_paper_id_norm": classify_external_id(ref_id)[1],
        }
        for ref_id in (paper.references_external or [])
        if ref_id
    ]
    return {
        "updates": {
            "paper_id": paper_id,
            "openalex_id": openalex_id,
            "s2_paper_id": None,
            "cited_by_count": paper.cited_by_count or 0,
            "primary_topic_id": paper.primary_topic_id,
            "primary_subfield_id": paper.primary_subfield_id,
            "primary_field_id": paper.primary_field_id,
            "primary_domain_id": paper.primary_domain_id,
        },
        "references": references,
        "topics": [],
        "affiliations": [],
    }


def parse_s2_paper(paper_id: str, data: dict) -> dict:
    ext = data.get("externalIds") or {}
    s2_id = data.get("paperId")

    fields = data.get("s2FieldsOfStudy") or data.get("fieldsOfStudy") or []
    topic_name = None
    if fields:
        first = fields[0]
        topic_name = first.get("category") if isinstance(first, dict) else str(first)

    topic_id = None
    if topic_name:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", topic_name.lower())[:40]
        topic_id = f"S2F:{slug}"

    references = []
    for ref in data.get("references") or []:
        ref_ext = _ref_external_id(ref)
        if ref_ext:
            references.append({
                "citing_paper_id": paper_id,
                "cited_paper_id_external": ref_ext,
                "cited_paper_id_provider": classify_external_id(ref_ext)[0],
                "cited_paper_id_norm": classify_external_id(ref_ext)[1],
            })

    return {
        "updates": {
            "paper_id": paper_id,
            "openalex_id": normalize_openalex_work_id(ext.get("OpenAlex")),
            "s2_paper_id": normalize_s2_paper_id(s2_id),
            "cited_by_count": data.get("citationCount") or 0,
            "primary_topic_id": topic_id,
            "primary_subfield_id": None,
            "primary_field_id": None,
            "primary_domain_id": None,
        },
        "references": references,
        "topics": (
            [{
                "topic_id": topic_id,
                "topic_name": topic_name,
                "subfield_id": None,
                "field_id": None,
                "domain_id": None,
                "subfield_name": None,
                "field_name": None,
                "domain_name": None,
            }]
            if topic_id and topic_name
            else []
        ),
        "affiliations": [],
    }


def _s2_rate_lock() -> asyncio.Lock:
    global _S2_RATE_LOCK
    if _S2_RATE_LOCK is None:
        _S2_RATE_LOCK = asyncio.Lock()
    return _S2_RATE_LOCK


async def _s2_rate_limit_wait() -> None:
    """全端点累计 1 req/s: 任意并发 enrich 共享间隔."""
    global _S2_LAST_REQUEST_MONO
    async with _s2_rate_lock():
        now = time.monotonic()
        wait = S2_MIN_INTERVAL - (now - _S2_LAST_REQUEST_MONO)
        if wait > 0:
            await asyncio.sleep(wait)
        _S2_LAST_REQUEST_MONO = time.monotonic()


async def fetch_semantic_scholar(
    client: httpx.AsyncClient,
    arxiv_id: Optional[str],
    doi: Optional[str],
) -> Optional[dict]:
    """
    按 arXiv 或 DOI 查询 Semantic Scholar Graph API。

    - 认证: Header ``x-api-key`` (SEMANTIC_SCHOLAR_API_KEY)
    - 限速: 全局 ``_s2_rate_limit_wait()`` 保证 1 request/second
    - 文档: https://api.semanticscholar.org/api-docs/
    """
    if SKIP_S2_WITHOUT_KEY and not SEMANTIC_SCHOLAR_API_KEY:
        return None

    clean_arxiv = _clean_arxiv(arxiv_id)
    clean_doi = _clean_doi(doi)
    paper_ids = []
    if clean_arxiv:
        paper_ids.append(f"ARXIV:{clean_arxiv}")
    if clean_doi:
        paper_ids.append(f"DOI:{clean_doi}")

    headers: dict[str, str] = {}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    else:
        logger.debug("S2: 无 API Key, 限速更严且遇 429 即放弃")

    max_retries = S2_MAX_RETRIES if SEMANTIC_SCHOLAR_API_KEY else 1

    for pid in paper_ids:
        url = f"{_S2_BASE}/paper/{pid}"
        for attempt in range(max_retries):
            try:
                await _s2_rate_limit_wait()
                resp = await client.get(
                    url,
                    params={"fields": _S2_FIELDS},
                    headers=headers,
                    timeout=30.0,
                )
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 404:
                    break
                if resp.status_code == 429:
                    if not SEMANTIC_SCHOLAR_API_KEY:
                        logger.debug("S2 429 without API key, skip")
                        return None
                    wait = max(S2_DELAY, min(60, 2 ** attempt * 5))
                    logger.warning(
                        "Semantic Scholar 429 (%s), waiting %.1fs (attempt %d/%d)",
                        pid, wait, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning(
                    "S2 HTTP %s for %s: %s",
                    resp.status_code, pid, resp.text[:200],
                )
                await asyncio.sleep(S2_DELAY)
            except Exception as exc:
                logger.warning("S2 fetch error (%s): %s", pid, exc)
                await asyncio.sleep(S2_DELAY)
    return None


async def fetch_crossref_paper(
    arxiv_id: Optional[str],
    doi: Optional[str],
) -> Optional[Paper]:
    harvester = CrossrefHarvester(mailto=CROSSREF_EMAIL, request_delay=CROSSREF_DELAY)
    clean_doi = _clean_doi(doi)
    clean_arxiv = _clean_arxiv(arxiv_id)
    if clean_doi:
        return await harvester.fetch_by_doi(clean_doi)
    if clean_arxiv:
        return await harvester.fetch_by_arxiv_id(clean_arxiv)
    return None


async def fetch_openalex(
    client: httpx.AsyncClient,
    arxiv_id: Optional[str],
    doi: Optional[str],
    delay: float = OPENALEX_POLITE_DELAY,
) -> Optional[dict]:
    if not USE_OPENALEX or time.time() < _OA_DISABLED_UNTIL:
        return None
    lookup_urls: list[str] = []
    clean_doi = _clean_doi(doi)
    clean_arxiv = _clean_arxiv(arxiv_id)
    if clean_doi:
        lookup_urls.append(
            f"https://api.openalex.org/works/doi:{clean_doi}?mailto={OPENALEX_EMAIL}"
        )
    if clean_arxiv:
        lookup_urls.append(
            f"https://api.openalex.org/works?filter=locations.landing_page_url:"
            f"https://arxiv.org/abs/{clean_arxiv}&per_page=1&mailto={OPENALEX_EMAIL}"
        )
    for url in lookup_urls:
        for attempt in range(OPENALEX_MAX_RETRIES):
            try:
                async with _openalex_semaphore():
                    resp = await client.get(url)
                if resp.status_code == 200:
                    global _OA_429_STREAK
                    _OA_429_STREAK = 0
                    data = resp.json()
                    if isinstance(data, dict) and "results" in data:
                        results = data.get("results") or []
                        if not results:
                            continue
                        await asyncio.sleep(delay)
                        return results[0]
                    await asyncio.sleep(delay)
                    return data
                if resp.status_code == 404:
                    break
                if resp.status_code == 429:
                    _note_openalex_429()
                    if time.time() < _OA_DISABLED_UNTIL:
                        return None
                    wait = min(12, 2 ** attempt * 3)
                    logger.warning("OpenAlex 429, waiting %ds", wait)
                    await asyncio.sleep(wait)
                    continue
            except Exception as exc:
                logger.warning("OpenAlex error (attempt %d): %s", attempt + 1, exc)
                await asyncio.sleep(1)
    return None


def _pick_best_result(
    candidates: list[tuple[dict, str]],
) -> tuple[Optional[dict], Optional[str]]:
    """优先引用边多的结果；同数量时优先 openalex."""
    if not candidates:
        return None, None
    order = {"openalex": 0, "crossref": 1, "s2": 2}

    def score(item: tuple[dict, str]) -> tuple[int, int]:
        payload, name = item
        nrefs = len(payload.get("references") or [])
        return (-nrefs, order.get(name, 9))

    return min(candidates, key=score)


async def _fetch_parallel_crossref_openalex(
    paper: dict,
) -> tuple[Optional[dict], Optional[str]]:
    """Crossref + OpenAlex 并行，取最优结果."""
    from echelon.v14b.step1_enrich import parse_openalex_work

    paper_id = paper["id"]
    arxiv_id = paper.get("arxiv_id")
    doi = paper.get("doi")

    async def try_crossref() -> tuple[Optional[dict], Optional[str]]:
        cr = await fetch_crossref_paper(arxiv_id, doi)
        if cr:
            return paper_to_enrich_result(paper_id, cr), "crossref"
        return None, None

    async def try_openalex() -> tuple[Optional[dict], Optional[str]]:
        async with httpx.AsyncClient(timeout=45.0) as client:
            raw = await fetch_openalex(client, arxiv_id, doi)
            if raw:
                return parse_openalex_work(paper_id, raw), "openalex"
        return None, None

    results = await asyncio.gather(
        try_crossref(),
        try_openalex(),
        return_exceptions=True,
    )
    candidates: list[tuple[dict, str]] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        if r[0]:
            candidates.append(r)
    return _pick_best_result(candidates)


async def fetch_enrich_payload(
    paper: dict,
    providers: Optional[list[str]] = None,
) -> tuple[Optional[dict], Optional[str]]:
    from echelon.v14b.step1_enrich import parse_openalex_work

    doi = paper.get("doi")
    has_doi = bool(_clean_doi(doi))
    providers = providers or effective_enrich_providers(has_doi=has_doi)
    paper_id = paper["id"]
    arxiv_id = paper.get("arxiv_id")

    if not providers:
        return None, None

    names = {p.strip().lower() for p in providers}

    # 可选并行 (默认关闭,避免 OpenAlex 429 雪崩)
    if (
        ENRICH_PARALLEL_CR_OA
        and "s2" not in names
        and "crossref" in names
        and "openalex" in names
    ):
        return await _fetch_parallel_crossref_openalex(paper)

    # 顺序遵循 V14B_ENRICH_PROVIDERS (如 s2,crossref,openalex)
    ordered = list(providers)

    async with httpx.AsyncClient(timeout=45.0) as client:
        for name in ordered:
            name = name.strip().lower()
            try:
                if name == "s2":
                    raw = await fetch_semantic_scholar(client, arxiv_id, doi)
                    if raw:
                        return parse_s2_paper(paper_id, raw), "s2"
                elif name == "crossref":
                    cr_paper = await fetch_crossref_paper(arxiv_id, doi)
                    if cr_paper:
                        return paper_to_enrich_result(paper_id, cr_paper), "crossref"
                elif name == "openalex":
                    raw = await fetch_openalex(client, arxiv_id, doi)
                    if raw:
                        return parse_openalex_work(paper_id, raw), "openalex"
            except Exception as exc:
                logger.warning("Provider %s failed for %s: %s", name, paper_id, exc)
    return None, None
