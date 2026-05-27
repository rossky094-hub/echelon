"""
echelon.library.schema
======================
V14 统一论文库 Pydantic v2 数据模型。

SQLite Pilot 实施 + Postgres schema 设计预留(production 切换路径明确)。

AUDIT-053: paper_references 独立纵表,保证引用关系完整性。
AUDIT-024: topics_hierarchy 完整 4 级(domain/field/subfield/topic)。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from echelon.core.ulid_utils import ulid_new


# ---------------------------------------------------------------------------
# Enums / constants
# ---------------------------------------------------------------------------

class ProviderEnum:
    OPENALEX = "openalex"
    ARXIV = "arxiv"
    BIORXIV = "biorxiv"
    CROSSREF = "crossref"


class JobStatusEnum:
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Core Pydantic models
# ---------------------------------------------------------------------------

class OpenAccessInfo(BaseModel):
    """OA 访问信息"""
    is_oa: bool = False
    oa_status: Optional[str] = None   # 'gold' | 'green' | 'hybrid' | 'bronze' | 'closed'
    oa_url: Optional[str] = None
    license: Optional[str] = None


class Author(BaseModel):
    """作者模型"""
    id: str = Field(default_factory=ulid_new)
    openalex_id: Optional[str] = None
    orcid: Optional[str] = None
    display_name: str = ""
    h_index: Optional[int] = None
    works_count: Optional[int] = None

    class Config:
        from_attributes = True


class Affiliation(BaseModel):
    """机构模型"""
    id: str = Field(default_factory=ulid_new)
    openalex_id: Optional[str] = None
    display_name: str = ""
    country_code: Optional[str] = None
    ror_id: Optional[str] = None

    class Config:
        from_attributes = True


class PaperAuthor(BaseModel):
    """论文-作者关联"""
    paper_id: str
    author_id: str
    author_position: int = 0        # 0-indexed 第几作者
    affiliation_id: Optional[str] = None

    class Config:
        from_attributes = True


class TopicHierarchy(BaseModel):
    """OpenAlex 完整 4 级学科层级"""
    topic_id: str                   # T10245
    topic_name: Optional[str] = None
    subfield_id: Optional[str] = None
    subfield_name: Optional[str] = None
    field_id: Optional[str] = None
    field_name: Optional[str] = None
    domain_id: Optional[str] = None
    domain_name: Optional[str] = None
    works_count: Optional[int] = None
    last_synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Paper(BaseModel):
    """
    统一论文模型 — 核心实体。

    来源可能是 OpenAlex / arXiv / bioRxiv / Crossref 任意一个或多个,
    通过 Normalizer 归一化为此格式。
    """
    id: str = Field(default_factory=ulid_new)

    # 外部 ID(多源)
    openalex_id: Optional[str] = None          # W4392199370
    doi: Optional[str] = None                   # 10.xxxx/xxxx
    arxiv_id: Optional[str] = None              # 2401.12345 (不含 abs/ 前缀)
    pmid: Optional[int] = None                  # PubMed ID

    # 核心字段
    title: str
    abstract: Optional[str] = None
    publication_date: date
    n_authors: Optional[int] = None
    cited_by_count: Optional[int] = None

    # 学科层级(主 topic)
    primary_topic_id: Optional[str] = None     # T10245
    primary_subfield_id: Optional[str] = None  # S3107
    primary_field_id: Optional[str] = None     # F22
    primary_domain_id: Optional[str] = None    # D3

    # 期刊/来源
    venue_id: Optional[str] = None             # V21034

    # 状态标记
    is_retracted: bool = False
    is_paratext: bool = False
    language: Optional[str] = None

    # OA 信息
    open_access: Optional[OpenAccessInfo] = None

    # 审计字段
    raw_jsonb: Optional[dict] = None            # 完整原始 JSON
    first_ingested_at: Optional[datetime] = None
    last_refreshed_at: Optional[datetime] = None
    source_provider: Optional[str] = None       # ProviderEnum
    ingestion_job_id: Optional[str] = None

    # 非数据库存储的内存字段
    authors: list[Author] = Field(default_factory=list, exclude=True)
    references_external: list[str] = Field(default_factory=list, exclude=True)

    @field_validator("doi", mode="before")
    @classmethod
    def normalize_doi(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        if v.startswith("https://doi.org/"):
            v = v[len("https://doi.org/"):]
        if v.startswith("http://dx.doi.org/"):
            v = v[len("http://dx.doi.org/"):]
        return v if v else None

    @field_validator("arxiv_id", mode="before")
    @classmethod
    def normalize_arxiv_id(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        # Remove common prefixes
        for prefix in ("arxiv:", "arXiv:", "https://arxiv.org/abs/", "http://arxiv.org/abs/"):
            if v.lower().startswith(prefix.lower()):
                v = v[len(prefix):]
        # Remove version suffix e.g. "2401.12345v2" -> "2401.12345"
        if "v" in v.split(".")[-1]:
            parts = v.rsplit("v", 1)
            if parts[-1].isdigit():
                v = parts[0]
        return v if v else None

    @model_validator(mode="after")
    def set_ingested_at(self):
        if self.first_ingested_at is None:
            self.first_ingested_at = datetime.now(timezone.utc)
        return self

    class Config:
        from_attributes = True


class PaperReference(BaseModel):
    """引用关系 — AUDIT-053 独立纵表"""
    citing_paper_id: str
    cited_paper_id_external: str            # W ID 字符串(可能不在 papers 表)
    cited_paper_id_internal: Optional[str] = None  # 若 papers 表里有则填

    class Config:
        from_attributes = True


class PdfRecord(BaseModel):
    """PDF 存储记录"""
    paper_id: str
    storage_uri: str                         # s3://echelon-pdfs/... 或本地路径
    source_url: Optional[str] = None
    license: Optional[str] = None            # 'cc-by' | 'cc-by-nc' | 'restricted'
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    downloaded_at: Optional[datetime] = None
    parser_compat_hash: Optional[str] = None  # AUDIT-032

    class Config:
        from_attributes = True


class Retraction(BaseModel):
    """撤稿记录"""
    paper_id: str
    retracted_at: Optional[date] = None
    reason: Optional[str] = None
    source: Optional[str] = None            # 'retraction_watch' | 'crossref'
    detected_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class IngestionJob(BaseModel):
    """摄入任务(Outbox 模式 + 状态追踪)"""
    job_id: str = Field(default_factory=ulid_new)
    provider: str                            # ProviderEnum
    query_params: dict = Field(default_factory=dict)
    status: str = JobStatusEnum.PENDING
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    papers_ingested: int = 0
    papers_skipped_duplicate: int = 0
    error_log: Optional[str] = None
    parent_job_id: Optional[str] = None

    class Config:
        from_attributes = True


class IngestionHWM(BaseModel):
    """摄入高水位标记 — 继承 V13 hwm.py 逻辑"""
    provider: str
    topic_id: str
    last_processed_date: Optional[date] = None
    last_cursor: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Postgres 预留注释(production 切换路径)
# ---------------------------------------------------------------------------
#
# SQLite Pilot -> Postgres 迁移路径:
#
# 1. 修改 echelon/library/db.py 中的 DATABASE_URL 环境变量
#    SQLite:    "sqlite+aiosqlite:///db/echelon_library.sqlite3"
#    Postgres:  "postgresql+asyncpg://user:pass@host/echelon"
#
# 2. Postgres 特有优化(SQLite 无此概念,建表时注释掉):
#    - JSONB 字段(raw_jsonb, open_access, query_params):
#      SQLite 用 JSON TEXT,Postgres 用 JSONB 并建 GIN 索引
#    - 全文检索:Postgres 用 tsvector + GIN,SQLite 用 FTS5
#    - ULID 主键:两者均用 TEXT(26 char)
#    - TIMESTAMPTZ:Postgres 原生,SQLite 用 DATETIME(存 UTC ISO8601)
#
# 3. Alembic 迁移:
#    alembic init alembic
#    alembic revision --autogenerate -m "v14_initial"
#    alembic upgrade head
#
# 4. 生产索引补充(Postgres):
#    CREATE INDEX CONCURRENTLY idx_papers_raw_jsonb ON papers USING GIN(raw_jsonb);
#    CREATE INDEX CONCURRENTLY idx_papers_title_fts ON papers USING GIN(to_tsvector('english', title));
