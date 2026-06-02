"""add_user_api_keys

Revision ID: d247c5a3c226
Revises: a1b2c3d4e5f6
Create Date: 2026-05-28 22:34:25.578764
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = 'd247c5a3c226'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_api_keys',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('provider', sa.String(50), nullable=False, server_default='openai'),
        sa.Column('api_key_encrypted', sa.String(1000), nullable=False),
        sa.Column('api_base_url', sa.String(500), nullable=True),
        sa.Column('model_name', sa.String(200), nullable=False, server_default=''),
        sa.Column('display_name', sa.String(200), nullable=False, server_default='我的 API'),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('model_mappings', JSONB, server_default='{}', nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('user_api_keys')
