"""Merging heads

Revision ID: d2c10200ff01
Revises: p0q1r2s3t4u5, t2u3v4w5x6y7
Create Date: 2026-03-11 15:53:42.698012

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = 'd2c10200ff01'
down_revision: Union[str, None] = ('p0q1r2s3t4u5', 't2u3v4w5x6y7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
