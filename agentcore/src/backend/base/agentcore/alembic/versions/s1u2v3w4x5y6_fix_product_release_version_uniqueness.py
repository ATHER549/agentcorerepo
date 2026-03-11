"""fix product_release version uniqueness shape

Revision ID: s1u2v3w4x5y6
Revises: r9t0u1v2w3x4
Create Date: 2026-03-10 23:25:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "s1u2v3w4x5y6"
down_revision: str | Sequence[str] | None = "r9t0u1v2w3x4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_constraint(bind, table_name: str, constraint_name: str) -> bool:
    return any(c.get("name") == constraint_name for c in sa.inspect(bind).get_unique_constraints(table_name))


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def _is_index_unique(bind, table_name: str, index_name: str) -> bool:
    for ix in sa.inspect(bind).get_indexes(table_name):
        if ix.get("name") == index_name:
            return bool(ix.get("unique"))
    return False


def upgrade() -> None:
    bind = op.get_bind()
    table = "product_release"
    idx = "ix_product_release_version"
    uq = "uq_product_release_version"

    if not _table_exists(bind, table):
        return

    if _has_constraint(bind, table, uq):
        op.drop_constraint(uq, table_name=table, type_="unique")

    if _has_index(bind, table, idx):
        if not _is_index_unique(bind, table, idx):
            op.drop_index(idx, table_name=table)
            op.create_index(idx, table, ["version"], unique=True)
    else:
        op.create_index(idx, table, ["version"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    table = "product_release"
    idx = "ix_product_release_version"
    uq = "uq_product_release_version"

    if not _table_exists(bind, table):
        return

    if _has_index(bind, table, idx):
        op.drop_index(idx, table_name=table)
    op.create_index(idx, table, ["version"], unique=False)

    if not _has_constraint(bind, table, uq):
        op.create_unique_constraint(uq, table, ["version"])
