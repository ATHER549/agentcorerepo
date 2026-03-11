"""create help_support_question table

Revision ID: m1n2o3p4q5r6
Revises: g1h2i3j4k5l6, l9a0b1c2d3e4
Create Date: 2026-02-23 18:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "m1n2o3p4q5r6"
down_revision: str | Sequence[str] | None = ("g1h2i3j4k5l6", "l9a0b1c2d3e4")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "help_support_question"):
        return

    op.create_table(
        "help_support_question",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.String(length=500), nullable=False),
        sa.Column("answer", sa.String(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "help_support_question"):
        op.drop_table("help_support_question")

