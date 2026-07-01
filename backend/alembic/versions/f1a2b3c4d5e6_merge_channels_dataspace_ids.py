"""merge 渠道接入线与 conversation_data_space_ids 线（归并两个 alembic head）

Revision ID: f1a2b3c4d5e6
Revises: c4d5e6f7a8b9, d1e2f3a4b5c6
Create Date: 2026-07-01

渠道接入线（d1e2f3a4b5c6：channel_configs / external_identities）与上游
conversation_data_space_ids 线（c4d5e6f7a8b9）都从 b3f1a2c4d5e6 分叉，
合并后出现两个 head。此为纯合并节点，无 schema 变更，仅把两线汇成单 head，
使 `alembic upgrade head` 可用。
"""
from __future__ import annotations

revision = "f1a2b3c4d5e6"
down_revision = ("c4d5e6f7a8b9", "d1e2f3a4b5c6")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
