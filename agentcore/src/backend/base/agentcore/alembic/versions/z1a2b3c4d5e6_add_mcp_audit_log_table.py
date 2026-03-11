"""add mcp_audit_log table

Revision ID: z1a2b3c4d5e6
Revises: 77540cb8b124
Create Date: 2026-03-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "z1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "77540cb8b124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "mcp_audit_log"):
        op.create_table(
            "mcp_audit_log",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("mcp_id", sa.Uuid(), nullable=True),
            sa.Column("action", sa.String(length=80), nullable=False, server_default=sa.text("'unknown'")),
            sa.Column("actor_id", sa.Uuid(), nullable=True),
            sa.Column("org_id", sa.Uuid(), nullable=True),
            sa.Column("dept_id", sa.Uuid(), nullable=True),
            sa.Column("deployment_env", sa.String(length=20), nullable=True),
            sa.Column("visibility", sa.String(length=20), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["mcp_id"], ["mcp_registry.id"], name="fk_mcp_audit_log_mcp_id_mcp_registry"),
            sa.ForeignKeyConstraint(["actor_id"], ["user.id"], name="fk_mcp_audit_log_actor_id_user"),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_mcp_audit_log_org_id_organization"),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"], name="fk_mcp_audit_log_dept_id_department"),
            sa.PrimaryKeyConstraint("id"),
        )

    for idx_name, cols in (
        ("ix_mcp_audit_log_mcp_id", ["mcp_id"]),
        ("ix_mcp_audit_log_actor_id", ["actor_id"]),
        ("ix_mcp_audit_log_org_id", ["org_id"]),
        ("ix_mcp_audit_log_dept_id", ["dept_id"]),
        ("ix_mcp_audit_action_created", ["action", "created_at"]),
        ("ix_mcp_audit_actor_created", ["actor_id", "created_at"]),
    ):
        if _table_exists(bind, "mcp_audit_log") and not _has_index(bind, "mcp_audit_log", idx_name):
            op.create_index(idx_name, "mcp_audit_log", cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "mcp_audit_log"):
        for idx_name in (
            "ix_mcp_audit_actor_created",
            "ix_mcp_audit_action_created",
            "ix_mcp_audit_log_dept_id",
            "ix_mcp_audit_log_org_id",
            "ix_mcp_audit_log_actor_id",
            "ix_mcp_audit_log_mcp_id",
        ):
            try:
                op.drop_index(idx_name, table_name="mcp_audit_log")
            except Exception:
                pass
        op.drop_table("mcp_audit_log")
