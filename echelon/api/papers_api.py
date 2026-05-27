"""
echelon.api.papers_api
========================
V14 统一论文库内部 API — 7 个 endpoint。

注册到 V13 FastAPI app (echelon/api/main.py)。

Endpoints:
1. GET  /papers                     列表查询(topic/日期/cursor 过滤)
2. GET  /papers/{id}                论文详情
3. GET  /papers/{id}/references     引用列表
4. GET  /papers/{id}/pdf            PDF URL
5. POST /crawl/by_query             手动触发抓取
6. POST /crawl/expand               从 seed 按引用扩展
7. GET  /crawl/jobs/{job_id}        任务状态
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from echelon.library.db import LIBRARY_DB_PATH, get_db_stats, get_session
from echelon.crawler.scheduler import schedule_ingestion_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/papers", tags=["v14-papers"])
crawl_router = APIRouter(prefix="/crawl", tags=["v14-crawl"])


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------

class PaperResponse(BaseModel):
    id: str
    openalex_id: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    title: str
    abstract: Optional[str] = None
    publication_date: str
    n_authors: Optional[int] = None
    cited_by_count: Optional[int] = None
    primary_topic_id: Optional[str] = None
    primary_field_id: Optional[str] = None
    source_provider: Optional[str] = None
    open_access: Optional[dict] = None
    is_retracted: bool = False


class PapersListResponse(BaseModel):
    papers: list[PaperResponse]
    total: int
    cursor: Optional[str] = None
    has_more: bool = False


class ReferenceResponse(BaseModel):
    citing_paper_id: str
    cited_paper_id_external: str
    cited_paper_id_internal: Optional[str] = None


class CrawlJobRequest(BaseModel):
    provider: str = "arxiv"
    set_spec: str = "physics:physics.optics"
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    max_results: Optional[int] = None
    delay: float = 3.0
    enrich: bool = False


class ExpandRequest(BaseModel):
    seed_id: str
    depth: int = 1
    max_per_level: int = 20


class JobStatusResponse(BaseModel):
    job_id: str
    provider: str
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    papers_ingested: int = 0
    papers_skipped_duplicate: int = 0
    error_log: Optional[str] = None
    query_params: Optional[dict] = None


# ---------------------------------------------------------------------------
# 1. GET /papers  — 列表查询
# ---------------------------------------------------------------------------

@router.get("", response_model=PapersListResponse, summary="论文列表查询")
async def list_papers(
    topic_id: Optional[str] = Query(None, description="OpenAlex topic_id 或 arXiv 分类"),
    from_date: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD"),
    source_provider: Optional[str] = Query(None, description="来源: arxiv/openalex/crossref"),
    cited_by_min: int = Query(0, description="最低引用数"),
    limit: int = Query(100, ge=1, le=1000, description="每页数量"),
    cursor: Optional[str] = Query(None, description="分页游标(上一次响应的 cursor)"),
    db_path: str = LIBRARY_DB_PATH,
) -> PapersListResponse:
    """
    查询论文列表。

    支持按 topic、日期范围、来源过滤。
    使用 cursor 分页(基于 ULID 有序性)。
    """
    conditions = ["1=1"]
    params: list[Any] = []

    if topic_id:
        conditions.append("primary_topic_id = ?")
        params.append(topic_id)
    if from_date:
        conditions.append("publication_date >= ?")
        params.append(from_date)
    if to_date:
        conditions.append("publication_date <= ?")
        params.append(to_date)
    if source_provider:
        conditions.append("source_provider = ?")
        params.append(source_provider)
    if cited_by_min > 0:
        conditions.append("cited_by_count >= ?")
        params.append(cited_by_min)
    if cursor:
        conditions.append("id > ?")
        params.append(cursor)

    where = " AND ".join(conditions)
    sql = f"SELECT * FROM papers WHERE {where} ORDER BY id LIMIT ?"
    params.append(limit + 1)

    try:
        with get_session(db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
            count_sql = f"SELECT COUNT(*) as n FROM papers WHERE {' AND '.join(conditions[:-1] if cursor else conditions)}"
            total_params = [p for p in params[:-1]]
            if cursor:
                total_params = [p for p in params[:-2]]
            total_row = conn.execute(count_sql, total_params).fetchone()
            total = total_row["n"] if total_row else 0
    except Exception as e:
        logger.error(f"[papers_api] list_papers 查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    has_more = len(rows) > limit
    rows = rows[:limit]

    papers = []
    for row in rows:
        row_dict = dict(row)
        oa = row_dict.get("open_access")
        if oa and isinstance(oa, str):
            try:
                oa = json.loads(oa)
            except Exception:
                oa = None
        papers.append(PaperResponse(
            id=row_dict["id"],
            openalex_id=row_dict.get("openalex_id"),
            doi=row_dict.get("doi"),
            arxiv_id=row_dict.get("arxiv_id"),
            title=row_dict.get("title", ""),
            abstract=row_dict.get("abstract"),
            publication_date=str(row_dict.get("publication_date", "")),
            n_authors=row_dict.get("n_authors"),
            cited_by_count=row_dict.get("cited_by_count"),
            primary_topic_id=row_dict.get("primary_topic_id"),
            primary_field_id=row_dict.get("primary_field_id"),
            source_provider=row_dict.get("source_provider"),
            open_access=oa,
            is_retracted=bool(row_dict.get("is_retracted", 0)),
        ))

    next_cursor = rows[-1]["id"] if (has_more and rows) else None

    return PapersListResponse(
        papers=papers,
        total=total,
        cursor=next_cursor,
        has_more=has_more,
    )


# ---------------------------------------------------------------------------
# 2. GET /papers/{id}  — 论文详情
# ---------------------------------------------------------------------------

@router.get("/{paper_id}", response_model=PaperResponse, summary="论文详情")
async def get_paper(
    paper_id: str,
    db_path: str = LIBRARY_DB_PATH,
) -> PaperResponse:
    """获取单篇论文详情。支持 ULID、arxiv_id、openalex_id、DOI 查找。"""
    try:
        with get_session(db_path) as conn:
            # 按多个 ID 字段查
            row = conn.execute(
                """SELECT * FROM papers WHERE id=? OR arxiv_id=? OR openalex_id=? OR doi=?
                   LIMIT 1""",
                (paper_id, paper_id, paper_id, paper_id)
            ).fetchone()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not row:
        raise HTTPException(status_code=404, detail=f"论文不存在: {paper_id}")

    row_dict = dict(row)
    oa = row_dict.get("open_access")
    if oa and isinstance(oa, str):
        try:
            oa = json.loads(oa)
        except Exception:
            oa = None

    return PaperResponse(
        id=row_dict["id"],
        openalex_id=row_dict.get("openalex_id"),
        doi=row_dict.get("doi"),
        arxiv_id=row_dict.get("arxiv_id"),
        title=row_dict.get("title", ""),
        abstract=row_dict.get("abstract"),
        publication_date=str(row_dict.get("publication_date", "")),
        n_authors=row_dict.get("n_authors"),
        cited_by_count=row_dict.get("cited_by_count"),
        primary_topic_id=row_dict.get("primary_topic_id"),
        primary_field_id=row_dict.get("primary_field_id"),
        source_provider=row_dict.get("source_provider"),
        open_access=oa,
        is_retracted=bool(row_dict.get("is_retracted", 0)),
    )


# ---------------------------------------------------------------------------
# 3. GET /papers/{id}/references  — 引用列表
# ---------------------------------------------------------------------------

@router.get("/{paper_id}/references", summary="论文引用列表")
async def get_references(
    paper_id: str,
    limit: int = Query(100, ge=1, le=1000),
    db_path: str = LIBRARY_DB_PATH,
) -> dict:
    """获取论文的引用关系列表(该论文引用了哪些文献)"""
    try:
        with get_session(db_path) as conn:
            # 先找 internal id
            row = conn.execute(
                "SELECT id FROM papers WHERE id=? OR arxiv_id=? OR openalex_id=? OR doi=? LIMIT 1",
                (paper_id, paper_id, paper_id, paper_id)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"论文不存在: {paper_id}")
            internal_id = row["id"]

            refs = conn.execute(
                """SELECT cited_paper_id_external, cited_paper_id_internal
                   FROM paper_references
                   WHERE citing_paper_id = ?
                   LIMIT ?""",
                (internal_id, limit)
            ).fetchall()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "paper_id": internal_id,
        "references": [
            {
                "cited_id_external": r["cited_paper_id_external"],
                "cited_id_internal": r["cited_paper_id_internal"],
            }
            for r in refs
        ],
        "total": len(refs),
    }


# ---------------------------------------------------------------------------
# 4. GET /papers/{id}/pdf  — PDF URL
# ---------------------------------------------------------------------------

@router.get("/{paper_id}/pdf", summary="论文 PDF 信息")
async def get_pdf(
    paper_id: str,
    db_path: str = LIBRARY_DB_PATH,
) -> dict:
    """获取论文 PDF 存储信息(storage_uri + source_url + license)"""
    try:
        with get_session(db_path) as conn:
            # 先找 internal id
            row = conn.execute(
                "SELECT id, arxiv_id, open_access FROM papers "
                "WHERE id=? OR arxiv_id=? OR openalex_id=? OR doi=? LIMIT 1",
                (paper_id, paper_id, paper_id, paper_id)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"论文不存在: {paper_id}")
            internal_id = row["id"]
            arxiv_id = row["arxiv_id"]

            pdf_row = conn.execute(
                "SELECT * FROM pdfs WHERE paper_id = ?",
                (internal_id,)
            ).fetchone()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if pdf_row:
        return {
            "paper_id": internal_id,
            "storage_uri": pdf_row["storage_uri"],
            "source_url": pdf_row["source_url"],
            "license": pdf_row["license"],
            "sha256": pdf_row["sha256"],
            "size_bytes": pdf_row["size_bytes"],
        }

    # arXiv 论文直接提供 PDF URL
    if arxiv_id:
        oa_url = f"https://arxiv.org/pdf/{arxiv_id}"
        return {
            "paper_id": internal_id,
            "storage_uri": None,
            "source_url": oa_url,
            "license": "open_access",
            "note": "arXiv PDF 未本地化存储,请直接访问 source_url",
        }

    raise HTTPException(
        status_code=404,
        detail=f"论文 {paper_id} 无 PDF 记录"
    )


# ---------------------------------------------------------------------------
# 5. POST /crawl/by_query  — 手动触发抓取
# ---------------------------------------------------------------------------

@crawl_router.post("/by_query", summary="手动触发抓取")
async def crawl_by_query(
    request: CrawlJobRequest,
    background_tasks: BackgroundTasks,
    db_path: str = LIBRARY_DB_PATH,
) -> dict:
    """
    手动触发一次数据抓取任务。

    任务在后台异步执行,返回 job_id 供后续查询状态。
    """
    query_params = {
        "set_spec": request.set_spec,
        "from_date": request.from_date,
        "to_date": request.to_date,
        "max_results": request.max_results,
        "delay": request.delay,
        "enrich": request.enrich,
    }

    job_id = schedule_ingestion_job(
        provider=request.provider,
        query_params=query_params,
        db_path=db_path,
        async_run=True,
    )

    return {
        "job_id": job_id,
        "status": "pending",
        "message": f"摄入任务已创建并在后台运行,provider={request.provider}",
        "query_params": query_params,
    }


# ---------------------------------------------------------------------------
# 6. POST /crawl/expand  — 从 seed 按引用扩展
# ---------------------------------------------------------------------------

@crawl_router.post("/expand", summary="从 seed 论文按引用 BFS 扩展")
async def expand_from_seed(
    request: ExpandRequest,
    db_path: str = LIBRARY_DB_PATH,
) -> dict:
    """
    从种子论文出发,按引用关系 BFS 扩展摄入相关论文。

    用于 Sci-Bot 探索新论文场景。
    深度 depth=1 → 只拉引用;depth=2 → 引用的引用。
    """
    from echelon.library.db import get_session

    # 找种子论文
    with get_session(db_path) as conn:
        seed_row = conn.execute(
            "SELECT id, arxiv_id, doi, title FROM papers "
            "WHERE id=? OR arxiv_id=? OR openalex_id=? OR doi=? LIMIT 1",
            (request.seed_id,) * 4
        ).fetchone()

    if not seed_row:
        raise HTTPException(status_code=404, detail=f"种子论文不存在: {request.seed_id}")

    seed_internal_id = seed_row["id"]

    # BFS 扩展
    visited = {seed_internal_id}
    queue = [seed_internal_id]
    expanded_jobs = []

    for depth_level in range(request.depth):
        next_queue = []
        for cid in queue[:request.max_per_level]:
            with get_session(db_path) as conn:
                refs = conn.execute(
                    "SELECT cited_paper_id_external FROM paper_references "
                    "WHERE citing_paper_id = ? LIMIT ?",
                    (cid, request.max_per_level)
                ).fetchall()

            for ref_row in refs:
                ref_ext_id = ref_row["cited_paper_id_external"]
                if ref_ext_id not in visited:
                    visited.add(ref_ext_id)
                    # 按 arXiv ID 触发摄入(若是 W 开头则用 OpenAlex)
                    if ref_ext_id.startswith("W"):
                        job_id = schedule_ingestion_job(
                            provider="openalex",
                            query_params={"openalex_id": ref_ext_id},
                            db_path=db_path,
                            async_run=True,
                        )
                    else:
                        job_id = schedule_ingestion_job(
                            provider="arxiv",
                            query_params={"arxiv_id": ref_ext_id},
                            db_path=db_path,
                            async_run=True,
                        )
                    expanded_jobs.append({"ref_id": ref_ext_id, "job_id": job_id})
                    next_queue.append(ref_ext_id)

        queue = next_queue

    return {
        "seed_id": seed_internal_id,
        "seed_title": seed_row["title"],
        "depth": request.depth,
        "expanded_count": len(expanded_jobs),
        "jobs": expanded_jobs[:20],  # 只返回前 20 个
        "message": f"已触发 {len(expanded_jobs)} 个扩展摄入任务",
    }


# ---------------------------------------------------------------------------
# 7. GET /crawl/jobs/{job_id}  — 任务状态
# ---------------------------------------------------------------------------

@crawl_router.get("/jobs/{job_id}", response_model=JobStatusResponse, summary="摄入任务状态")
async def get_job_status(
    job_id: str,
    db_path: str = LIBRARY_DB_PATH,
) -> JobStatusResponse:
    """获取摄入任务的状态和统计信息"""
    try:
        with get_session(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE job_id = ?",
                (job_id,)
            ).fetchone()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not row:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}")

    row_dict = dict(row)
    qp = row_dict.get("query_params")
    if qp and isinstance(qp, str):
        try:
            qp = json.loads(qp)
        except Exception:
            qp = None

    return JobStatusResponse(
        job_id=row_dict["job_id"],
        provider=row_dict["provider"],
        status=row_dict["status"],
        started_at=row_dict.get("started_at"),
        finished_at=row_dict.get("finished_at"),
        papers_ingested=row_dict.get("papers_ingested", 0),
        papers_skipped_duplicate=row_dict.get("papers_skipped_duplicate", 0),
        error_log=row_dict.get("error_log"),
        query_params=qp,
    )


# ---------------------------------------------------------------------------
# 统计端点
# ---------------------------------------------------------------------------

@crawl_router.get("/stats/db", summary="数据库统计")
async def get_library_stats(db_path: str = LIBRARY_DB_PATH) -> dict:
    """获取数据库各表行数和文件大小"""
    return get_db_stats(db_path)
