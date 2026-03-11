"""merge all alembic heads

Revision ID: 87927a23509a
Revises: a660cf7c98d9, fdf483318169
Create Date: 2026-03-02 01:07:45.595677

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '87927a23509a'
down_revision: Union[str, None] = ('a660cf7c98d9', 'fdf483318169')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
