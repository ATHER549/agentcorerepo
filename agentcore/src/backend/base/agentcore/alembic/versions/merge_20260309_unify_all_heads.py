"""merge all three heads into single lineage

Revision ID: abc123merge01
Revises: 84c14b0721d8, ev2b3c4d5e6f, lf1a2b3c4d5f
Create Date: 2026-03-09 00:00:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "abc123merge01"
down_revision: Union[str, Sequence[str], None] = (
    "84c14b0721d8",
    "ev2b3c4d5e6f",
    "lf1a2b3c4d5f",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
