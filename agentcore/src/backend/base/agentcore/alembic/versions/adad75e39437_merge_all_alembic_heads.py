"""merge all alembic heads

Revision ID: adad75e39437
Revises: f1375b53908f
Create Date: 2026-03-02 00:47:27.355559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = 'adad75e39437'
down_revision: Union[str, None] = 'f1375b53908f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
