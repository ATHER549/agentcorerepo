"""align vector db catalogue rbac scope

Revision ID: l9a0b1c2d3e4
Revises: k8f9a0b1c2d3
Create Date: 2026-02-20 16:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "l9a0b1c2d3e4"
down_revision: str | Sequence[str] | None = "k8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def _has_index(bind, table_name: str, index_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(idx["name"] == index_name for idx in sa.inspect(bind).get_indexes(table_name))


def _has_unique(bind, table_name: str, name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(uc["name"] == name for uc in sa.inspect(bind).get_unique_constraints(table_name))


def _has_fk(bind, table_name: str, name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(fk["name"] == name for fk in sa.inspect(bind).get_foreign_keys(table_name))


def _has_check(bind, table_name: str, name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    checks = sa.inspect(bind).get_check_constraints(table_name)
    return any(chk["name"] == name for chk in checks)


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "vector_db_catalogue"):
        return

    if not _has_column(bind, "vector_db_catalogue", "dept_id"):
        op.add_column("vector_db_catalogue", sa.Column("dept_id", sa.Uuid(), nullable=True))
    if not _has_column(bind, "vector_db_catalogue", "published_by"):
        op.add_column("vector_db_catalogue", sa.Column("published_by", sa.Uuid(), nullable=True))
    if not _has_column(bind, "vector_db_catalogue", "published_at"):
        op.add_column("vector_db_catalogue", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))

    if _has_unique(bind, "vector_db_catalogue", "uq_vector_db_catalogue_org_name"):
        op.drop_constraint("uq_vector_db_catalogue_org_name", "vector_db_catalogue", type_="unique")

    if not _has_unique(bind, "vector_db_catalogue", "uq_vector_db_catalogue_scope_name"):
        op.create_unique_constraint(
            "uq_vector_db_catalogue_scope_name",
            "vector_db_catalogue",
            ["org_id", "dept_id", "name"],
        )

    if not _has_index(bind, "vector_db_catalogue", "ix_vector_db_catalogue_dept_id"):
        op.create_index("ix_vector_db_catalogue_dept_id", "vector_db_catalogue", ["dept_id"], unique=False)
    if not _has_index(bind, "vector_db_catalogue", "ix_vector_db_catalogue_org_dept"):
        op.create_index("ix_vector_db_catalogue_org_dept", "vector_db_catalogue", ["org_id", "dept_id"], unique=False)

    if not _has_fk(bind, "vector_db_catalogue", "fk_vector_db_catalogue_dept_id_department"):
        op.create_foreign_key(
            "fk_vector_db_catalogue_dept_id_department",
            "vector_db_catalogue",
            "department",
            ["dept_id"],
            ["id"],
        )
    if not _has_fk(bind, "vector_db_catalogue", "fk_vector_db_catalogue_published_by_user"):
        op.create_foreign_key(
            "fk_vector_db_catalogue_published_by_user",
            "vector_db_catalogue",
            "user",
            ["published_by"],
            ["id"],
        )
    if not _has_fk(bind, "vector_db_catalogue", "fk_vector_db_org_dept_department"):
        op.create_foreign_key(
            "fk_vector_db_org_dept_department",
            "vector_db_catalogue",
            "department",
            ["org_id", "dept_id"],
            ["org_id", "id"],
        )

    if not _has_check(bind, "vector_db_catalogue", "ck_vector_db_scope_consistency"):
        op.create_check_constraint(
            "ck_vector_db_scope_consistency",
            "vector_db_catalogue",
            "(dept_id IS NULL) OR (org_id IS NOT NULL)",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "vector_db_catalogue"):
        return

    if _has_check(bind, "vector_db_catalogue", "ck_vector_db_scope_consistency"):
        op.drop_constraint("ck_vector_db_scope_consistency", "vector_db_catalogue", type_="check")

    if _has_fk(bind, "vector_db_catalogue", "fk_vector_db_org_dept_department"):
        op.drop_constraint("fk_vector_db_org_dept_department", "vector_db_catalogue", type_="foreignkey")
    if _has_fk(bind, "vector_db_catalogue", "fk_vector_db_catalogue_published_by_user"):
        op.drop_constraint("fk_vector_db_catalogue_published_by_user", "vector_db_catalogue", type_="foreignkey")
    if _has_fk(bind, "vector_db_catalogue", "fk_vector_db_catalogue_dept_id_department"):
        op.drop_constraint("fk_vector_db_catalogue_dept_id_department", "vector_db_catalogue", type_="foreignkey")

    if _has_index(bind, "vector_db_catalogue", "ix_vector_db_catalogue_org_dept"):
        op.drop_index("ix_vector_db_catalogue_org_dept", table_name="vector_db_catalogue")
    if _has_index(bind, "vector_db_catalogue", "ix_vector_db_catalogue_dept_id"):
        op.drop_index("ix_vector_db_catalogue_dept_id", table_name="vector_db_catalogue")

    if _has_unique(bind, "vector_db_catalogue", "uq_vector_db_catalogue_scope_name"):
        op.drop_constraint("uq_vector_db_catalogue_scope_name", "vector_db_catalogue", type_="unique")
    if not _has_unique(bind, "vector_db_catalogue", "uq_vector_db_catalogue_org_name"):
        op.create_unique_constraint("uq_vector_db_catalogue_org_name", "vector_db_catalogue", ["org_id", "name"])

    if _has_column(bind, "vector_db_catalogue", "published_at"):
        op.drop_column("vector_db_catalogue", "published_at")
    if _has_column(bind, "vector_db_catalogue", "published_by"):
        op.drop_column("vector_db_catalogue", "published_by")
    if _has_column(bind, "vector_db_catalogue", "dept_id"):
        op.drop_column("vector_db_catalogue", "dept_id")
