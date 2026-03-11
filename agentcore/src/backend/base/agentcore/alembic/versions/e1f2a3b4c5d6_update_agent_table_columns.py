"""update agent table columns

Revision ID: e1f2a3b4c5d6
Revises: d7e8f9a0b1c2
Create Date: 2026-02-19 14:45:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True) if op.get_bind().dialect.name == "postgresql" else sa.String(36)


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def _has_index(bind, table_name: str, index_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(i["name"] == index_name for i in sa.inspect(bind).get_indexes(table_name))


def _has_unique(bind, table_name: str, constraint_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(u["name"] == constraint_name for u in sa.inspect(bind).get_unique_constraints(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "agent"):
        return

    if _has_unique(bind, "agent", "unique_agent_endpoint_name"):
        op.drop_constraint("unique_agent_endpoint_name", "agent", type_="unique")
    if _has_index(bind, "agent", "ix_agent_endpoint_name"):
        op.drop_index("ix_agent_endpoint_name", table_name="agent")

    for col in ["icon_bg_color", "gradient", "is_component", "webhook", "endpoint_name"]:
        if _has_column(bind, "agent", col):
            op.drop_column("agent", col)

    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'lifecycle_status_enum') THEN "
                "CREATE TYPE lifecycle_status_enum AS ENUM ('DRAFT', 'PENDING_APPROVAL', 'PUBLISHED', 'DEPRECATED', 'ARCHIVED'); "
                "END IF; "
                "END $$;"
            )
        )

    if not _has_column(bind, "agent", "lifecycle_status"):
        op.add_column(
            "agent",
            sa.Column(
                "lifecycle_status",
                sa.Enum("DRAFT", "PENDING_APPROVAL", "PUBLISHED", "DEPRECATED", "ARCHIVED", name="lifecycle_status_enum"),
                nullable=False,
                server_default=sa.text("'DRAFT'"),
            ),
        )

    if not _has_column(bind, "agent", "cloned_from_deployment_id"):
        op.add_column("agent", sa.Column("cloned_from_deployment_id", _uuid_type(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "agent"):
        return

    if _has_column(bind, "agent", "cloned_from_deployment_id"):
        op.drop_column("agent", "cloned_from_deployment_id")
    if _has_column(bind, "agent", "lifecycle_status"):
        op.drop_column("agent", "lifecycle_status")

    if not _has_column(bind, "agent", "icon_bg_color"):
        op.add_column("agent", sa.Column("icon_bg_color", sa.String(), nullable=True))
    if not _has_column(bind, "agent", "gradient"):
        op.add_column("agent", sa.Column("gradient", sa.String(), nullable=True))
    if not _has_column(bind, "agent", "is_component"):
        op.add_column("agent", sa.Column("is_component", sa.Boolean(), nullable=True, server_default=sa.text("false")))
    if not _has_column(bind, "agent", "webhook"):
        op.add_column("agent", sa.Column("webhook", sa.Boolean(), nullable=True, server_default=sa.text("false")))
    if not _has_column(bind, "agent", "endpoint_name"):
        op.add_column("agent", sa.Column("endpoint_name", sa.String(), nullable=True))

    if not _has_index(bind, "agent", "ix_agent_endpoint_name"):
        op.create_index("ix_agent_endpoint_name", "agent", ["endpoint_name"])
    if not _has_unique(bind, "agent", "unique_agent_endpoint_name"):
        op.create_unique_constraint("unique_agent_endpoint_name", "agent", ["user_id", "endpoint_name"])
