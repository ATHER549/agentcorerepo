"""add connector permissions to rbac

Revision ID: u5v6w7x8y9z0
Revises: n2o3p4q5r6s7
Create Date: 2026-02-28 12:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "u5v6w7x8y9z0"
down_revision: str | Sequence[str] | None = "n2o3p4q5r6s7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = [
    ("connectore_page", "Connectors"),
    ("add_connector", "Connectors"),
]

ROLE_GRANTS = {
    "root": ["connectore_page", "add_connector"],
    "super_admin": ["connectore_page", "add_connector"],
    "department_admin": ["connectore_page", "add_connector"],
    "developer": ["connectore_page", "add_connector"],
    "business_user": ["connectore_page", "add_connector"],
}


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def _upsert_permission(bind, key: str, category: str) -> None:
    has_category = _has_column(bind, "permission", "category")
    has_is_system = _has_column(bind, "permission", "is_system")
    has_created_at = _has_column(bind, "permission", "created_at")
    has_updated_at = _has_column(bind, "permission", "updated_at")

    row = bind.execute(sa.text("SELECT id FROM permission WHERE key = :key"), {"key": key}).fetchone()
    if row:
        set_parts = ["name = :name", "description = :description"]
        params = {"key": key, "name": key.replace("_", " "), "description": None, "category": category, "is_system": True}
        if has_category:
            set_parts.append("category = :category")
        if has_is_system:
            set_parts.append("is_system = :is_system")
        if has_updated_at:
            set_parts.append("updated_at = CURRENT_TIMESTAMP")
        bind.execute(sa.text(f"UPDATE permission SET {', '.join(set_parts)} WHERE key = :key"), params)
        return

    cols = ["id", "key", "name", "description"]
    vals = [":id", ":key", ":name", ":description"]
    params = {
        "id": str(uuid4()),
        "key": key,
        "name": key.replace("_", " "),
        "description": None,
        "category": category,
        "is_system": True,
    }
    if has_category:
        cols.append("category")
        vals.append(":category")
    if has_is_system:
        cols.append("is_system")
        vals.append(":is_system")
    if has_created_at:
        cols.append("created_at")
        vals.append("CURRENT_TIMESTAMP")
    if has_updated_at:
        cols.append("updated_at")
        vals.append("CURRENT_TIMESTAMP")
    bind.execute(sa.text(f"INSERT INTO permission ({', '.join(cols)}) VALUES ({', '.join(vals)})"), params)


def upgrade() -> None:
    bind = op.get_bind()
    if not (_table_exists(bind, "permission") and _table_exists(bind, "role") and _table_exists(bind, "role_permission")):
        return

    for key, category in PERMISSIONS:
        _upsert_permission(bind, key, category)

    role_rows = bind.execute(
        sa.text("SELECT id, name FROM role WHERE name IN :names").bindparams(sa.bindparam("names", expanding=True)),
        {"names": list(ROLE_GRANTS.keys())},
    ).fetchall()
    role_id_by_name = {str(r[1]): str(r[0]) for r in role_rows}

    permission_rows = bind.execute(
        sa.text("SELECT id, key FROM permission WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": [k for keys in ROLE_GRANTS.values() for k in keys]},
    ).fetchall()
    permission_id_by_key = {str(r[1]): str(r[0]) for r in permission_rows}
    has_created_at = _has_column(bind, "role_permission", "created_at")
    has_updated_at = _has_column(bind, "role_permission", "updated_at")
    has_created_by = _has_column(bind, "role_permission", "created_by")
    has_updated_by = _has_column(bind, "role_permission", "updated_by")

    for role_name, keys in ROLE_GRANTS.items():
        role_id = role_id_by_name.get(role_name)
        if not role_id:
            continue
        for key in keys:
            permission_id = permission_id_by_key.get(key)
            if not permission_id:
                continue
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
                    "  SELECT 1 FROM role_permission WHERE role_id = :role_id AND permission_id = :permission_id"
                    ")"
                ),
                params,
            )


def downgrade() -> None:
    return
