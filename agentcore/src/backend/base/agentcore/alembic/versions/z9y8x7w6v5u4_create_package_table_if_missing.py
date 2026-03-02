"""create package table if missing

Revision ID: z9y8x7w6v5u4
Revises: merge_20260227_unify_heads
Create Date: 2026-02-27 00:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "z9y8x7w6v5u4"
down_revision: str | Sequence[str] | None = "merge_20260227_unify_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "package"):
        return

    op.create_table(
        "package",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("version_spec", sa.String(length=255), nullable=True),
        sa.Column("package_type", sa.String(length=20), nullable=False),
        sa.Column("required_by", sa.JSON(), nullable=True),
        sa.Column("source", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "package_type", name="uq_package_name_type"),
    )
    with op.batch_alter_table("package", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_package_name"), ["name"], unique=False)
        batch_op.create_index(batch_op.f("ix_package_package_type"), ["package_type"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "package"):
        return

    with op.batch_alter_table("package", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_package_package_type"))
        batch_op.drop_index(batch_op.f("ix_package_name"))

    op.drop_table("package")
