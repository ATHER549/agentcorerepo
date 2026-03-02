"""merge all alembic heads

Revision ID: 6a797d30d8ef
Revises: f1eb37880886, x1y2z3a4b5c6
Create Date: 2026-03-01 17:12:47.238701

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '6a797d30d8ef'
down_revision: Union[str, None] = ('f1eb37880886', 'x1y2z3a4b5c6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
