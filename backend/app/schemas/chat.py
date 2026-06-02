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
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    model_id: Optional[str] = None


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
