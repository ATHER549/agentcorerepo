"""merge all alembic heads

Revision ID: a660cf7c98d9
Revises: adad75e39437
Create Date: 2026-03-02 00:55:27.833070

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = 'a660cf7c98d9'
down_revision: Union[str, None] = 'adad75e39437'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
