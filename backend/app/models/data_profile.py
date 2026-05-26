"""数据画像模型 - 存储文件预处理结果"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class DataProfile(Base):
    __tablename__ = "data_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    data_space_id = Column(UUID(as_uuid=True), ForeignKey("data_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    profile_type = Column(String(20), nullable=False)  # "tabular" | "text" | "document"
    profile_data = Column(JSONB, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="pending")  # pending | processing | ready | error
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
