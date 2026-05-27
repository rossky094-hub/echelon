"""
tests/test_v14_library_crawler.py
===================================
V14 统一论文爬虫库单元测试 + 集成测试。

测试覆盖:
- Paper schema 验证
- normalize_* 归一化函数
- DeduplicationService
- IngestionJob 生命周期
- HWM 逻辑
- ArxivHarvester OAI-PMH 解析(fixture XML)
- ArxivHarvester 429 退避
- OpenAlexHarvester 补元数据
- CrossrefHarvester DOI 查询
- API endpoints (mock DB)
- 真实集成测试 (1 篇真 arXiv)

运行:
    # 全部测试(慢)
    pytest tests/test_v14_library_crawler.py -v

    # 跳过真实网络测试
    pytest tests/test_v14_library_crawler.py -v -m "not real_network"
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

# ---------------------------------------------------------------------------
# 路径设置
# ---------------------------------------------------------------------------

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echelon.library.schema import (
    Author,
    IngestionJob,
    IngestionHWM,
    JobStatusEnum,
    OpenAccessInfo,
    Paper,
    PaperReference,
    ProviderEnum,
    TopicHierarchy,
)
from echelon.library.db import (
    get_db_stats,
    get_hwm_v14,
    get_session,
    init_db,
    set_hwm_v14,
    upsert_author,
    upsert_ingestion_job,
    upsert_paper,
    upsert_paper_references,
)
from echelon.crawler.normalizer import (
    normalize_arxiv_record,
    normalize_crossref_msg,
    normalize_openalex_work,
    _rebuild_abstract,
)
from echelon.crawler.dedup import DeduplicationService, _jaccard, _tokenize
from echelon.core.ulid_utils import ulid_new


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db():
    """临时 SQLite 数据库(每次测试独立)"""
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
def sample_paper():
    """样本 Paper 对象"""
    return Paper(
        id=ulid_new(),
        arxiv_id="2401.12345",
        doi="10.1234/test.2024",
        title="Test Optical Paper on Metasurfaces",
        abstract="We study optical properties of metasurfaces using advanced techniques.",
        publication_date=date(2024, 1, 15),
        n_authors=3,
        cited_by_count=42,
        primary_topic_id="physics.optics",
        language="en",
        source_provider="arxiv",
        open_access=OpenAccessInfo(is_oa=True, oa_status="green",
                                    oa_url="https://arxiv.org/abs/2401.12345"),
    )


@pytest.fixture
def arxiv_oai_xml_single():
    """arXiv OAI-PMH ListRecords 单条 record XML fixture"""
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:arXiv="http://arxiv.org/OAI/arXiv/"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <responseDate>2024-01-15T12:00:00Z</responseDate>
  <request verb="ListRecords" set="physics:physics.optics"
           metadataPrefix="arXiv">https://export.arxiv.org/oai2</request>
  <ListRecords>
    <record>
      <header>
        <identifier>oai:arXiv.org:2401.12345</identifier>
        <datestamp>2024-01-15</datestamp>
        <setSpec>physics:physics.optics</setSpec>
      </header>
      <metadata>
        <arXiv:arXiv xsi:schemaLocation="http://arxiv.org/OAI/arXiv/ http://arxiv.org/OAI/arXiv.xsd">
          <arXiv:id>2401.12345</arXiv:id>
          <arXiv:created>2024-01-15</arXiv:created>
          <arXiv:updated>2024-01-16</arXiv:updated>
          <arXiv:authors>
            <arXiv:author>
              <arXiv:keyname>Smith</arXiv:keyname>
              <arXiv:forenames>John A.</arXiv:forenames>
            </arXiv:author>
            <arXiv:author>
              <arXiv:keyname>Zhang</arXiv:keyname>
              <arXiv:forenames>Wei</arXiv:forenames>
            </arXiv:author>
          </arXiv:authors>
          <arXiv:title>Advanced Optical Metasurface Design Using Neural Networks</arXiv:title>
          <arXiv:categories>physics.optics cs.NE</arXiv:categories>
          <arXiv:license>http://arxiv.org/licenses/nonexclusive-distrib/1.0/</arXiv:license>
          <arXiv:abstract>  We present a novel approach to designing optical metasurfaces
  using deep learning techniques. Our method achieves unprecedented control
  over wavefront manipulation.  </arXiv:abstract>
          <arXiv:doi>10.1234/optics.2024.001</arXiv:doi>
        </arXiv:arXiv>
      </metadata>
    </record>
  </ListRecords>
</OAI-PMH>"""


