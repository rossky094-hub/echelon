"""
echelon.crawler.normalizer
============================
V14 多源归一化器。

将来自 arXiv / OpenAlex / Crossref / bioRxiv 的不同 JSON 格式
归一化为统一的 Paper schema。

函数:
- normalize_arxiv_record(raw) -> Paper
- normalize_openalex_work(raw) -> Paper
- normalize_crossref_msg(raw) -> Paper
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Optional

from echelon.library.schema import Author, OpenAccessInfo, Paper
from echelon.core.ulid_utils import ulid_new

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# arXiv 归一化
# ---------------------------------------------------------------------------

def normalize_arxiv_record(raw: dict) -> Optional[Paper]:
    """
    将 arXiv 原始 JSON(来自 OAI-PMH 解析后的字典)归一化为 Paper。

    字段映射:
    - arxiv_id → Paper.arxiv_id
    - title → Paper.title
    - abstract → Paper.abstract
    - doi → Paper.doi
    - created → Paper.publication_date
    - authors → Paper.authors
    - categories[0] → Paper.primary_topic_id
    - license → Paper.open_access.license

    Args:
        raw: arXiv OAI-PMH 解析后的字典(由 ArxivHarvester._parse_oai_record 产出的 raw_jsonb)

    Returns:
        Paper 或 None(解析失败)
    """
    try:
        arxiv_id = raw.get("arxiv_id", "")
        title = (raw.get("title") or "").strip()
        abstract = raw.get("abstract") or None
        doi = raw.get("doi") or None
        categories = raw.get("categories", [])
        created = raw.get("created")
        updated = raw.get("updated")
        license_text = raw.get("license")
        authors_raw = raw.get("authors", [])

        if not title:
            logger.debug(f"[normalizer] arXiv record 缺少 title: {arxiv_id}")
            return None

        # 发表日期
        pub_date_str = created or raw.get("datestamp") or "1900-01-01"
        try:
            pub_date = date.fromisoformat(pub_date_str[:10])
        except ValueError:
            pub_date = date(1900, 1, 1)

        # 清理 abstract
        if abstract:
            abstract = re.sub(r"\s+", " ", abstract).strip()

        # 作者
        authors = []
        for name in authors_raw:
            if isinstance(name, str) and name.strip():
                authors.append(Author(id=ulid_new(), display_name=name.strip()))

        # 主 topic
        primary_topic_id = categories[0] if categories else None

        # OA 信息(arXiv 全部 OA)
        open_access = OpenAccessInfo(
            is_oa=True,
            oa_status="green",
            oa_url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
            license=license_text,
        )

        paper = Paper(
            id=ulid_new(),
            arxiv_id=arxiv_id if arxiv_id else None,
            doi=doi,
            title=title,
            abstract=abstract,
            publication_date=pub_date,
            n_authors=len(authors),
            primary_topic_id=primary_topic_id,
            language="en",
            open_access=open_access,
            raw_jsonb=raw,
            source_provider="arxiv",
            first_ingested_at=datetime.now(timezone.utc),
        )
        paper.authors = authors
        return paper

    except Exception as e:
        logger.error(f"[normalizer] normalize_arxiv_record 异常: {e}")
        return None


# ---------------------------------------------------------------------------
# OpenAlex 归一化
# ---------------------------------------------------------------------------

def normalize_openalex_work(raw: dict) -> Optional[Paper]:
    """
    将 OpenAlex Work JSON 归一化为 Paper。

    字段映射:
    - id → Paper.openalex_id (W...)
    - doi → Paper.doi
    - title → Paper.title
    - abstract_inverted_index → Paper.abstract (需重建)
    - publication_date → Paper.publication_date
    - cited_by_count → Paper.cited_by_count
    - primary_topic → Paper.primary_topic_id + subfield + field + domain
    - authorships → Paper.authors
    - open_access → Paper.open_access
    - referenced_works → Paper.references_external

    Args:
        raw: OpenAlex Work JSON dict

    Returns:
        Paper 或 None
    """
    try:
        openalex_id = raw.get("id", "")
        # 清理 ID: "https://openalex.org/W4392199370" -> "W4392199370"
        if openalex_id.startswith("https://openalex.org/"):
            openalex_id = openalex_id[len("https://openalex.org/"):]

        title = (raw.get("title") or raw.get("display_name") or "").strip()
        if not title:
            return None

        doi = raw.get("doi")
        pub_date_str = raw.get("publication_date") or "1900-01-01"
        try:
            pub_date = date.fromisoformat(pub_date_str[:10])
        except ValueError:
            pub_date = date(1900, 1, 1)

        cited_by_count = raw.get("cited_by_count")
        language = raw.get("language")
        is_retracted = bool(raw.get("is_retracted", False))
        is_paratext = bool(raw.get("is_paratext", False))

        # abstract: 从 inverted index 重建
        abstract = None
        aii = raw.get("abstract_inverted_index")
        if aii:
            abstract = _rebuild_abstract(aii)

        # primary topic
        primary_topic_id = None
        primary_subfield_id = None
        primary_field_id = None
        primary_domain_id = None
        pt = raw.get("primary_topic") or {}
        if pt:
            t_id = pt.get("id", "")
            if t_id.startswith("https://openalex.org/"):
                t_id = t_id[len("https://openalex.org/"):]
            primary_topic_id = t_id or None

            sf = pt.get("subfield") or {}
            sf_id = sf.get("id", "")
            if sf_id.startswith("https://openalex.org/"):
                sf_id = sf_id[len("https://openalex.org/"):]
            primary_subfield_id = sf_id or None

            f = pt.get("field") or {}
            f_id = f.get("id", "")
            if f_id.startswith("https://openalex.org/"):
                f_id = f_id[len("https://openalex.org/"):]
            primary_field_id = f_id or None

            d = pt.get("domain") or {}
            d_id = d.get("id", "")
            if d_id.startswith("https://openalex.org/"):
                d_id = d_id[len("https://openalex.org/"):]
            primary_domain_id = d_id or None

        # authors
        authors = []
        for authorship in raw.get("authorships", []):
            author_raw = authorship.get("author") or {}
            a_id = author_raw.get("id", "")
            if a_id.startswith("https://openalex.org/"):
                a_id = a_id[len("https://openalex.org/"):]
            name = author_raw.get("display_name", "")
            if name:
                authors.append(Author(
                    id=ulid_new(),
                    openalex_id=a_id or None,
                    display_name=name,
                ))

        # open_access
        oa_raw = raw.get("open_access") or {}
        open_access = OpenAccessInfo(
            is_oa=bool(oa_raw.get("is_oa", False)),
            oa_status=oa_raw.get("oa_status"),
            oa_url=oa_raw.get("oa_url"),
            license=None,
        )

        # referenced_works → external IDs
        references_external = []
        for ref_id in raw.get("referenced_works", []):
            if ref_id.startswith("https://openalex.org/"):
                ref_id = ref_id[len("https://openalex.org/"):]
            references_external.append(ref_id)

        # venue
        venue_id = None
        primary_location = raw.get("primary_location") or {}
        source = primary_location.get("source") or {}
        if source:
            v_id = source.get("id", "")
            if v_id.startswith("https://openalex.org/"):
                v_id = v_id[len("https://openalex.org/"):]
            venue_id = v_id or None

        # arxiv_id: 从 locations 中找 arXiv source
        arxiv_id = None
        for loc in raw.get("locations", []):
            loc_source = loc.get("source") or {}
            if "arxiv" in str(loc_source.get("display_name", "")).lower():
                landing = loc.get("landing_page_url", "")
                m = re.search(r"arxiv\.org/abs/([^\s/]+)", landing)
                if m:
                    arxiv_id = m.group(1)
                    break
        # 也检查 ids.arxiv
        ids = raw.get("ids") or {}
        if not arxiv_id and ids.get("arxiv"):
            m = re.search(r"arxiv\.org/abs/([^\s/]+)", ids["arxiv"])
            if m:
                arxiv_id = m.group(1)

        paper = Paper(
            id=ulid_new(),
            openalex_id=openalex_id or None,
            doi=doi,
            arxiv_id=arxiv_id,
            title=title,
            abstract=abstract,
            publication_date=pub_date,
            n_authors=len(authors),
            cited_by_count=cited_by_count,
            primary_topic_id=primary_topic_id,
            primary_subfield_id=primary_subfield_id,
            primary_field_id=primary_field_id,
            primary_domain_id=primary_domain_id,
            venue_id=venue_id,
            is_retracted=is_retracted,
            is_paratext=is_paratext,
            language=language,
            open_access=open_access,
            raw_jsonb=raw,
            source_provider="openalex",
            first_ingested_at=datetime.now(timezone.utc),
        )
        paper.authors = authors
        paper.references_external = references_external
        return paper

    except Exception as e:
        logger.error(f"[normalizer] normalize_openalex_work 异常: {e}")
        return None


# ---------------------------------------------------------------------------
# Crossref 归一化
# ---------------------------------------------------------------------------

def normalize_crossref_msg(raw: dict) -> Optional[Paper]:
    """
    将 Crossref API message JSON 归一化为 Paper。

    字段映射:
    - DOI → Paper.doi
    - title[0] → Paper.title
    - abstract → Paper.abstract
    - issued.date-parts → Paper.publication_date
    - author → Paper.authors
    - reference → Paper.references_external

    Args:
        raw: Crossref /works/{doi} 返回的 message dict

    Returns:
        Paper 或 None
    """
    try:
        doi = raw.get("DOI", "").strip()

        # title
        titles = raw.get("title", [])
        if not titles:
            return None
        title = titles[0].strip() if isinstance(titles[0], str) else str(titles[0]).strip()
        if not title:
            return None

        # abstract
        abstract = raw.get("abstract")
        if abstract:
            # 去除 JATS 标签
            abstract = re.sub(r"<[^>]+>", " ", abstract)
            abstract = re.sub(r"\s+", " ", abstract).strip()
            if not abstract:
                abstract = None

        # publication_date
        pub_date = None
        issued = raw.get("issued") or raw.get("published") or {}
        date_parts = issued.get("date-parts", [[]])
        if date_parts and date_parts[0]:
            parts = date_parts[0]
            year = parts[0] if len(parts) > 0 else 1900
            month = parts[1] if len(parts) > 1 else 1
            day = parts[2] if len(parts) > 2 else 1
            try:
                pub_date = date(year, month, day)
            except ValueError:
                pub_date = date(year, 1, 1)
        if pub_date is None:
            pub_date = date(1900, 1, 1)

        # authors
        authors = []
        for author_raw in raw.get("author", []):
            family = author_raw.get("family", "")
            given = author_raw.get("given", "")
            orcid = author_raw.get("ORCID", "")
            if orcid:
                orcid = orcid.replace("http://orcid.org/", "").replace("https://orcid.org/", "")
            name = f"{given} {family}".strip() if given else family
            if name:
                authors.append(Author(
                    id=ulid_new(),
                    orcid=orcid or None,
                    display_name=name,
                ))

        # references
        references_external = []
        for ref in raw.get("reference", []):
            ref_doi = ref.get("DOI", "")
            if ref_doi:
                references_external.append(ref_doi)

        # cited_by_count
        cited_by_count = raw.get("is-referenced-by-count")

        # license
        license_text = None
        for lic in raw.get("license", []):
            url = lic.get("URL", "")
            if "creativecommons" in url.lower():
                if "by-nc" in url.lower():
                    license_text = "cc-by-nc"
                elif "by/" in url.lower():
                    license_text = "cc-by"
                else:
                    license_text = "cc"
                break

        open_access = OpenAccessInfo(
            is_oa=bool(license_text and "cc" in license_text),
            oa_status="gold" if license_text else "closed",
            license=license_text,
        )

        paper = Paper(
            id=ulid_new(),
            doi=doi or None,
            title=title,
            abstract=abstract,
            publication_date=pub_date,
            n_authors=len(authors),
            cited_by_count=cited_by_count,
            open_access=open_access,
            raw_jsonb=raw,
            source_provider="crossref",
            first_ingested_at=datetime.now(timezone.utc),
        )
        paper.authors = authors
        paper.references_external = references_external
        return paper

    except Exception as e:
        logger.error(f"[normalizer] normalize_crossref_msg 异常: {e}")
        return None


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _rebuild_abstract(abstract_inverted_index: dict) -> str:
    """
    从 OpenAlex abstract_inverted_index 重建 abstract 文本。

    格式: {"word": [position, ...], ...}
    """
    if not abstract_inverted_index:
        return ""
    try:
        max_pos = max(
            pos
            for positions in abstract_inverted_index.values()
            for pos in positions
        )
        words = [""] * (max_pos + 1)
        for word, positions in abstract_inverted_index.items():
            for pos in positions:
                if 0 <= pos <= max_pos:
                    words[pos] = word
        return " ".join(w for w in words if w)
    except Exception:
        return ""
