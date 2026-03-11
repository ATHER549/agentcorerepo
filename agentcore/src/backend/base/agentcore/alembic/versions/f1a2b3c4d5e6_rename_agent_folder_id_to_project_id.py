"""rename agent project_id to project_id

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-02-18 02:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    return any(col["name"] == column for col in inspector.get_columns(table))


def _has_index(bind, table: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()

    if _has_column(bind, "agent", "project_id") and not _has_column(bind, "agent", "project_id"):
        op.alter_column("agent", "project_id", new_column_name="project_id", existing_type=sa.Uuid(), nullable=True)

    # Keep index naming aligned with column naming.
    if _has_index(bind, "agent", "ix_agent_project_id") and not _has_index(bind, "agent", "ix_agent_project_id"):
        op.execute(sa.text("ALTER INDEX ix_agent_project_id RENAME TO ix_agent_project_id"))


def downgrade() -> None:
    bind = op.get_bind()

    if _has_column(bind, "agent", "project_id") and not _has_column(bind, "agent", "project_id"):
        op.alter_column("agent", "project_id", new_column_name="project_id", existing_type=sa.Uuid(), nullable=True)

    if _has_index(bind, "agent", "ix_agent_project_id") and not _has_index(bind, "agent", "ix_agent_project_id"):
        op.execute(sa.text("ALTER INDEX ix_agent_project_id RENAME TO ix_agent_project_id"))
