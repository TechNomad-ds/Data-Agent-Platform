"""知识图谱路由 - 图谱查询、可视化导出"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.graph import GraphService

router = APIRouter()


@router.get("/{space_id}/graph/stats")
async def get_graph_stats(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
):
    """获取知识图谱统计信息"""
    gs = GraphService(str(current_user.id), str(space_id))
    return gs.stats()


@router.get("/{space_id}/graph/search")
async def search_graph(
    space_id: uuid.UUID,
    q: str = Query(..., min_length=1),
    top_k: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
):
    """搜索知识图谱中的实体"""
    gs = GraphService(str(current_user.id), str(space_id))
    results = await gs.search_entities(q, top_k=top_k)
    return {"query": q, "results": results}


@router.get("/{space_id}/graph/neighbors/{entity}")
async def get_neighbors(
    space_id: uuid.UUID,
    entity: str,
    direction: str = Query(default="both", regex="^(in|out|both)$"),
    current_user: User = Depends(get_current_user),
):
    """获取实体的直接邻居"""
    gs = GraphService(str(current_user.id), str(space_id))
    neighbors = await gs.neighbors(entity, direction=direction)
    return {"entity": entity, "neighbors": neighbors}


@router.get("/{space_id}/graph/traverse/{entity}")
async def traverse_graph(
    space_id: uuid.UUID,
    entity: str,
    max_hops: int = Query(default=2, ge=1, le=5),
    current_user: User = Depends(get_current_user),
):
    """从实体出发遍历关系路径"""
    gs = GraphService(str(current_user.id), str(space_id))
    paths = await gs.traverse(entity, max_hops=max_hops)
    return {"start": entity, "max_hops": max_hops, "paths": paths}


@router.get("/{space_id}/graph/export")
async def export_graph(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
):
    """导出完整图谱数据（用于前端可视化）"""
    gs = GraphService(str(current_user.id), str(space_id))
    data = gs.export_for_frontend()
    data["stats"] = gs.stats()
    return data
