"""add provider_config to connector_catalogue

Revision ID: q3r4s5t6u7v8
Revises: p2q3r4s5t6u7
Create Date: 2026-02-25 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "q3r4s5t6u7v8"
down_revision: str | Sequence[str] | None = "p2q3r4s5t6u7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("connector_catalogue")]

    # Add provider_config JSON column for non-DB providers (Azure Blob, SharePoint)
    if "provider_config" not in columns:
        op.add_column("connector_catalogue", sa.Column("provider_config", sa.JSON(), nullable=True))

    # Make DB-specific columns nullable so Azure Blob / SharePoint connectors can omit them
    op.alter_column("connector_catalogue", "host", nullable=True)
    op.alter_column("connector_catalogue", "port", nullable=True)
    op.alter_column("connector_catalogue", "database_name", nullable=True)
    op.alter_column("connector_catalogue", "schema_name", nullable=True)
    op.alter_column("connector_catalogue", "username", nullable=True)
    op.alter_column("connector_catalogue", "password_encrypted", nullable=True)


def downgrade() -> None:
    op.drop_column("connector_catalogue", "provider_config")
    # Restore NOT NULL constraints (will fail if non-DB connectors exist — drop those first)
    op.alter_column("connector_catalogue", "host", nullable=False)
    op.alter_column("connector_catalogue", "port", nullable=False)
    op.alter_column("connector_catalogue", "database_name", nullable=False)
    op.alter_column("connector_catalogue", "schema_name", nullable=False)
    op.alter_column("connector_catalogue", "username", nullable=False)
    op.alter_column("connector_catalogue", "password_encrypted", nullable=False)
