"""Merge revision to unify multiple heads

Revision ID: merge_20260227_unify_heads
Revises: 17b99611cc4e, c2e5756285b4, c9d0e1f2a3b4, p5q6r7s8t9u0, r1s2t3u4v5w6
Create Date: 2026-02-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "merge_20260227_unify_heads"
down_revision: Sequence[str] = (
    "17b99611cc4e",
    "c2e5756285b4",
    "c9d0e1f2a3b4",
    "p5q6r7s8t9u0",
    "r1s2t3u4v5w6",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge migration - no schema changes needed."""
    pass


def downgrade() -> None:
    """Merge migration - no schema changes needed."""
    pass
