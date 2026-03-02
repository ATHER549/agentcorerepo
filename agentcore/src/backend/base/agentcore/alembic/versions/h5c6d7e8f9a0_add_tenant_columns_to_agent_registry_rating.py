"""add tenant columns to agent_registry_rating

Revision ID: h5c6d7e8f9a0
Revises: c3d4e5f6a7b8
Create Date: 2026-02-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "h5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(col["name"] == column_name for col in sa.inspect(bind).get_columns(table_name))


def _has_index(bind, table_name: str, index_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(idx["name"] == index_name for idx in sa.inspect(bind).get_indexes(table_name))


def _has_fk(bind, table_name: str, fk_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(fk["name"] == fk_name for fk in sa.inspect(bind).get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    table = "agent_registry_rating"

    if not _table_exists(bind, table):
        return

    if not _has_column(bind, table, "org_id"):
        op.add_column(table, sa.Column("org_id", sa.Uuid(), nullable=True))
    if not _has_column(bind, table, "dept_id"):
        op.add_column(table, sa.Column("dept_id", sa.Uuid(), nullable=True))

    if not _has_fk(bind, table, "fk_agent_registry_rating_org_id_organization"):
        op.create_foreign_key(
            "fk_agent_registry_rating_org_id_organization",
            table,
            "organization",
            ["org_id"],
            ["id"],
        )
    if not _has_fk(bind, table, "fk_agent_registry_rating_dept_id_department"):
        op.create_foreign_key(
            "fk_agent_registry_rating_dept_id_department",
            table,
            "department",
            ["dept_id"],
            ["id"],
        )

    if not _has_index(bind, table, "ix_agent_registry_rating_org_id"):
        op.create_index("ix_agent_registry_rating_org_id", table, ["org_id"], unique=False)
    if not _has_index(bind, table, "ix_agent_registry_rating_dept_id"):
        op.create_index("ix_agent_registry_rating_dept_id", table, ["dept_id"], unique=False)
    if not _has_index(bind, table, "ix_registry_rating_org"):
        op.create_index("ix_registry_rating_org", table, ["org_id"], unique=False)
    if not _has_index(bind, table, "ix_registry_rating_dept"):
        op.create_index("ix_registry_rating_dept", table, ["dept_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    table = "agent_registry_rating"

    if not _table_exists(bind, table):
        return

    if _has_index(bind, table, "ix_registry_rating_dept"):
        op.drop_index("ix_registry_rating_dept", table_name=table)
    if _has_index(bind, table, "ix_registry_rating_org"):
        op.drop_index("ix_registry_rating_org", table_name=table)
    if _has_index(bind, table, "ix_agent_registry_rating_dept_id"):
        op.drop_index("ix_agent_registry_rating_dept_id", table_name=table)
    if _has_index(bind, table, "ix_agent_registry_rating_org_id"):
        op.drop_index("ix_agent_registry_rating_org_id", table_name=table)

    if _has_fk(bind, table, "fk_agent_registry_rating_dept_id_department"):
        op.drop_constraint("fk_agent_registry_rating_dept_id_department", table, type_="foreignkey")
    if _has_fk(bind, table, "fk_agent_registry_rating_org_id_organization"):
        op.drop_constraint("fk_agent_registry_rating_org_id_organization", table, type_="foreignkey")

    if _has_column(bind, table, "dept_id"):
        op.drop_column(table, "dept_id")
    if _has_column(bind, table, "org_id"):
        op.drop_column(table, "org_id")

