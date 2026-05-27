"""
echelon.core.async_task
========================
异步任务管理模块(Pilot 内存实现)。

[修订自 AUDIT-070] 原实现同步阻塞 API,在大批量 ingestion 时超时。
本模块提供 202 Accepted + task_id 模式:
- Pilot: asyncio.Task + 内存 dict 追踪状态
- Production: 替换为 Celery + Redis

API 模式:
  POST /ingest  → 202 {"task_id": "..."}
  GET  /tasks/{task_id} → {"status": "pending"|"running"|"success"|"failed", ...}

参考: V11.2 白皮书 §3.5 异步 API 设计;AUDIT-070
"""

from __future__ import annotations

import asyncio
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable


# ---------------------------------------------------------------------------
# 任务状态枚举
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    """异步任务状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# 任务记录
# ---------------------------------------------------------------------------


@dataclass
class TaskRecord:
    """单个异步任务的状态记录。

    Attributes
    ----------
    task_id:
        任务唯一 ID(UUID v4)。
    status:
        当前状态。
    created_at:
        创建时间(UTC)。
    started_at:
        开始执行时间(UTC),未开始为 None。
    finished_at:
        完成时间(UTC),未完成为 None。
    result:
        任务成功时的返回值。
    error:
        任务失败时的错误信息。
    meta:
        额外元数据 dict。
    """

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: Any = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 任务管理器
# ---------------------------------------------------------------------------


class AsyncTaskManager:
    """基于 asyncio + 内存 dict 的异步任务管理器(Pilot 实现)。

    生产环境中用 Celery + Redis 替换本类,接口保持兼容。

    Examples
    --------
    ::

        manager = AsyncTaskManager()

        async def my_work():
            await asyncio.sleep(0.1)
            return {"processed": 42}

        task_id = await manager.submit(my_work)
        print(task_id)  # "01234567-..."

        await asyncio.sleep(0.2)
        record = manager.get_task(task_id)
        print(record.status)  # TaskStatus.SUCCESS
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._asyncio_tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # 提交任务
    # ------------------------------------------------------------------

    async def submit(
        self,
        coro_or_func: Callable[[], Awaitable[Any]] | Awaitable[Any],
        *,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """提交一个异步任务,立即返回 task_id。

        Parameters
        ----------
        coro_or_func:
            可以是 ``async def`` 函数(zero-arg callable)或 coroutine。
        meta:
            额外元数据(如 topic_id、since/until 等)。

        Returns
        -------
        str
            任务 ID(UUID v4 字符串)。
        """
        task_id = str(uuid.uuid4())
        record = TaskRecord(task_id=task_id, meta=meta or {})
        self._tasks[task_id] = record

        # 构建 coroutine
        if asyncio.iscoroutine(coro_or_func):
            coro = coro_or_func
        else:
            coro = coro_or_func()  # type: ignore[operator]

        # 包装执行逻辑
        async def _runner() -> None:
            record.status = TaskStatus.RUNNING
            record.started_at = datetime.now(timezone.utc)
            try:
                result = await coro
                record.result = result
                record.status = TaskStatus.SUCCESS
            except Exception as exc:
                record.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                record.status = TaskStatus.FAILED
            finally:
                record.finished_at = datetime.now(timezone.utc)

        asyncio_task = asyncio.create_task(_runner(), name=f"echelon-task-{task_id}")
        self._asyncio_tasks[task_id] = asyncio_task
        return task_id

    # ------------------------------------------------------------------
    # 查询状态
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> TaskRecord:
        """查询任务状态。

        Parameters
        ----------
        task_id:
            任务 ID。

        Returns
        -------
        TaskRecord
            任务状态记录。

        Raises
        ------
        KeyError
            若 task_id 不存在。
        """
        if task_id not in self._tasks:
            raise KeyError(f"Task not found: {task_id!r}")
        return self._tasks[task_id]

    def get_status(self, task_id: str) -> TaskStatus:
        """快捷查询任务状态枚举。"""
        return self.get_task(task_id).status

    def list_tasks(
        self,
        status: TaskStatus | None = None,
    ) -> list[TaskRecord]:
        """列出所有任务,可按状态过滤。

        Parameters
        ----------
        status:
            若非 None,仅返回指定状态的任务。

        Returns
        -------
        list[TaskRecord]
            任务列表,按创建时间升序。
        """
        records = list(self._tasks.values())
        if status is not None:
            records = [r for r in records if r.status == status]
        return sorted(records, key=lambda r: r.created_at)

    async def wait_for(
        self,
        task_id: str,
        timeout: float | None = None,
    ) -> TaskRecord:
        """等待任务完成。

        Parameters
        ----------
        task_id:
            任务 ID。
        timeout:
            超时秒数;None 表示无限等待。

        Returns
        -------
        TaskRecord
            完成(SUCCESS 或 FAILED)的任务记录。

        Raises
        ------
        asyncio.TimeoutError
            若超时。
        KeyError
            若 task_id 不存在。
        """
        asyncio_task = self._asyncio_tasks.get(task_id)
        if asyncio_task is None:
            raise KeyError(f"No asyncio.Task for task_id {task_id!r}")
        if timeout is not None:
            await asyncio.wait_for(asyncio.shield(asyncio_task), timeout=timeout)
        else:
            await asyncio_task
        return self._tasks[task_id]

    def task_count(self) -> int:
        """返回已提交任务总数。"""
        return len(self._tasks)


# ---------------------------------------------------------------------------
# 全局默认实例(供 FastAPI / 测试直接导入)
# ---------------------------------------------------------------------------

_default_manager: AsyncTaskManager | None = None


def get_default_manager() -> AsyncTaskManager:
    """获取全局默认 AsyncTaskManager 实例(懒初始化)。"""
    global _default_manager
    if _default_manager is None:
        _default_manager = AsyncTaskManager()
    return _default_manager
