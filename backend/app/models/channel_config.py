"""渠道凭据与配置模型（每用户每渠道一行）

BYO 模型：凭据 JSON 用 encrypt_api_key 加密落库，不明文存储。
见 docs/channel-integration-design.md §5。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.core.database import Base


class ChannelConfig(Base):
    __tablename__ = "channel_configs"
    __table_args__ = (
        UniqueConstraint("user_id", "channel", name="uq_channel_config_user_channel"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 渠道标识：'feishu' | 'dingtalk' | 'weixin'
    channel: Mapped[str] = mapped_column(String(20), nullable=False)

    # 凭据 JSON（明文示例：{"app_id":"…","app_secret":"…"}）用 Fernet 对称加密整体存储
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 渠道是否已由用户手动启用
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 运行时连接状态（长连接实际 up/down；重启后由连接管理进程刷新）
    connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 该渠道的默认数据空间（可覆盖账号级默认）
    default_data_space_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_spaces.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 该渠道的默认模型 ID（可覆盖账号级默认）
    default_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # 机器人信息快照（bot name/avatar/open_id 等，测连后刷新）
    bot_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
