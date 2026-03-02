"""add guardrail visibility fields

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-02-28 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "u4v5w6x7y8z9"
down_revision: str | Sequence[str] | None = "t3u4v5w6x7y8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "guardrail_catalogue"):
        return

    if not _has_column(bind, "guardrail_catalogue", "visibility"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"),
        )
    if not _has_column(bind, "guardrail_catalogue", "public_scope"):
        op.add_column("guardrail_catalogue", sa.Column("public_scope", sa.String(length=20), nullable=True))
    if not _has_column(bind, "guardrail_catalogue", "shared_user_ids"):
        op.add_column("guardrail_catalogue", sa.Column("shared_user_ids", sa.JSON(), nullable=True))
    if not _has_column(bind, "guardrail_catalogue", "public_dept_ids"):
        op.add_column("guardrail_catalogue", sa.Column("public_dept_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "guardrail_catalogue"):
        return

    if _has_column(bind, "guardrail_catalogue", "public_dept_ids"):
        op.drop_column("guardrail_catalogue", "public_dept_ids")
    if _has_column(bind, "guardrail_catalogue", "shared_user_ids"):
        op.drop_column("guardrail_catalogue", "shared_user_ids")
    if _has_column(bind, "guardrail_catalogue", "public_scope"):
        op.drop_column("guardrail_catalogue", "public_scope")
    if _has_column(bind, "guardrail_catalogue", "visibility"):
        op.drop_column("guardrail_catalogue", "visibility")