@pytest.fixture
def arxiv_oai_xml_with_token():
    """arXiv OAI-PMH 带 resumptionToken 的 XML fixture"""
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:arXiv="http://arxiv.org/OAI/arXiv/"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <responseDate>2024-01-15T12:00:00Z</responseDate>
  <ListRecords>
    <record>
      <header>
        <identifier>oai:arXiv.org:2401.99999</identifier>
        <datestamp>2024-01-15</datestamp>
      </header>
      <metadata>
        <arXiv:arXiv xsi:schemaLocation="http://arxiv.org/OAI/arXiv/ http://arxiv.org/OAI/arXiv.xsd">
          <arXiv:id>2401.99999</arXiv:id>
          <arXiv:created>2024-01-15</arXiv:created>
          <arXiv:authors>
            <arXiv:author>
              <arXiv:keyname>Doe</arXiv:keyname>
              <arXiv:forenames>Jane</arXiv:forenames>
            </arXiv:author>
          </arXiv:authors>
          <arXiv:title>Second Paper in Batch with ResumptionToken</arXiv:title>
          <arXiv:categories>physics.optics</arXiv:categories>
          <arXiv:abstract>This is the second paper in a batch test.</arXiv:abstract>
        </arXiv:arXiv>
      </metadata>
    </record>
    <resumptionToken cursor="1000" completeListSize="5000">some-token-abc123</resumptionToken>
  </ListRecords>
</OAI-PMH>"""


@pytest.fixture
def arxiv_oai_xml_empty():
    """arXiv OAI-PMH 空结果集(无 resumptionToken)"""
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:arXiv="http://arxiv.org/OAI/arXiv/"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <responseDate>2024-01-15T12:00:00Z</responseDate>
  <ListRecords>
    <record>
      <header>
        <identifier>oai:arXiv.org:2401.00001</identifier>
        <datestamp>2024-01-15</datestamp>
      </header>
      <metadata>
        <arXiv:arXiv xsi:schemaLocation="http://arxiv.org/OAI/arXiv/ http://arxiv.org/OAI/arXiv.xsd">
          <arXiv:id>2401.00001</arXiv:id>
          <arXiv:created>2024-01-15</arXiv:created>
          <arXiv:authors>
            <arXiv:author>
              <arXiv:keyname>Test</arXiv:keyname>
            </arXiv:author>
          </arXiv:authors>
          <arXiv:title>Final Paper No Token</arXiv:title>
          <arXiv:categories>physics.optics</arXiv:categories>
          <arXiv:abstract>Final paper abstract.</arXiv:abstract>
        </arXiv:arXiv>
      </metadata>
    </record>
  </ListRecords>
</OAI-PMH>"""


# ===========================================================================
# 单元测试: Paper Schema 验证
# ===========================================================================

class TestPaperSchema:

    def test_paper_schema_basic_validation(self):
        """test_paper_schema_validation: 基础字段验证"""
        paper = Paper(
            title="Test Paper",
            publication_date=date(2024, 1, 1),
        )
        assert paper.title == "Test Paper"
        assert paper.publication_date == date(2024, 1, 1)
        assert paper.id  # ULID 自动生成
        assert len(paper.id) == 26

    def test_paper_doi_normalization(self):
        """DOI 自动规范化(去除 URL 前缀)"""
        paper = Paper(
            title="Test",
            publication_date=date(2024, 1, 1),
            doi="https://doi.org/10.1234/test",
        )
        assert paper.doi == "10.1234/test"

    def test_paper_doi_normalization_dx(self):
        """DOI dx.doi.org 前缀去除"""
        paper = Paper(
            title="Test",
            publication_date=date(2024, 1, 1),
            doi="http://dx.doi.org/10.5678/example",
        )
        assert paper.doi == "10.5678/example"

    def test_paper_arxiv_id_normalization(self):
        """arXiv ID 规范化(去除前缀和版本号)"""
        paper = Paper(
            title="Test",
            publication_date=date(2024, 1, 1),
            arxiv_id="arxiv:2401.12345v2",
        )
        assert paper.arxiv_id == "2401.12345"

    def test_paper_arxiv_id_url_normalization(self):
        """arXiv ID 从 URL 中提取"""
        paper = Paper(
            title="Test",
            publication_date=date(2024, 1, 1),
            arxiv_id="https://arxiv.org/abs/2401.12345",
        )
        assert paper.arxiv_id == "2401.12345"

    def test_paper_first_ingested_at_auto_set(self):
        """first_ingested_at 自动设置"""
        paper = Paper(title="Test", publication_date=date(2024, 1, 1))
        assert paper.first_ingested_at is not None

    def test_paper_optional_fields_default_none(self):
        """可选字段默认 None"""
        paper = Paper(title="Test", publication_date=date(2024, 1, 1))
        assert paper.doi is None
        assert paper.abstract is None
        assert paper.arxiv_id is None
        assert paper.openalex_id is None

    def test_paper_is_retracted_default_false(self):
        """is_retracted 默认 False"""
        paper = Paper(title="Test", publication_date=date(2024, 1, 1))
        assert paper.is_retracted is False

    def test_open_access_info_model(self):
        """OpenAccessInfo 模型验证"""
        oa = OpenAccessInfo(
            is_oa=True,
            oa_status="green",
            oa_url="https://arxiv.org/abs/2401.12345",
            license="cc-by",
        )
        assert oa.is_oa is True
        assert oa.oa_status == "green"


