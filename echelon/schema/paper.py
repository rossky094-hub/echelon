"""
echelon.schema.paper
=====================
论文 Pydantic v2 Schema。

主键采用 ULID(AUDIT-026),publication_date 使用 ``datetime.date``
类型(AUDIT-074),primary_topic_id 字段显式声明(AUDIT-024)。

参考: V11.2 白皮书 §2.3 数据模型;AUDIT-026/024/074
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from echelon.core.date_utils import parse_pub_date
from echelon.core.topic_mapper import PILOT_TOPIC_IDS
from echelon.core.ulid_utils import ULIDStr, ulid_new


class AuthorInfo(BaseModel):
    """作者信息。"""

    author_id: str | None = None
    display_name: str
    orcid: str | None = None
    institutions: list[str] = Field(default_factory=list)


class Paper(BaseModel):
    """论文数据模型。

    Attributes
    ----------
    id:
        论文主键,ULID 格式(26 字符 Crockford base32)。
    openalex_id:
        OpenAlex 原始 ID,如 ``"W2741809807"``。
    doi:
        DOI 字符串,如 ``"10.1000/xyz"``。
    title:
        论文标题。
    abstract:
        摘要全文。
    publication_date:
        发表日期 ``datetime.date``(AUDIT-074:禁止用 str)。
    primary_topic_id:
        OpenAlex 主题 ID(AUDIT-024),如 ``"T10245"``。
    primary_topic_name:
        主题名称。
    field_name:
        一级学科。
    subfield_name:
        二级学科。
    authorships:
        作者列表。
    referenced_work_ids:
        引用论文 OpenAlex ID 列表。
    cited_by_count:
        被引次数。
    language:
        论文语言代码,如 ``"en"``。
    is_retracted:
        是否撤稿。
    source_url:
        来源 URL(arXiv / OpenAlex)。
    version:
        数据版本号(乐观锁)。
    extra:
        额外字段 dict(用于存储不在 schema 中的字段)。
    """

    id: ULIDStr = Field(default_factory=ulid_new, description="ULID 主键")
    openalex_id: str | None = Field(default=None, description="OpenAlex Work ID")
    doi: str | None = Field(default=None)
    title: str = Field(min_length=1)
    abstract: str | None = Field(default=None)
    publication_date: date = Field(description="发表日期(datetime.date 类型)")
    primary_topic_id: str | None = Field(
        default=None, description="OpenAlex 主题 ID(AUDIT-024)"
    )
    primary_topic_name: str | None = Field(default=None)
    field_name: str | None = Field(default=None)
    subfield_name: str | None = Field(default=None)
    authorships: list[AuthorInfo] = Field(default_factory=list)
    referenced_work_ids: list[str] = Field(default_factory=list)
    cited_by_count: int = Field(default=0, ge=0)
    language: str | None = Field(default=None)
    is_retracted: bool = Field(default=False)
    source_url: str | None = Field(default=None)
    version: int = Field(default=1, ge=1)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("publication_date", mode="before")
    @classmethod
    def coerce_publication_date(cls, v: Any) -> date:
        """将各种格式日期统一为 datetime.date(AUDIT-074)。"""
        return parse_pub_date(v)

    @field_validator("primary_topic_id", mode="before")
    @classmethod
    def validate_topic_id(cls, v: Any) -> str | None:
        """警告非 Pilot topic ID(不强制拒绝,以支持未来扩展)。"""
        if v is not None and v not in PILOT_TOPIC_IDS:
            import logging
            logging.getLogger(__name__).debug(
                "primary_topic_id %r is not in Pilot topics %r",
                v,
                PILOT_TOPIC_IDS,
            )
        return v

    @model_validator(mode="after")
    def validate_non_retracted_has_title(self) -> "Paper":
        """非撤稿论文必须有非空标题(防御性校验)。"""
        if not self.is_retracted and not self.title.strip():
            raise ValueError("Non-retracted paper must have a non-empty title")
        return self

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class PaperSummary(BaseModel):
    """论文摘要视图(用于 API 列表响应)。"""

    id: ULIDStr
    title: str
    publication_date: date
    primary_topic_id: str | None = None
    cited_by_count: int = 0
