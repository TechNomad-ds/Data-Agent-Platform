"""智能建议路由 - 基于数据画像生成分析建议"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.data_space import DataSpace
from app.models.data_profile import DataProfile

router = APIRouter()


@router.get("/{space_id}/suggestions")
async def get_suggestions(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """基于数据画像生成智能分析建议"""
    result = await db.execute(
        select(DataSpace).where(DataSpace.id == space_id, DataSpace.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="数据空间不存在")

    profiles_result = await db.execute(
        select(DataProfile).where(
            DataProfile.data_space_id == space_id,
            DataProfile.status == "ready",
        )
    )
    profiles = profiles_result.scalars().all()

    if not profiles:
        return {"suggestions": ["上传数据文件开始分析"], "summary": None}

    suggestions = []
    summary_parts = []
    total_rows = 0
    total_files = len(profiles)
    tabular_files = []
    text_files = []

    for p in profiles:
        data = p.profile_data or {}
        if p.profile_type == "tabular":
            rows = data.get("row_count", 0)
            cols = data.get("column_count", 0)
            total_rows += rows
            tabular_files.append({
                "rows": rows,
                "cols": cols,
                "columns": data.get("columns", []),
            })
        elif p.profile_type in ("text", "document"):
            text_files.append(data)

    summary_parts.append(f"共 {total_files} 个文件")
    if tabular_files:
        summary_parts.append(f"{len(tabular_files)} 个表格文件（共 {total_rows} 行）")
    if text_files:
        summary_parts.append(f"{len(text_files)} 个文档")

    # Generate smart suggestions based on data characteristics
    if tabular_files:
        suggestions.append("帮我概述一下这些数据的整体情况")

        # Check for high missing values
        for tf in tabular_files:
            high_null_cols = [c["name"] for c in tf["columns"] if c.get("null_pct", 0) > 20]
            if high_null_cols:
                suggestions.append(f"有些列缺失率较高（{', '.join(high_null_cols[:3])}），帮我分析一下原因")
                break

        # Check for numeric columns -> suggest visualization
        has_numeric = any(
            any(c.get("stats") for c in tf["columns"])
            for tf in tabular_files
        )
        if has_numeric:
            suggestions.append("帮我生成数据分布的可视化图表")

        # Multiple tables -> suggest relationship analysis
        if len(tabular_files) > 1:
            suggestions.append("这几个表之间有什么关联？帮我分析一下")

        suggestions.append("数据有什么异常或值得关注的模式？")

    if text_files:
        suggestions.append("帮我总结一下文档的主要内容")

    if total_rows > 1000:
        suggestions.append("帮我做一个完整的数据质量报告")

    return {
        "suggestions": suggestions[:6],
        "summary": "、".join(summary_parts),
    }
