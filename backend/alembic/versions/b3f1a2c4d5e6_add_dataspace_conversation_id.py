"""add conversation_id to data_spaces (conversation-scoped temp file area)

Revision ID: b3f1a2c4d5e6
Revises: a1b2c3d4e5f6
Create Date: 2026-06-29

非空 conversation_id 表示该 data_space 是某对话的「临时文件区」：
聊天框上传的文件落在这里，不出现在项目列表，随对话删除而级联清理。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "b3f1a2c4d5e6"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_spaces",
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_data_spaces_conversation_id", "data_spaces", ["conversation_id"]
    )
    op.create_foreign_key(
        "fk_data_spaces_conversation_id",
        "data_spaces",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_data_spaces_conversation_id", "data_spaces", type_="foreignkey")
    op.drop_index("ix_data_spaces_conversation_id", table_name="data_spaces")
    op.drop_column("data_spaces", "conversation_id")
