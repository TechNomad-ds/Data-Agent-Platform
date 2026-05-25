"""反馈路由"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.feedback import Feedback
from app.models.conversation import Message

router = APIRouter()


class FeedbackCreate(BaseModel):
    message_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    tags: list[str] = []
    comment: str | None = None


@router.post("", status_code=201)
async def submit_feedback(
    data: FeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交反馈"""
    # 验证消息存在且属于当前用户的对话
    result = await db.execute(select(Message).where(Message.id == data.message_id))
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")

    feedback = Feedback(
        user_id=current_user.id,
        message_id=data.message_id,
        conversation_id=message.conversation_id,
        rating=data.rating,
        tags=data.tags,
        comment=data.comment,
    )
    db.add(feedback)
    return {"message": "反馈已提交"}
