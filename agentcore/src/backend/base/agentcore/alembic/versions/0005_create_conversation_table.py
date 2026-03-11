"""Create conversation table

Revision ID: 0005
Revises: 0004
Create Date: 2026-02-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = "e5f7c2"
down_revision: Union[str, None] = "d4e6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Naive datetime (no timezone) — timestamps stored as UTC without tz info
        # to prevent PostgreSQL timezone conversion issues
        sa.Column("timestamp", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("sender", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sender_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("files", sa.JSON(), nullable=True),
        sa.Column("error", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("properties", sa.JSON(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True, server_default=sa.text("'message'")),
        sa.Column("content_blocks", sa.JSON(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("conversation")
