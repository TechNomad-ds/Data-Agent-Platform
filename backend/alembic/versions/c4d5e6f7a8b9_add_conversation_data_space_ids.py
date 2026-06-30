"""add data_space_ids to conversations (multi-project chat)

Revision ID: c4d5e6f7a8b9
Revises: b3f1a2c4d5e6
Create Date: 2026-06-30

JSONB 列，存本对话绑定的全部数据空间 id 列表（含主空间，主空间排第一）。
为空时回退到单空间 data_space_id。用于「多项目聊天」的可恢复持久化。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "c4d5e6f7a8b9"
down_revision = "b3f1a2c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("data_space_ids", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "data_space_ids")
