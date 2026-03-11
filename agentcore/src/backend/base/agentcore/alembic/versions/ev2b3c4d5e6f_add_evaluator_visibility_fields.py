"""add visibility fields to evaluator table

Revision ID: ev2b3c4d5e6f
Revises: ev1a2b3c4d5e
Create Date: 2026-03-09 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ev2b3c4d5e6f"
down_revision: str | Sequence[str] | None = "ev1a2b3c4d5e"
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
    if not _table_exists(bind, "evaluator"):
        return

    if not _has_column(bind, "evaluator", "visibility"):
        op.add_column(
            "evaluator",
            sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"),
        )
    if not _has_column(bind, "evaluator", "public_scope"):
        op.add_column("evaluator", sa.Column("public_scope", sa.String(length=20), nullable=True))
    if not _has_column(bind, "evaluator", "shared_user_ids"):
        op.add_column("evaluator", sa.Column("shared_user_ids", sa.JSON(), nullable=True))
    if not _has_column(bind, "evaluator", "public_dept_ids"):
        op.add_column("evaluator", sa.Column("public_dept_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "evaluator"):
        return

    if _has_column(bind, "evaluator", "public_dept_ids"):
        op.drop_column("evaluator", "public_dept_ids")
    if _has_column(bind, "evaluator", "shared_user_ids"):
        op.drop_column("evaluator", "shared_user_ids")
    if _has_column(bind, "evaluator", "public_scope"):
        op.drop_column("evaluator", "public_scope")
    if _has_column(bind, "evaluator", "visibility"):
        op.drop_column("evaluator", "visibility")
