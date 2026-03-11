"""merge all alembic heads

Revision ID: f1eb37880886
Revises: h1i2j3k4l5m6, i9j0k1l2m3n4, u5v6w7x8y9z0, w6x7y8z9a0b1
Create Date: 2026-03-01 16:51:40.406728

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = 'f1eb37880886'
down_revision: Union[str, None] = ('h1i2j3k4l5m6', 'i9j0k1l2m3n4', 'u5v6w7x8y9z0', 'w6x7y8z9a0b1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    pass


def downgrade() -> None:
    conn = op.get_bind()
    pass
