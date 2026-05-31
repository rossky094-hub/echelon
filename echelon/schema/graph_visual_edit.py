"""
echelon.schema.graph_visual_edit
================================
[V13 预埋, V14 实现]
专家对融合图谱的可视化编辑操作 + 检索查询 Pydantic v2 Schema。

继承 V11.2 GraphEditOperation (AUDIT-079/080) 的设计理念:
  - ULID 主键
  - audit_log 字段 (timestamp, expert_id)
  - optimistic locking (version 字段)
  - @model_validator(mode='after') 跨字段校验

参考: V13 系统级方案 §4 接口预埋
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from echelon.core.ulid_utils import ulid_new, ULIDStr


# ---------------------------------------------------------------------------
# GraphVisualEdit
# ---------------------------------------------------------------------------

class GraphVisualEdit(BaseModel):
    """专家对融合图谱的可视化编辑操作。

    [V13 预埋, V14 实现] 12 种编辑 action 涵盖节点/边/地标/注释/光环/带的
    位置、权重、颜色、标签、合并、拆分、显隐、晋降地标、注释等操作。

    Attributes
    ----------
    edit_id:
        操作唯一 ULID,由 ulid_new() 自动生成。
    target_type:
        被编辑对象的类型:node | edge | landmark | annotation | halo | band。
    target_id:
        被编辑对象的 ID(非空,最长 100 字符)。
    action:
        编辑动作类型,12 种之一。
    payload:
        动作附加参数 dict,各 action 要求不同 key(由 validate_payload_keys 校验)。
    rationale:
        编辑理由说明(10-2000 字符),用于审计日志。
    expert_id:
        执行编辑的专家 ID(字母数字下划线横线)。
    timestamp:
        操作时间戳(UTC,自动填充)。
    version:
        乐观锁版本号(≥1),用于并发冲突检测。
    """

    edit_id: ULIDStr = Field(default_factory=ulid_new, description="操作唯一 ULID")
    target_type: Literal["node", "edge", "landmark", "annotation", "halo", "band"] = Field(
        description="被编辑对象类型"
    )
    target_id: str = Field(min_length=1, max_length=100, description="被编辑对象 ID")
    action: Literal[
        "pin_position",
        "override_fused_weight",
        "override_color",
        "add_label",
        "merge_nodes",
        "split_node",
        "hide",
        "show",
        "promote_landmark",
        "demote_landmark",
        "annotate",
    ] = Field(description="编辑动作,12 种之一")
    payload: dict = Field(default_factory=dict, description="动作附加参数,keys 随 action 变化")
    rationale: str = Field(min_length=10, max_length=2000, description="编辑理由 (审计日志)")
    expert_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", description="执行编辑的专家 ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="操作时间戳 (UTC)")
    version: int = Field(default=1, ge=1, description="乐观锁版本号 (≥1)")

    # ------------------------------------------------------------------
    # Payload key requirements per action
    # ------------------------------------------------------------------
    _ACTION_REQUIRED_KEYS: dict[str, set[str]] = {
        "pin_position":           {"x", "y"},
        "override_fused_weight":  {"weight"},
        "override_color":         {"hex_color"},
        "add_label":              {"label_text"},
        "merge_nodes":            {"merge_target_ids"},
        "split_node":             {"split_into_ids"},
        "hide":                   set(),
        "show":                   set(),
        "promote_landmark":       {"short_label_zh"},
        "demote_landmark":        set(),
        "annotate":               {"annotation_text"},
    }

    @model_validator(mode="after")
    def validate_payload_keys(self) -> "GraphVisualEdit":
        """校验 payload 包含 action 所必须的 keys (AUDIT-079 设计继承)。

        Raises
        ------
        ValueError
            若 payload 缺少 action 对应的必须 key。
        """
        required: set[str] = self._ACTION_REQUIRED_KEYS.get(self.action, set())
        missing = required - set(self.payload.keys())
        if missing:
            raise ValueError(
                f"action={self.action!r} requires payload keys {required!r}; "
                f"missing: {missing!r}"
            )
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "target_type": "node",
                    "target_id": "paper-01ARY",
                    "action": "pin_position",
                    "payload": {"x": 120.5, "y": -45.0},
                    "rationale": "Expert manually repositioned to align with cluster centroid",
                    "expert_id": "expert_alice",
                    "version": 1,
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# GraphSearchQuery
# ---------------------------------------------------------------------------

class GraphSearchQuery(BaseModel):
    """图谱检索查询 Schema。

    [V13 预埋, V14 实现] 12 种查询类型涵盖语义、引用、主题、新颖度、
    生命周期、领域、地标邻近度、瓶颈、元原理、专家编辑等维度。

    Attributes
    ----------
    query_id:
        查询唯一 ULID,自动生成。
    query_type:
        查询类型,12 种之一。
    query_text:
        自然语言查询文本(semantic/topic 类型使用)。
    filters:
        附加过滤条件 dict。
    top_k:
        返回结果数量上限 (1-500,默认 50)。
    expert_id:
        发起查询的专家 ID(可选)。
    timestamp:
        查询时间戳(UTC,自动填充)。
    """

    query_id: ULIDStr = Field(default_factory=ulid_new, description="查询唯一 ULID")
    query_type: Literal[
        "semantic",
        "cite",
        "topic",
        "novelty_range",
        "lifecycle",
        "field",
        "subfield",
        "domain",
        "landmark_proximity",
        "bottleneck",
        "meta_principle",
        "expert_edited",
    ] = Field(description="查询类型,12 种之一")
    query_text: Optional[str] = Field(
        default=None, max_length=1000, description="自然语言查询文本(semantic/topic 类型)"
    )
    filters: dict = Field(default_factory=dict, description="附加过滤条件")
    top_k: int = Field(default=50, ge=1, le=500, description="返回结果上限 (1-500)")
    expert_id: Optional[str] = Field(
        default=None, pattern=r"^[a-zA-Z0-9_-]+$", description="发起查询的专家 ID"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="查询时间戳 (UTC)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query_type": "semantic",
                    "query_text": "graph neural network scalable training",
                    "filters": {"year_from": 2020, "min_citations": 10},
                    "top_k": 20,
                    "expert_id": "expert_alice",
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# EvidenceAtomSearchQuery
# ---------------------------------------------------------------------------

class EvidenceAtomSearchQuery(BaseModel):
    """Traceable section-atom retrieval query.

    This query is intentionally evidence-scoped: exact hits and fuzzy vector
    recalls are retrieval context only.  Step5c/Step13 promotion must attach
    evidence-chain contracts before any scientific claim is upgraded.
    """

    query_id: ULIDStr = Field(default_factory=ulid_new, description="查询唯一 ULID")
    query_text: str = Field(min_length=1, max_length=1000, description="section atom 检索文本")
    search_mode: Literal["exact", "fuzzy", "hybrid"] = Field(
        default="hybrid",
        description="exact=FTS/BM25; fuzzy=atom vector recall; hybrid=exact first, fuzzy candidates second",
    )
    phrase_query: bool = Field(
        default=False,
        description="对 exact 分支启用可复现 phrase query；fuzzy 分支仍只做候选召回",
    )
    filters: dict = Field(
        default_factory=dict,
        description="paper_id/doi/arxiv_id/s2_paper_id/title/atom_type/section_name 等过滤条件",
    )
    top_k: int = Field(default=50, ge=1, le=200, description="返回结果上限")
    exact_top_k: Optional[int] = Field(default=None, ge=1, le=500, description="hybrid exact 分支上限")
    fuzzy_top_k: Optional[int] = Field(default=None, ge=1, le=500, description="hybrid fuzzy 分支上限")
    include_section_context: bool = Field(
        default=False,
        description="可选返回 section embedding fuzzy context；仍为 retrieval_context_only",
    )
    section_top_k: Optional[int] = Field(default=None, ge=1, le=200, description="section context fuzzy 召回上限")
    min_fuzzy_score: float = Field(default=0.0, ge=0.0, le=1.0, description="fuzzy 召回最低分")
    embedding_model: str = Field(
        default="deterministic_hashing_atom_embedding_v1",
        max_length=200,
        description="atom embedding 模型标识",
    )
    embedding_dim: int = Field(default=256, ge=1, le=4096, description="atom embedding 维度")
    section_embedding_model: str = Field(
        default="deterministic_hashing_section_embedding_v1",
        max_length=200,
        description="section embedding 模型标识",
    )
    section_embedding_dim: int = Field(default=256, ge=1, le=4096, description="section embedding 维度")
    expert_id: Optional[str] = Field(
        default=None, pattern=r"^[a-zA-Z0-9_-]+$", description="发起查询的专家 ID"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="查询时间戳 (UTC)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query_text": "fabrication loss thermal instability",
                    "search_mode": "hybrid",
                    "phrase_query": False,
                    "filters": {"section_name": "Discussion", "doi": "10.1234/example"},
                    "top_k": 20,
                    "expert_id": "expert_alice",
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# GraphSearchResult
# ---------------------------------------------------------------------------

class GraphSearchResult(BaseModel):
    """图谱检索结果 Schema。

    [V13 预埋, V14 实现]

    Attributes
    ----------
    query_id:
        对应的查询 ULID。
    hits:
        命中结果列表,每项为 dict(结构由 V14 定义)。
    total_matches:
        总命中数。
    elapsed_ms:
        查询耗时 (毫秒)。
    schema_version:
        Schema 版本标记。
    """

    query_id: ULIDStr = Field(description="对应查询的 ULID")
    hits: list[dict] = Field(default_factory=list, description="命中结果列表")
    total_matches: int = Field(ge=0, description="总命中数")
    elapsed_ms: int = Field(ge=0, description="查询耗时 (ms)")
    schema_version: str = Field(default="V13.0", description="Schema 版本")
