"""
echelon.core.async_task_quota
===============================
Merge/Split API 限额追踪器(SQLite 简易实现)。

[修订自 AUDIT-030]
V11.1 问题:Merge/Split API 没有 quota 控制,expert 用户可以无限触发,
导致图重算任务排队雪崩。

V11.2 修复:
  - ``MergeQuotaTracker``:基于 SQLite 的滑动窗口 quota(≤10 次/小时/expert)
  - 提供 ``check_and_consume(expert_id) -> bool`` 接口:
      - True  → quota 未超,已扣减 1 次
      - False → quota 耗尽(调用方返回 HTTP 429)
  - 提供 ``get_remaining(expert_id) -> int`` 查询剩余次数
  - Pilot 使用 SQLite;生产替换为 Redis INCR + EXPIRE

参考: V11.2 白皮书 §15.10.1 Merge/Split quota
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Generator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

MERGE_QUOTA_PER_HOUR: int = 10
"""每位 expert 每小时最多 Merge/Split 操作次数 [AUDIT-030]。"""

DEFAULT_DB_PATH: str = "/tmp/echelon_quota.db"

QUOTA_TABLE: str = "merge_split_quota_log"


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


def _ensure_table(db_path: str) -> None:
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {QUOTA_TABLE} (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        expert_id   TEXT    NOT NULL,
        action      TEXT    NOT NULL DEFAULT 'merge_split',
        created_at  TEXT    NOT NULL   -- ISO 8601 UTC
    );
    CREATE INDEX IF NOT EXISTS idx_quota_expert_created
        ON {QUOTA_TABLE} (expert_id, created_at);
    """
    with _db(db_path) as conn:
        conn.executescript(ddl)


# ---------------------------------------------------------------------------
# MergeQuotaTracker
# ---------------------------------------------------------------------------


class MergeQuotaTracker:
    """Merge/Split API 滑动窗口 quota 追踪器(SQLite Pilot)。

    [修订自 AUDIT-030]

    Parameters
    ----------
    db_path:
        SQLite 数据库路径(Pilot)。
    quota_per_hour:
        每位 expert 每小时最大操作次数,默认 10。
    window_seconds:
        滑动窗口大小(秒),默认 3600(1 小时)。

    Examples
    --------
    ::

        tracker = MergeQuotaTracker()
        if tracker.check_and_consume("expert_001"):
            # 执行 merge/split ...
        else:
            raise HTTPException(429, "Merge/Split quota exceeded (≤10/hour)")
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        quota_per_hour: int = MERGE_QUOTA_PER_HOUR,
        window_seconds: int = 3600,
    ) -> None:
        self.db_path = db_path
        self.quota_per_hour = quota_per_hour
        self.window_seconds = window_seconds
        _ensure_table(db_path)

    # ------------------------------------------------------------------
    # 核心接口
    # ------------------------------------------------------------------

    def check_and_consume(
        self,
        expert_id: str,
        action: str = "merge_split",
    ) -> bool:
        """检查 quota 并在未超限时扣减 1 次。

        [修订自 AUDIT-030]

        Parameters
        ----------
        expert_id:
            Expert 用户 ID。
        action:
            操作类型标签(默认 ``"merge_split"``),便于后续分别统计
            merge 和 split。

        Returns
        -------
        bool
            ``True``  → 未超限,quota 已扣减 1(可以执行操作)。
            ``False`` → 已超限(调用方应返回 HTTP 429)。
        """
        now = datetime.now(timezone.utc)
        window_start = (now - timedelta(seconds=self.window_seconds)).isoformat()

        with _db(self.db_path) as conn:
            # 计算滑动窗口内已使用次数
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS cnt
                FROM {QUOTA_TABLE}
                WHERE expert_id = ?
                  AND created_at >= ?
                """,
                (expert_id, window_start),
            ).fetchone()
            used = row["cnt"] if row else 0

            if used >= self.quota_per_hour:
                logger.warning(
                    "[AUDIT-030] quota exceeded: expert=%r used=%d limit=%d",
                    expert_id,
                    used,
                    self.quota_per_hour,
                )
                return False

            # 扣减:写入一条日志记录
            conn.execute(
                f"""
                INSERT INTO {QUOTA_TABLE} (expert_id, action, created_at)
                VALUES (?, ?, ?)
                """,
                (expert_id, action, now.isoformat()),
            )
            logger.debug(
                "[AUDIT-030] quota consumed: expert=%r used=%d→%d limit=%d",
                expert_id,
                used,
                used + 1,
                self.quota_per_hour,
            )
            return True

    def get_remaining(self, expert_id: str) -> int:
        """查询 expert 在当前滑动窗口内剩余 quota。

        [修订自 AUDIT-030]

        Returns
        -------
        int
            剩余次数(≥ 0)。
        """
        now = datetime.now(timezone.utc)
        window_start = (now - timedelta(seconds=self.window_seconds)).isoformat()

        with _db(self.db_path) as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS cnt
                FROM {QUOTA_TABLE}
                WHERE expert_id = ?
                  AND created_at >= ?
                """,
                (expert_id, window_start),
            ).fetchone()
        used = row["cnt"] if row else 0
        return max(0, self.quota_per_hour - used)

    def get_usage_log(self, expert_id: str, limit: int = 20) -> list[dict]:
        """查询最近操作日志(调试用)。

        Returns
        -------
        list[dict]
            最近 ``limit`` 条操作记录。
        """
        with _db(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT id, expert_id, action, created_at
                FROM {QUOTA_TABLE}
                WHERE expert_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (expert_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def reset_quota(self, expert_id: str) -> int:
        """清除指定 expert 的所有 quota 记录(仅测试/管理员用途)。

        Returns
        -------
        int
            删除的记录数。
        """
        with _db(self.db_path) as conn:
            conn.execute(
                f"DELETE FROM {QUOTA_TABLE} WHERE expert_id = ?",
                (expert_id,),
            )
            deleted = conn.execute("SELECT changes()").fetchone()[0]
        logger.info("[AUDIT-030] quota reset: expert=%r deleted=%d", expert_id, deleted)
        return deleted
