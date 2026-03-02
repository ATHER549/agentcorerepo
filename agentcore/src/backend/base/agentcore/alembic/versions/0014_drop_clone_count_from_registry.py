"""Drop clone_count column from agent_registry

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-02-19

Changes:
  - DROP COLUMN: agent_registry.clone_count
    The clone_count column was added previously but is no longer
    used in the model. Cloning stats are tracked via the
    cloned_from_deployment_id on the agent table instead.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "agent_registry") and _has_column(bind, "agent_registry", "clone_count"):
        op.drop_column("agent_registry", "clone_count")


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "agent_registry") and not _has_column(bind, "agent_registry", "clone_count"):
        op.add_column(
            "agent_registry",
            sa.Column(
                "clone_count",
                sa.INTEGER(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
