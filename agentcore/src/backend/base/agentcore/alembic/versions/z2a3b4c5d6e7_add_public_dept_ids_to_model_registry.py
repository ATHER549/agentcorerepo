"""add public_dept_ids to model_registry

Revision ID: z2a3b4c5d6e7
Revises: x1y2z3a4b5c6
Create Date: 2026-03-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "z2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "x1y2z3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "model_registry"):
        return
    if not _has_column(bind, "model_registry", "public_dept_ids"):
        op.add_column("model_registry", sa.Column("public_dept_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "model_registry"):
        return
    if _has_column(bind, "model_registry", "public_dept_ids"):
        op.drop_column("model_registry", "public_dept_ids")
