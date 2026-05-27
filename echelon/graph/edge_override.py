"""
echelon.graph.edge_override
==============================
EdgeOverride 管理:软删除 + audit_log 回溯。

[修订自 AUDIT-079]
V11.1 问题:EdgeOverride \"delete\" 操作将边从图中移除后,
``load_edge(edge_id)`` 直接查询图存储,遇到已删除边返回 404,
导致下游引用该边的代码崩溃。

V11.2 修复(软删除 + audit_log fallback):
  1. ``apply_edge_override(action, ...)`` 执行 override 并将操作前状态
     写入 ``edge_audit_log`` 表(SQLite Pilot)。
  2. ``load_edge_with_audit_fallback(edge_id)`` 先查图存储,
     若 404 则从 ``edge_audit_log.before_state`` 恢复 source/target。
  3. 支持 ``add`` / ``update`` / ``delete`` 三种 action。

参考: V11.2 白皮书 §6.4.2;AUDIT-079
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generator

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH: str = "/tmp/echelon_edge_override.db"
AUDIT_TABLE: str = "edge_audit_log"


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class EdgeAction(str, Enum):
    """EdgeOverride 操作类型。"""

    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"


# ---------------------------------------------------------------------------
# Edge 数据模型
# ---------------------------------------------------------------------------


class EdgeRecord(BaseModel):
    """图边记录。

    [修订自 AUDIT-079]

    Attributes
    ----------
    edge_id:
        边 ULID。
    source_id:
        源节点 ULID。
    target_id:
        目标节点 ULID。
    edge_type:
        边类型(如 ``"cites"``, ``"co_cites"`` 等)。
    weight:
        边权重。
    is_deleted:
        软删除标志(True = 已删除但可从 audit_log 恢复)。
    extra:
        额外属性。
    """

    edge_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    edge_type: str = Field(default="cites")
    weight: float = Field(default=1.0)
    is_deleted: bool = Field(default=False)
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


@contextmanager
def _db(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_tables(db_path: str) -> None:
    """建表:edge_store(边主表)+ edge_audit_log(操作日志)。"""
    with _db(db_path) as conn:
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS edge_store (
                edge_id     TEXT PRIMARY KEY,
                source_id   TEXT NOT NULL,
                target_id   TEXT NOT NULL,
                edge_type   TEXT NOT NULL DEFAULT 'cites',
                weight      REAL NOT NULL DEFAULT 1.0,
                is_deleted  INTEGER NOT NULL DEFAULT 0,
                extra       TEXT NOT NULL DEFAULT '{{}}',
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                edge_id      TEXT NOT NULL,
                action       TEXT NOT NULL,        -- add/update/delete
                before_state TEXT,                 -- JSON of EdgeRecord before change
                after_state  TEXT,                 -- JSON of EdgeRecord after change
                operator_id  TEXT,
                created_at   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_edge_id
                ON {AUDIT_TABLE} (edge_id);
            """
        )


# ---------------------------------------------------------------------------
# EdgeOverrideStore:在内存 dict 上做 Pilot 模拟
# ---------------------------------------------------------------------------


