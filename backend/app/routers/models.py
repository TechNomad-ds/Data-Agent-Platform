"""公开模型列表路由 - 供前端获取可用模型"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.llm_model import LLMModel

router = APIRouter()


@router.get("/available")
async def list_available_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户可用的模型列表"""
    result = await db.execute(
        select(LLMModel).where(
            LLMModel.is_active == True,
            LLMModel.visible_to_users == True,
        )
    )
    models = result.scalars().all()

    return [
        {
            "id": m.id,
            "display_name": m.display_name,
            "model_name": m.model_name,
            "provider": m.provider,
            "credit_multiplier": float(m.credit_multiplier),
        }
        for m in models
    ]
