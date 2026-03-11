"""remove permission group and add custom permissions

Revision ID: c4d9e2f8a1b0
Revises: d1e2f3a4b5c6
Create Date: 2026-02-11 00:00:00.000000
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c4d9e2f8a1b0"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


PERMISSION_KEYS = (
    "view_dashboard",
    "view_admin_page",
    "create_users",
    "manage_roles",
    "manage_users",
    "edit_projects_page",
    "view_projects_page",
    "edit_agents",
    "view_agents_page",
    "view_knowledge_base_management",
    "view_approval_page",
    "view_only_agent",
    "approve_reject_page",
    "TBD",
    "view_published_agents",
    "copy_agents",
    "view_models",
    "add_new_model",
    "retire_model",
    "view_control_panel",
    "start_stop_agent",
    "enable_disable_agent",
    "share_agent",
    "interact_agents",
    "view_traces",
    "view_evaluation",
    "view_guardrails",
    "add_guardrails",
    "retire_guardrails",
    "view_vector_db",
    "add_vector_db",
    "retire_vector_db",
    "view_mcp",
    "add_mcp",
    "retire_mcp",
    "view_settings_page",
    "view_platform_configs",
    "edit_platform_configs",
)


ROLE_SEEDS = (
    {"name": "super_admin", "description": "Full access", "is_system": True},
    {"name": "department_admin", "description": "Department-level admin", "is_system": True},
    {"name": "developer", "description": "Developer", "is_system": True},
    {"name": "business_user", "description": "Business User", "is_system": True},
)


def _uuid_type():
    return postgresql.UUID(as_uuid=True) if op.get_bind().dialect.name == "postgresql" else sa.String(36)


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def _has_index(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _create_rbac_tables_if_missing(bind) -> None:
    if not _table_exists(bind, "permission"):
        op.create_table(
            "permission",
            sa.Column("id", _uuid_type(), primary_key=True),
            sa.Column("key", sa.String(length=200), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("group", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("key", name="uq_permission_key"),
        )

    if not _has_index(bind, "permission", "ix_permission_key"):
        op.create_index("ix_permission_key", "permission", ["key"])

    if not _table_exists(bind, "role"):
        op.create_table(
            "role",
            sa.Column("id", _uuid_type(), primary_key=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("name", name="uq_role_name"),
        )

    if not _has_index(bind, "role", "ix_role_name"):
        op.create_index("ix_role_name", "role", ["name"])

    if not _table_exists(bind, "role_permission"):
        op.create_table(
            "role_permission",
            sa.Column("id", _uuid_type(), primary_key=True),
            sa.Column("role_id", _uuid_type(), nullable=False),
            sa.Column("permission_id", _uuid_type(), nullable=False),
            sa.ForeignKeyConstraint(["role_id"], ["role.id"], name="fk_role_permission_role_id_role"),
            sa.ForeignKeyConstraint(["permission_id"], ["permission.id"], name="fk_role_permission_permission_id_permission"),
            sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission_pair"),
        )

    if not _has_index(bind, "role_permission", "ix_role_permission_role_id"):
        op.create_index("ix_role_permission_role_id", "role_permission", ["role_id"])
    if not _has_index(bind, "role_permission", "ix_role_permission_permission_id"):
        op.create_index("ix_role_permission_permission_id", "role_permission", ["permission_id"])


def _upsert_roles(bind) -> None:
    for role in ROLE_SEEDS:
        existing = bind.execute(sa.text("SELECT id FROM role WHERE name = :name"), {"name": role["name"]}).fetchone()
        if existing:
            bind.execute(
                sa.text(
                    "UPDATE role "
                    "SET description = :description, is_system = :is_system, updated_at = CURRENT_TIMESTAMP "
                    "WHERE name = :name"
                ),
                {
                    "name": role["name"],
                    "description": role["description"],
                    "is_system": True if role["is_system"] else False,
                },
            )
            continue

        bind.execute(
            sa.text(
                "INSERT INTO role (id, name, description, is_system, created_at, updated_at) "
                "VALUES (:id, :name, :description, :is_system, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": str(uuid4()),
                "name": role["name"],
                "description": role["description"],
                "is_system": True if role["is_system"] else False,
            },
        )


def _upsert_permissions(bind) -> None:
    for key in PERMISSION_KEYS:
        existing = bind.execute(sa.text("SELECT id FROM permission WHERE key = :key"), {"key": key}).fetchone()
        if existing:
            bind.execute(
                sa.text(
                    "UPDATE permission "
                    "SET name = :name, description = :description, updated_at = CURRENT_TIMESTAMP "
                    "WHERE key = :key"
                ),
                {"key": key, "name": key.replace("_", " "), "description": None},
            )
            continue

        bind.execute(
            sa.text(
                "INSERT INTO permission (id, key, name, description, created_at, updated_at) "
                "VALUES (:id, :key, :name, :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": str(uuid4()),
                "key": key,
                "name": key.replace("_", " "),
                "description": None,
            },
        )


def _delete_stale_permissions(bind) -> None:
    stale_rows = bind.execute(
        sa.text("SELECT id FROM permission WHERE key NOT IN :permission_keys").bindparams(
            sa.bindparam("permission_keys", expanding=True)
        ),
        {"permission_keys": list(PERMISSION_KEYS)},
    ).fetchall()
    stale_ids = [str(row[0]) for row in stale_rows]
    if not stale_ids:
        return

    bind.execute(
        sa.text("DELETE FROM role_permission WHERE permission_id IN :permission_ids").bindparams(
            sa.bindparam("permission_ids", expanding=True)
        ),
        {"permission_ids": stale_ids},
    )
    bind.execute(
        sa.text("DELETE FROM permission WHERE id IN :permission_ids").bindparams(
            sa.bindparam("permission_ids", expanding=True)
        ),
        {"permission_ids": stale_ids},
    )


def _grant_super_admin_all_permissions(bind) -> None:
    role_row = bind.execute(sa.text("SELECT id FROM role WHERE name = :name"), {"name": "super_admin"}).fetchone()
    if not role_row:
        return
    role_id = str(role_row[0])
    perm_rows = bind.execute(
        sa.text("SELECT id FROM permission WHERE key IN :permission_keys").bindparams(
            sa.bindparam("permission_keys", expanding=True)
        ),
        {"permission_keys": list(PERMISSION_KEYS)},
    ).fetchall()
    has_created_at = _has_column(bind, "role_permission", "created_at")
    has_updated_at = _has_column(bind, "role_permission", "updated_at")
    has_created_by = _has_column(bind, "role_permission", "created_by")
    has_updated_by = _has_column(bind, "role_permission", "updated_by")
    for row in perm_rows:
        permission_id = str(row[0])
        insert_cols = ["id", "role_id", "permission_id"]
        insert_vals = [":id", ":role_id", ":permission_id"]
        params = {"id": str(uuid4()), "role_id": role_id, "permission_id": permission_id}
        if has_created_by:
            insert_cols.append("created_by")
            insert_vals.append("NULL")
        if has_created_at:
            insert_cols.append("created_at")
            insert_vals.append("CURRENT_TIMESTAMP")
        if has_updated_by:
            insert_cols.append("updated_by")
            insert_vals.append("NULL")
        if has_updated_at:
            insert_cols.append("updated_at")
            insert_vals.append("CURRENT_TIMESTAMP")
        bind.execute(
            sa.text(
                f"INSERT INTO role_permission ({', '.join(insert_cols)}) "
                f"SELECT {', '.join(insert_vals)} "
                "WHERE NOT EXISTS ("
                "    SELECT 1 FROM role_permission WHERE role_id = :role_id AND permission_id = :permission_id"
                ")"
            ),
            params,
        )


def upgrade() -> None:
    bind = op.get_bind()
    _create_rbac_tables_if_missing(bind)

    if _has_column(bind, "permission", "group"):
        with op.batch_alter_table("permission") as batch_op:
            batch_op.drop_column("group")

    if _has_column(bind, "user", "role"):
        bind.execute(sa.text("UPDATE \"user\" SET role = 'super_admin' WHERE role = 'admin'"))

    _upsert_roles(bind)
    _upsert_permissions(bind)
    _delete_stale_permissions(bind)
    _grant_super_admin_all_permissions(bind)


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "permission") and not _has_column(bind, "permission", "group"):
        with op.batch_alter_table("permission") as batch_op:
            batch_op.add_column(sa.Column("group", sa.String(length=100), nullable=True))

    if not _table_exists(bind, "permission"):
        return

    permission_rows = bind.execute(
        sa.text("SELECT id FROM permission WHERE key IN :permission_keys").bindparams(
            sa.bindparam("permission_keys", expanding=True)
        ),
        {"permission_keys": list(PERMISSION_KEYS)},
    ).fetchall()
    permission_ids = [str(row[0]) for row in permission_rows]

    if _table_exists(bind, "role_permission") and permission_ids:
        bind.execute(
            sa.text("DELETE FROM role_permission WHERE permission_id IN :permission_ids").bindparams(
                sa.bindparam("permission_ids", expanding=True)
            ),
            {"permission_ids": permission_ids},
        )

    bind.execute(
        sa.text("DELETE FROM permission WHERE key IN :permission_keys").bindparams(
            sa.bindparam("permission_keys", expanding=True)
        ),
        {"permission_keys": list(PERMISSION_KEYS)},
    )
