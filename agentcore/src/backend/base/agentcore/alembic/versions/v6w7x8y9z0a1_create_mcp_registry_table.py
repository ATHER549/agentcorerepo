"""create mcp_registry table

Revision ID: v6w7x8y9z0a1
Revises: r1s2t3u4v5w6
Create Date: 2026-02-28 00:00:01.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v6w7x8y9z0a1"
down_revision: str | Sequence[str] | None = "r1s2t3u4v5w6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_registry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("command", sa.String(), nullable=True),
        sa.Column("args", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("env_vars_encrypted", sa.Text(), nullable=True),
        sa.Column("headers_encrypted", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mcp_registry_server_name", "mcp_registry", ["server_name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_mcp_registry_server_name", table_name="mcp_registry")
    op.drop_table("mcp_registry")
