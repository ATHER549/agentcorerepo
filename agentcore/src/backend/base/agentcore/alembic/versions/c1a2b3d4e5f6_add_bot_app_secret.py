"""add_bot_app_secret_to_teams_app

Revision ID: c1a2b3d4e5f6
Revises: b9f48ef919cd
Create Date: 2026-02-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = 'b9f48ef919cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('teams_app', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bot_app_secret', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('teams_app', schema=None) as batch_op:
        batch_op.drop_column('bot_app_secret')
