"""对话路由 - 创建会话、发送消息（SSE流式）"""
import uuid
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.models.data_space import DataSpace
from app.schemas.chat import (
    ConversationCreate, ConversationResponse, MessageCreate,
    MessageResponse, ConversationDetailResponse,
)
from app.agent.loop import AgentLoop

router = APIRouter()


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建新对话"""
    # 验证数据空间归属
    if data.data_space_id:
        result = await db.execute(
            select(DataSpace).where(
                DataSpace.id == data.data_space_id, DataSpace.user_id == current_user.id
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="数据空间不存在")

    conversation = Conversation(
        user_id=current_user.id,
        data_space_id=data.data_space_id,
        model_id=data.model_id,
        title=data.title,
    )
    db.add(conversation)
    await db.flush()
    return conversation


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的对话列表"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


@router.get("/conversations/{conv_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conv_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取对话详情（含消息历史）"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    msg_result = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    )
    messages = msg_result.scalars().all()

    return ConversationDetailResponse(
        id=conv.id, data_space_id=conv.data_space_id, title=conv.title,
        model_id=conv.model_id, created_at=conv.created_at, updated_at=conv.updated_at,
        messages=[MessageResponse.model_validate(m) for m in messages],
    )


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除对话"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    await db.delete(conv)


@router.post("/conversations/{conv_id}/messages")
async def send_message(
    conv_id: uuid.UUID,
    data: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发送消息并获取 Agent 流式回复（SSE）"""
    # 验证对话归属
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 保存用户消息
    user_message = Message(
        conversation_id=conv_id,
        role="user",
        content=data.content,
    )
    db.add(user_message)
    await db.flush()

    # 如果对话没有标题，用第一条消息生成标题
    if not conv.title:
        conv.title = data.content[:50]

    await db.commit()

    # 流式返回 Agent 回复
    async def event_stream() -> AsyncGenerator[str, None]:
        agent = AgentLoop()
        full_content = ""

        async for event in agent.run(
            conversation_id=conv_id,
            user_id=current_user.id,
            data_space_id=conv.data_space_id,
            model_id=conv.model_id,
            user_message=data.content,
        ):
            if event["type"] == "text":
                full_content += event["delta"]
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # 保存助手消息
        async with get_session_factory()() as save_db:
            assistant_message = Message(
                conversation_id=conv_id,
                role="assistant",
                content=full_content,
                token_usage=event.get("usage"),
                credits_used=event.get("credits_used"),
            )
            save_db.add(assistant_message)
            await save_db.commit()

        yield "data: [DONE]\n\n"

    from app.core.database import get_session_factory
    return StreamingResponse(event_stream(), media_type="text/event-stream")
