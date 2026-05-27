"""
echelon.schema.graph_edit
==========================
图谱编辑操作 Pydantic v2 Schema。

[修订自 AUDIT-072] 原实现使用 Pydantic v1 ``@validator``,升级 v2 后
``@validator`` 语义变更导致 ``merge``/``split`` 操作校验失败。
本模块使用 ``@model_validator(mode='after')`` 确保跨字段一致性校验。

参考: V11.2 白皮书 §6.4 图谱编辑操作;AUDIT-072
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class EditType(str, Enum):
    """图谱编辑操作类型枚举。"""

    MERGE = "merge"
    """合并两个节点为一个。"""

    SPLIT = "split"
    """将一个节点拆分为多个。"""

    ADD_EDGE = "add_edge"
    """添加一条边。"""

    REMOVE_EDGE = "remove_edge"
    """删除一条边。"""

    UPDATE_ATTRIBUTE = "update_attribute"
    """更新节点/边属性。"""


class GraphEditOperation(BaseModel):
    """图谱编辑操作。

    使用 ``@model_validator(mode='after')`` 实现跨字段一致性校验:
    - ``merge`` 操作必须提供至少 2 个 ``source_ids``
    - ``split`` 操作必须提供至少 1 个 ``target_ids``(分裂后的新节点)
    - ``add_edge``/``remove_edge`` 必须提供 ``edge_source`` 和 ``edge_target``

    Attributes
    ----------
    edit_type:
        操作类型。
    source_ids:
        被操作的源节点 ULID 列表(merge 时为被合并节点,split 时为单元素)。
    target_ids:
        目标节点 ULID 列表(split 时为新节点 ULID)。
    edge_source:
        边起点 ULID(add_edge/remove_edge 使用)。
    edge_target:
        边终点 ULID(add_edge/remove_edge 使用)。
    edge_type:
        边类型标签(如 ``"cites"``、``"shares_dataset"``)。
    attributes:
        附加属性 dict。
    operator_id:
        执行操作的用户/服务 ID。
    reason:
        编辑原因说明。
    """

    edit_type: EditType
    source_ids: list[str] = Field(default_factory=list)
    target_ids: list[str] = Field(default_factory=list)
    edge_source: str | None = Field(default=None)
    edge_target: str | None = Field(default=None)
    edge_type: str | None = Field(default=None)
    attributes: dict[str, Any] = Field(default_factory=dict)
    operator_id: str | None = Field(default=None)
    reason: str | None = Field(default=None)

    @model_validator(mode="after")
    def validate_operation_fields(self) -> "GraphEditOperation":
        """跨字段一致性校验(AUDIT-072 核心修复)。

        Validates
        ---------
        - ``MERGE``: ``source_ids`` 长度 >= 2
        - ``SPLIT``: ``source_ids`` 长度 == 1,``target_ids`` 长度 >= 2
        - ``ADD_EDGE`` / ``REMOVE_EDGE``: ``edge_source`` 与 ``edge_target``
          均不为 None

        Raises
        ------
        ValueError
            若跨字段约束不满足。
        """
        edit_type = self.edit_type

        if edit_type == EditType.MERGE:
            if len(self.source_ids) < 2:
                raise ValueError(
                    f"MERGE operation requires at least 2 source_ids, "
                    f"got {len(self.source_ids)}: {self.source_ids!r}"
                )

        elif edit_type == EditType.SPLIT:
            if len(self.source_ids) != 1:
                raise ValueError(
                    f"SPLIT operation requires exactly 1 source_id, "
                    f"got {len(self.source_ids)}"
                )
            if len(self.target_ids) < 2:
                raise ValueError(
                    f"SPLIT operation requires at least 2 target_ids (new nodes), "
                    f"got {len(self.target_ids)}: {self.target_ids!r}"
                )

        elif edit_type in (EditType.ADD_EDGE, EditType.REMOVE_EDGE):
            if self.edge_source is None or self.edge_target is None:
                raise ValueError(
                    f"{edit_type.value.upper()} operation requires both "
                    f"'edge_source' and 'edge_target' to be non-None"
                )

        return self

    @property
    def is_structural(self) -> bool:
        """是否为结构性编辑(merge 或 split)。"""
        return self.edit_type in (EditType.MERGE, EditType.SPLIT)

    @property
    def affected_node_ids(self) -> list[str]:
        """返回所有受影响的节点 ID 列表(去重)。"""
        ids: set[str] = set(self.source_ids) | set(self.target_ids)
        if self.edge_source:
            ids.add(self.edge_source)
        if self.edge_target:
            ids.add(self.edge_target)
        return sorted(ids)


class GraphEditBatch(BaseModel):
    """批量图谱编辑操作。

    Attributes
    ----------
    operations:
        编辑操作列表。
    transaction_id:
        批次事务 ID(ULID)。
    """

    operations: list[GraphEditOperation] = Field(min_length=1)
    transaction_id: str | None = Field(default=None)

    @model_validator(mode="after")
    def validate_no_conflict(self) -> "GraphEditBatch":
        """检查同批次操作无明显冲突(同一节点不同时 merge 和 split)。

        Raises
        ------
        ValueError
            若同一节点在同批次中既参与 merge 又参与 split。
        """
        merge_sources: set[str] = set()
        split_sources: set[str] = set()
        for op in self.operations:
            if op.edit_type == EditType.MERGE:
                merge_sources.update(op.source_ids)
            elif op.edit_type == EditType.SPLIT:
                split_sources.update(op.source_ids)

        conflict = merge_sources & split_sources
        if conflict:
            raise ValueError(
                f"Nodes {conflict!r} appear in both MERGE and SPLIT operations "
                f"in the same batch."
            )
        return self