# ===========================================================================
# 单元测试: 数据库操作
# ===========================================================================

class TestDatabase:

    def test_init_db_creates_tables(self, tmp_db):
        """init_db 成功创建所有必需表"""
        with get_session(tmp_db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {row["name"] for row in tables}

        expected = {"papers", "paper_references", "authors", "paper_authors",
                    "affiliations", "topics_hierarchy", "pdfs", "retractions",
                    "ingestion_jobs", "ingestion_hwm"}
        assert expected.issubset(table_names), f"缺少表: {expected - table_names}"

    def test_upsert_paper_insert(self, tmp_db, sample_paper):
        """upsert_paper 新插入"""
        paper_dict = sample_paper.model_dump(exclude={"authors", "references_external"})
        paper_dict["open_access"] = sample_paper.open_access.model_dump()
        result = upsert_paper(paper_dict, db_path=tmp_db)
        # 验证写入成功
        with get_session(tmp_db) as conn:
            row = conn.execute("SELECT * FROM papers WHERE id=?", (sample_paper.id,)).fetchone()
        assert row is not None
        assert row["title"] == sample_paper.title
        assert row["arxiv_id"] == "2401.12345"

    def test_upsert_paper_idempotent(self, tmp_db, sample_paper):
        """upsert_paper 幂等性(重复插入不报错)"""
        paper_dict = sample_paper.model_dump(exclude={"authors", "references_external"})
        paper_dict["open_access"] = sample_paper.open_access.model_dump()
        upsert_paper(paper_dict, db_path=tmp_db)
        upsert_paper(paper_dict, db_path=tmp_db)  # 第二次不应报错
        with get_session(tmp_db) as conn:
            count = conn.execute(
                "SELECT COUNT(*) as n FROM papers WHERE id=?", (sample_paper.id,)
            ).fetchone()["n"]
        assert count == 1

    def test_upsert_paper_references(self, tmp_db, sample_paper):
        """upsert_paper_references 批量写入"""
        paper_dict = sample_paper.model_dump(exclude={"authors", "references_external"})
        paper_dict["open_access"] = sample_paper.open_access.model_dump()
        upsert_paper(paper_dict, db_path=tmp_db)

        refs = ["W1234567890", "W9876543210", "W1111111111"]
        inserted = upsert_paper_references(sample_paper.id, refs, db_path=tmp_db)
        assert inserted == 3

        with get_session(tmp_db) as conn:
            count = conn.execute(
                "SELECT COUNT(*) as n FROM paper_references WHERE citing_paper_id=?",
                (sample_paper.id,)
            ).fetchone()["n"]
        assert count == 3

    def test_get_db_stats(self, tmp_db):
        """get_db_stats 返回正确统计"""
        stats = get_db_stats(tmp_db)
        assert "papers" in stats
        assert "paper_references" in stats
        assert "authors" in stats
        assert stats["papers"] == 0  # 空库

    def test_hwm_set_and_get(self, tmp_db):
        """V14 HWM 读写"""
        set_hwm_v14("arxiv", "physics.optics", "2024-01-31", db_path=tmp_db)
        hwm = get_hwm_v14("arxiv", "physics.optics", db_path=tmp_db)
        assert hwm == "2024-01-31"

    def test_hwm_returns_none_for_missing(self, tmp_db):
        """未设置 HWM 时返回 None"""
        hwm = get_hwm_v14("arxiv", "nonexistent", db_path=tmp_db)
        assert hwm is None

    def test_ingestion_job_lifecycle(self, tmp_db):
        """test_ingestion_job_lifecycle: pending → running → done"""
        job_id = ulid_new()

        # pending
        upsert_ingestion_job({
            "job_id": job_id,
            "provider": "arxiv",
            "query_params": {"set_spec": "physics:physics.optics"},
            "status": "pending",
        }, db_path=tmp_db)

        with get_session(tmp_db) as conn:
            row = conn.execute("SELECT status FROM ingestion_jobs WHERE job_id=?",
                               (job_id,)).fetchone()
        assert row["status"] == "pending"

        # running
        upsert_ingestion_job({
            "job_id": job_id,
            "provider": "arxiv",
            "query_params": {},
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }, db_path=tmp_db)

        with get_session(tmp_db) as conn:
            row = conn.execute("SELECT status FROM ingestion_jobs WHERE job_id=?",
                               (job_id,)).fetchone()
        assert row["status"] == "running"

        # done
        upsert_ingestion_job({
            "job_id": job_id,
            "provider": "arxiv",
            "query_params": {},
            "status": "done",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "papers_ingested": 100,
        }, db_path=tmp_db)

        with get_session(tmp_db) as conn:
            row = conn.execute("SELECT * FROM ingestion_jobs WHERE job_id=?",
                               (job_id,)).fetchone()
        assert row["status"] == "done"
        assert row["papers_ingested"] == 100


# ===========================================================================
# 单元测试: Normalizer
# ===========================================================================

class TestNormalizer:

    def test_normalize_arxiv_record_minimal(self):
        """test_normalize_arxiv_record_minimal: 最小字段集"""
        raw = {
            "arxiv_id": "2401.12345",
            "title": "Test Optics Paper",
            "abstract": "An abstract about optics.",
            "created": "2024-01-15",
            "categories": ["physics.optics"],
            "authors": [],
        }
        paper = normalize_arxiv_record(raw)
        assert paper is not None
        assert paper.arxiv_id == "2401.12345"
        assert paper.title == "Test Optics Paper"
        assert paper.publication_date == date(2024, 1, 15)
        assert paper.primary_topic_id == "physics.optics"
        assert paper.source_provider == "arxiv"
        assert paper.open_access is not None
        assert paper.open_access.is_oa is True

    def test_normalize_arxiv_record_with_authors(self):
        """test_normalize_arxiv_record_with_authors: 带作者字段"""
        raw = {
            "arxiv_id": "2401.22222",
            "title": "Multi-Author Optics Study",
            "abstract": "Study by multiple authors.",
            "created": "2024-02-01",
            "categories": ["physics.optics", "cs.NE"],
            "authors": ["John Smith", "Wei Zhang", "Maria Garcia"],
            "doi": "10.1234/optics.multi",
        }
        paper = normalize_arxiv_record(raw)
        assert paper is not None
        assert len(paper.authors) == 3
        assert paper.authors[0].display_name == "John Smith"
        assert paper.doi == "10.1234/optics.multi"
        assert paper.n_authors == 3

    def test_normalize_arxiv_record_missing_title_returns_none(self):
        """缺少标题的 record 返回 None"""
        raw = {"arxiv_id": "2401.99999", "created": "2024-01-15"}
        paper = normalize_arxiv_record(raw)
        assert paper is None

    def test_normalize_openalex_to_paper(self):
        """test_normalize_openalex_to_paper: OpenAlex Work JSON 归一化"""
        raw = {
            "id": "https://openalex.org/W4392199370",
            "doi": "https://doi.org/10.5678/oa.test",
            "title": "OpenAlex Paper on Photonics",
            "publication_date": "2024-03-15",
            "cited_by_count": 150,
            "is_retracted": False,
            "is_paratext": False,
            "language": "en",
            "primary_topic": {
                "id": "https://openalex.org/T10245",
                "subfield": {"id": "https://openalex.org/S3107"},
                "field": {"id": "https://openalex.org/F22"},
                "domain": {"id": "https://openalex.org/D3"},
            },
            "authorships": [
                {"author": {"id": "https://openalex.org/A12345",
                             "display_name": "Dr. Alice"}},
            ],
            "open_access": {"is_oa": True, "oa_status": "gold", "oa_url": "https://doi.org/xxx"},
            "referenced_works": ["https://openalex.org/W111", "https://openalex.org/W222"],
        }
        paper = normalize_openalex_work(raw)
        assert paper is not None
        assert paper.openalex_id == "W4392199370"
        assert paper.doi == "10.5678/oa.test"
        assert paper.title == "OpenAlex Paper on Photonics"
        assert paper.cited_by_count == 150
        assert paper.primary_topic_id == "T10245"
        assert paper.primary_subfield_id == "S3107"
        assert paper.primary_field_id == "F22"
        assert paper.primary_domain_id == "D3"
        assert len(paper.authors) == 1
        assert paper.authors[0].display_name == "Dr. Alice"
        assert "W111" in paper.references_external
        assert "W222" in paper.references_external

    def test_normalize_openalex_abstract_inverted_index(self):
        """OpenAlex abstract_inverted_index 重建"""
        raw = {
            "id": "https://openalex.org/W999",
            "title": "Test Abstract Rebuild",
            "publication_date": "2024-01-01",
            "abstract_inverted_index": {
                "Hello": [0],
                "world": [1],
                "optics": [2],
            },
        }
        paper = normalize_openalex_work(raw)
        assert paper is not None
        assert "Hello" in paper.abstract
        assert "world" in paper.abstract
        assert "optics" in paper.abstract

    def test_normalize_crossref_to_paper(self):
        """test_normalize_crossref_to_paper: Crossref message JSON 归一化"""
        raw = {
            "DOI": "10.9999/crossref.test",
            "title": ["A Crossref Test Paper on Lasers"],
            "abstract": "<jats:p>Laser physics abstract content here.</jats:p>",
            "issued": {"date-parts": [[2024, 4, 20]]},
            "author": [
                {"given": "Bob", "family": "Wilson", "ORCID": "https://orcid.org/0000-0001-2345-6789"},
                {"given": "Carol", "family": "Chen"},
            ],
            "is-referenced-by-count": 25,
            "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
            "reference": [
                {"DOI": "10.1111/ref.001"},
                {"DOI": "10.2222/ref.002"},
            ],
        }
        paper = normalize_crossref_msg(raw)
        assert paper is not None
        assert paper.doi == "10.9999/crossref.test"
        assert paper.title == "A Crossref Test Paper on Lasers"
        assert paper.publication_date == date(2024, 4, 20)
        assert paper.cited_by_count == 25
        assert len(paper.authors) == 2
        assert paper.authors[0].orcid == "0000-0001-2345-6789"
        assert "10.1111/ref.001" in paper.references_external
        # JATS 标签应被清理
        assert "<jats:p>" not in (paper.abstract or "")

    def test_rebuild_abstract_from_inverted_index(self):
        """test_normalize_openalex_abstract: inverted index 重建文本"""
        aii = {"The": [0], "quick": [1], "brown": [2], "fox": [3]}
        result = _rebuild_abstract(aii)
        assert result == "The quick brown fox"

    def test_rebuild_abstract_empty(self):
        """空 inverted index 返回空字符串"""
        assert _rebuild_abstract({}) == ""
        assert _rebuild_abstract(None) == ""


# ===========================================================================
# 单元测试: 去重
# ===========================================================================

class TestDeduplication:

    def test_dedup_by_doi_priority(self, tmp_db, sample_paper):
        """test_dedup_by_doi_priority: DOI 精确匹配优先级最高"""
        paper_dict = sample_paper.model_dump(exclude={"authors", "references_external"})
        paper_dict["open_access"] = sample_paper.open_access.model_dump()
        upsert_paper(paper_dict, db_path=tmp_db)

        # 创建不同 arxiv_id 但相同 DOI 的 paper
        new_paper = Paper(
            title="Different Title Same DOI",
            publication_date=date(2024, 1, 20),
            arxiv_id="2401.99999",
            doi=sample_paper.doi,  # 同 DOI
        )
        svc = DeduplicationService(tmp_db)
        result = svc.find_duplicate(new_paper)
        assert result is not None
        assert result["doi"] == sample_paper.doi

    def test_dedup_by_arxiv_id_fallback(self, tmp_db, sample_paper):
        """test_dedup_by_arxiv_id_fallback: arxiv_id 去重"""
        paper_dict = sample_paper.model_dump(exclude={"authors", "references_external"})
        paper_dict["open_access"] = sample_paper.open_access.model_dump()
        upsert_paper(paper_dict, db_path=tmp_db)

        new_paper = Paper(
            title="Slightly Different Title",
            publication_date=date(2024, 1, 20),
            arxiv_id=sample_paper.arxiv_id,  # 同 arxiv_id
            doi="10.9999/different.doi",
        )
        svc = DeduplicationService(tmp_db)
        result = svc.find_duplicate(new_paper)
        assert result is not None
        assert result["arxiv_id"] == sample_paper.arxiv_id

    def test_dedup_no_match(self, tmp_db, sample_paper):
        """完全不同的论文返回 None"""
        paper_dict = sample_paper.model_dump(exclude={"authors", "references_external"})
        paper_dict["open_access"] = sample_paper.open_access.model_dump()
        upsert_paper(paper_dict, db_path=tmp_db)

        new_paper = Paper(
            title="Completely Different Paper on Quantum Computing",
            publication_date=date(2023, 5, 10),
            arxiv_id="9999.99999",
            doi="10.9999/quantum.xyz",
        )
        svc = DeduplicationService(tmp_db)
        result = svc.find_duplicate(new_paper)
        assert result is None

    def test_dedup_by_title_fuzzy(self, tmp_db):
        """test_dedup_by_title_fuzzy: 标题模糊匹配"""
        paper = Paper(
            id=ulid_new(),
            title="Optical properties of photonic crystals in the visible spectrum",
            publication_date=date(2024, 1, 1),
        )
        paper_dict = paper.model_dump(exclude={"authors", "references_external"})
        upsert_paper(paper_dict, db_path=tmp_db)

        # 几乎相同的标题
        new_paper = Paper(
            title="Optical properties of photonic crystals in the visible spectrum",
            publication_date=date(2024, 1, 2),
        )
        svc = DeduplicationService(tmp_db)
        result = svc.find_duplicate(new_paper)
        assert result is not None

    def test_jaccard_similarity_exact(self):
        """Jaccard 相似度:完全相同"""
        s = {"a", "b", "c"}
        assert _jaccard(s, s) == 1.0

    def test_jaccard_similarity_disjoint(self):
        """Jaccard 相似度:完全不同"""
        assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_jaccard_similarity_partial(self):
        """Jaccard 相似度:部分重叠"""
        score = _jaccard({"a", "b", "c"}, {"b", "c", "d"})
        assert 0.4 < score < 0.6  # 2/4 = 0.5

    def test_tokenize_basic(self):
        """_tokenize 基础分词"""
        tokens = _tokenize("Hello, World! Test 123")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens


# ===========================================================================
# Mock 集成测试: ArxivHarvester
# ===========================================================================

class TestArxivHarvesterMock:

    @pytest.mark.asyncio
    async def test_arxiv_oai_pmh_parse_single_record(self, arxiv_oai_xml_single):
        """test_arxiv_oai_pmh_parse_single_record: 解析单条 OAI-PMH record"""
        from echelon.crawler.arxiv_harvester import ArxivHarvester

        # Mock HTTP 客户端返回 fixture XML
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = arxiv_oai_xml_single
        mock_response.headers = {}
        mock_client.get = AsyncMock(return_value=mock_response)

        harvester = ArxivHarvester(
            request_delay=0.0,  # 测试不等待
            http_client=mock_client
        )
        papers = []
        async for paper in harvester.fetch_full_set(
            set_spec="physics:physics.optics",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 31),
        ):
            papers.append(paper)

        assert len(papers) == 1
        p = papers[0]
        assert p.arxiv_id == "2401.12345"
        assert "Metasurface" in p.title
        assert p.doi == "10.1234/optics.2024.001"
        assert len(p.authors) == 2
        assert p.publication_date == date(2024, 1, 15)
        assert p.source_provider == "arxiv"

    @pytest.mark.asyncio
    async def test_arxiv_oai_pmh_resumption_token(
        self, arxiv_oai_xml_with_token, arxiv_oai_xml_empty
    ):
        """test_arxiv_oai_pmh_resumption_token: resumptionToken 分页"""
        from echelon.crawler.arxiv_harvester import ArxivHarvester

        call_count = 0
        async def mock_get(url, params=None, headers=None, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            if call_count == 1:
                resp.content = arxiv_oai_xml_with_token  # 有 token
            else:
                resp.content = arxiv_oai_xml_empty  # 无 token,结束
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get

        harvester = ArxivHarvester(request_delay=0.0, http_client=mock_client)
        papers = []
        async for paper in harvester.fetch_full_set(
            set_spec="physics:physics.optics",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 31),
        ):
            papers.append(paper)

        # 第一批1篇 + 第二批1篇
        assert len(papers) == 2
        assert call_count == 2
        arxiv_ids = {p.arxiv_id for p in papers}
        assert "2401.99999" in arxiv_ids
        assert "2401.00001" in arxiv_ids

    @pytest.mark.asyncio
    async def test_arxiv_429_retry_with_backoff(self, arxiv_oai_xml_empty):
        """test_arxiv_429_retry_with_backoff: 遇 429 退避后成功"""
        from echelon.crawler.arxiv_harvester import ArxivHarvester

        call_count = 0
        async def mock_get(url, params=None, headers=None, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.headers = {}
            if call_count <= 2:
                resp.status_code = 429  # 前两次 429
            else:
                resp.status_code = 200  # 第三次成功
                resp.content = arxiv_oai_xml_empty
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get

        harvester = ArxivHarvester(request_delay=0.0, http_client=mock_client)
        # 修改退避为 0 秒(测试不等待)
        from echelon.crawler import arxiv_harvester as hmod
        original_backoff = hmod.BACKOFF_SCHEDULE
        hmod.BACKOFF_SCHEDULE = [0, 0, 0, 0, 0]

        try:
            papers = []
            async for paper in harvester.fetch_full_set(
                set_spec="physics:physics.optics",
                from_date=date(2024, 1, 1),
                to_date=date(2024, 1, 31),
            ):
                papers.append(paper)
        finally:
            hmod.BACKOFF_SCHEDULE = original_backoff

        # 应该在第3次成功
        assert call_count == 3
        assert len(papers) == 1  # arxiv_oai_xml_empty 含1条

    @pytest.mark.asyncio
    async def test_arxiv_max_results_limit(self, arxiv_oai_xml_with_token, arxiv_oai_xml_empty):
        """max_results 截断正确"""
        from echelon.crawler.arxiv_harvester import ArxivHarvester

        # 每批返回 1 条,但 max=1
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = arxiv_oai_xml_with_token
        mock_response.headers = {}
        mock_client.get = AsyncMock(return_value=mock_response)

        harvester = ArxivHarvester(request_delay=0.0, http_client=mock_client)
        papers = []
        async for paper in harvester.fetch_full_set(
            set_spec="physics:physics.optics",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 31),
            max_results=1,
        ):
            papers.append(paper)

        assert len(papers) == 1

    def test_arxiv_parse_deleted_record(self):
        """deleted status 的 record 应返回 None"""
        from echelon.crawler.arxiv_harvester import ArxivHarvester
        from lxml import etree

        deleted_xml = b"""<record xmlns="http://www.openarchives.org/OAI/2.0/">
          <header status="deleted">
            <identifier>oai:arXiv.org:2401.deleted</identifier>
          </header>
        </record>"""
        root = etree.fromstring(deleted_xml)
        harvester = ArxivHarvester()
        result = harvester._parse_oai_record(root)
        assert result is None


