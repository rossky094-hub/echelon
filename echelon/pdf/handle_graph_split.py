"""
echelon.pdf.handle_graph_split
================================
Split 操作触发节点 0 重新解析。

[修订自 AUDIT-031]
V11.1 问题:当一篇\"复合论文\"(multi-paper PDF)被 Split 拆分为多篇子论文后,
原始父节点 0 继续持有合并状态的证据和摘要,与新产生的子论文节点语义重叠,
导致图谱拓扑不一致(边指向已拆分的父节点,但父节点内容未更新)。

V11.2 修复:
  - ``handle_graph_split(parent_id, child_papers) -> ReparseTask``
      产生重新解析任务,记录父节点 ID 和子论文列表。
  - ``reparse_as_child_paper(child_id, parent_evidence)``
      Pilot 桩函数:基于 abstract 从父节点证据中提取子论文相关内容。
  - ``ReparseTask`` Pydantic v2 模型记录任务状态(pending/running/done/failed)。

参考: V11.2 白皮书 §5.1.6 Split 触发解析;AUDIT-031
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 任务状态枚举
# ---------------------------------------------------------------------------


class ReparseStatus(str, Enum):
    """重新解析任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# 子论文描述
# ---------------------------------------------------------------------------


class ChildPaperRef(BaseModel):
    """Split 产生的子论文引用。

    Attributes
    ----------
    child_id:
        子论文 ULID。
    title:
        子论文标题(可选,用于日志)。
    abstract:
        子论文摘要(Pilot 桩函数使用 abstract 替代全文解析)。
    doi:
        DOI(可选)。
    """

    child_id: str = Field(min_length=1)
    title: str | None = None
    abstract: str | None = None
    doi: str | None = None

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# 重新解析任务记录
# ---------------------------------------------------------------------------


class ReparseTask(BaseModel):
    """Split 操作产生的重新解析任务。

    [修订自 AUDIT-031]

    Attributes
    ----------
    task_id:
        任务 ULID。
    parent_id:
        被拆分的父节点 ULID。
    child_papers:
        子论文列表(至少 1 篇)。
    status:
        当前状态。
    created_at:
        任务创建时间(UTC)。
    started_at:
        任务开始时间(UTC)。
    finished_at:
        任务完成时间(UTC)。
    error:
        失败时的错误信息。
    reparse_results:
        每篇子论文的解析结果摘要。
    """

    task_id: str = Field(min_length=1)
    parent_id: str = Field(min_length=1)
    child_papers: list[ChildPaperRef] = Field(min_length=1)
    status: ReparseStatus = Field(default=ReparseStatus.PENDING)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    reparse_results: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_child_papers_nonempty(self) -> "ReparseTask":
        """[AUDIT-031] Split 至少产生 1 篇子论文。"""
        if not self.child_papers:
            raise ValueError("ReparseTask must have at least 1 child paper")
        return self

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# 主入口:handle_graph_split
# ---------------------------------------------------------------------------


def handle_graph_split(
    parent_id: str,
    child_papers: list[ChildPaperRef] | list[dict],
) -> ReparseTask:
    """Split 操作触发节点 0 重新解析。

    [修订自 AUDIT-031]

    Split 操作将父节点拆分为多篇子论文后,本函数:
    1. 验证参数合法性(child_papers 非空)
    2. 创建 ``ReparseTask`` 记录(status=PENDING)
    3. 记录日志(后续由 AsyncTaskManager 调度执行)

    Parameters
    ----------
    parent_id:
        被拆分的父节点 ULID。
    child_papers:
        子论文列表,可以是 ``ChildPaperRef`` 对象或原始 dict。

    Returns
    -------
    ReparseTask
        状态为 PENDING 的重新解析任务。

    Raises
    ------
    ValueError
        若 parent_id 为空或 child_papers 为空列表。
    """
    from echelon.core.ulid_utils import ulid_new

    if not parent_id or not parent_id.strip():
        raise ValueError("[AUDIT-031] parent_id must not be empty")

    # 规范化 child_papers
    normalized: list[ChildPaperRef] = []
    for cp in child_papers:
        if isinstance(cp, ChildPaperRef):
            normalized.append(cp)
        elif isinstance(cp, dict):
            normalized.append(ChildPaperRef(**cp))
        else:
            raise TypeError(
                f"[AUDIT-031] child_papers elements must be ChildPaperRef or dict, got {type(cp)}"
            )

    if not normalized:
        raise ValueError("[AUDIT-031] child_papers must not be empty")

    task = ReparseTask(
        task_id=ulid_new(),
        parent_id=parent_id,
        child_papers=normalized,
        status=ReparseStatus.PENDING,
    )

    logger.info(
        "[AUDIT-031] handle_graph_split: parent=%r -> %d children, task=%r",
        parent_id,
        len(normalized),
        task.task_id,
    )
    return task


