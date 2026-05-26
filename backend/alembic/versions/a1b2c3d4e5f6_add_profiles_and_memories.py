"""add data_profiles and agent_memories tables

Revision ID: a1b2c3d4e5f6
Revises: 0f20d6f273ad
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a1b2c3d4e5f6'
down_revision = '0f20d6f273ad'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'data_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('file_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('files.id', ondelete='CASCADE'), nullable=False),
        sa.Column('data_space_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('data_spaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('profile_type', sa.String(20), nullable=False),
        sa.Column('profile_data', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_data_profiles_file_id', 'data_profiles', ['file_id'])
    op.create_index('ix_data_profiles_data_space_id', 'data_profiles', ['data_space_id'])

    op.create_table(
        'agent_memories',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('data_space_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('data_spaces.id', ondelete='SET NULL'), nullable=True),
        sa.Column('session_id', sa.String(64), nullable=True),
        sa.Column('scope', sa.String(20), nullable=False, server_default='session'),
        sa.Column('kind', sa.String(20), nullable=False, server_default='fact'),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('importance', sa.Integer, server_default='5'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_agent_memories_user_id', 'agent_memories', ['user_id'])
    op.create_index('ix_agent_memories_data_space_id', 'agent_memories', ['data_space_id'])
    op.create_index('ix_agent_memories_session_id', 'agent_memories', ['session_id'])


def downgrade() -> None:
    op.drop_table('agent_memories')
    op.drop_table('data_profiles')
