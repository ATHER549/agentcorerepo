"""merge all alembic heads

Revision ID: edf739ef6fa5
Revises: abc123merge01, r8s9t0u1v2w3
Create Date: 2026-03-09 23:21:46.874772

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = 'edf739ef6fa5'
down_revision: Union[str, None] = ('abc123merge01', 'r8s9t0u1v2w3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
