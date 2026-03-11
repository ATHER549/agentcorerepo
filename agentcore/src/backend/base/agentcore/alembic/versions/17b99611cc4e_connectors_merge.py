"""connectors_merge

Revision ID: 17b99611cc4e
Revises: 32241ba468df, o1p2q3r4s5t6
Create Date: 2026-02-25 11:20:40.158558

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '17b99611cc4e'
down_revision: Union[str, None] = ('32241ba468df', 'o1p2q3r4s5t6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
