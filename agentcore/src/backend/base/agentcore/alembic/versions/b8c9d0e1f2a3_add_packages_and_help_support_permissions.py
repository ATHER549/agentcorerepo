"""add packages and help support permissions

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-02-25 12:30:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = [
    ("view_packages_page", "Packages"),
    ("view_help_support_page", "Help & Support"),
    ("add_faq", "Help & Support"),
]


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [col["name"] for col in inspector.get_columns(table_name)]


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "permission"):
        return

    has_category = _has_column(bind, "permission", "category")
    has_is_system = _has_column(bind, "permission", "is_system")
    has_created_at = _has_column(bind, "permission", "created_at")
    has_updated_at = _has_column(bind, "permission", "updated_at")

    for key, category in NEW_PERMISSIONS:
        existing = bind.execute(
            sa.text("SELECT id FROM permission WHERE key = :key"),
            {"key": key},
        ).fetchone()
        if existing:
            continue

        insert_cols = ["id", "key", "name", "description"]
        insert_vals = [":id", ":key", ":name", ":description"]
        params = {
            "id": str(uuid4()),
            "key": key,
            "name": key.replace("_", " "),
            "description": None,
            "category": category,
            "is_system": True,
        }

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
                f"INSERT INTO permission ({', '.join(insert_cols)}) "
                f"VALUES ({', '.join(insert_vals)})"
            ),
            params,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "permission"):
        return

    keys = [key for key, _ in NEW_PERMISSIONS]

    # Remove role_permission mappings first
    if _table_exists(bind, "role_permission"):
        perm_rows = bind.execute(
            sa.text("SELECT id FROM permission WHERE key IN :keys").bindparams(
                sa.bindparam("keys", expanding=True)
            ),
            {"keys": keys},
        ).fetchall()
        if perm_rows:
            perm_ids = [str(row[0]) for row in perm_rows]
            bind.execute(
                sa.text("DELETE FROM role_permission WHERE permission_id IN :ids").bindparams(
                    sa.bindparam("ids", expanding=True)
                ),
                {"ids": perm_ids},
            )

    bind.execute(
        sa.text("DELETE FROM permission WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": keys},
    )
