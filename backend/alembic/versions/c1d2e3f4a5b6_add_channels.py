"""add channel 对话渠道接入层：external_identities + conversations.channel

Revision ID: c1d2e3f4a5b6
Revises: b3f1a2c4d5e6
Create Date: 2026-06-30

为「飞书/邮箱等外部渠道直接和 agent 对话」打地基（见 docs/channel-integration-design.md）：
- external_identities：外部平台用户(open_id/邮箱) → 内部 user 的映射 + 配对授权时间。
  跨渠道复用同一张表，(channel, platform_user_id) 唯一。
- conversations 增 channel / channel_thread_id：把外部会话线程映射到内部 conversation，
  实现「同一飞书会话连续多轮」。channel 默认 'web'，不影响现有网页对话。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "c1d2e3f4a5b6"
down_revision = "b3f1a2c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_identities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("platform_user_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "channel", "platform_user_id", name="uq_external_identity_channel_user"
        ),
    )
    op.create_index(
        "ix_external_identities_user_id", "external_identities", ["user_id"]
    )

    op.add_column(
        "conversations",
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="web"),
    )
    op.add_column(
        "conversations",
        sa.Column("channel_thread_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_conversations_channel_thread",
        "conversations",
        ["channel", "channel_thread_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_channel_thread", table_name="conversations")
    op.drop_column("conversations", "channel_thread_id")
    op.drop_column("conversations", "channel")
    op.drop_index("ix_external_identities_user_id", table_name="external_identities")
    op.drop_table("external_identities")
