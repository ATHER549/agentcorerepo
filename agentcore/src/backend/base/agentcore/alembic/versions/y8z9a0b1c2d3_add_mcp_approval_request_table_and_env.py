"""add mcp approval request table and deployment env

Revision ID: y8z9a0b1c2d3
Revises: 7c8d9e0f1a2b
Create Date: 2026-03-01
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "y8z9a0b1c2d3"
down_revision: str | Sequence[str] | None = "7c8d9e0f1a2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "mcp_registry") and not _has_column(bind, "mcp_registry", "deployment_env"):
        op.add_column(
            "mcp_registry",
            sa.Column("deployment_env", sa.String(length=10), nullable=False, server_default="PROD"),
        )
    if _table_exists(bind, "mcp_registry") and not _has_index(bind, "mcp_registry", "ix_mcp_registry_deployment_env"):
        op.create_index("ix_mcp_registry_deployment_env", "mcp_registry", ["deployment_env"], unique=False)

    if not _table_exists(bind, "mcp_approval_request"):
        op.create_table(
            "mcp_approval_request",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("mcp_id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=True),
            sa.Column("dept_id", sa.Uuid(), nullable=True),
            sa.Column("requested_by", sa.Uuid(), nullable=False),
            sa.Column("request_to", sa.Uuid(), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision", sa.String(length=20), nullable=True),
            sa.Column("justification", sa.Text(), nullable=True),
            sa.Column("file_path", sa.JSON(), nullable=True),
            sa.Column("deployment_env", sa.String(length=10), nullable=False, server_default="PROD"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["mcp_id"], ["mcp_registry.id"], name="fk_mcp_approval_request_mcp_id_mcp_registry"),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_mcp_approval_request_org_id_organization"),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"], name="fk_mcp_approval_request_dept_id_department"),
            sa.ForeignKeyConstraint(["requested_by"], ["user.id"], name="fk_mcp_approval_request_requested_by_user"),
            sa.ForeignKeyConstraint(["request_to"], ["user.id"], name="fk_mcp_approval_request_request_to_user"),
            sa.PrimaryKeyConstraint("id"),
        )

    for idx_name, cols in (
        ("ix_mcp_approval_mcp_id", ["mcp_id"]),
        ("ix_mcp_approval_org", ["org_id"]),
        ("ix_mcp_approval_dept", ["dept_id"]),
        ("ix_mcp_approval_request_to_decision", ["request_to", "decision"]),
        ("ix_mcp_approval_requested_by_decision", ["requested_by", "decision"]),
    ):
        if _table_exists(bind, "mcp_approval_request") and not _has_index(bind, "mcp_approval_request", idx_name):
            op.create_index(idx_name, "mcp_approval_request", cols, unique=False)

    # Backfill existing MCP requests into the dedicated approval table.
    if _table_exists(bind, "mcp_approval_request") and _table_exists(bind, "mcp_registry"):
        existing_mcp_ids = {
            str(row[0])
            for row in bind.execute(sa.text("SELECT mcp_id FROM mcp_approval_request")).fetchall()
        }
        registry_rows = bind.execute(
            sa.text(
                """
                SELECT id, org_id, dept_id, requested_by, request_to, requested_at, reviewed_at,
                       approval_status, review_comments, review_attachments, deployment_env,
                       created_at, updated_at
                FROM mcp_registry
                WHERE requested_by IS NOT NULL AND request_to IS NOT NULL
                """
            )
        ).fetchall()
        inserts: list[dict] = []
        for row in registry_rows:
            mcp_id = str(row[0])
            if mcp_id in existing_mcp_ids:
                continue
            approval_status = str(row[7] or "pending").lower()
            decision = "APPROVED" if approval_status == "approved" else ("REJECTED" if approval_status == "rejected" else None)
            inserts.append(
                {
                    "id": uuid4(),
                    "mcp_id": row[0],
                    "org_id": row[1],
                    "dept_id": row[2],
                    "requested_by": row[3],
                    "request_to": row[4],
                    "requested_at": row[5] or row[11],
                    "reviewed_at": row[6],
                    "decision": decision,
                    "justification": row[8],
                    "file_path": row[9],
                    "deployment_env": row[10] or "PROD",
                    "created_at": row[11],
                    "updated_at": row[12],
                }
            )
        if inserts:
            mcp_approval = sa.table(
                "mcp_approval_request",
                sa.column("id", sa.Uuid()),
                sa.column("mcp_id", sa.Uuid()),
                sa.column("org_id", sa.Uuid()),
                sa.column("dept_id", sa.Uuid()),
                sa.column("requested_by", sa.Uuid()),
                sa.column("request_to", sa.Uuid()),
                sa.column("requested_at", sa.DateTime(timezone=True)),
                sa.column("reviewed_at", sa.DateTime(timezone=True)),
                sa.column("decision", sa.String(20)),
                sa.column("justification", sa.Text()),
                sa.column("file_path", sa.JSON()),
                sa.column("deployment_env", sa.String(10)),
                sa.column("created_at", sa.DateTime(timezone=True)),
                sa.column("updated_at", sa.DateTime(timezone=True)),
            )
            op.bulk_insert(mcp_approval, inserts)


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "mcp_approval_request"):
        for idx_name in (
            "ix_mcp_approval_requested_by_decision",
            "ix_mcp_approval_request_to_decision",
            "ix_mcp_approval_dept",
            "ix_mcp_approval_org",
            "ix_mcp_approval_mcp_id",
        ):
            if _has_index(bind, "mcp_approval_request", idx_name):
                op.drop_index(idx_name, table_name="mcp_approval_request")
        op.drop_table("mcp_approval_request")

    if _table_exists(bind, "mcp_registry"):
        if _has_index(bind, "mcp_registry", "ix_mcp_registry_deployment_env"):
            op.drop_index("ix_mcp_registry_deployment_env", table_name="mcp_registry")
        if _has_column(bind, "mcp_registry", "deployment_env"):
            op.drop_column("mcp_registry", "deployment_env")
