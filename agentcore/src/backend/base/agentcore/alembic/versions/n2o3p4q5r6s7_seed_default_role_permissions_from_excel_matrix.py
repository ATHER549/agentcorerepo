"""seed default role permissions from provided excel matrix

Revision ID: n2o3p4q5r6s7
Revises: m1n2o3p4q5r6
Create Date: 2026-02-23 20:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "n2o3p4q5r6s7"
down_revision: str | Sequence[str] | None = "m1n2o3p4q5r6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "root": [
        "view_dashboard",
        "view_projects_page",
        "prod_publish_approval_required",
        "prod_publish_approval_not_required",
        "view_approval_page",
        "view_agent",
        "view_model",
        "view_mcp",
        "view_published_agents",
        "copy_agents",
        "view_only_agent",
        "view_models",
        "add_new_model",
        "request_new_model",
        "retire_model",
        "view_control_panel",
        "share_agent",
        "start_stop_agent",
        "enable_disable_agent",
        "view_orchastration_page",
        "interact_agents",
        "view_observability_page",
        "view_evaluation_page",
        "view_guardrail_page",
        "add_guardrails",
        "retire_guardrails",
        "view_vectordb_page",
        "view_mcp_page",
        "add_new_mcp",
        "retire_mcp",
        "request_new_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "view_platform_configs",
        "edit_platform_configs",
        "view_admin_page",
        "view_access_control_page",
        "connectore_page",
        "add_connector",
    ],
    "super_admin": [
        "view_dashboard",
        "view_projects_page",
        "prod_publish_approval_not_required",
        "view_approval_page",
        "view_agent",
        "view_model",
        "view_mcp",
        "view_published_agents",
        "copy_agents",
        "view_only_agent",
        "view_models",
        "add_new_model",
        "retire_model",
        "view_control_panel",
        "share_agent",
        "start_stop_agent",
        "enable_disable_agent",
        "view_orchastration_page",
        "interact_agents",
        "view_observability_page",
        "view_evaluation_page",
        "view_guardrail_page",
        "add_guardrails",
        "retire_guardrails",
        "view_vectordb_page",
        "view_mcp_page",
        "add_new_mcp",
        "retire_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "view_admin_page",
        "connectore_page",
        "add_connector",
    ],
    "department_admin": [
        "view_dashboard",
        "view_projects_page",
        "prod_publish_approval_not_required",
        "view_approval_page",
        "view_agent",
        "view_model",
        "view_mcp",
        "view_published_agents",
        "copy_agents",
        "view_only_agent",
        "view_models",
        "add_new_model",
        "retire_model",
        "view_control_panel",
        "share_agent",
        "start_stop_agent",
        "enable_disable_agent",
        "view_orchastration_page",
        "interact_agents",
        "view_observability_page",
        "view_evaluation_page",
        "view_guardrail_page",
        "add_guardrails",
        "retire_guardrails",
        "view_vectordb_page",
        "view_mcp_page",
        "add_new_mcp",
        "retire_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "view_admin_page",
        "connectore_page",
        "add_connector",
    ],
    "developer": [
        "view_dashboard",
        "view_projects_page",
        "prod_publish_approval_required",
        "view_published_agents",
        "copy_agents",
        "view_only_agent",
        "view_models",
        "request_new_model",
        "view_control_panel",
        "start_stop_agent",
        "view_orchastration_page",
        "interact_agents",
        "view_observability_page",
        "view_evaluation_page",
        "view_guardrail_page",
        "view_vectordb_page",
        "view_mcp_page",
        "request_new_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "connectore_page",
        "add_connector",
    ],
    "business_user": [
        "view_dashboard",
        "view_projects_page",
        "prod_publish_approval_required",
        "view_published_agents",
        "copy_agents",
        "view_only_agent",
        "view_models",
        "request_new_model",
        "view_control_panel",
        "start_stop_agent",
        "view_orchastration_page",
        "interact_agents",
        "view_observability_page",
        "view_evaluation_page",
        "view_guardrail_page",
        "view_vectordb_page",
        "view_mcp_page",
        "request_new_mcp",
        "view_knowledge_base",
        "add_new_knowledge",
        "connectore_page",
        "add_connector",
    ],
    "consumer": [
        "view_published_agents",
        "view_only_agent",
        "view_orchastration_page",
        "interact_agents",
        "view_knowledge_base",
        "add_new_knowledge",
    ],
}


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "role") or not _table_exists(bind, "permission") or not _table_exists(bind, "role_permission"):
        return

    role_names = list(DEFAULT_ROLE_PERMISSIONS.keys())
    permission_keys = sorted({key for keys in DEFAULT_ROLE_PERMISSIONS.values() for key in keys})

    role_rows = bind.execute(
        sa.text("SELECT id, name FROM role WHERE name IN :names").bindparams(
            sa.bindparam("names", expanding=True)
        ),
        {"names": role_names},
    ).fetchall()
    role_id_by_name = {str(row[1]): str(row[0]) for row in role_rows}

    permission_rows = bind.execute(
        sa.text("SELECT id, key FROM permission WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": permission_keys},
    ).fetchall()
    permission_id_by_key = {str(row[1]): str(row[0]) for row in permission_rows}

    has_created_at = _has_column(bind, "role_permission", "created_at")
    has_updated_at = _has_column(bind, "role_permission", "updated_at")

    for role_name, role_permission_keys in DEFAULT_ROLE_PERMISSIONS.items():
        role_id = role_id_by_name.get(role_name)
        if not role_id:
            continue

        bind.execute(
            sa.text("DELETE FROM role_permission WHERE role_id = :role_id"),
            {"role_id": role_id},
        )

        for permission_key in role_permission_keys:
            permission_id = permission_id_by_key.get(permission_key)
            if not permission_id:
                continue

            insert_cols = ["id", "role_id", "permission_id"]
            insert_vals = [":id", ":role_id", ":permission_id"]
            if has_created_at:
                insert_cols.append("created_at")
                insert_vals.append("CURRENT_TIMESTAMP")
            if has_updated_at:
                insert_cols.append("updated_at")
                insert_vals.append("CURRENT_TIMESTAMP")

            bind.execute(
                sa.text(
                    f"INSERT INTO role_permission ({', '.join(insert_cols)}) "
                    f"VALUES ({', '.join(insert_vals)})"
                ),
                {
                    "id": str(uuid4()),
                    "role_id": role_id,
                    "permission_id": permission_id,
                },
            )


def downgrade() -> None:
    pass
