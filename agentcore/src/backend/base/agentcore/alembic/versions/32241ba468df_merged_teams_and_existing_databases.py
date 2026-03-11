"""merged_teams_and_existing_databases

Revision ID: 32241ba468df
Revises: 2f8c3b9c43bd, o4p5q6r7s8t9
Create Date: 2026-02-24 20:50:02.043691

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '32241ba468df'
down_revision: Union[str, None] = ('2f8c3b9c43bd', 'o4p5q6r7s8t9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