# ===========================================================================
# Mock 集成测试: OpenAlexHarvester
# ===========================================================================

class TestOpenAlexHarvesterMock:

    @pytest.mark.asyncio
    async def test_openalex_enrich_by_arxiv_id(self):
        """test_openalex_enrich_by_arxiv_id: 用 OpenAlex 补充 arXiv 论文元数据"""
        from echelon.crawler.openalex_harvester import OpenAlexHarvester

        mock_response_data = {
            "results": [{
                "id": "https://openalex.org/W4392199370",
                "doi": "https://doi.org/10.1234/test",
                "title": "Test Optics Paper",
                "publication_date": "2024-01-15",
                "cited_by_count": 99,
                "primary_topic": {
                    "id": "https://openalex.org/T10245",
                    "subfield": {"id": "https://openalex.org/S3107"},
                    "field": {"id": "https://openalex.org/F22"},
                    "domain": {"id": "https://openalex.org/D3"},
                },
                "open_access": {"is_oa": True, "oa_status": "green", "oa_url": None},
                "authorships": [],
                "referenced_works": ["https://openalex.org/W111"],
            }]
        }

        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=mock_response_data)
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.aclose = AsyncMock()

        harvester = OpenAlexHarvester(http_client=mock_client)
        paper = Paper(
            title="Test Optics Paper",
            publication_date=date(2024, 1, 15),
            arxiv_id="2401.12345",
        )
        enriched = await harvester.enrich_paper(paper)

        assert enriched.openalex_id == "W4392199370"
        assert enriched.cited_by_count == 99
        assert enriched.primary_topic_id == "T10245"
        assert "W111" in enriched.references_external


