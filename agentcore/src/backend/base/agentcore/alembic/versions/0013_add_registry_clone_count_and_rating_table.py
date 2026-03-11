"""Create agent_registry_rating table for per-user star ratings

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_index(bind, table_name: str, index_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(i["name"] == index_name for i in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "agent_registry_rating"):
        op.create_table(
            "agent_registry_rating",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("registry_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("review", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["registry_id"], ["agent_registry.id"], name="fk_registry_rating_registry"),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_registry_rating_user"),
            sa.UniqueConstraint("registry_id", "user_id", name="uq_registry_rating_user"),
        )
    if _table_exists(bind, "agent_registry_rating") and not _has_index(bind, "agent_registry_rating", "ix_registry_rating_registry"):
        op.create_index("ix_registry_rating_registry", "agent_registry_rating", ["registry_id"], unique=False)
    if _table_exists(bind, "agent_registry_rating") and not _has_index(bind, "agent_registry_rating", "ix_registry_rating_user"):
        op.create_index("ix_registry_rating_user", "agent_registry_rating", ["user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "agent_registry_rating"):
        if _has_index(bind, "agent_registry_rating", "ix_registry_rating_user"):
            op.drop_index("ix_registry_rating_user", table_name="agent_registry_rating")
        if _has_index(bind, "agent_registry_rating", "ix_registry_rating_registry"):
            op.drop_index("ix_registry_rating_registry", table_name="agent_registry_rating")
        op.drop_table("agent_registry_rating")
