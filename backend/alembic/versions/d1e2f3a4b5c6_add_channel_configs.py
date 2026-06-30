"""add channel_configs 渠道凭据与配置表

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-06-30

每用户每渠道存一行：加密凭据 + 启用开关 + 运行时连接状态 + 默认空间/模型 + bot 信息快照。
见 docs/channel-integration-design.md §5。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "d1e2f3a4b5c6"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("credentials_encrypted", sa.Text, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("connected", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "default_data_space_id",
            UUID(as_uuid=True),
            sa.ForeignKey("data_spaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("default_model", sa.String(length=100), nullable=True),
        sa.Column("bot_info", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "channel", name="uq_channel_config_user_channel"
        ),
    )
    op.create_index("ix_channel_configs_user_id", "channel_configs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_channel_configs_user_id", table_name="channel_configs")
    op.drop_table("channel_configs")