# ===========================================================================
# Mock 集成测试: CrossrefHarvester
# ===========================================================================

class TestCrossrefHarvesterMock:

    @pytest.mark.asyncio
    async def test_crossref_doi_lookup(self):
        """test_crossref_doi_lookup: DOI 查询 Crossref"""
        from echelon.crawler.crossref_harvester import CrossrefHarvester

        mock_msg = {
            "DOI": "10.9999/test.crossref",
            "title": ["Crossref Test Optics Paper"],
            "abstract": "Test abstract content.",
            "issued": {"date-parts": [[2024, 3, 10]]},
            "author": [{"given": "Alice", "family": "Smith"}],
            "is-referenced-by-count": 5,
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"message": mock_msg})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.aclose = AsyncMock()

        harvester = CrossrefHarvester(http_client=mock_client)
        paper = await harvester.fetch_by_doi("10.9999/test.crossref")

        assert paper is not None
        assert paper.doi == "10.9999/test.crossref"
        assert "Crossref Test" in paper.title
        assert paper.publication_date == date(2024, 3, 10)
        assert paper.cited_by_count == 5

    @pytest.mark.asyncio
    async def test_crossref_404_returns_none(self):
        """Crossref 404 返回 None"""
        from echelon.crawler.crossref_harvester import CrossrefHarvester

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json = MagicMock(return_value={})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.aclose = AsyncMock()

        harvester = CrossrefHarvester(http_client=mock_client)
        paper = await harvester.fetch_by_doi("10.nonexistent/xxx")
        assert paper is None


