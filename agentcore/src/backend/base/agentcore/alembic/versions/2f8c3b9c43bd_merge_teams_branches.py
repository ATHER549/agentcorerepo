"""merge_teams_branches

Revision ID: 2f8c3b9c43bd
Revises: 8427dd771044, c1a2b3d4e5f6
Create Date: 2026-02-24 17:11:53.248337

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '2f8c3b9c43bd'
down_revision: Union[str, None] = ('8427dd771044', 'c1a2b3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
