"""
echelon.ingest.retraction_check
==================================
撤稿增量检查与级联失效。

[修订自 AUDIT-081]
V11.1 问题:``is_retracted`` 字段在 ingestion 时一次性写入后不再更新。
若论文发表后才被撤稿(常见于"室温超导"类事件),系统中该论文仍标记为有效,
导致图谱推荐、卡点提炼等下游模块基于已失效论文产生错误结论。

V11.2 修复:
  - ``weekly_retraction_check(corpus_papers)``
      每周扫描最近 1 年论文,检查 ``is_retracted`` 状态变化。
  - ``cascade_invalidate(retracted_paper_id, db_paths)``
      对新撤稿论文执行级联失效:
      1. 在 paper 表将 ``is_retracted=True``
      2. 在 Neo4j 软删除相关边(Pilot:SQLite edge_store)
      3. 向专家发送告警(Pilot:写入 alert_log 表)

参考: V11.2 白皮书 §3.3.6, §6.5.1;AUDIT-081
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Generator

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH: str = "/tmp/echelon_retraction.db"
RETRACTION_CHECK_WINDOW_DAYS: int = 365  # 每次检查最近 1 年的论文
ALERT_TABLE: str = "retraction_alert_log"


# ---------------------------------------------------------------------------
# 论文引用(用于 corpus 传入)
# ---------------------------------------------------------------------------


class CorpusPaperRef(BaseModel):
    """语料库论文引用(用于撤稿检查输入)。

    Attributes
    ----------
    paper_id:
        论文 ULID 或 OpenAlex ID。
    title:
        论文标题。
    publication_date:
        发表日期(ISO 字符串或 datetime.date)。
    is_retracted:
        当前已知撤稿状态。
    doi:
        DOI(可选,用于向 Crossref/Retraction Watch 查询)。
    openalex_id:
        OpenAlex ID(可选)。
    """

    paper_id: str = Field(min_length=1)
    title: str | None = None
    publication_date: str | None = None  # ISO 8601
    is_retracted: bool = False
    doi: str | None = None
    openalex_id: str | None = None

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
    """建表:paper_store(论文状态)+ retraction_alert_log(告警日志)。"""
    with _db(db_path) as conn:
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS paper_store (
                paper_id        TEXT PRIMARY KEY,
                title           TEXT,
                publication_date TEXT,
                is_retracted    INTEGER NOT NULL DEFAULT 0,
                updated_at      TEXT NOT NULL,
                extra           TEXT NOT NULL DEFAULT '{{}}'
            );

            CREATE TABLE IF NOT EXISTS {ALERT_TABLE} (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id        TEXT NOT NULL,
                alert_type      TEXT NOT NULL DEFAULT 'retraction',
                message         TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                acknowledged    INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_alert_paper_id
                ON {ALERT_TABLE} (paper_id);
            """
        )


# ---------------------------------------------------------------------------
# 每周撤稿检查
# ---------------------------------------------------------------------------


def weekly_retraction_check(
    corpus_papers: list[CorpusPaperRef | dict],
    db_path: str = DEFAULT_DB_PATH,
    fetcher_fn: Any = None,
) -> dict[str, Any]:
    """每周扫描最近 1 年论文的撤稿状态。

    [修订自 AUDIT-081]

    Algorithm:
    1. 过滤出 publication_date 在最近 ``RETRACTION_CHECK_WINDOW_DAYS`` 天内的论文
    2. 调用 ``fetcher_fn(paper_ref) -> bool`` 查询最新撤稿状态
       (Pilot: fetcher_fn=None 时使用 mock,保持 is_retracted 不变)
    3. 若状态变化(False → True),调用 ``cascade_invalidate``

    Parameters
    ----------
    corpus_papers:
        语料库论文列表(``CorpusPaperRef`` 或原始 dict)。
    db_path:
        SQLite 数据库路径(Pilot)。
    fetcher_fn:
        可选的外部状态查询函数 ``(CorpusPaperRef) -> bool``。
        None → Pilot mock(保持当前状态)。

    Returns
    -------
    dict
        摘要:
        - ``checked_count``: 检查论文数
        - ``newly_retracted``: 新发现撤稿论文 ID 列表
        - ``unchanged_count``: 状态未变论文数
        - ``error_count``: 查询失败次数
        - ``check_window_days``: 检查窗口天数
    """
    _ensure_tables(db_path)

    # 规范化输入
    papers: list[CorpusPaperRef] = []
    for p in corpus_papers:
        if isinstance(p, CorpusPaperRef):
            papers.append(p)
        elif isinstance(p, dict):
            papers.append(CorpusPaperRef(**p))
        else:
            raise TypeError(f"[AUDIT-081] unexpected type: {type(p)}")

    # 过滤最近 1 年的论文
    cutoff = date.today() - timedelta(days=RETRACTION_CHECK_WINDOW_DAYS)
    recent_papers = []
    for p in papers:
        if p.publication_date:
            try:
                pub = date.fromisoformat(p.publication_date[:10])
                if pub >= cutoff:
                    recent_papers.append(p)
            except ValueError:
                recent_papers.append(p)  # 日期解析失败:纳入检查
        else:
            recent_papers.append(p)

    logger.info(
        "[AUDIT-081] weekly_retraction_check: total=%d recent(≤%dd)=%d",
        len(papers),
        RETRACTION_CHECK_WINDOW_DAYS,
        len(recent_papers),
    )

    newly_retracted: list[str] = []
    unchanged_count = 0
    error_count = 0

    for paper in recent_papers:
        try:
            if fetcher_fn is not None:
                new_is_retracted: bool = fetcher_fn(paper)
            else:
                # Pilot mock:保持原状态(不做真实 API 调用)
                new_is_retracted = paper.is_retracted

            if new_is_retracted and not paper.is_retracted:
                # 状态变化:False → True
                logger.warning(
                    "[AUDIT-081] newly retracted: paper_id=%r title=%r",
                    paper.paper_id,
                    paper.title,
                )
                newly_retracted.append(paper.paper_id)
                cascade_invalidate(paper.paper_id, db_path=db_path)
            else:
                unchanged_count += 1

        except Exception as exc:
            logger.error(
                "[AUDIT-081] retraction check failed for paper %r: %s",
                paper.paper_id,
                exc,
            )
            error_count += 1

    result = {
        "checked_count": len(recent_papers),
        "newly_retracted": newly_retracted,
        "unchanged_count": unchanged_count,
        "error_count": error_count,
        "check_window_days": RETRACTION_CHECK_WINDOW_DAYS,
    }
    logger.info("[AUDIT-081] weekly_retraction_check result: %s", result)
    return result


