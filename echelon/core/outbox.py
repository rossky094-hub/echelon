"""
echelon.core.outbox
===================
Transactional Outbox 模拟实现(Pilot 用 SQLite 单库)。

[修订自 AUDIT-025] 原实现使用双写(先写业务表,再写消息队列),存在脑裂
风险:若写入 MQ 前宕机,事件丢失。Transactional Outbox 模式将事件写入
业务库同一事务,由 CDC(Change Data Capture,如 Debezium)异步捕获并转发,
彻底消除双写风险。

Pilot 阶段使用 SQLite 单库模拟,接口与 PostgreSQL outbox 风格完全兼容:
- 业务操作与 outbox 写入在同一 SQLite 事务中
- 生产环境(PG)只需替换 ``_get_connection()`` 实现

参考: V11.2 白皮书 §3.4 Outbox 模式;AUDIT-025
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterator


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_OUTBOX_DDL = """
CREATE TABLE IF NOT EXISTS outbox (
    id          TEXT PRIMARY KEY,          -- UUID v4
    event_type  TEXT NOT NULL,             -- e.g. 'paper.ingested'
    aggregate_id TEXT NOT NULL,            -- ULID 主键(业务实体 ID)
    payload     TEXT NOT NULL,             -- JSON 序列化事件体
    created_at  TEXT NOT NULL,             -- ISO-8601 UTC
    processed   INTEGER NOT NULL DEFAULT 0 -- 0=pending, 1=dispatched by CDC
);
"""


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class OutboxEvent:
    """单条 Outbox 事件记录。

    Attributes
    ----------
    event_type:
        事件类型,如 ``"paper.ingested"``、``"graph.edge.created"``。
    aggregate_id:
        业务实体 ULID(如论文 ID)。
    payload:
        事件体 dict,会被序列化为 JSON。
    id:
        事件唯一 ID(UUID v4),自动生成。
    created_at:
        UTC 创建时间,自动填写。
    """

    event_type: str
    aggregate_id: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Outbox 实现
# ---------------------------------------------------------------------------


class OutboxStore:
    """SQLite Transactional Outbox 存储。

    Parameters
    ----------
    db_path:
        SQLite 数据库文件路径;传入 ``":memory:"`` 用于内存库(测试)。

    Examples
    --------
    ::

        store = OutboxStore(":memory:")
        store.initialize()

        with store.transaction() as conn:
            # 业务写入(略)
            store.append_event(
                conn,
                event_type="paper.ingested",
                aggregate_id=ulid_new(),
                payload={"title": "Example"},
            )

        events = store.pending_events()
        store.mark_processed(events[0].id)
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """创建 outbox 表(幂等,IF NOT EXISTS)。"""
        conn = self._ensure_conn()
        conn.execute(_OUTBOX_DDL)
        conn.commit()

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                isolation_level=None,  # 手动事务
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    # ------------------------------------------------------------------
    # 事务上下文管理器
    # ------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """提供事务上下文,确保业务写入与 outbox 写入原子性。

        Yields
        ------
        sqlite3.Connection
            处于事务中的连接,供调用方执行业务 SQL + ``append_event``。

        Example
        -------
        ::

            with store.transaction() as conn:
                conn.execute("INSERT INTO papers ...")
                store.append_event(conn, ...)
        """
        conn = self._ensure_conn()
        conn.execute("BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def append_event(
        self,
        conn: sqlite3.Connection,
        event_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> OutboxEvent:
        """在当前事务中追加一条 outbox 事件。

        Parameters
        ----------
        conn:
            ``transaction()`` 上下文提供的连接。
        event_type:
            事件类型字符串。
        aggregate_id:
            业务实体 ULID。
        payload:
            事件体 dict。

        Returns
        -------
        OutboxEvent
            已写入的事件记录。
        """
        event = OutboxEvent(
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload=payload,
        )
        conn.execute(
            """
            INSERT INTO outbox (id, event_type, aggregate_id, payload, created_at, processed)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                event.id,
                event.event_type,
                event.aggregate_id,
                json.dumps(event.payload, ensure_ascii=False),
                event.created_at,
            ),
        )
        return event

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def pending_events(self, limit: int = 100) -> list[OutboxEvent]:
        """查询未处理(processed=0)的 outbox 事件。

        Parameters
        ----------
        limit:
            最多返回条数。

        Returns
        -------
        list[OutboxEvent]
            按创建时间升序排列的待处理事件列表。
        """
        conn = self._ensure_conn()
        rows = conn.execute(
            """
            SELECT id, event_type, aggregate_id, payload, created_at
            FROM outbox
            WHERE processed = 0
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            OutboxEvent(
                id=row["id"],
                event_type=row["event_type"],
                aggregate_id=row["aggregate_id"],
                payload=json.loads(row["payload"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def mark_processed(self, event_id: str) -> None:
        """将指定事件标记为已处理(模拟 CDC dispatch)。

        Parameters
        ----------
        event_id:
            ``OutboxEvent.id``(UUID v4 字符串)。
        """
        conn = self._ensure_conn()
        conn.execute(
            "UPDATE outbox SET processed = 1 WHERE id = ?",
            (event_id,),
        )
        conn.commit()

    def count_pending(self) -> int:
        """返回未处理事件数量。"""
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM outbox WHERE processed = 0"
        ).fetchone()
        return row[0]

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn:
            self._conn.close()
            self._conn = None
