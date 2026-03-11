"""rename model_registry secret column to api_key_secret_ref

Revision ID: r8s9t0u1v2w3
Revises: q0r1s2t3u4v5
Create Date: 2026-03-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "r8s9t0u1v2w3"
down_revision: str | Sequence[str] | None = "q0r1s2t3u4v5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "model_registry"):
        return
    if _has_column(bind, "model_registry", "api_key_encrypted") and not _has_column(
        bind, "model_registry", "api_key_secret_ref"
    ):
        op.alter_column("model_registry", "api_key_encrypted", new_column_name="api_key_secret_ref")


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "model_registry"):
        return
    if _has_column(bind, "model_registry", "api_key_secret_ref") and not _has_column(
        bind, "model_registry", "api_key_encrypted"
    ):
        op.alter_column("model_registry", "api_key_secret_ref", new_column_name="api_key_encrypted")
