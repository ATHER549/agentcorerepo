"""add agent_id and agent_ids fields to evaluator table

Revision ID: d1e2f3a4b5c6
Revises: cfe1a9d2b123
Create Date: 2026-02-11 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'cfe1a9d2b123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name, column_name):
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col"
        ),
        {"table": table_name, "col": column_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    # Add agent_id and agent_ids columns to evaluator table
    # These are aliases for agent_id/agent_ids since agents are agents in the system
    if not column_exists('evaluator', 'agent_id'):
        op.add_column('evaluator', sa.Column('agent_id', sa.String(), nullable=True))
    if not column_exists('evaluator', 'agent_ids'):
        op.add_column('evaluator', sa.Column('agent_ids', postgresql.JSON(), nullable=True))


def downgrade() -> None:
    # Remove the columns
    op.drop_column('evaluator', 'agent_ids')
    op.drop_column('evaluator', 'agent_id')
