"""用户设置 Schemas"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ApiKeyCreate(BaseModel):
    provider: str = Field(..., pattern="^(anthropic|openai)$")
    api_key: str = Field(..., min_length=5)
    api_base_url: Optional[str] = None
    model_name: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)


class ApiKeyUpdate(BaseModel):
    api_key: Optional[str] = None
    api_base_url: Optional[str] = None
    model_name: Optional[str] = None
    display_name: Optional[str] = None
    is_active: Optional[bool] = None


class ApiKeyResponse(BaseModel):
    id: str
    provider: str
    api_key_masked: str
    api_base_url: Optional[str]
    model_name: str
    display_name: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ModelOption(BaseModel):
    id: str
    display_name: str
    model_name: str
    provider: str
    source: str  # "platform" | "user"
    credit_multiplier: Optional[float] = None
