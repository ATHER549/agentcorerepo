"""add organization and department tables; extend project table for tenancy

Revision ID: a9b7c6d5e4f3
Revises: f0a1b2c3d4e5
Create Date: 2026-02-17 22:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9b7c6d5e4f3"
down_revision: Union[str, None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def _has_fk(bind, table_name: str, fk_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(fk.get("name") == fk_name for fk in sa.inspect(bind).get_foreign_keys(table_name))


def _has_unique(bind, table_name: str, constraint_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(u.get("name") == constraint_name for u in sa.inspect(bind).get_unique_constraints(table_name))


def _has_unique_columns(bind, table_name: str, columns: list[str]) -> bool:
    if not _table_exists(bind, table_name):
        return False
    target = tuple(columns)
    for unique in sa.inspect(bind).get_unique_constraints(table_name):
        cols = unique.get("column_names") or []
        if tuple(cols) == target:
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "organization"):
        op.create_table(
            "organization",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'active'")),
            sa.Column("owner_user_id", sa.Uuid(), nullable=True),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_by", sa.Uuid(), nullable=True),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["deleted_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["owner_user_id"], ["user.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _table_exists(bind, "department"):
        op.create_table(
            "department",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("code", sa.String(length=50), nullable=True),
            sa.Column("admin_user_id", sa.Uuid(), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'active'")),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_by", sa.Uuid(), nullable=True),
            sa.ForeignKeyConstraint(["admin_user_id"], ["user.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["deleted_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("org_id", "id", name="uq_department_org_id_id"),
            sa.UniqueConstraint("org_id", "code", name="uq_department_org_id_code"),
        )
    if _table_exists(bind, "department") and not _has_index(bind, "department", "ix_department_org_id"):
        op.create_index("ix_department_org_id", "department", ["org_id"])

    if _table_exists(bind, "project") and not _has_column(bind, "project", "org_id"):
        op.add_column("project", sa.Column("org_id", sa.Uuid(), nullable=True))
    if _table_exists(bind, "project") and not _has_column(bind, "project", "dept_id"):
        op.add_column("project", sa.Column("dept_id", sa.Uuid(), nullable=True))
    if _table_exists(bind, "project") and not _has_column(bind, "project", "owner_user_id"):
        op.add_column("project", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    if _table_exists(bind, "project") and not _has_column(bind, "project", "status"):
        op.add_column("project", sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'active'")))
    if _table_exists(bind, "project") and not _has_column(bind, "project", "created_by"):
        op.add_column("project", sa.Column("created_by", sa.Uuid(), nullable=True))
    if _table_exists(bind, "project") and not _has_column(bind, "project", "created_at"):
        op.add_column("project", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    if _table_exists(bind, "project") and not _has_column(bind, "project", "updated_by"):
        op.add_column("project", sa.Column("updated_by", sa.Uuid(), nullable=True))
    if _table_exists(bind, "project") and not _has_column(bind, "project", "updated_at"):
        op.add_column("project", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    if _table_exists(bind, "project") and not _has_column(bind, "project", "deleted_at"):
        op.add_column("project", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    if _table_exists(bind, "project") and not _has_column(bind, "project", "deleted_by"):
        op.add_column("project", sa.Column("deleted_by", sa.Uuid(), nullable=True))

    if _table_exists(bind, "project") and not _has_index(bind, "project", "ix_project_org_id"):
        op.create_index("ix_project_org_id", "project", ["org_id"])
    if _table_exists(bind, "project") and not _has_index(bind, "project", "ix_project_dept_id"):
        op.create_index("ix_project_dept_id", "project", ["dept_id"])

    if _table_exists(bind, "project") and _table_exists(bind, "organization") and not _has_fk(bind, "project", "fk_project_org_id_organization"):
        op.create_foreign_key("fk_project_org_id_organization", "project", "organization", ["org_id"], ["id"])
    if _table_exists(bind, "project") and _table_exists(bind, "department") and not _has_fk(bind, "project", "fk_project_dept_id_department"):
        op.create_foreign_key("fk_project_dept_id_department", "project", "department", ["dept_id"], ["id"])
    if _table_exists(bind, "project") and _table_exists(bind, "user") and not _has_fk(bind, "project", "fk_project_owner_user_id_user"):
        op.create_foreign_key("fk_project_owner_user_id_user", "project", "user", ["owner_user_id"], ["id"])
    if _table_exists(bind, "project") and _table_exists(bind, "user") and not _has_fk(bind, "project", "fk_project_created_by_user"):
        op.create_foreign_key("fk_project_created_by_user", "project", "user", ["created_by"], ["id"])
    if _table_exists(bind, "project") and _table_exists(bind, "user") and not _has_fk(bind, "project", "fk_project_updated_by_user"):
        op.create_foreign_key("fk_project_updated_by_user", "project", "user", ["updated_by"], ["id"])
    if _table_exists(bind, "project") and _table_exists(bind, "user") and not _has_fk(bind, "project", "fk_project_deleted_by_user"):
        op.create_foreign_key("fk_project_deleted_by_user", "project", "user", ["deleted_by"], ["id"])
    if _table_exists(bind, "department") and not _has_unique(bind, "department", "uq_department_org_id_id") and not _has_unique_columns(bind, "department", ["org_id", "id"]):
        op.create_unique_constraint("uq_department_org_id_id", "department", ["org_id", "id"])
    if _table_exists(bind, "project") and _table_exists(bind, "department") and not _has_fk(bind, "project", "fk_project_org_id_dept_id_department"):
        op.create_foreign_key(
            "fk_project_org_id_dept_id_department",
            "project",
            "department",
            ["org_id", "dept_id"],
            ["org_id", "id"],
        )


def downgrade() -> None:
    op.drop_constraint("fk_project_org_id_dept_id_department", "project", type_="foreignkey")
    op.drop_constraint("fk_project_deleted_by_user", "project", type_="foreignkey")
    op.drop_constraint("fk_project_updated_by_user", "project", type_="foreignkey")
    op.drop_constraint("fk_project_created_by_user", "project", type_="foreignkey")
    op.drop_constraint("fk_project_owner_user_id_user", "project", type_="foreignkey")
    op.drop_constraint("fk_project_dept_id_department", "project", type_="foreignkey")
    op.drop_constraint("fk_project_org_id_organization", "project", type_="foreignkey")
    op.drop_index("ix_project_dept_id", table_name="project")
    op.drop_index("ix_project_org_id", table_name="project")
    op.drop_column("project", "deleted_by")
    op.drop_column("project", "deleted_at")
    op.drop_column("project", "updated_at")
    op.drop_column("project", "updated_by")
    op.drop_column("project", "created_at")
    op.drop_column("project", "created_by")
    op.drop_column("project", "status")
    op.drop_column("project", "owner_user_id")
    op.drop_column("project", "dept_id")
    op.drop_column("project", "org_id")

    op.drop_index("ix_department_org_id", table_name="department")
    op.drop_table("department")

    op.drop_table("organization")
