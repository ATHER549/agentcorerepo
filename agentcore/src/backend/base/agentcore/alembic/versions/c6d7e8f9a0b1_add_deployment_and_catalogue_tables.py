"""add deployment and catalogue tables

Revision ID: c6d7e8f9a0b1
Revises: b4c5d6e7f8a9
Create Date: 2026-02-19 14:40:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True) if op.get_bind().dialect.name == "postgresql" else sa.String(36)


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _has_fk(bind, table_name: str, fk_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(fk.get("name") == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    # Keep imports inside upgrade to avoid polluting global SQLModel metadata during `alembic check`.
    from agentcore.services.database.models.agent_bundle.model import AgentBundle
    from agentcore.services.database.models.agent_deployment_prod.model import AgentDeploymentProd
    from agentcore.services.database.models.agent_deployment_uat.model import AgentDeploymentUAT
    from agentcore.services.database.models.agent_registry.model import AgentRegistry, AgentRegistryRating
    from agentcore.services.database.models.approval_request.model import ApprovalRequest
    from agentcore.services.database.models.conversation_prod.model import ConversationProdTable
    from agentcore.services.database.models.conversation_uat.model import ConversationUATTable
    from agentcore.services.database.models.transaction_prod.model import TransactionProdTable
    from agentcore.services.database.models.transaction_uat.model import TransactionUATTable
    managed_tables = [
        AgentDeploymentUAT.__table__,
        ApprovalRequest.__table__,
        AgentDeploymentProd.__table__,
        AgentBundle.__table__,
        AgentRegistry.__table__,
        AgentRegistryRating.__table__,
        ConversationUATTable.__table__,
        ConversationProdTable.__table__,
        TransactionUATTable.__table__,
        TransactionProdTable.__table__,
    ]

    for table in managed_tables:
        table.create(bind, checkfirst=True)

    if _table_exists(bind, "agent_deployment_uat") and not _has_column(bind, "agent_deployment_uat", "dept_id"):
        op.add_column("agent_deployment_uat", sa.Column("dept_id", _uuid_type(), nullable=True))
        if not _has_fk(bind, "agent_deployment_uat", "fk_agent_deployment_uat_dept_id_department"):
            op.create_foreign_key(
                "fk_agent_deployment_uat_dept_id_department",
                "agent_deployment_uat",
                "department",
                ["dept_id"],
                ["id"],
            )
    if _table_exists(bind, "agent_deployment_uat") and not _has_index(bind, "agent_deployment_uat", "ix_deployment_uat_dept"):
        op.create_index("ix_deployment_uat_dept", "agent_deployment_uat", ["dept_id"])

    if _table_exists(bind, "agent_deployment_prod") and not _has_column(bind, "agent_deployment_prod", "dept_id"):
        op.add_column("agent_deployment_prod", sa.Column("dept_id", _uuid_type(), nullable=True))
        if not _has_fk(bind, "agent_deployment_prod", "fk_agent_deployment_prod_dept_id_department"):
            op.create_foreign_key(
                "fk_agent_deployment_prod_dept_id_department",
                "agent_deployment_prod",
                "department",
                ["dept_id"],
                ["id"],
            )
    if _table_exists(bind, "agent_deployment_prod") and not _has_index(bind, "agent_deployment_prod", "ix_deployment_prod_dept"):
        op.create_index("ix_deployment_prod_dept", "agent_deployment_prod", ["dept_id"])

    if _table_exists(bind, "approval_request"):
        if _has_column(bind, "approval_request", "agent_publish_id") and not _has_column(bind, "approval_request", "deployment_id"):
            op.alter_column(
                "approval_request",
                "agent_publish_id",
                new_column_name="deployment_id",
                existing_type=_uuid_type(),
                existing_nullable=False,
            )
        if _has_fk(bind, "approval_request", "fk_approval_agent_publish_id"):
            op.drop_constraint("fk_approval_agent_publish_id", "approval_request", type_="foreignkey")
        if not _has_fk(bind, "approval_request", "fk_approval_deployment_id"):
            op.create_foreign_key(
                "fk_approval_deployment_id",
                "approval_request",
                "agent_deployment_prod",
                ["deployment_id"],
                ["id"],
            )
        if _has_index(bind, "approval_request", "ix_approval_agent_publish_id"):
            op.drop_index("ix_approval_agent_publish_id", table_name="approval_request")
        if not _has_index(bind, "approval_request", "ix_approval_deployment_id"):
            op.create_index("ix_approval_deployment_id", "approval_request", ["deployment_id"])
        if _has_index(bind, "approval_request", "ix_approval_reviewer_id"):
            op.drop_index("ix_approval_reviewer_id", table_name="approval_request")
        if _has_column(bind, "approval_request", "reviewer_id"):
            fk_names = [
                fk["name"]
                for fk in sa.inspect(bind).get_foreign_keys("approval_request")
                if "reviewer_id" in (fk.get("constrained_columns") or [])
            ]
            for fk_name in fk_names:
                if fk_name:
                    op.drop_constraint(fk_name, "approval_request", type_="foreignkey")
            op.drop_column("approval_request", "reviewer_id")

    if _table_exists(bind, "agent_deployment_prod") and _table_exists(bind, "approval_request"):
        if not _has_fk(bind, "agent_deployment_prod", "fk_agent_deployment_prod_approval_id"):
            op.create_foreign_key(
                "fk_agent_deployment_prod_approval_id",
                "agent_deployment_prod",
                "approval_request",
                ["approval_id"],
                ["id"],
            )

def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_sync_control_panel_uat_from_deployment ON agent_deployment_uat"))
        bind.execute(sa.text("DROP FUNCTION IF EXISTS fn_sync_control_panel_uat_from_deployment"))

    if _table_exists(bind, "approval_request"):
        if _has_column(bind, "approval_request", "deployment_id") and not _has_column(bind, "approval_request", "agent_publish_id"):
            if _has_fk(bind, "approval_request", "fk_approval_deployment_id"):
                op.drop_constraint("fk_approval_deployment_id", "approval_request", type_="foreignkey")
            op.alter_column(
                "approval_request",
                "deployment_id",
                new_column_name="agent_publish_id",
                existing_type=_uuid_type(),
                existing_nullable=False,
            )
            op.create_foreign_key(
                "fk_approval_agent_publish_id",
                "approval_request",
                "agent_deployment_prod",
                ["agent_publish_id"],
                ["id"],
            )
        if not _has_column(bind, "approval_request", "reviewer_id"):
            op.add_column("approval_request", sa.Column("reviewer_id", _uuid_type(), nullable=True))
            op.create_foreign_key("fk_approval_reviewer_id_user", "approval_request", "user", ["reviewer_id"], ["id"])
        if _has_index(bind, "approval_request", "ix_approval_deployment_id"):
            op.drop_index("ix_approval_deployment_id", table_name="approval_request")
        if not _has_index(bind, "approval_request", "ix_approval_agent_publish_id"):
            op.create_index("ix_approval_agent_publish_id", "approval_request", ["agent_publish_id"])
        if not _has_index(bind, "approval_request", "ix_approval_reviewer_id"):
            op.create_index("ix_approval_reviewer_id", "approval_request", ["reviewer_id"])

    if _table_exists(bind, "agent_deployment_prod") and _has_column(bind, "agent_deployment_prod", "dept_id"):
        if _has_fk(bind, "agent_deployment_prod", "fk_agent_deployment_prod_dept_id_department"):
            op.drop_constraint("fk_agent_deployment_prod_dept_id_department", "agent_deployment_prod", type_="foreignkey")
        if _has_index(bind, "agent_deployment_prod", "ix_deployment_prod_dept"):
            op.drop_index("ix_deployment_prod_dept", table_name="agent_deployment_prod")
        op.drop_column("agent_deployment_prod", "dept_id")

    if _table_exists(bind, "agent_deployment_uat") and _has_column(bind, "agent_deployment_uat", "dept_id"):
        if _has_fk(bind, "agent_deployment_uat", "fk_agent_deployment_uat_dept_id_department"):
            op.drop_constraint("fk_agent_deployment_uat_dept_id_department", "agent_deployment_uat", type_="foreignkey")
        if _has_index(bind, "agent_deployment_uat", "ix_deployment_uat_dept"):
            op.drop_index("ix_deployment_uat_dept", table_name="agent_deployment_uat")
        op.drop_column("agent_deployment_uat", "dept_id")
