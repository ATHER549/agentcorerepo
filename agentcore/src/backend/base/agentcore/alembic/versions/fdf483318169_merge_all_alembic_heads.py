"""merge all alembic heads

Revision ID: fdf483318169
Revises: f1375b53908f, n8m7l6k5j4h3, z2a3b4c5d6e7
Create Date: 2026-03-02 00:27:56.417333

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = 'fdf483318169'
down_revision: Union[str, None] = ('f1375b53908f', 'n8m7l6k5j4h3', 'z2a3b4c5d6e7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
