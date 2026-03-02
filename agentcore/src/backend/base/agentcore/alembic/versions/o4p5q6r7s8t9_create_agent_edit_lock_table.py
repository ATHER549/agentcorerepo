"""create agent_edit_lock table

Revision ID: o4p5q6r7s8t9
Revises: n2o3p4q5r6s7
Create Date: 2026-02-24 17:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "o4p5q6r7s8t9"
down_revision: str | Sequence[str] | None = "n2o3p4q5r6s7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "agent_edit_lock"):
        return

    op.create_table(
        "agent_edit_lock",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("locked_by", sa.Uuid(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["locked_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("agent_id"),
    )
    op.create_index("ix_agent_edit_lock_locked_by", "agent_edit_lock", ["locked_by"], unique=False)
    op.create_index("ix_agent_edit_lock_expires_at", "agent_edit_lock", ["expires_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "agent_edit_lock"):
        op.drop_index("ix_agent_edit_lock_expires_at", table_name="agent_edit_lock")
        op.drop_index("ix_agent_edit_lock_locked_by", table_name="agent_edit_lock")
        op.drop_table("agent_edit_lock")

