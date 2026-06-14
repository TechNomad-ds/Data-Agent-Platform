"""知识图谱路由 - 图谱查询、可视化导出、懒加载构建"""
import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.file import File
from app.models.data_profile import DataProfile
from app.services.graph import GraphService

router = APIRouter()

# 追踪正在构建图谱的 space，避免重复触发
_building_spaces: set[str] = set()


@router.get("/{space_id}/graph/stats")
async def get_graph_stats(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
):
    """获取知识图谱统计信息"""
    gs = GraphService(str(current_user.id), str(space_id))
    stats = gs.stats()
    stats["building"] = str(space_id) in _building_spaces
    return stats


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
    data["building"] = str(space_id) in _building_spaces
    return data


@router.post("/{space_id}/graph/build")
async def build_graph(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """懒加载触发图谱构建 - 从该 space 的文本/文档文件中抽取三元组"""
    space_key = str(space_id)

    # 校验数据空间归属，防止越权将他人文件抽取进自己的图谱
    from app.models.data_space import DataSpace, DataSpaceFile
    space_check = await db.execute(
        select(DataSpace).where(DataSpace.id == space_id, DataSpace.user_id == current_user.id)
    )
    if not space_check.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="数据空间不存在")

    if space_key in _building_spaces:
        return {"status": "building", "message": "图谱正在构建中，请稍候..."}

    # 查找该 space 下所有文本/文档类型的文件（通过关联表）
    result = await db.execute(
        select(File)
        .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
        .where(
            DataSpaceFile.data_space_id == space_id,
            File.user_id == current_user.id,
            File.file_type.in_(["txt", "md", "pdf", "docx", "py", "sql", "html", "xml", "yaml", "yml"]),
        )
    )
    files = result.scalars().all()

    if not files:
        return {"status": "empty", "message": "没有可用于构建图谱的文本文件"}

    gs = GraphService(str(current_user.id), space_key)
    existing_stats = gs.stats()
    if existing_stats["nodes"] > 0:
        return {
            "status": "ready",
            "message": f"图谱已存在（{existing_stats['nodes']} 个节点，{existing_stats['edges']} 条边）",
            "stats": existing_stats,
        }

    # 后台异步构建
    _building_spaces.add(space_key)

    import logging
    logger = logging.getLogger("graph")

    async def _do_build():
        try:
            total_triples = 0
            for f in files:
                file_path = Path(settings.storage_root) / f.storage_path
                if not file_path.exists():
                    continue

                ext = f.file_type.lower()
                text = ""
                if ext in ("txt", "md", "py", "sql", "html", "xml", "yaml", "yml"):
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                elif ext == "pdf":
                    try:
                        import fitz
                        doc = fitz.open(str(file_path))
                        for page in doc:
                            text += page.get_text() + "\n"
                        doc.close()
                    except Exception:
                        continue
                elif ext == "docx":
                    try:
                        from docx import Document
                        doc = Document(str(file_path))
                        for para in doc.paragraphs:
                            text += para.text + "\n"
                    except Exception:
                        continue

                if len(text.strip()) < 100:
                    continue

                try:
                    result = await gs.extract_triples_from_text(
                        text[:5000], max_triples=settings.graph_max_triples_per_file
                    )
                    total_triples += result.get("added", 0)
                except Exception as e:
                    logger.error(f"图谱抽取失败 ({f.filename}): {e}", exc_info=True)
            logger.info(f"图谱构建完成: space={space_key}, triples={total_triples}")
        except Exception as e:
            logger.error(f"图谱构建异常: {e}", exc_info=True)
        finally:
            _building_spaces.discard(space_key)

    asyncio.create_task(_do_build())

    return {
        "status": "building",
        "message": f"开始构建图谱，正在处理 {len(files)} 个文件...",
        "file_count": len(files),
    }
