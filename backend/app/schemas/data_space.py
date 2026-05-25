"""数据空间相关的请求/响应模型"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DataSpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class DataSpaceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None


class DataSpaceResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    index_status: str
    file_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DataSpaceDetailResponse(DataSpaceResponse):
    files: list["FileInSpace"] = []


class FileInSpace(BaseModel):
    file_id: uuid.UUID
    filename: str
    file_type: str
    file_size: int
    added_at: datetime


class AddFilesRequest(BaseModel):
    file_ids: list[uuid.UUID]
