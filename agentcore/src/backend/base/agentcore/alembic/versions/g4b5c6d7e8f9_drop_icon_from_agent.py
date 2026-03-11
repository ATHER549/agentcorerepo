"""drop icon column from agent

Revision ID: g4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-02-19 15:25:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g4b5c6d7e8f9"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "agent", "icon"):
        op.drop_column("agent", "icon")


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "agent") and not _has_column(bind, "agent", "icon"):
        op.add_column("agent", sa.Column("icon", sa.String(), nullable=True))
