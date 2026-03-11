"""add hitl and scheduler permissions

Revision ID: p9q0r1s2t3u4
Revises: n2o3p4q5r6s7
Create Date: 2026-03-07 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "p9q0r1s2t3u4"
down_revision: str | Sequence[str] | None = "n2o3p4q5r6s7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS: list[tuple[str, str]] = [
    ("view_hitl_approvals_page", "HITL Approvals"),
    ("hitl_approve", "HITL Approvals"),
    ("hitl_reject", "HITL Approvals"),
    ("view_agent_scheduler_page", "Agent Scheduler"),
    ("add_scheduler", "Agent Scheduler"),
]


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

    existing = bind.execute(
        sa.text("SELECT id FROM permission WHERE key = :key"),
        {"key": key},
    ).fetchone()

    params = {
        "key": key,
        "name": key.replace("_", " "),
        "description": None,
        "category": category,
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
            sa.text(f"UPDATE permission SET {', '.join(set_parts)} WHERE key = :key"),
            params,
        )
        return

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


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "permission"):
        return

    for key, category in PERMISSIONS:
        _upsert_permission(bind, key, category)


def downgrade() -> None:
    # Intentionally non-destructive.
    return
