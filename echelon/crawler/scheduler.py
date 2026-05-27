"""
echelon.crawler.scheduler
===========================
V14 摄入任务调度器 (Pilot: threading.Thread + time.sleep)。

Pilot 不引入 Celery,用原生线程简化。
Postgres/生产切换路径: Celery beat + Redis broker。

功能:
- schedule_ingestion_job: 创建任务 + 写 ingestion_jobs 表 + 启动后台线程
- ingestion_completed 事件: 每次 ingest 后触发(Outbox 模式)
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

from echelon.core.ulid_utils import ulid_new
from echelon.library.db import (
    LIBRARY_DB_PATH,
    get_db_stats,
    get_hwm_v14,
    set_hwm_v14,
    upsert_ingestion_job,
    upsert_paper,
    upsert_paper_references,
    upsert_author,
    link_paper_author,
)
from echelon.library.schema import IngestionJob, JobStatusEnum, Paper

logger = logging.getLogger(__name__)

# Outbox 事件回调列表
_event_handlers: list[Callable[[str, dict], None]] = []


def register_event_handler(handler: Callable[[str, dict], None]) -> None:
    """
    注册 Outbox 事件回调。

    回调签名: handler(event_name: str, payload: dict) -> None

    用法::

        def on_completed(event: str, payload: dict):
            print(f"摄入完成: {payload}")

        register_event_handler(on_completed)
    """
    _event_handlers.append(handler)


def emit_event(event_name: str, payload: dict) -> None:
    """触发 Outbox 事件,调用所有注册的处理器"""
    for handler in _event_handlers:
        try:
            handler(event_name, payload)
        except Exception as e:
            logger.error(f"[scheduler] 事件处理器异常: {e}")


def schedule_ingestion_job(
    provider: str,
    query_params: dict,
    db_path: str = LIBRARY_DB_PATH,
    async_run: bool = True,
) -> str:
    """
    创建并调度一个摄入任务。

    Args:
        provider: 'arxiv' | 'openalex' | 'crossref'
        query_params: 查询参数字典,如 {set_spec, from_date, to_date, max_results}
        db_path: 数据库路径
        async_run: 是否在后台线程异步执行

    Returns:
        job_id: ULID 字符串
    """
    job_id = ulid_new()
    job = IngestionJob(
        job_id=job_id,
        provider=provider,
        query_params=query_params,
        status=JobStatusEnum.PENDING,
    )
    upsert_ingestion_job(job.model_dump(), db_path=db_path)
    logger.info(f"[scheduler] 任务已创建: job_id={job_id} provider={provider}")

    if async_run:
        t = threading.Thread(
            target=_run_job_sync,
            args=(job_id, provider, query_params, db_path),
            daemon=True,
            name=f"ingestion-{job_id[:8]}",
        )
        t.start()
        logger.info(f"[scheduler] 后台线程已启动: {t.name}")

    return job_id


def _run_job_sync(
    job_id: str,
    provider: str,
    query_params: dict,
    db_path: str,
) -> None:
    """
    在同步上下文中运行异步摄入任务。

    将协程包装到新的事件循环中执行。
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _run_job_async(job_id, provider, query_params, db_path)
        )
    finally:
        loop.close()


async def _run_job_async(
    job_id: str,
    provider: str,
    query_params: dict,
    db_path: str,
) -> None:
    """
    异步执行摄入任务。

    流程:
    1. 更新任务状态为 running
    2. 根据 provider 实例化对应 Harvester
    3. 运行摄入:拉取 → 去重 → 写库
    4. 更新 HWM
    5. 更新任务状态为 done/failed
    6. 触发 ingestion_completed 事件
    """
    from echelon.crawler.worker import run_ingestion

    # 标记为 running
    upsert_ingestion_job(
        {
            "job_id": job_id,
            "provider": provider,
            "query_params": query_params,
            "status": JobStatusEnum.RUNNING,
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
        db_path=db_path,
    )

    try:
        result = await run_ingestion(provider, query_params, job_id, db_path)

        # 标记为 done
        upsert_ingestion_job(
            {
                "job_id": job_id,
                "provider": provider,
                "query_params": query_params,
                "status": JobStatusEnum.DONE,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "papers_ingested": result.get("papers_ingested", 0),
                "papers_skipped_duplicate": result.get("papers_skipped_duplicate", 0),
            },
            db_path=db_path,
        )

        # 触发 Outbox 事件
        emit_event(
            "ingestion_completed",
            {
                "job_id": job_id,
                "provider": provider,
                "query_params": query_params,
                **result,
            }
        )
        logger.info(f"[scheduler] 任务完成: job_id={job_id}, 结果={result}")

    except Exception as e:
        logger.error(f"[scheduler] 任务失败: job_id={job_id}: {e}", exc_info=True)
        upsert_ingestion_job(
            {
                "job_id": job_id,
                "provider": provider,
                "query_params": query_params,
                "status": JobStatusEnum.FAILED,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_log": str(e)[:2000],
            },
            db_path=db_path,
        )
        emit_event(
            "ingestion_failed",
            {"job_id": job_id, "provider": provider, "error": str(e)}
        )