class EdgeOverrideStore:
    """EdgeOverride 存储(SQLite Pilot)。

    [修订自 AUDIT-079]

    Examples
    --------
    ::

        store = EdgeOverrideStore()
        edge = EdgeRecord(edge_id="E1", source_id="A", target_id="B")
        store.apply_edge_override(EdgeAction.ADD, edge)
        store.apply_edge_override(EdgeAction.DELETE, edge)
        recovered = store.load_edge_with_audit_fallback("E1")
        assert recovered["source_id"] == "A"
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        _ensure_tables(db_path)

    # ------------------------------------------------------------------
    # apply_edge_override
    # ------------------------------------------------------------------

    def apply_edge_override(
        self,
        action: EdgeAction | str,
        edge: EdgeRecord,
        operator_id: str | None = None,
    ) -> None:
        """应用 EdgeOverride 操作并写入 audit_log。

        [修订自 AUDIT-079]

        Parameters
        ----------
        action:
            操作类型(add/update/delete)。
        edge:
            边记录。
        operator_id:
            操作者 ID(Expert ULID 或系统标识)。
        """
        if isinstance(action, str):
            action = EdgeAction(action)

        now = datetime.now(timezone.utc).isoformat()

        with _db(self.db_path) as conn:
            # 读取 before_state
            row = conn.execute(
                "SELECT * FROM edge_store WHERE edge_id = ?",
                (edge.edge_id,),
            ).fetchone()
            before_state = json.dumps(dict(row)) if row else None

            if action == EdgeAction.ADD:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO edge_store
                        (edge_id, source_id, target_id, edge_type, weight,
                         is_deleted, extra, updated_at)
                    VALUES (?,?,?,?,?,0,?,?)
                    """,
                    (
                        edge.edge_id,
                        edge.source_id,
                        edge.target_id,
                        edge.edge_type,
                        edge.weight,
                        json.dumps(edge.extra),
                        now,
                    ),
                )

            elif action == EdgeAction.UPDATE:
                conn.execute(
                    """
                    UPDATE edge_store
                    SET source_id=?, target_id=?, edge_type=?, weight=?,
                        is_deleted=0, extra=?, updated_at=?
                    WHERE edge_id=?
                    """,
                    (
                        edge.source_id,
                        edge.target_id,
                        edge.edge_type,
                        edge.weight,
                        json.dumps(edge.extra),
                        now,
                        edge.edge_id,
                    ),
                )

            elif action == EdgeAction.DELETE:
                # 软删除:标记 is_deleted=1,不物理删除行
                conn.execute(
                    """
                    UPDATE edge_store
                    SET is_deleted=1, updated_at=?
                    WHERE edge_id=?
                    """,
                    (now, edge.edge_id),
                )

            # after_state
            after_row = conn.execute(
                "SELECT * FROM edge_store WHERE edge_id = ?",
                (edge.edge_id,),
            ).fetchone()
            after_state = json.dumps(dict(after_row)) if after_row else None

            # 写入 audit_log
            conn.execute(
                f"""
                INSERT INTO {AUDIT_TABLE}
                    (edge_id, action, before_state, after_state, operator_id, created_at)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    edge.edge_id,
                    action.value,
                    before_state,
                    after_state,
                    operator_id,
                    now,
                ),
            )

        logger.info(
            "[AUDIT-079] apply_edge_override: edge=%r action=%s operator=%r",
            edge.edge_id,
            action.value,
            operator_id,
        )

    # ------------------------------------------------------------------
    # load_edge_with_audit_fallback
    # ------------------------------------------------------------------

    def load_edge_with_audit_fallback(
        self,
        edge_id: str,
    ) -> dict[str, Any]:
        """加载边记录;若边已删除,从 audit_log.before_state 恢复。

        [修订自 AUDIT-079]

        Parameters
        ----------
        edge_id:
            边 ULID。

        Returns
        -------
        dict
            边记录字典,包含字段:
            - ``edge_id``, ``source_id``, ``target_id``, ``edge_type``, ``weight``
            - ``is_deleted``: True 表示从 audit_log 恢复的已删除边
            - ``_source``: ``"live"`` 或 ``"audit_log"``

        Raises
        ------
        KeyError
            若边在图存储和 audit_log 中均不存在。
        """
        with _db(self.db_path) as conn:
            # 1. 先查 edge_store
            row = conn.execute(
                "SELECT * FROM edge_store WHERE edge_id = ?",
                (edge_id,),
            ).fetchone()

            if row is not None:
                record = dict(row)
                record["is_deleted"] = bool(record.get("is_deleted", 0))
                record["_source"] = "live"

                if not record["is_deleted"]:
                    return record

                # 已软删除:仍尝试从 audit_log 取 before_state 补充信息
                logger.info(
                    "[AUDIT-079] edge %r is soft-deleted; trying audit_log fallback",
                    edge_id,
                )

            # 2. Fallback: 从 audit_log 最后一次 before_state 恢复
            audit_row = conn.execute(
                f"""
                SELECT before_state
                FROM {AUDIT_TABLE}
                WHERE edge_id = ?
                  AND action = 'delete'
                  AND before_state IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (edge_id,),
            ).fetchone()

            if audit_row and audit_row["before_state"]:
                before = json.loads(audit_row["before_state"])
                before["is_deleted"] = True
                before["_source"] = "audit_log"
                logger.info(
                    "[AUDIT-079] edge %r recovered from audit_log: source=%r target=%r",
                    edge_id,
                    before.get("source_id"),
                    before.get("target_id"),
                )
                return before

        raise KeyError(
            f"[AUDIT-079] Edge {edge_id!r} not found in edge_store or audit_log"
        )

    def get_audit_log(self, edge_id: str) -> list[dict]:
        """获取指定边的完整 audit 日志。"""
        with _db(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {AUDIT_TABLE}
                WHERE edge_id = ?
                ORDER BY created_at
                """,
                (edge_id,),
            ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 模块级便捷函数
# ---------------------------------------------------------------------------


def apply_edge_override(
    action: EdgeAction | str,
    edge: EdgeRecord,
    operator_id: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """模块级 apply_edge_override(使用默认 store)。

    [修订自 AUDIT-079]
    """
    store = EdgeOverrideStore(db_path=db_path)
    store.apply_edge_override(action, edge, operator_id=operator_id)


def load_edge_with_audit_fallback(
    edge_id: str,
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """模块级 load_edge_with_audit_fallback(使用默认 store)。

    [修订自 AUDIT-079]
    """
    store = EdgeOverrideStore(db_path=db_path)
    return store.load_edge_with_audit_fallback(edge_id)
