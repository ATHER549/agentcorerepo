"""create trigger_config and trigger_execution_log tables

Revision ID: p2q3r4s5t6u7
Revises: 17b99611cc4e
Create Date: 2026-02-25 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p2q3r4s5t6u7"
down_revision: str | Sequence[str] | None = "17b99611cc4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    # ── trigger_config ────────────────────────────────────────────────────
    if not _table_exists(bind, "trigger_config"):
        op.create_table(
            "trigger_config",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("agent_id", sa.Uuid(), nullable=False),
            sa.Column("deployment_id", sa.Uuid(), nullable=True),
            sa.Column(
                "trigger_type",
                sa.Enum("schedule", "folder_monitor", name="trigger_type_enum"),
                nullable=False,
            ),
            sa.Column("trigger_config", sa.JSON(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("environment", sa.String(10), nullable=False, server_default="dev"),
            sa.Column("version", sa.String(20), nullable=True),
            sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("trigger_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_by", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_trigger_config_agent"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_trigger_config_created_by"),
        )

        op.create_index("ix_trigger_config_agent", "trigger_config", ["agent_id"])
        op.create_index("ix_trigger_config_agent_id", "trigger_config", ["agent_id"])
        op.create_index("ix_trigger_config_type", "trigger_config", ["trigger_type"])
        op.create_index("ix_trigger_config_active", "trigger_config", ["is_active"])
        op.create_index("ix_trigger_config_env", "trigger_config", ["environment"])
        op.create_index("ix_trigger_config_created_by", "trigger_config", ["created_by"])
        op.create_index("ix_trigger_config_deployment_id", "trigger_config", ["deployment_id"])

    # ── trigger_execution_log ─────────────────────────────────────────────
    if not _table_exists(bind, "trigger_execution_log"):
        op.create_table(
            "trigger_execution_log",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("trigger_config_id", sa.Uuid(), nullable=False),
            sa.Column("agent_id", sa.Uuid(), nullable=False),
            sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column(
                "status",
                sa.Enum("started", "success", "error", name="trigger_execution_status_enum"),
                nullable=False,
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("execution_duration_ms", sa.Integer(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["trigger_config_id"], ["trigger_config.id"], name="fk_trigger_exec_config"
            ),
        )

        op.create_index("ix_trigger_exec_config", "trigger_execution_log", ["trigger_config_id"])
        op.create_index("ix_trigger_exec_agent", "trigger_execution_log", ["agent_id"])
        op.create_index("ix_trigger_exec_status", "trigger_execution_log", ["status"])
        op.create_index("ix_trigger_exec_triggered_at", "trigger_execution_log", ["triggered_at"])
        op.create_index("ix_trigger_execution_log_agent_id", "trigger_execution_log", ["agent_id"])
        op.create_index("ix_trigger_execution_log_trigger_config_id", "trigger_execution_log", ["trigger_config_id"])


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "trigger_execution_log"):
        op.drop_index("ix_trigger_exec_triggered_at", table_name="trigger_execution_log")
        op.drop_index("ix_trigger_exec_status", table_name="trigger_execution_log")
        op.drop_index("ix_trigger_exec_agent", table_name="trigger_execution_log")
        op.drop_index("ix_trigger_exec_config", table_name="trigger_execution_log")
        op.drop_table("trigger_execution_log")

    if _table_exists(bind, "trigger_config"):
        op.drop_index("ix_trigger_config_env", table_name="trigger_config")
        op.drop_index("ix_trigger_config_active", table_name="trigger_config")
        op.drop_index("ix_trigger_config_type", table_name="trigger_config")
        op.drop_index("ix_trigger_config_agent", table_name="trigger_config")
        op.drop_table("trigger_config")

    # Drop the enum types
    sa.Enum(name="trigger_execution_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="trigger_type_enum").drop(op.get_bind(), checkfirst=True)