# ---------------------------------------------------------------------------
# 子论文重新解析桩函数(Pilot)
# ---------------------------------------------------------------------------


def reparse_as_child_paper(
    child_id: str,
    parent_evidence: str | None,
) -> dict[str, Any]:
    """基于父节点证据,为子论文进行轻量重解析(Pilot 桩函数)。

    [修订自 AUDIT-031]

    Pilot 简化实现:直接使用传入的 ``parent_evidence``(通常是父节点 abstract)
    作为子论文的初始证据文本。生产环境中应触发全文 PDF 重解析流程。

    Parameters
    ----------
    child_id:
        子论文 ULID。
    parent_evidence:
        父节点证据文本(abstract 或关键段落)。

    Returns
    -------
    dict
        包含以下字段:
        - ``child_id``: 子论文 ID
        - ``evidence_text``: 提取的证据文本(截断 at 2000 chars)
        - ``source``: ``"abstract"``(Pilot)或 ``"full_pdf"``(生产)
        - ``status``: ``"ok"`` 或 ``"empty"``
        - ``parsed_at``: ISO 8601 时间戳
    """
    MAX_EVIDENCE_LEN = 2000

    evidence_text = (parent_evidence or "").strip()
    if len(evidence_text) > MAX_EVIDENCE_LEN:
        evidence_text = evidence_text[:MAX_EVIDENCE_LEN]

    status = "ok" if evidence_text else "empty"
    if status == "empty":
        logger.warning(
            "[AUDIT-031] reparse_as_child_paper: child=%r has empty parent_evidence",
            child_id,
        )

    result: dict[str, Any] = {
        "child_id": child_id,
        "evidence_text": evidence_text,
        "source": "abstract",  # Pilot: uses abstract; Production: full_pdf
        "status": status,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.debug("[AUDIT-031] reparse_as_child_paper result: %r", result)
    return result


# ---------------------------------------------------------------------------
# 执行完整 Split 重解析任务(协调函数)
# ---------------------------------------------------------------------------


def run_reparse_task(task: ReparseTask) -> ReparseTask:
    """执行 ReparseTask:对所有子论文调用 reparse_as_child_paper。

    [修订自 AUDIT-031]

    Parameters
    ----------
    task:
        PENDING 状态的 ReparseTask。

    Returns
    -------
    ReparseTask
        状态更新为 DONE 或 FAILED 的任务。
    """
    task = task.model_copy(
        update={
            "status": ReparseStatus.RUNNING,
            "started_at": datetime.now(timezone.utc),
        }
    )

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for child in task.child_papers:
        try:
            res = reparse_as_child_paper(
                child_id=child.child_id,
                parent_evidence=child.abstract,
            )
            results.append(res)
        except Exception as exc:
            err_msg = f"child={child.child_id!r}: {exc}"
            logger.error("[AUDIT-031] reparse failed: %s", err_msg)
            errors.append(err_msg)

    now = datetime.now(timezone.utc)
    if errors:
        return task.model_copy(
            update={
                "status": ReparseStatus.FAILED,
                "finished_at": now,
                "error": "; ".join(errors),
                "reparse_results": results,
            }
        )

    logger.info(
        "[AUDIT-031] run_reparse_task done: task=%r results=%d",
        task.task_id,
        len(results),
    )
    return task.model_copy(
        update={
            "status": ReparseStatus.DONE,
            "finished_at": now,
            "reparse_results": results,
        }
    )
