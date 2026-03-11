"""drop publish_record and control_panel_uat tables

Revision ID: f3a4b5c6d7e8
Revises: e1f2a3b4c5d6
Create Date: 2026-02-19 15:05:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True) if op.get_bind().dialect.name == "postgresql" else sa.String(36)


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_sync_control_panel_uat_from_deployment ON agent_deployment_uat"))
        bind.execute(sa.text("DROP FUNCTION IF EXISTS fn_sync_control_panel_uat_from_deployment"))

    if _table_exists(bind, "control_panel_uat"):
        op.drop_table("control_panel_uat")

    if _table_exists(bind, "publish_record"):
        op.drop_table("publish_record")
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("DROP TYPE IF EXISTS publish_status_enum"))


def downgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "publish_record"):
        op.create_table(
            "publish_record",
            sa.Column("id", _uuid_type(), primary_key=True),
            sa.Column("agent_id", _uuid_type(), nullable=False),
            sa.Column("org_id", _uuid_type(), nullable=True),
            sa.Column("dept_id", _uuid_type(), nullable=True),
            sa.Column("platform", sa.String(), nullable=False),
            sa.Column("platform_url", sa.String(), nullable=False),
            sa.Column("external_id", sa.String(), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_by", _uuid_type(), nullable=False),
            sa.Column(
                "status",
                sa.Enum("ACTIVE", "UNPUBLISHED", "ERROR", "PENDING", name="publish_status_enum"),
                nullable=False,
                server_default=sa.text("'ACTIVE'"),
            ),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"]),
            sa.ForeignKeyConstraint(["published_by"], ["user.id"]),
            sa.UniqueConstraint("agent_id", "platform", "platform_url", "status", name="unique_active_publication"),
        )
        op.create_index("ix_publish_record_agent_id", "publish_record", ["agent_id"])
        op.create_index("ix_publish_record_platform", "publish_record", ["platform"])
        op.create_index("ix_publish_record_org_id", "publish_record", ["org_id"])
        op.create_index("ix_publish_record_dept_id", "publish_record", ["dept_id"])

    if not _table_exists(bind, "control_panel_uat"):
        op.create_table(
            "control_panel_uat",
            sa.Column("id", _uuid_type(), primary_key=True),
            sa.Column("deployment_id", _uuid_type(), nullable=False),
            sa.Column("agent_id", _uuid_type(), nullable=False),
            sa.Column("org_id", _uuid_type(), nullable=False),
            sa.Column("dept_id", _uuid_type(), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'PUBLISHED'")),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", _uuid_type(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_by", _uuid_type(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["deployment_id"], ["agent_deployment_uat.id"]),
            sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"]),
            sa.UniqueConstraint("deployment_id", name="uq_control_panel_uat_deployment"),
        )
        op.create_index("ix_control_panel_uat_deployment_id", "control_panel_uat", ["deployment_id"])
        op.create_index("ix_control_panel_uat_agent_id", "control_panel_uat", ["agent_id"])
        op.create_index("ix_control_panel_uat_org_id", "control_panel_uat", ["org_id"])
        op.create_index("ix_control_panel_uat_dept_id", "control_panel_uat", ["dept_id"])
        op.create_index("ix_control_panel_uat_created_by", "control_panel_uat", ["created_by"])
        op.create_index("ix_control_panel_uat_updated_by", "control_panel_uat", ["updated_by"])
        op.create_index("ix_control_panel_uat_org_dept", "control_panel_uat", ["org_id", "dept_id"])

    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "CREATE OR REPLACE FUNCTION fn_sync_control_panel_uat_from_deployment() "
                "RETURNS TRIGGER AS $$ "
                "BEGIN "
                "INSERT INTO control_panel_uat (id, deployment_id, agent_id, org_id, dept_id, status, created_by, updated_by, created_at, updated_at) "
                "VALUES (NEW.id, NEW.id, NEW.agent_id, NEW.org_id, NEW.dept_id, 'PUBLISHED', NEW.deployed_by, NEW.deployed_by, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT (deployment_id) DO NOTHING; "
                "RETURN NEW; "
                "END; "
                "$$ LANGUAGE plpgsql;"
            )
        )
        bind.execute(
            sa.text(
                "CREATE TRIGGER trg_sync_control_panel_uat_from_deployment "
                "AFTER INSERT ON agent_deployment_uat "
                "FOR EACH ROW EXECUTE FUNCTION fn_sync_control_panel_uat_from_deployment()"
            )
        )
