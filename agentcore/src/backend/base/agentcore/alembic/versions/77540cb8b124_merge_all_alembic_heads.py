"""merge all alembic heads

Revision ID: 77540cb8b124
Revises: 87927a23509a
Create Date: 2026-03-02 01:17:22.374152

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '77540cb8b124'
down_revision: Union[str, None] = '87927a23509a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
