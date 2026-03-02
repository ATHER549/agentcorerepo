"""Drop outbound MCP columns from agent table

Revision ID: p5q6r7s8t9u0
Revises: 32241ba468df
Create Date: 2026-02-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "p5q6r7s8t9u0"
down_revision: Union[str, None] = "32241ba468df"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("agent")]

    if "mcp_enabled" in columns:
        op.drop_column("agent", "mcp_enabled")
    if "action_name" in columns:
        op.drop_column("agent", "action_name")
    if "action_description" in columns:
        op.drop_column("agent", "action_description")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("agent")]

    if "action_description" not in columns:
        op.add_column("agent", sa.Column("action_description", sa.Text(), nullable=True))
    if "action_name" not in columns:
        op.add_column("agent", sa.Column("action_name", sa.VARCHAR(), nullable=True))
    if "mcp_enabled" not in columns:
        op.add_column(
            "agent",
            sa.Column(
                "mcp_enabled",
                sa.Boolean(),
                nullable=True,
                server_default=sa.text("false"),
            ),
        )
