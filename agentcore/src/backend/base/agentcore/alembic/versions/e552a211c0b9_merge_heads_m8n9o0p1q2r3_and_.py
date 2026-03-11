"""merge heads m8n9o0p1q2r3 and q4r5s6t7u8v9

Revision ID: e552a211c0b9
Revises: m8n9o0p1q2r3, q4r5s6t7u8v9
Create Date: 2026-03-10 19:23:58.107912

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = 'e552a211c0b9'
down_revision: Union[str, None] = ('m8n9o0p1q2r3', 'q4r5s6t7u8v9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