# ===========================================================================
# 单元测试: Outbox 事件
# ===========================================================================

class TestOutboxEvents:

    def test_outbox_event_emitted_on_completion(self):
        """test_outbox_event_emitted_on_completion: ingestion_completed 事件触发"""
        from echelon.crawler.scheduler import emit_event, register_event_handler, _event_handlers

        received_events = []

        def handler(event: str, payload: dict):
            received_events.append({"event": event, "payload": payload})

        # 注册并触发
        _event_handlers.append(handler)
        try:
            emit_event("ingestion_completed", {
                "job_id": ulid_new(),
                "papers_ingested": 100,
                "provider": "arxiv",
            })
            assert len(received_events) == 1
            assert received_events[0]["event"] == "ingestion_completed"
            assert received_events[0]["payload"]["papers_ingested"] == 100
        finally:
            _event_handlers.remove(handler)

    def test_outbox_event_handler_exception_isolated(self):
        """事件处理器异常不影响其他处理器"""
        from echelon.crawler.scheduler import emit_event, _event_handlers

        good_received = []

        def bad_handler(event, payload):
            raise RuntimeError("Test error")

        def good_handler(event, payload):
            good_received.append(event)

        _event_handlers.extend([bad_handler, good_handler])
        try:
            emit_event("test_event", {})
            assert good_received == ["test_event"]
        finally:
            _event_handlers.remove(bad_handler)
            _event_handlers.remove(good_handler)


