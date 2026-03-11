"""add creator/department columns to user

Revision ID: f0a1b2c3d4e5
Revises: c4d9e2f8a1b0
Create Date: 2026-02-16 22:24:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, None] = "c4d9e2f8a1b0"
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
    if _table_exists(bind, "user") and not _has_column(bind, "user", "creator_email"):
        op.add_column("user", sa.Column("creator_email", sa.String(), nullable=True))
    if _table_exists(bind, "user") and not _has_column(bind, "user", "creator_role"):
        op.add_column("user", sa.Column("creator_role", sa.String(length=50), nullable=True))
    if _table_exists(bind, "user") and not _has_column(bind, "user", "department_admin_email"):
        op.add_column("user", sa.Column("department_admin_email", sa.String(), nullable=True))
    if _table_exists(bind, "user") and not _has_column(bind, "user", "department_name"):
        op.add_column("user", sa.Column("department_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "department_name")
    op.drop_column("user", "department_admin_email")
    op.drop_column("user", "creator_role")
    op.drop_column("user", "creator_email")
