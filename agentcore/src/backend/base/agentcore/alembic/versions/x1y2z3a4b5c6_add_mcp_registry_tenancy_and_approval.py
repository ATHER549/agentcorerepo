"""add tenancy and approval fields to mcp_registry

Revision ID: x1y2z3a4b5c6
Revises: w6x7y8z9a0b1
Create Date: 2026-03-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "x1y2z3a4b5c6"
down_revision: str | Sequence[str] | None = "w6x7y8z9a0b1"
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
    if not _table_exists(bind, "mcp_registry"):
        return

    if not _has_column(bind, "mcp_registry", "status"):
        op.add_column(
            "mcp_registry",
            sa.Column("status", sa.String(length=50), nullable=False, server_default="disconnected"),
        )
    if not _has_column(bind, "mcp_registry", "visibility"):
        op.add_column(
            "mcp_registry",
            sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"),
        )
    if not _has_column(bind, "mcp_registry", "public_scope"):
        op.add_column("mcp_registry", sa.Column("public_scope", sa.String(length=20), nullable=True))
    if not _has_column(bind, "mcp_registry", "public_dept_ids"):
        op.add_column("mcp_registry", sa.Column("public_dept_ids", sa.JSON(), nullable=True))
    if not _has_column(bind, "mcp_registry", "shared_user_ids"):
        op.add_column("mcp_registry", sa.Column("shared_user_ids", sa.JSON(), nullable=True))
    if not _has_column(bind, "mcp_registry", "org_id"):
        op.add_column("mcp_registry", sa.Column("org_id", sa.Uuid(), nullable=True))
    if not _has_column(bind, "mcp_registry", "dept_id"):
        op.add_column("mcp_registry", sa.Column("dept_id", sa.Uuid(), nullable=True))
    if not _has_column(bind, "mcp_registry", "approval_status"):
        op.add_column(
            "mcp_registry",
            sa.Column("approval_status", sa.String(length=20), nullable=False, server_default="approved"),
        )
    if not _has_column(bind, "mcp_registry", "requested_by"):
        op.add_column("mcp_registry", sa.Column("requested_by", sa.Uuid(), nullable=True))
    if not _has_column(bind, "mcp_registry", "request_to"):
        op.add_column("mcp_registry", sa.Column("request_to", sa.Uuid(), nullable=True))
    if not _has_column(bind, "mcp_registry", "requested_at"):
        op.add_column("mcp_registry", sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(bind, "mcp_registry", "reviewed_at"):
        op.add_column("mcp_registry", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(bind, "mcp_registry", "reviewed_by"):
        op.add_column("mcp_registry", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    if not _has_column(bind, "mcp_registry", "review_comments"):
        op.add_column("mcp_registry", sa.Column("review_comments", sa.Text(), nullable=True))
    if not _has_column(bind, "mcp_registry", "review_attachments"):
        op.add_column("mcp_registry", sa.Column("review_attachments", sa.JSON(), nullable=True))
    if not _has_column(bind, "mcp_registry", "created_by_id"):
        op.add_column("mcp_registry", sa.Column("created_by_id", sa.Uuid(), nullable=True))

    if not _has_index(bind, "mcp_registry", "ix_mcp_registry_org_id"):
        op.create_index("ix_mcp_registry_org_id", "mcp_registry", ["org_id"], unique=False)
    if not _has_index(bind, "mcp_registry", "ix_mcp_registry_dept_id"):
        op.create_index("ix_mcp_registry_dept_id", "mcp_registry", ["dept_id"], unique=False)
    if not _has_index(bind, "mcp_registry", "ix_mcp_registry_org_dept"):
        op.create_index("ix_mcp_registry_org_dept", "mcp_registry", ["org_id", "dept_id"], unique=False)
    if not _has_index(bind, "mcp_registry", "ix_mcp_registry_approval_status"):
        op.create_index("ix_mcp_registry_approval_status", "mcp_registry", ["approval_status"], unique=False)
    if not _has_index(bind, "mcp_registry", "ix_mcp_registry_requested_by"):
        op.create_index("ix_mcp_registry_requested_by", "mcp_registry", ["requested_by"], unique=False)
    if not _has_index(bind, "mcp_registry", "ix_mcp_registry_request_to"):
        op.create_index("ix_mcp_registry_request_to", "mcp_registry", ["request_to"], unique=False)
    if not _has_index(bind, "mcp_registry", "ix_mcp_registry_created_by_id"):
        op.create_index("ix_mcp_registry_created_by_id", "mcp_registry", ["created_by_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "mcp_registry"):
        return

    for idx_name in (
        "ix_mcp_registry_created_by_id",
        "ix_mcp_registry_request_to",
        "ix_mcp_registry_requested_by",
        "ix_mcp_registry_approval_status",
        "ix_mcp_registry_org_dept",
        "ix_mcp_registry_dept_id",
        "ix_mcp_registry_org_id",
    ):
        if _has_index(bind, "mcp_registry", idx_name):
            op.drop_index(idx_name, table_name="mcp_registry")

    for col_name in (
        "created_by_id",
        "review_attachments",
        "review_comments",
        "reviewed_by",
        "reviewed_at",
        "requested_at",
        "request_to",
        "requested_by",
        "approval_status",
        "dept_id",
        "org_id",
        "shared_user_ids",
        "public_dept_ids",
        "public_scope",
        "visibility",
        "status",
    ):
        if _has_column(bind, "mcp_registry", col_name):
            op.drop_column("mcp_registry", col_name)
