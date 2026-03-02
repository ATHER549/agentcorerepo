"""add missing foreign keys for mcp_registry

Revision ID: 7c8d9e0f1a2b
Revises: 6a797d30d8ef
Create Date: 2026-03-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "7c8d9e0f1a2b"
down_revision: Union[str, None] = "6a797d30d8ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "mcp_registry"


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_fk(bind, table_name: str, fk_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any((fk.get("name") or "") == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, TABLE_NAME):
        return

    fk_specs = (
        ("fk_mcp_registry_requested_by_user", ["requested_by"], "user", ["id"]),
        ("fk_mcp_registry_dept_id_department", ["dept_id"], "department", ["id"]),
        ("fk_mcp_registry_org_dept_department", ["org_id", "dept_id"], "department", ["org_id", "id"]),
        ("fk_mcp_registry_request_to_user", ["request_to"], "user", ["id"]),
        ("fk_mcp_registry_reviewed_by_user", ["reviewed_by"], "user", ["id"]),
        ("fk_mcp_registry_created_by_id_user", ["created_by_id"], "user", ["id"]),
        ("fk_mcp_registry_org_id_organization", ["org_id"], "organization", ["id"]),
    )

    for fk_name, local_cols, remote_table, remote_cols in fk_specs:
        if not _has_fk(bind, TABLE_NAME, fk_name):
            op.create_foreign_key(
                fk_name,
                TABLE_NAME,
                remote_table,
                local_cols,
                remote_cols,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, TABLE_NAME):
        return

    for fk_name in (
        "fk_mcp_registry_org_id_organization",
        "fk_mcp_registry_created_by_id_user",
        "fk_mcp_registry_reviewed_by_user",
        "fk_mcp_registry_request_to_user",
        "fk_mcp_registry_org_dept_department",
        "fk_mcp_registry_dept_id_department",
        "fk_mcp_registry_requested_by_user",
    ):
        if _has_fk(bind, TABLE_NAME, fk_name):
            op.drop_constraint(fk_name, TABLE_NAME, type_="foreignkey")
