"""add kb visibility column

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-02-25 13:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_table_columns(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def _has_index(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    columns = _get_table_columns(bind, "knowledge_base")

    # Create the enum type (PostgreSQL requires explicit type creation)
    kb_visibility_enum = sa.Enum("PRIVATE", "DEPARTMENT", "ORGANIZATION", name="kb_visibility_enum")
    kb_visibility_enum.create(bind, checkfirst=True)

    if "visibility" not in columns:
        op.add_column(
            "knowledge_base",
            sa.Column(
                "visibility",
                sa.Enum("PRIVATE", "DEPARTMENT", "ORGANIZATION", name="kb_visibility_enum"),
                nullable=False,
                server_default=sa.text("'PRIVATE'"),
            ),
        )

    if not _has_index(bind, "knowledge_base", "ix_knowledge_base_visibility"):
        op.create_index(
            "ix_knowledge_base_visibility",
            "knowledge_base",
            ["visibility"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _has_index(bind, "knowledge_base", "ix_knowledge_base_visibility"):
        op.drop_index("ix_knowledge_base_visibility", table_name="knowledge_base")

    columns = _get_table_columns(bind, "knowledge_base")
    if "visibility" in columns:
        op.drop_column("knowledge_base", "visibility")

    sa.Enum(name="kb_visibility_enum").drop(bind, checkfirst=True)
