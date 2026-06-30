"""外部渠道身份映射模型

把外部平台用户（飞书 open_id / 邮箱地址 等）映射到内部 user，承载配对授权状态。
跨渠道复用同一张表，(channel, platform_user_id) 唯一。详见 docs/channel-integration-design.md。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint(
            "channel", "platform_user_id", name="uq_external_identity_channel_user"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # feishu|email|...
    platform_user_id: Mapped[str] = mapped_column(String(255), nullable=False)  # open_id / 邮箱
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
