"""Create vertex_build table

Revision ID: 0007
Revises: 0006
Create Date: 2026-02-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = "a7b9e4"
down_revision: Union[str, None] = "f6a8d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vertex_build",
        sa.Column("build_id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("artifacts", sa.JSON(), nullable=True),
        sa.Column("params", sa.Text(), nullable=True),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("build_id"),
    )


def downgrade() -> None:
    op.drop_table("vertex_build")
