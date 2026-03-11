"""merge guardrails runtime config and model registry heads

Revision ID: c2e5756285b4
Revises: g1h2i3j4k5l6, m1n2o3p4q5r8
Create Date: 2026-02-23 17:09:21.426116

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "c2e5756285b4"
down_revision: tuple = ("g1h2i3j4k5l6", "m1n2o3p4q5r8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge migration - no schema changes needed."""
    pass


def downgrade() -> None:
    """Merge migration - no schema changes needed."""
    pass
