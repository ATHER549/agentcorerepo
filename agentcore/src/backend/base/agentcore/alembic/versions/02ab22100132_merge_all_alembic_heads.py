"""merge all alembic heads

Revision ID: 02ab22100132
Revises: edf739ef6fa5, s0t1u2v3w4x5
Create Date: 2026-03-10 13:36:22.432414

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '02ab22100132'
down_revision: Union[str, None] = ('edf739ef6fa5', 's0t1u2v3w4x5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