# ===========================================================================
# 单元测试: HWM 继承 V13
# ===========================================================================

class TestHWMResume:

    def test_hwm_resume_correct(self, tmp_db):
        """test_hwm_resume_correct: HWM 正确从断点恢复"""
        # 设置 HWM 到某个日期
        set_hwm_v14("arxiv", "physics.optics", "2024-03-15", db_path=tmp_db)

        # 读取并验证
        hwm = get_hwm_v14("arxiv", "physics.optics", db_path=tmp_db)
        assert hwm == "2024-03-15"

    def test_hwm_update_advances(self, tmp_db):
        """HWM 可以向前推进"""
        set_hwm_v14("arxiv", "physics.optics", "2024-01-31", db_path=tmp_db)
        set_hwm_v14("arxiv", "physics.optics", "2024-02-29", db_path=tmp_db)
        hwm = get_hwm_v14("arxiv", "physics.optics", db_path=tmp_db)
        assert hwm == "2024-02-29"

    def test_hwm_multiple_providers(self, tmp_db):
        """不同 provider 的 HWM 相互独立"""
        set_hwm_v14("arxiv", "physics.optics", "2024-01-31", db_path=tmp_db)
        set_hwm_v14("openalex", "T10245", "2024-02-15", db_path=tmp_db)

        arxiv_hwm = get_hwm_v14("arxiv", "physics.optics", db_path=tmp_db)
        oa_hwm = get_hwm_v14("openalex", "T10245", db_path=tmp_db)
        assert arxiv_hwm == "2024-01-31"
        assert oa_hwm == "2024-02-15"


