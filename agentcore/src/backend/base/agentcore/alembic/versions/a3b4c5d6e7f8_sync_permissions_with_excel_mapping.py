"""sync permissions with excel mapping

Revision ID: a3b4c5d6e7f8
Revises: f2b3c4d5e6f7
Create Date: 2026-02-18 18:30:00.000000
"""

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSIONS = [
    ("view_dashboard", "Dashboard"),
    ("view_projects_page", "Projects"),
    ("prod_publish_approval_required", "Projects"),
    ("prod_publish_approval_not_required", "Projects"),
    ("view_approval_page", "Review & Approval"),
    ("view_agent", "Review & Approval"),
    ("view_model", "Review & Approval"),
    ("view_mcp", "Review & Approval"),
    ("view_published_agents", "Agent Registry"),
    ("copy_agents", "Agent Registry"),
    ("view_only_agent", "Agent Registry"),
    ("view_models", "Model Registry"),
    ("add_new_model", "Model Registry"),
    ("request_new_model", "Model Registry"),
    ("retire_model", "Model Registry"),
    ("view_control_panel", "Agent Control Panel"),
    ("share_agent", "Agent Control Panel"),
    ("start_stop_agent", "Agent Control Panel"),
    ("enable_disable_agent", "Agent Control Panel"),
    ("view_orchastration_page", "Orchestration Chat"),
    ("interact_agents", "Orchestration Chat"),
    ("view_observability_page", "Observability"),
    ("view_evaluation_page", "Evaluation"),
    ("view_guardrail_page", "Guardrails Catalogue"),
    ("add_guardrails", "Guardrails Catalogue"),
    ("retire_guardrails", "Guardrails Catalogue"),
    ("view_vectordb_page", "VectorDB Catalogue"),
    ("view_mcp_page", "MCP Servers"),
    ("add_new_mcp", "MCP Servers"),
    ("retire_mcp", "MCP Servers"),
    ("request_new_mcp", "MCP Servers"),
    ("view_knowledge_base", "Knowledge Base Management"),
    ("add_new_knowledge", "Knowledge Base Management"),
    ("view_platform_configs", "Platform Configurations"),
    ("edit_platform_configs", "Platform Configurations"),
    ("view_admin_page", "Admin Page"),
    ("view_access_control_page", "Access Control"),
    ("connectore_page", "Connectors"),
    ("add_connector", "Connectors"),
]

LEGACY_KEYS_TO_REMOVE = [
    "create_users",
    "manage_roles",
    "manage_users",
    "edit_projects_page",
    "view_agents_page",
    "view_knowledge_base_management",
    "approve_reject_page",
    "tbd",
    "view_published_agents_page",
    "add_guardrails",
    "view_guardrails",
    "retire_guardrails",
    "view_vector_db",
    "add_vector_db",
    "retire_vector_db",
    "add_mcp",
    "view_evaluation",
    "view_traces",
    "view_orchestrator_page",
    "view_observability_dashboard",
    "view_mcp_servers_page",
    "view_guardrails_page",
    "view_vector_db_page",
    "view_vectorDb_page",
    "view_prod",
    "prod_share_agent",
    "prod_start_stop_agent",
    "prod_enable_disable_agent",
    "view_uat",
    "uat_share_agent",
    "uat_start_stop_agent",
    "uat_enable_disable_agent",
    "view_model_catalogue_page",
    "view_agent_catalogue_page",
]


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


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


def _remove_legacy_permissions(bind) -> None:
    if not _table_exists(bind, "permission"):
        return

    permission_rows = bind.execute(
        sa.text("SELECT id FROM permission WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": LEGACY_KEYS_TO_REMOVE},
    ).fetchall()
    if not permission_rows:
        return

    permission_ids = [str(row[0]) for row in permission_rows]
    if _table_exists(bind, "role_permission"):
        bind.execute(
            sa.text("DELETE FROM role_permission WHERE permission_id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": permission_ids},
        )
    bind.execute(
        sa.text("DELETE FROM permission WHERE id IN :ids").bindparams(
            sa.bindparam("ids", expanding=True)
        ),
        {"ids": permission_ids},
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "permission"):
        return

    for key, category in PERMISSIONS:
        _upsert_permission(bind, key, category)

    _remove_legacy_permissions(bind)


def downgrade() -> None:
    # Intentionally non-destructive.
    return
