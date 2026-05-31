"""
echelon.api.graph_visual
========================
[V14B] FastAPI router for graph visual edit + search.

参考: V13 系统级方案 §4 接口预埋
继承 V11.2 RBAC (AUDIT-056): require_role("expert"|"viewer")
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from echelon.schema.graph_visual_edit import EvidenceAtomSearchQuery, GraphSearchQuery, GraphVisualEdit
from echelon.api.graph_visual_backend import (
    get_visual_clusters,
    get_visual_edges,
    get_visual_edit_history,
    get_visual_edit_status,
    get_visual_graph_status,
    get_visual_nodes,
    get_visual_paper_detail,
    get_topic_lens,
    get_visual_story_steps,
    get_visual_tiles,
    search_evidence_atoms,
    search_visual_graph,
    submit_visual_edit,
)
from echelon.core.rbac import (
    check_role,
    AuthError,
)

router = APIRouter(
    prefix="/graph/visual",
    tags=["graph_visual_v14b"],
)


# ---------------------------------------------------------------------------
# FastAPI dependency factories (convert RBAC check_role into Depends)
# [V11.2 RBAC AUDIT-056] require_role is designed as a decorator;
# here we wrap it as FastAPI Depends-compatible async functions.
# ---------------------------------------------------------------------------

def _make_role_dependency(minimum_role: str):
    """Create a FastAPI dependency that enforces minimum RBAC role.

    Raises HTTP 401/403 on auth failure so FastAPI can handle the response.
    """
    async def dependency(request: Request) -> str:
        try:
            return check_role(request, minimum_role)
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    dependency.__name__ = f"require_{minimum_role}"
    return dependency


_require_expert = _make_role_dependency("expert")
_require_viewer = _make_role_dependency("viewer")


@router.get(
    "/status",
    response_model=dict,
    summary="[V14B] 图谱产品层状态",
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}},
)
async def visual_status(_role: str = Depends(_require_viewer)) -> dict:
    """Return materialized visual graph readiness and table counts."""
    return get_visual_graph_status()


@router.get(
    "/tiles",
    response_model=dict,
    summary="[V14B] 获取 2.5D LOD tiles",
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}},
)
async def visual_tiles(
    lod_level: int = 0,
    cluster_id: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 200,
    _role: str = Depends(_require_viewer),
) -> dict:
    """Return level-of-detail tiles for WebGL rendering."""
    return get_visual_tiles(
        lod_level=lod_level,
        cluster_id=cluster_id,
        year_from=year_from,
        year_to=year_to,
        limit=limit,
    )


@router.get(
    "/nodes",
    response_model=dict,
    summary="[V14B] 获取 WebGL 节点批次",
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}},
)
async def visual_nodes(
    cluster_id: str | None = None,
    branch_id: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    role: str | None = None,
    limit: int = 5000,
    offset: int = 0,
    _role: str = Depends(_require_viewer),
) -> dict:
    """Return node batches for point-cloud rendering and topic lenses."""
    return get_visual_nodes(
        cluster_id=cluster_id,
        branch_id=branch_id,
        year_from=year_from,
        year_to=year_to,
        role=role,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/edges",
    response_model=dict,
    summary="[V14B] 获取 LOD 边批次",
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}},
)
async def visual_edges(
    layer: str | None = None,
    cluster_id: str | None = None,
    lod_max: int = 1,
    limit: int = 20000,
    offset: int = 0,
    _role: str = Depends(_require_viewer),
) -> dict:
    """Return edge batches with LOD controls so the browser never loads all edges."""
    return get_visual_edges(
        layer=layer,
        cluster_id=cluster_id,
        lod_max=lod_max,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/papers/{paper_id}",
    response_model=dict,
    summary="[V14B] 获取单篇论文详情和局部邻域",
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}},
)
async def visual_paper(
    paper_id: str,
    edge_limit: int = 80,
    _role: str = Depends(_require_viewer),
) -> dict:
    """Return paper metadata, abstract/sections/limitations, and local visual edges."""
    return get_visual_paper_detail(paper_id, edge_limit=edge_limit)


@router.get(
    "/clusters",
    response_model=dict,
    summary="[V14B] 获取 cluster 和 branch lineage",
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}},
)
async def visual_clusters(
    limit: int = 200,
    _role: str = Depends(_require_viewer),
) -> dict:
    """Return visual clusters plus branch lineage records."""
    return get_visual_clusters(limit=limit)


@router.get(
    "/story",
    response_model=dict,
    summary="[V14B] 获取 Story Mode 时间切片",
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}},
)
async def visual_story(_role: str = Depends(_require_viewer)) -> dict:
    """Return precomputed story-mode steps for temporal playback."""
    return get_visual_story_steps()


@router.get(
    "/topic-lens",
    response_model=dict,
    summary="[V14B] Topic Lens: 论文+脉络+卡点+未来方向",
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}},
)
async def visual_topic_lens(
    topic: str,
    top_k: int = 50,
    corpus_id: str | None = None,
    _role: str = Depends(_require_viewer),
) -> dict:
    """Return Sci-Bot style topic lens over the visual graph product layer."""
    return get_topic_lens(topic=topic, top_k=top_k, corpus_id=corpus_id)


# ---------------------------------------------------------------------------
# POST /graph/visual/edit  — GraphVisualEdit (Expert only)
# ---------------------------------------------------------------------------

@router.post(
    "/edit",
    response_model=dict,
    summary="[V14B] 提交专家可视化编辑操作",
    description=(
        "接受 GraphVisualEdit payload 并执行图谱可视化编辑。\n\n"
        "需要 `expert` 或更高角色 (RBAC AUDIT-056)。\n\n"
        "支持 11 种 action: `pin_position`, `override_fused_weight`, "
        "`override_color`, `add_label`, `merge_nodes`, `split_node`, "
        "`hide`, `show`, `promote_landmark`, `demote_landmark`, `annotate`。"
    ),
    responses={
        200: {"description": "Edit accepted or idempotently replayed"},
        401: {"description": "Unauthorized — 缺少或无效 token"},
        403: {"description": "Forbidden — 角色权限不足 (需要 expert)"},
    },
)
async def submit_edit(
    edit: GraphVisualEdit,
    _role: str = Depends(_require_expert),
) -> dict:
    """Submit an expert visual edit into the V14B edit ledger."""
    return submit_visual_edit(edit)


# ---------------------------------------------------------------------------
# POST /graph/visual/search  — GraphSearchQuery (Viewer+)
# ---------------------------------------------------------------------------

@router.post(
    "/search",
    response_model=dict,
    summary="[V14B] 图谱检索查询",
    description=(
        "接受 GraphSearchQuery payload 并返回图谱检索结果。\n\n"
        "需要 `viewer` 或更高角色 (RBAC AUDIT-056)。\n\n"
        "支持 12 种 query_type: `semantic`, `cite`, `topic`, `novelty_range`, "
        "`lifecycle`, `field`, `subfield`, `domain`, `landmark_proximity`, "
        "`bottleneck`, `meta_principle`, `expert_edited`。"
    ),
    responses={
        200: {"description": "Search result; ready=false when Step10 tables are absent"},
        401: {"description": "Unauthorized — 缺少或无效 token"},
        403: {"description": "Forbidden — 角色权限不足 (需要 viewer)"},
    },
)
async def search_graph(
    query: GraphSearchQuery,
    _role: str = Depends(_require_viewer),
) -> dict:
    """Run V14B hybrid visual-graph search."""
    return search_visual_graph(query)


# ---------------------------------------------------------------------------
# POST /graph/visual/evidence-atoms/search — EvidenceAtomSearchQuery (Viewer+)
# ---------------------------------------------------------------------------

@router.post(
    "/evidence-atoms/search",
    response_model=dict,
    summary="[V14B] Evidence atom exact/fuzzy search",
    description=(
        "在 section_atoms 上执行精准 ID/DOI/arXiv/title/section/phrase/FTS/BM25、"
        "atom embedding 模糊召回或 hybrid 检索。\n\n"
        "所有返回结果都保持 `retrieval_context_only`；GNN/graph expansion 只能作为候选扩展，"
        "不能直接生成 section atom 或晋升为 Step13 结论。"
    ),
    responses={
        200: {"description": "Evidence atom retrieval result"},
        401: {"description": "Unauthorized — 缺少或无效 token"},
        403: {"description": "Forbidden — 角色权限不足 (需要 viewer)"},
    },
)
async def search_evidence_atom_layer(
    query: EvidenceAtomSearchQuery,
    _role: str = Depends(_require_viewer),
) -> dict:
    """Run traceable section atom retrieval with exact/fuzzy contracts."""
    return search_evidence_atoms(query)


# ---------------------------------------------------------------------------
# GET /graph/visual/edits/{edit_id}  — 查询单条编辑状态
# ---------------------------------------------------------------------------

@router.get(
    "/edits/{edit_id}",
    summary="[V14B] 获取编辑操作状态",
    description=(
        "根据 edit_id (ULID) 查询编辑操作的处理状态。"
    ),
    responses={
        200: {"description": "Edit status or not_found marker"},
    },
)
async def get_edit_status(edit_id: str) -> dict:
    """Get visual edit status."""
    return get_visual_edit_status(edit_id)


# ---------------------------------------------------------------------------
# GET /graph/visual/edits/history/{expert_id}  — 专家编辑历史
# ---------------------------------------------------------------------------

@router.get(
    "/edits/history/{expert_id}",
    summary="[V14B] 获取专家编辑历史",
    description=(
        "根据 expert_id 获取该专家的所有历史编辑记录。"
    ),
    responses={
        200: {"description": "Expert edit history"},
    },
)
async def get_expert_history(expert_id: str) -> dict:
    """Get visual edit history for an expert."""
    return get_visual_edit_history(expert_id)
