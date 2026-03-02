"""Merge deployment architecture branch and evaluator/user-columns branch

Revision ID: a1b2c3d4e5f6
Revises: c9d2f6, f0a1b2c3d4e5
Create Date: 2026-02-18

This is a merge migration that combines two divergent branches:
  - Branch A (c9d2f6): deployment architecture (0009)
  - Branch B (f0a1b2c3d4e5): evaluator tables + user creator/department columns
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: tuple = ("c9d2f6", "f0a1b2c3d4e5")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge migration — no schema changes needed."""
    pass


def downgrade() -> None:
    """Merge migration — no schema changes needed."""
    pass
