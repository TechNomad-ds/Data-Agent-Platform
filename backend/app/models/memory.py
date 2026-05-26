"""Agent 记忆模型 - 存储长期记忆"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class AgentMemory(Base):
    __tablename__ = "agent_memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    data_space_id = Column(UUID(as_uuid=True), ForeignKey("data_spaces.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(String(64), nullable=True, index=True)
    scope = Column(String(20), nullable=False, default="session")  # session | space | global
    kind = Column(String(20), nullable=False, default="fact")  # fact | preference | workflow | summary
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=True)
    importance = Column(Integer, default=5)  # 1-10
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
