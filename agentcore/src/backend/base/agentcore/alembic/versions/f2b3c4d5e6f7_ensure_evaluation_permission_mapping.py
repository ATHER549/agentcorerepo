"""ensure evaluation permission mapping

Revision ID: f2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-02-18 12:00:00.000000
"""

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSION_KEY = "view_evaluation_page"
PERMISSION_NAME = "view evaluation page"
PERMISSION_DESCRIPTION = "Access Evaluation page and evaluation APIs."
PERMISSION_CATEGORY = "Evaluation"


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def _upsert_evaluation_permission(bind) -> str | None:
    if not _table_exists(bind, "permission"):
        return None

    has_category = _has_column(bind, "permission", "category")
    has_is_system = _has_column(bind, "permission", "is_system")
    has_updated_at = _has_column(bind, "permission", "updated_at")
    has_created_at = _has_column(bind, "permission", "created_at")

    existing = bind.execute(
        sa.text("SELECT id FROM permission WHERE key = :key"),
        {"key": PERMISSION_KEY},
    ).fetchone()

    params = {
        "key": PERMISSION_KEY,
        "name": PERMISSION_NAME,
        "description": PERMISSION_DESCRIPTION,
        "category": PERMISSION_CATEGORY,
        "is_system": True,
    }

    if existing:
        set_parts = ["name = :name", "description = :description"]
        if has_category:
            set_parts.append("category = :category")
        if has_is_system:
            set_parts.append("is_system = :is_system")
        if has_updated_at:
            set_parts.append("updated_at = CURRENT_TIMESTAMP")

        bind.execute(
            sa.text(
                f"UPDATE permission SET {', '.join(set_parts)} WHERE key = :key"
            ),
            params,
        )
        return str(existing[0])

    insert_cols = ["id", "key", "name", "description"]
    insert_vals = [":id", ":key", ":name", ":description"]
    params["id"] = str(uuid4())

    if has_category:
        insert_cols.append("category")
        insert_vals.append(":category")
    if has_is_system:
        insert_cols.append("is_system")
        insert_vals.append(":is_system")
    if has_created_at:
        insert_cols.append("created_at")
        insert_vals.append("CURRENT_TIMESTAMP")
    if has_updated_at:
        insert_cols.append("updated_at")
        insert_vals.append("CURRENT_TIMESTAMP")

    bind.execute(
        sa.text(
            f"INSERT INTO permission ({', '.join(insert_cols)}) VALUES ({', '.join(insert_vals)})"
        ),
        params,
    )
    return params["id"]


def _grant_permission_to_role(
    bind,
    *,
    role_name: str,
    permission_id: str,
    skip_if_role_has_no_permissions: bool = False,
) -> None:
    if not _table_exists(bind, "role") or not _table_exists(bind, "role_permission"):
        return

    role_row = bind.execute(
        sa.text("SELECT id FROM role WHERE name = :name"),
        {"name": role_name},
    ).fetchone()
    if not role_row:
        return
    role_id = str(role_row[0])

    if skip_if_role_has_no_permissions:
        perm_count_row = bind.execute(
            sa.text("SELECT COUNT(1) FROM role_permission WHERE role_id = :role_id"),
            {"role_id": role_id},
        ).fetchone()
        perm_count = int((perm_count_row[0] if perm_count_row else 0) or 0)
        if perm_count == 0:
            return

    existing_pair = bind.execute(
        sa.text(
            "SELECT 1 FROM role_permission WHERE role_id = :role_id AND permission_id = :permission_id"
        ),
        {"role_id": role_id, "permission_id": permission_id},
    ).fetchone()
    if existing_pair:
        return

    has_created_at = _has_column(bind, "role_permission", "created_at")
    has_updated_at = _has_column(bind, "role_permission", "updated_at")

    insert_cols = ["id", "role_id", "permission_id"]
    insert_vals = [":id", ":role_id", ":permission_id"]
    params = {"id": str(uuid4()), "role_id": role_id, "permission_id": permission_id}

    if has_created_at:
        insert_cols.append("created_at")
        insert_vals.append("CURRENT_TIMESTAMP")
    if has_updated_at:
        insert_cols.append("updated_at")
        insert_vals.append("CURRENT_TIMESTAMP")

    bind.execute(
        sa.text(
            f"INSERT INTO role_permission ({', '.join(insert_cols)}) VALUES ({', '.join(insert_vals)})"
        ),
        params,
    )


def upgrade() -> None:
    bind = op.get_bind()

    permission_id = _upsert_evaluation_permission(bind)
    if not permission_id:
        return

    # Super admin should have access in DB-backed RBAC setups.
    _grant_permission_to_role(bind, role_name="super_admin", permission_id=permission_id)

    # Root often relies on fallback permissions when it has no DB mappings.
    # Only add this key if root is already DB-mapped, to avoid changing
    # fallback behavior into a partial DB permission set.
    _grant_permission_to_role(
        bind,
        role_name="root",
        permission_id=permission_id,
        skip_if_role_has_no_permissions=True,
    )


def downgrade() -> None:
    # Intentionally non-destructive data migration.
    return

