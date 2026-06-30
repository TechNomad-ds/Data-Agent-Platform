"""对话相关的请求/响应模型"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    data_space_id: Optional[uuid.UUID] = None
    model_id: str = Field(min_length=1)
    title: Optional[str] = None


class ConversationResponse(BaseModel):
    id: uuid.UUID
    data_space_id: Optional[uuid.UUID] = None
    title: Optional[str] = None
    model_id: str
    channel: Optional[str] = None  # 'weixin'/'feishu' 来自渠道；'web'/None 为网页
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    model_id: Optional[str] = None
    # #13 对话中切换数据空间：本轮起改用该空间，并更新会话绑定（None 表示不改）
    data_space_id: Optional[uuid.UUID] = None
    # #12 同时绑定多个数据空间：本轮活跃空间全集（含主空间）。传了则跨这些空间检索/查表。
    data_space_ids: Optional[list[uuid.UUID]] = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list] = None
    token_usage: Optional[dict] = None
    credits_used: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse] = []
