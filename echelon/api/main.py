"""
echelon.api.main
================
[V13] Echelon FastAPI 应用入口。
包含 V14B graph_visual edit/search router。

Usage (dev):
    uvicorn echelon.api.main:app --reload

OpenAPI docs:
    http://localhost:8000/docs       (Swagger UI)
    http://localhost:8000/redoc      (ReDoc)
    http://localhost:8000/openapi.json
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from echelon.api.graph_visual import router as graph_visual_router
from echelon.api.papers_api import router as papers_router, crawl_router

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Echelon API",
    version="14.0.0-crawler",
    description=(
        "Echelon 融合图谱 API。\n\n"
        "**V14B 图谱接口** (`/graph/visual/*`) 已注册,支持 materialized "
        "visual graph 检索与专家编辑记录。\n\n"
        "RBAC (AUDIT-056): 使用 `Authorization: Bearer <pilot-*-token>` 或 "
        "`X-Pilot-Token` header。\n"
        "  - `pilot-admin-token` → admin\n"
        "  - `pilot-expert-token` → expert\n"
        "  - `pilot-viewer-token` → viewer"
    ),
    contact={"name": "Echelon Team"},
    license_info={"name": "Internal"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8787",
        "http://127.0.0.1:8787",
        "null",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------

app.include_router(graph_visual_router)
# V14 统一论文库 API
app.include_router(papers_router)
app.include_router(crawl_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"], summary="健康检查")
async def health() -> dict:
    """返回服务健康状态。"""
    return {"status": "ok", "version": "14.0.0-crawler"}


# ---------------------------------------------------------------------------
# Root redirect to docs
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root() -> JSONResponse:
    return JSONResponse(
        {"message": "Echelon API V14B", "docs": "/docs", "openapi": "/openapi.json"}
    )
