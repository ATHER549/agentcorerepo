"""add model approval/audit tables and model_registry approval fields

Revision ID: n8m7l6k5j4h3
Revises: y8z9a0b1c2d3, z9y8x7w6v5u4
Create Date: 2026-03-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n8m7l6k5j4h3"
down_revision: str | Sequence[str] | None = ("y8z9a0b1c2d3", "z9y8x7w6v5u4")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def _has_fk(bind, table_name: str, fk_name: str) -> bool:
    return any((fk.get("name") or "") == fk_name for fk in sa.inspect(bind).get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "model_registry"):
        if not _has_column(bind, "model_registry", "source_model_id"):
            op.add_column("model_registry", sa.Column("source_model_id", sa.Uuid(), nullable=True))
        if not _has_column(bind, "model_registry", "org_id"):
            op.add_column("model_registry", sa.Column("org_id", sa.Uuid(), nullable=True))
        if not _has_column(bind, "model_registry", "dept_id"):
            op.add_column("model_registry", sa.Column("dept_id", sa.Uuid(), nullable=True))
        if not _has_column(bind, "model_registry", "created_by_id"):
            op.add_column("model_registry", sa.Column("created_by_id", sa.Uuid(), nullable=True))
        if not _has_column(bind, "model_registry", "visibility_scope"):
            op.add_column(
                "model_registry",
                sa.Column("visibility_scope", sa.String(length=20), nullable=False, server_default=sa.text("'private'")),
            )
        if not _has_column(bind, "model_registry", "approval_status"):
            op.add_column(
                "model_registry",
                sa.Column("approval_status", sa.String(length=20), nullable=False, server_default=sa.text("'approved'")),
            )
        if not _has_column(bind, "model_registry", "requested_by"):
            op.add_column("model_registry", sa.Column("requested_by", sa.Uuid(), nullable=True))
        if not _has_column(bind, "model_registry", "request_to"):
            op.add_column("model_registry", sa.Column("request_to", sa.Uuid(), nullable=True))
        if not _has_column(bind, "model_registry", "requested_at"):
            op.add_column("model_registry", sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True))
        if not _has_column(bind, "model_registry", "reviewed_at"):
            op.add_column("model_registry", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        if not _has_column(bind, "model_registry", "reviewed_by"):
            op.add_column("model_registry", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
        if not _has_column(bind, "model_registry", "review_comments"):
            op.add_column("model_registry", sa.Column("review_comments", sa.Text(), nullable=True))
        if not _has_column(bind, "model_registry", "review_attachments"):
            op.add_column("model_registry", sa.Column("review_attachments", sa.JSON(), nullable=True))

        if not _has_index(bind, "model_registry", "ix_model_registry_source_model_id"):
            op.create_index("ix_model_registry_source_model_id", "model_registry", ["source_model_id"], unique=False)
        if not _has_index(bind, "model_registry", "ix_model_registry_org_id"):
            op.create_index("ix_model_registry_org_id", "model_registry", ["org_id"], unique=False)
        if not _has_index(bind, "model_registry", "ix_model_registry_dept_id"):
            op.create_index("ix_model_registry_dept_id", "model_registry", ["dept_id"], unique=False)
        if not _has_index(bind, "model_registry", "ix_model_registry_created_by_id"):
            op.create_index("ix_model_registry_created_by_id", "model_registry", ["created_by_id"], unique=False)
        if not _has_index(bind, "model_registry", "ix_model_registry_requested_by"):
            op.create_index("ix_model_registry_requested_by", "model_registry", ["requested_by"], unique=False)
        if not _has_index(bind, "model_registry", "ix_model_registry_request_to"):
            op.create_index("ix_model_registry_request_to", "model_registry", ["request_to"], unique=False)
        if not _has_index(bind, "model_registry", "ix_model_registry_reviewed_by"):
            op.create_index("ix_model_registry_reviewed_by", "model_registry", ["reviewed_by"], unique=False)

        if not _has_fk(bind, "model_registry", "fk_model_registry_source_model_id_model_registry"):
            op.create_foreign_key(
                "fk_model_registry_source_model_id_model_registry",
                "model_registry",
                "model_registry",
                ["source_model_id"],
                ["id"],
            )
        if not _has_fk(bind, "model_registry", "fk_model_registry_org_id_organization"):
            op.create_foreign_key(
                "fk_model_registry_org_id_organization",
                "model_registry",
                "organization",
                ["org_id"],
                ["id"],
            )
        if not _has_fk(bind, "model_registry", "fk_model_registry_dept_id_department"):
            op.create_foreign_key(
                "fk_model_registry_dept_id_department",
                "model_registry",
                "department",
                ["dept_id"],
                ["id"],
            )
        if not _has_fk(bind, "model_registry", "fk_model_registry_created_by_id_user"):
            op.create_foreign_key(
                "fk_model_registry_created_by_id_user",
                "model_registry",
                "user",
                ["created_by_id"],
                ["id"],
            )
        if not _has_fk(bind, "model_registry", "fk_model_registry_requested_by_user"):
            op.create_foreign_key(
                "fk_model_registry_requested_by_user",
                "model_registry",
                "user",
                ["requested_by"],
                ["id"],
            )
        if not _has_fk(bind, "model_registry", "fk_model_registry_request_to_user"):
            op.create_foreign_key(
                "fk_model_registry_request_to_user",
                "model_registry",
                "user",
                ["request_to"],
                ["id"],
            )
        if not _has_fk(bind, "model_registry", "fk_model_registry_reviewed_by_user"):
            op.create_foreign_key(
                "fk_model_registry_reviewed_by_user",
                "model_registry",
                "user",
                ["reviewed_by"],
                ["id"],
            )

    if not _table_exists(bind, "model_approval_request"):
        op.create_table(
            "model_approval_request",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("model_id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=True),
            sa.Column("dept_id", sa.Uuid(), nullable=True),
            sa.Column("request_type", sa.String(length=20), nullable=False, server_default=sa.text("'create'")),
            sa.Column("source_environment", sa.String(length=20), nullable=False, server_default=sa.text("'test'")),
            sa.Column("target_environment", sa.String(length=20), nullable=False, server_default=sa.text("'test'")),
            sa.Column("final_target_environment", sa.String(length=20), nullable=True),
            sa.Column("visibility_requested", sa.String(length=20), nullable=False, server_default=sa.text("'private'")),
            sa.Column("requested_by", sa.Uuid(), nullable=False),
            sa.Column("request_to", sa.Uuid(), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision", sa.String(length=20), nullable=True),
            sa.Column("justification", sa.Text(), nullable=True),
            sa.Column("file_path", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["model_id"], ["model_registry.id"], name="fk_model_approval_request_model_id_model_registry"),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_model_approval_request_org_id_organization"),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"], name="fk_model_approval_request_dept_id_department"),
            sa.ForeignKeyConstraint(["requested_by"], ["user.id"], name="fk_model_approval_request_requested_by_user"),
            sa.ForeignKeyConstraint(["request_to"], ["user.id"], name="fk_model_approval_request_request_to_user"),
            sa.PrimaryKeyConstraint("id"),
        )
    elif not _has_column(bind, "model_approval_request", "final_target_environment"):
        op.add_column("model_approval_request", sa.Column("final_target_environment", sa.String(length=20), nullable=True))

    for idx_name, cols in (
        ("ix_model_approval_model_id", ["model_id"]),
        ("ix_model_approval_org", ["org_id"]),
        ("ix_model_approval_dept", ["dept_id"]),
        ("ix_model_approval_request_to_decision", ["request_to", "decision"]),
        ("ix_model_approval_requested_by_decision", ["requested_by", "decision"]),
    ):
        if _table_exists(bind, "model_approval_request") and not _has_index(bind, "model_approval_request", idx_name):
            op.create_index(idx_name, "model_approval_request", cols, unique=False)

    if not _table_exists(bind, "model_audit_log"):
        op.create_table(
            "model_audit_log",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("model_id", sa.Uuid(), nullable=True),
            sa.Column("action", sa.String(length=80), nullable=False, server_default=sa.text("'unknown'")),
            sa.Column("actor_id", sa.Uuid(), nullable=True),
            sa.Column("org_id", sa.Uuid(), nullable=True),
            sa.Column("dept_id", sa.Uuid(), nullable=True),
            sa.Column("from_environment", sa.String(length=20), nullable=True),
            sa.Column("to_environment", sa.String(length=20), nullable=True),
            sa.Column("from_visibility", sa.String(length=20), nullable=True),
            sa.Column("to_visibility", sa.String(length=20), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["model_id"], ["model_registry.id"], name="fk_model_audit_log_model_id_model_registry"),
            sa.ForeignKeyConstraint(["actor_id"], ["user.id"], name="fk_model_audit_log_actor_id_user"),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_model_audit_log_org_id_organization"),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"], name="fk_model_audit_log_dept_id_department"),
            sa.PrimaryKeyConstraint("id"),
        )

    for idx_name, cols in (
        ("ix_model_audit_log_model_id", ["model_id"]),
        ("ix_model_audit_log_actor_id", ["actor_id"]),
        ("ix_model_audit_log_org_id", ["org_id"]),
        ("ix_model_audit_log_dept_id", ["dept_id"]),
        ("ix_model_audit_action_created", ["action", "created_at"]),
        ("ix_model_audit_actor_created", ["actor_id", "created_at"]),
    ):
        if _table_exists(bind, "model_audit_log") and not _has_index(bind, "model_audit_log", idx_name):
            op.create_index(idx_name, "model_audit_log", cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "model_audit_log"):
        for idx_name in (
            "ix_model_audit_actor_created",
            "ix_model_audit_action_created",
            "ix_model_audit_log_dept_id",
            "ix_model_audit_log_org_id",
            "ix_model_audit_log_actor_id",
            "ix_model_audit_log_model_id",
        ):
            if _has_index(bind, "model_audit_log", idx_name):
                op.drop_index(idx_name, table_name="model_audit_log")
        op.drop_table("model_audit_log")

    if _table_exists(bind, "model_approval_request"):
        for idx_name in (
            "ix_model_approval_requested_by_decision",
            "ix_model_approval_request_to_decision",
            "ix_model_approval_dept",
            "ix_model_approval_org",
            "ix_model_approval_model_id",
        ):
            if _has_index(bind, "model_approval_request", idx_name):
                op.drop_index(idx_name, table_name="model_approval_request")
        op.drop_table("model_approval_request")

    if _table_exists(bind, "model_registry"):
        for fk_name in (
            "fk_model_registry_reviewed_by_user",
            "fk_model_registry_request_to_user",
            "fk_model_registry_requested_by_user",
            "fk_model_registry_created_by_id_user",
            "fk_model_registry_dept_id_department",
            "fk_model_registry_org_id_organization",
            "fk_model_registry_source_model_id_model_registry",
        ):
            if _has_fk(bind, "model_registry", fk_name):
                op.drop_constraint(fk_name, "model_registry", type_="foreignkey")

        for idx_name in (
            "ix_model_registry_reviewed_by",
            "ix_model_registry_request_to",
            "ix_model_registry_requested_by",
            "ix_model_registry_created_by_id",
            "ix_model_registry_dept_id",
            "ix_model_registry_org_id",
            "ix_model_registry_source_model_id",
        ):
            if _has_index(bind, "model_registry", idx_name):
                op.drop_index(idx_name, table_name="model_registry")

        for col_name in (
            "review_attachments",
            "review_comments",
            "reviewed_by",
            "reviewed_at",
            "requested_at",
            "request_to",
            "requested_by",
            "approval_status",
            "visibility_scope",
            "created_by_id",
            "dept_id",
            "org_id",
            "source_model_id",
        ):
            if _has_column(bind, "model_registry", col_name):
                op.drop_column("model_registry", col_name)
