"""add runtime config to guardrail catalogue

Revision ID: r1s2t3u4v5w6
Revises: 8427dd771044
Create Date: 2026-02-23 19:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "r1s2t3u4v5w6"
down_revision: str | Sequence[str] | None = "8427dd771044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(column["name"] == column_name for column in sa.inspect(bind).get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "guardrail_catalogue") and not _column_exists(
        bind, "guardrail_catalogue", "runtime_config"
    ):
        op.add_column("guardrail_catalogue", sa.Column("runtime_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "guardrail_catalogue") and _column_exists(
        bind, "guardrail_catalogue", "runtime_config"
    ):
        op.drop_column("guardrail_catalogue", "runtime_config")
