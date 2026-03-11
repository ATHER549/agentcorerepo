"""merge hitl_request and connector provider-config heads

Revision ID: s5t6u7v8w9x0
Revises: m3r9g8h7k6l5, r4s5t6u7v8w9
Create Date: 2026-02-27 00:00:00.000000

This is a no-op merge migration that resolves the two independent heads:
  - m3r9g8h7k6l5  (merge_kb_visibility_mcp_columns_connector_provider)
  - r4s5t6u7v8w9  (create_hitl_request_table)

Both were created branching off q3r4s5t6u7v8. This merge restores a single
linear head so Alembic upgrade/downgrade operations are unambiguous.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "s5t6u7v8w9x0"
down_revision: tuple[str, str] = ("m3r9g8h7k6l5", "r4s5t6u7v8w9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
