"""add model_type column to model_registry

Revision ID: i9j0k1l2m3n4
Revises: m3r9g8h7k6l5
Create Date: 2026-02-28 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "i9j0k1l2m3n4"
down_revision: str | Sequence[str] | None = "m3r9g8h7k6l5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_registry",
        sa.Column("model_type", sa.String(), nullable=False, server_default=sa.text("'llm'")),
    )
    op.create_index("ix_model_registry_model_type", "model_registry", ["model_type"])


def downgrade() -> None:
    op.drop_index("ix_model_registry_model_type", table_name="model_registry")
    op.drop_column("model_registry", "model_type")