# ---------------------------------------------------------------------------
# 级联失效
# ---------------------------------------------------------------------------


def cascade_invalidate(
    retracted_paper_id: str,
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """对撤稿论文执行级联失效。

    [修订自 AUDIT-081]

    操作序列:
    1. 在 paper_store 将 ``is_retracted=1``
    2. 在 edge_store(若存在)软删除涉及该论文的所有边
    3. 写入专家告警日志(``retraction_alert_log``)

    Parameters
    ----------
    retracted_paper_id:
        已确认撤稿的论文 ULID。
    db_path:
        SQLite 数据库路径(Pilot)。

    Returns
    -------
    dict
        操作摘要:
        - ``paper_id``: 论文 ID
        - ``paper_updated``: bool
        - ``edges_invalidated``: 软删除的边数
        - ``alert_written``: bool
        - ``invalidated_at``: ISO 8601 时间戳
    """
    _ensure_tables(db_path)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    paper_updated = False
    edges_invalidated = 0
    alert_written = False

    with _db(db_path) as conn:
        # 1. 更新 paper_store
        conn.execute(
            """
            UPDATE paper_store
            SET is_retracted=1, updated_at=?
            WHERE paper_id=?
            """,
            (now_iso, retracted_paper_id),
        )
        # 若不存在则插入(保证状态写入)
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_store
                (paper_id, is_retracted, updated_at, extra)
            VALUES (?,1,?,?)
            """,
            (retracted_paper_id, now_iso, "{}"),
        )
        paper_updated = True

        # 2. 软删除 edge_store 中涉及该论文的边(若表存在)
        try:
            result = conn.execute(
                """
                UPDATE edge_store
                SET is_deleted=1, updated_at=?
                WHERE (source_id=? OR target_id=?)
                  AND is_deleted=0
                """,
                (now_iso, retracted_paper_id, retracted_paper_id),
            )
            edges_invalidated = result.rowcount
        except sqlite3.OperationalError:
            # edge_store 表不存在(纯 retraction DB 场景)
            edges_invalidated = 0

        # 3. 写入专家告警日志
        message = (
            f"论文 {retracted_paper_id!r} 已被撤稿。"
            "相关边已级联失效。请人工审查引用该论文的卡点结论。"
        )
        conn.execute(
            f"""
            INSERT INTO {ALERT_TABLE}
                (paper_id, alert_type, message, created_at, acknowledged)
            VALUES (?,?,?,?,0)
            """,
            (retracted_paper_id, "retraction", message, now_iso),
        )
        alert_written = True

    result_dict = {
        "paper_id": retracted_paper_id,
        "paper_updated": paper_updated,
        "edges_invalidated": edges_invalidated,
        "alert_written": alert_written,
        "invalidated_at": now_iso,
    }
    logger.warning(
        "[AUDIT-081] cascade_invalidate complete: %s",
        result_dict,
    )
    return result_dict


def get_retraction_alerts(
    db_path: str = DEFAULT_DB_PATH,
    unacknowledged_only: bool = True,
) -> list[dict]:
    """获取撤稿告警列表。

    [修订自 AUDIT-081]

    Parameters
    ----------
    db_path:
        SQLite 数据库路径。
    unacknowledged_only:
        True → 仅返回未确认告警。

    Returns
    -------
    list[dict]
        告警记录列表。
    """
    _ensure_tables(db_path)
    with _db(db_path) as conn:
        if unacknowledged_only:
            rows = conn.execute(
                f"SELECT * FROM {ALERT_TABLE} WHERE acknowledged=0 ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM {ALERT_TABLE} ORDER BY created_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]
