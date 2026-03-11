"""add package history columns and remove unique current-row constraint

Revision ID: t2u3v4w5x6y7
Revises: s1u2v3w4x5y6
Create Date: 2026-03-10 23:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "t2u3v4w5x6y7"
down_revision: str | Sequence[str] | None = "s1u2v3w4x5y6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_constraint(bind, table_name: str, constraint_name: str) -> bool:
    return any(c.get("name") == constraint_name for c in sa.inspect(bind).get_unique_constraints(table_name))


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in sa.inspect(bind).get_columns(table_name))


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_column(bind, "package", "required_by_details"):
        with op.batch_alter_table("package", schema=None) as batch_op:
            batch_op.add_column(sa.Column("required_by_details", sa.JSON(), nullable=True))

    if not _has_column(bind, "package", "start_date"):
        with op.batch_alter_table("package", schema=None) as batch_op:
            batch_op.add_column(sa.Column("start_date", sa.Date(), nullable=True))

    if not _has_column(bind, "package", "end_date"):
        with op.batch_alter_table("package", schema=None) as batch_op:
            batch_op.add_column(sa.Column("end_date", sa.Date(), nullable=True))

    op.execute("UPDATE package SET start_date = COALESCE(start_date, CURRENT_DATE)")
    op.execute("UPDATE package SET end_date = COALESCE(end_date, DATE '9999-12-31')")

    with op.batch_alter_table("package", schema=None) as batch_op:
        batch_op.alter_column("start_date", nullable=False)
        batch_op.alter_column("end_date", nullable=False)

    if _has_constraint(bind, "package", "uq_package_name_type"):
        op.drop_constraint("uq_package_name_type", "package", type_="unique")

    if not _has_index(bind, "package", "ix_package_start_date"):
        op.create_index("ix_package_start_date", "package", ["start_date"], unique=False)
    if not _has_index(bind, "package", "ix_package_end_date"):
        op.create_index("ix_package_end_date", "package", ["end_date"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    if _has_index(bind, "package", "ix_package_end_date"):
        op.drop_index("ix_package_end_date", table_name="package")
    if _has_index(bind, "package", "ix_package_start_date"):
        op.drop_index("ix_package_start_date", table_name="package")

    if not _has_constraint(bind, "package", "uq_package_name_type"):
        op.create_unique_constraint("uq_package_name_type", "package", ["name", "package_type"])

    with op.batch_alter_table("package", schema=None) as batch_op:
        batch_op.drop_column("end_date")
        batch_op.drop_column("start_date")
        batch_op.drop_column("required_by_details")
