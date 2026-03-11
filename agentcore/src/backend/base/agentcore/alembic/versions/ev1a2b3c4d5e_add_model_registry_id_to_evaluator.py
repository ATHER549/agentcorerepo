"""add model_registry_id and drop model_api_key from evaluator table

Revision ID: ev1a2b3c4d5e
Revises: q0r1s2t3u4v5
Create Date: 2026-03-09 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ev1a2b3c4d5e"
down_revision: str | Sequence[str] | None = "q0r1s2t3u4v5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col"
        ),
        {"table": table_name, "col": column_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if not column_exists("evaluator", "model_registry_id"):
        op.add_column(
            "evaluator",
            sa.Column("model_registry_id", sa.String(), nullable=True, index=True),
        )
    if column_exists("evaluator", "model_api_key"):
        op.drop_column("evaluator", "model_api_key")


def downgrade() -> None:
    op.drop_column("evaluator", "model_registry_id")
    if not column_exists("evaluator", "model_api_key"):
        op.add_column(
            "evaluator",
            sa.Column("model_api_key", sa.String(), nullable=True),
        )
