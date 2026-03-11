"""merge heads

Revision ID: 8427dd771044
Revises: b2d65b9595aa, n2o3p4q5r6s7
Create Date: 2026-02-24 10:28:07.063892

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '8427dd771044'
down_revision: Union[str, None] = ('b2d65b9595aa', 'n2o3p4q5r6s7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
