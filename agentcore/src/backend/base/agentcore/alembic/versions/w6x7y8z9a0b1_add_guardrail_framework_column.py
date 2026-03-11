"""add framework column to guardrail catalogue

Revision ID: w6x7y8z9a0b1
Revises: v5w6x7y8z9a0
Create Date: 2026-03-01 18:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "w6x7y8z9a0b1"
down_revision: str | Sequence[str] | None = "v5w6x7y8z9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def _has_index(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "guardrail_catalogue"):
        return

    if not _has_column(bind, "guardrail_catalogue", "framework"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("framework", sa.String(length=50), nullable=False, server_default="nemo"),
        )

    op.execute(
        sa.text(
            """
            UPDATE guardrail_catalogue
            SET framework = 'nemo'
            WHERE framework IS NULL OR TRIM(framework) = ''
            """
        )
    )

    if not _has_index(bind, "guardrail_catalogue", "ix_guardrail_catalogue_framework"):
        op.create_index("ix_guardrail_catalogue_framework", "guardrail_catalogue", ["framework"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "guardrail_catalogue"):
        return

    if _has_index(bind, "guardrail_catalogue", "ix_guardrail_catalogue_framework"):
        op.drop_index("ix_guardrail_catalogue_framework", table_name="guardrail_catalogue")

    if _has_column(bind, "guardrail_catalogue", "framework"):
        op.drop_column("guardrail_catalogue", "framework")
