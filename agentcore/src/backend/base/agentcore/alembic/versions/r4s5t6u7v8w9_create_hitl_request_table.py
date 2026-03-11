"""create hitl_request table for Human-in-the-Loop paused runs

Revision ID: r4s5t6u7v8w9
Revises: q3r4s5t6u7v8
Create Date: 2026-02-27 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r4s5t6u7v8w9"
down_revision: str | Sequence[str] | None = "q3r4s5t6u7v8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "hitl_request"):
        op.create_table(
            "hitl_request",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("thread_id", sa.Text(), nullable=False),
            sa.Column("agent_id", sa.Uuid(), nullable=False),
            sa.Column("session_id", sa.Text(), nullable=True),
            sa.Column("user_id", sa.Uuid(), nullable=True),
            sa.Column("interrupt_data", sa.JSON(), nullable=True),
            sa.Column(
                "status",
                sa.Enum(
                    "pending",
                    "approved",
                    "rejected",
                    "edited",
                    "cancelled",
                    "timed_out",
                    name="hitl_status_enum",
                ),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("decision", sa.JSON(), nullable=True),
            sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
            sa.Column(
                "requested_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

        op.create_index("ix_hitl_thread_id", "hitl_request", ["thread_id"])
        op.create_index("ix_hitl_agent_id", "hitl_request", ["agent_id"])
        op.create_index("ix_hitl_status", "hitl_request", ["status"])
        op.create_index("ix_hitl_user_id", "hitl_request", ["user_id"])
        op.create_index("ix_hitl_requested_at", "hitl_request", ["requested_at"])


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "hitl_request"):
        op.drop_index("ix_hitl_requested_at", table_name="hitl_request")
        op.drop_index("ix_hitl_user_id", table_name="hitl_request")
        op.drop_index("ix_hitl_status", table_name="hitl_request")
        op.drop_index("ix_hitl_agent_id", table_name="hitl_request")
        op.drop_index("ix_hitl_thread_id", table_name="hitl_request")
        op.drop_table("hitl_request")

    sa.Enum(name="hitl_status_enum").drop(op.get_bind(), checkfirst=True)
