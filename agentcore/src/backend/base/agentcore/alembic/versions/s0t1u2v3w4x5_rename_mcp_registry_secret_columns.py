"""rename mcp_registry secret columns to *_secret_ref

Revision ID: s0t1u2v3w4x5
Revises: r8s9t0u1v2w3
Create Date: 2026-03-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "s0t1u2v3w4x5"
down_revision: str | Sequence[str] | None = "r8s9t0u1v2w3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "mcp_registry"):
        return
    if _has_column(bind, "mcp_registry", "env_vars_encrypted") and not _has_column(
        bind, "mcp_registry", "env_vars_secret_ref"
    ):
        op.alter_column("mcp_registry", "env_vars_encrypted", new_column_name="env_vars_secret_ref")
    if _has_column(bind, "mcp_registry", "headers_encrypted") and not _has_column(
        bind, "mcp_registry", "headers_secret_ref"
    ):
        op.alter_column("mcp_registry", "headers_encrypted", new_column_name="headers_secret_ref")


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "mcp_registry"):
        return
    if _has_column(bind, "mcp_registry", "env_vars_secret_ref") and not _has_column(
        bind, "mcp_registry", "env_vars_encrypted"
    ):
        op.alter_column("mcp_registry", "env_vars_secret_ref", new_column_name="env_vars_encrypted")
    if _has_column(bind, "mcp_registry", "headers_secret_ref") and not _has_column(
        bind, "mcp_registry", "headers_encrypted"
    ):
        op.alter_column("mcp_registry", "headers_secret_ref", new_column_name="headers_encrypted")
