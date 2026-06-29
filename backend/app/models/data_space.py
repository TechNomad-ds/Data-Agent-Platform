"""数据空间模型"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.core.database import Base


class DataSpace(Base):
    __tablename__ = "data_spaces"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_space_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # 非空 = 该空间是某个对话的「临时文件区」（聊天框上传的文件落在这里，
    # 不出现在项目列表/切换器中，随对话删除一并清理）；为空 = 正式项目。
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    index_status: Mapped[str] = mapped_column(String(20), default="empty")  # empty|building|ready|error
    index_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DataSpaceFile(Base):
    __tablename__ = "data_space_files"

    data_space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_spaces.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
