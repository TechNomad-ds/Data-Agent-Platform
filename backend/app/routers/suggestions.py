"""智能建议路由 - 返回通用分析建议"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.data_space import DataSpace, DataSpaceFile

router = APIRouter()

DEFAULT_SUGGESTIONS = [
    "帮我看看项目里有什么文件",
    "帮我概述一下这些文件的整体情况",
    "帮我做一个关键内容的摘要",
    "这些资料里有哪些值得关注的重点？",
]


@router.get("/{space_id}/suggestions")
async def get_suggestions(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回通用分析建议"""
    result = await db.execute(
        select(DataSpace).where(DataSpace.id == space_id, DataSpace.user_id == current_user.id)
    )
    space = result.scalar_one_or_none()
    if not space:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 只统计文件数量用于 summary，不依赖画像
    file_count_result = await db.execute(
        select(func.count()).select_from(DataSpaceFile).where(DataSpaceFile.data_space_id == space_id)
    )
    file_count = file_count_result.scalar() or 0

    summary = f"共 {file_count} 个文件" if file_count > 0 else None

    return {
        "suggestions": DEFAULT_SUGGESTIONS,
        "summary": summary,
    }
