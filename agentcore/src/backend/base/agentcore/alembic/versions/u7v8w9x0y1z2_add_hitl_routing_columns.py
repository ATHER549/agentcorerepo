"""add routing columns to hitl_request for department-admin-based approval

Revision ID: u7v8w9x0y1z2
Revises: e552a211c0b9
Create Date: 2026-03-10 00:00:00.000000

Adds assigned_to, dept_id, org_id, is_deployed_run, delegated_by, and
delegated_at columns to the hitl_request table so that published-agent
HIL requests are routed to the department admin and can be delegated.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "u7v8w9x0y1z2"
down_revision: str = "e552a211c0b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hitl_request",
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "hitl_request",
        sa.Column("dept_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "hitl_request",
        sa.Column("org_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "hitl_request",
        sa.Column("is_deployed_run", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "hitl_request",
        sa.Column("delegated_by", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "hitl_request",
        sa.Column("delegated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_hitl_assigned_to", "hitl_request", ["assigned_to"])


def downgrade() -> None:
    op.drop_index("ix_hitl_assigned_to", table_name="hitl_request")
    op.drop_column("hitl_request", "delegated_at")
    op.drop_column("hitl_request", "delegated_by")
    op.drop_column("hitl_request", "is_deployed_run")
    op.drop_column("hitl_request", "org_id")
    op.drop_column("hitl_request", "dept_id")
    op.drop_column("hitl_request", "assigned_to")
