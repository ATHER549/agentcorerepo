"""merge all alembic heads

Revision ID: 095943f9dd36
Revises: 7c8d9e0f1a2b
Create Date: 2026-03-01 17:27:13.708323

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '095943f9dd36'
down_revision: Union[str, None] = '7c8d9e0f1a2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
