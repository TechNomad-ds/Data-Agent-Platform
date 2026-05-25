"""文件相关的请求/响应模型"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class FileResponse(BaseModel):
    id: uuid.UUID
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    mime_type: Optional[str] = None
    parse_status: str
    metadata_: dict = {}
    created_at: datetime

    class Config:
        from_attributes = True


class FileListResponse(BaseModel):
    files: list[FileResponse]
    total: int
