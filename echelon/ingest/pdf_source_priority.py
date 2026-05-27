"""
echelon.ingest.pdf_source_priority
====================================
PDF 来源优先级选择。

[修订自 AUDIT-082]
V11.1 问题:PDF 获取直接依赖 Unpaywall(需要 DOI),导致 arXiv preprint
无法通过 Unpaywall 获取(arXiv preprint 在发表前无 DOI),形成 preprint
黑洞——尤其是光学/物理领域大量高质量预印本无法进入语料库。

V11.2 修复:PDF 来源优先级:
    arXiv > Unpaywall > Crossref

  - ``PDF_SOURCE_PRIORITY``:优先级常量(数值越小优先级越高)
  - ``select_pdf_source(paper) -> str | None``:
      按优先级选择最佳 PDF URL;返回 URL 字符串或 None(无可用来源)

参考: V11.2 白皮书 §3.3.2;AUDIT-082
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 优先级常量 [AUDIT-082]
# ---------------------------------------------------------------------------

PDF_SOURCE_PRIORITY: dict[str, int] = {
    "arxiv": 1,        # 最高优先级:arXiv preprint 直接下载
    "unpaywall": 2,    # 次优:Unpaywall open access
    "crossref": 3,     # 最低:Crossref landing page(可能需要机构访问)
}
"""PDF 来源优先级常量。数值越小优先级越高。[修订自 AUDIT-082]"""

# arXiv ID 正则:匹配 2312.00001 或 cs.AI/0101001 等格式
_ARXIV_ID_RE = re.compile(
    r"(?:arxiv[:/]?\s*|abs/)?((?:\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# arXiv URL 构建
# ---------------------------------------------------------------------------


def _build_arxiv_pdf_url(arxiv_id: str) -> str:
    """将 arXiv ID 转为 PDF 直链。

    [修订自 AUDIT-082]

    Examples
    --------
    ::

        _build_arxiv_pdf_url("2312.00001") -> "https://arxiv.org/pdf/2312.00001"
        _build_arxiv_pdf_url("2312.00001v2") -> "https://arxiv.org/pdf/2312.00001v2"
    """
    arxiv_id = arxiv_id.strip()
    return f"https://arxiv.org/pdf/{arxiv_id}"


def _extract_arxiv_id(text: str) -> str | None:
    """从任意文本中提取 arXiv ID。"""
    if not text:
        return None
    m = _ARXIV_ID_RE.search(text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------


def select_pdf_source(paper: Any) -> str | None:
    """按优先级(arXiv > Unpaywall > Crossref)选择最佳 PDF URL。

    [修订自 AUDIT-082]

    接受 Paper 对象(有 .source_url/.doi 等属性)或 dict。

    Parameters
    ----------
    paper:
        ``echelon.schema.paper.Paper`` 对象或包含以下字段的 dict:
        - ``source_url``:当前来源 URL(可能是 arXiv/OpenAlex/Unpaywall 链接)
        - ``doi``:DOI 字符串(用于 Unpaywall/Crossref 查询)
        - ``openalex_id``:OpenAlex Work ID
        - ``extra``:包含 ``unpaywall_url``、``crossref_url`` 等字段的 dict

    Returns
    -------
    str | None
        最佳 PDF URL;若无可用来源返回 None。

    Priority:
        1. arXiv PDF(从 source_url 或 doi 中提取 arXiv ID)
        2. Unpaywall open access URL(从 extra["unpaywall_url"] 或 doi 构建)
        3. Crossref landing page(从 doi 构建)

    Notes
    -----
    Pilot 实现不做真实 HTTP 请求,仅构建 URL。
    生产环境中应对每个 URL 进行 HEAD 请求验证可达性。
    """
    # 规范化访问接口
    if isinstance(paper, dict):
        source_url: str | None = paper.get("source_url")
        doi: str | None = paper.get("doi")
        openalex_id: str | None = paper.get("openalex_id")
        extra: dict = paper.get("extra") or {}
    else:
        source_url = getattr(paper, "source_url", None)
        doi = getattr(paper, "doi", None)
        openalex_id = getattr(paper, "openalex_id", None)
        extra = getattr(paper, "extra", {}) or {}

    # ── Priority 1: arXiv ──────────────────────────────────────────────────
    arxiv_url = _try_arxiv(source_url, doi, openalex_id, extra)
    if arxiv_url:
        logger.debug(
            "[AUDIT-082] select_pdf_source: chose arXiv URL=%r for doi=%r",
            arxiv_url,
            doi,
        )
        return arxiv_url

    # ── Priority 2: Unpaywall ──────────────────────────────────────────────
    unpaywall_url = _try_unpaywall(doi, extra)
    if unpaywall_url:
        logger.debug(
            "[AUDIT-082] select_pdf_source: chose Unpaywall URL=%r for doi=%r",
            unpaywall_url,
            doi,
        )
        return unpaywall_url

    # ── Priority 3: Crossref ───────────────────────────────────────────────
    crossref_url = _try_crossref(doi, extra)
    if crossref_url:
        logger.debug(
            "[AUDIT-082] select_pdf_source: chose Crossref URL=%r for doi=%r",
            crossref_url,
            doi,
        )
        return crossref_url

    logger.info(
        "[AUDIT-082] select_pdf_source: no PDF source available for doi=%r source_url=%r",
        doi,
        source_url,
    )
    return None


# ---------------------------------------------------------------------------
# 各来源尝试函数
# ---------------------------------------------------------------------------


def _try_arxiv(
    source_url: str | None,
    doi: str | None,
    openalex_id: str | None,
    extra: dict,
) -> str | None:
    """尝试构建 arXiv PDF URL。[AUDIT-082]"""
    candidates = [
        source_url,
        doi,
        extra.get("arxiv_id"),
        extra.get("arxiv_url"),
    ]

    for text in candidates:
        if not text:
            continue
        # 直接 arXiv URL
        if "arxiv.org" in str(text):
            arxiv_id = _extract_arxiv_id(str(text))
            if arxiv_id:
                return _build_arxiv_pdf_url(arxiv_id)
        # DOI 中可能包含 arXiv ID(如 10.48550/arXiv.2312.00001)
        if doi and "arxiv" in doi.lower():
            arxiv_id = _extract_arxiv_id(doi)
            if arxiv_id:
                return _build_arxiv_pdf_url(arxiv_id)

    # extra 中显式指定的 arxiv_id
    arxiv_id_explicit = extra.get("arxiv_id")
    if arxiv_id_explicit:
        return _build_arxiv_pdf_url(str(arxiv_id_explicit))

    return None


def _try_unpaywall(doi: str | None, extra: dict) -> str | None:
    """尝试从 extra 或 DOI 构建 Unpaywall PDF URL。[AUDIT-082]"""
    # extra 中已有缓存 URL
    unpaywall_url = extra.get("unpaywall_url") or extra.get("oa_url")
    if unpaywall_url:
        return str(unpaywall_url)

    # Pilot:若有 DOI,构建 Unpaywall API 查询 URL(生产需实际请求)
    # 实际 Unpaywall API: https://api.unpaywall.org/v2/{doi}?email=...
    # 这里返回 None 表示 Pilot 不做真实请求,由调用层处理
    return None


def _try_crossref(doi: str | None, extra: dict) -> str | None:
    """尝试从 DOI 构建 Crossref 来源 URL。[AUDIT-082]"""
    crossref_url = extra.get("crossref_url")
    if crossref_url:
        return str(crossref_url)

    if doi:
        # Crossref DOI landing page(生产需验证可达性)
        doi_clean = doi.strip().lstrip("https://doi.org/").lstrip("doi:")
        return f"https://doi.org/{doi_clean}"

    return None


# ---------------------------------------------------------------------------
# 批量处理
# ---------------------------------------------------------------------------


def select_pdf_sources_batch(
    papers: list[Any],
) -> list[dict[str, Any]]:
    """批量为论文列表选择 PDF 来源。

    [修订自 AUDIT-082]

    Returns
    -------
    list[dict]
        每条记录包含 ``paper_id``、``pdf_url``(或 None)、``source``(来源名称)。
    """
    results = []
    for paper in papers:
        if isinstance(paper, dict):
            pid = paper.get("id") or paper.get("paper_id", "unknown")
        else:
            pid = getattr(paper, "id", None) or getattr(paper, "paper_id", "unknown")

        pdf_url = select_pdf_source(paper)
        source_name: str | None = None
        if pdf_url:
            if "arxiv.org" in pdf_url:
                source_name = "arxiv"
            elif "unpaywall" in pdf_url or (
                isinstance(paper, dict) and paper.get("extra", {}).get("unpaywall_url")
            ):
                source_name = "unpaywall"
            else:
                source_name = "crossref"

        results.append(
            {
                "paper_id": pid,
                "pdf_url": pdf_url,
                "source": source_name,
            }
        )
    return results
