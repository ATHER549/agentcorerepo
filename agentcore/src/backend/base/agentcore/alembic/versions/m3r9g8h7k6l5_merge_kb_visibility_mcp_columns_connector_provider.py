"""merge kb_visibility, mcp_columns, connector_provider_config

Revision ID: m3r9g8h7k6l5
Revises: c9d0e1f2a3b4, p5q6r7s8t9u0, q3r4s5t6u7v8
Create Date: 2026-02-27

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m3r9g8h7k6l5"
down_revision: tuple[str, ...] = ("c9d0e1f2a3b4", "p5q6r7s8t9u0", "q3r4s5t6u7v8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