# ===========================================================================
# 单元测试: BioRxiv 占位
# ===========================================================================

class TestBioRxivPlaceholder:

    @pytest.mark.asyncio
    async def test_biorxiv_raises_not_implemented(self):
        """BioRxivHarvester 正确抛出 NotImplementedError"""
        from echelon.crawler.biorxiv_harvester import BioRxivHarvester

        harvester = BioRxivHarvester()
        with pytest.raises(NotImplementedError, match="V15 vertical: bio"):
            await harvester.fetch_by_id("dummy")

        with pytest.raises(NotImplementedError):
            await harvester.fetch_by_doi("10.xxx")


# ===========================================================================
# 真实集成测试(慢,标记 real_network)
# ===========================================================================

@pytest.mark.real_network
class TestArxivRealIntegration:

    @pytest.mark.asyncio
    async def test_arxiv_real_fetch_one_paper(self, tmp_db):
        """
        test_arxiv_real_fetch_one_paper: 真实 arXiv OAI-PMH 拉1篇验证 end-to-end。

        验证:
        - 能成功连接 arXiv OAI-PMH API
        - 解析出有效 Paper 对象
        - 写入 SQLite 数据库
        - arXiv ID 格式正确

        注意: 此测试耗时 3-5 秒(速率限制)
        """
        from echelon.crawler.arxiv_harvester import ArxivHarvester

        harvester = ArxivHarvester(request_delay=3.0)
        papers = []

        async for paper in harvester.fetch_full_set(
            set_spec="physics:physics.optics",
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 2),
            max_results=1,
        ):
            papers.append(paper)
            break  # 只取 1 篇

        assert len(papers) >= 1, "未能从真实 arXiv 拉取到任何论文"

        paper = papers[0]
        assert paper.arxiv_id is not None, "arxiv_id 不应为空"
        assert paper.title, "标题不应为空"
        assert paper.publication_date is not None

        # 写入数据库
        paper_dict = paper.model_dump(exclude={"authors", "references_external"})
        if paper.open_access:
            paper_dict["open_access"] = paper.open_access.model_dump()
        upsert_paper(paper_dict, db_path=tmp_db)

        # 验证写入
        with get_session(tmp_db) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE arxiv_id=?", (paper.arxiv_id,)
            ).fetchone()
        assert row is not None
        assert row["title"] == paper.title
