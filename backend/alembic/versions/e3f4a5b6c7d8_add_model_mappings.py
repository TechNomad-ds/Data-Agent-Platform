"""add model_mappings to user_api_keys (already included in table creation)

Revision ID: e3f4a5b6c7d8
Revises: d247c5a3c226
Create Date: 2026-05-31
"""
from typing import Sequence, Union

revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, None] = 'd247c5a3c226'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
