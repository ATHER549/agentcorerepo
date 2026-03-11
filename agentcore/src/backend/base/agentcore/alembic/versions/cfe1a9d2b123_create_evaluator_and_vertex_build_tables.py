"""create evaluator and vertex_build tables

Revision ID: cfe1a9d2b123
Revises: 85febef4f6fb
Create Date: 2026-02-11 11:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'cfe1a9d2b123'
down_revision: Union[str, None] = '85febef4f6fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create evaluator table
    op.create_table(
        'evaluator',
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('criteria', sa.Text(), nullable=False),
        sa.Column('model', sa.String(), nullable=True, server_default=sa.text("'gpt-4o'")),
        sa.Column('preset_id', sa.String(), nullable=True),
        sa.Column('ground_truth', sa.Text(), nullable=True),
        sa.Column('target', postgresql.JSON(), nullable=True),
        sa.Column('trace_id', sa.String(), nullable=True),
        sa.Column('agent_id', sa.String(), nullable=True),
        sa.Column('agent_ids', postgresql.JSON(), nullable=True),
        sa.Column('agent_name', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('project_name', sa.String(), nullable=True),
        sa.Column('ts_from', sa.DateTime(), nullable=True),
        sa.Column('ts_to', sa.DateTime(), nullable=True),
        sa.Column('model_api_key', sa.String(), nullable=True),
        sa.Column('id', postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column('user_id', postgresql.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_evaluator_user_id', 'evaluator', ['user_id'])

    # Create vertex_build table
    op.create_table(
        'vertex_build',
        sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('data', postgresql.JSON(), nullable=True),
        sa.Column('artifacts', postgresql.JSON(), nullable=True),
        sa.Column('params', sa.Text(), nullable=True),
        sa.Column('valid', sa.Boolean(), nullable=False),
        sa.Column('agent_id', postgresql.UUID(), nullable=False),
        sa.Column('build_id', postgresql.UUID(), primary_key=True, nullable=False),
    )


def downgrade() -> None:
    op.drop_table('vertex_build')
    op.drop_index('ix_evaluator_user_id', table_name='evaluator')
    op.drop_table('evaluator')
