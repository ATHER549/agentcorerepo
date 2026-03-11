"""add checkpoint_data column to hitl_request table

Revision ID: t6u7v8w9x0y1
Revises: s5t6u7v8w9x0
Create Date: 2026-02-28 00:00:00.000000

Stores the serialized LangGraph MemorySaver checkpoint alongside the
HITLRequest record so that the checkpoint survives server restarts.
The resume endpoint restores this data into the in-process MemorySaver
before calling ainvoke(Command(resume=...)).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "t6u7v8w9x0y1"
down_revision: str = "s5t6u7v8w9x0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hitl_request",
        sa.Column("checkpoint_data", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hitl_request", "checkpoint_data")
