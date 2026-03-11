"""add langfuse observability binding/provision tables

Revision ID: lf1a2b3c4d5e
Revises: m1n2o3p4q5r8, c2e5756285b4, 77540cb8b124, c9d2f6, d1e2f3a4b5c6
Create Date: 2026-03-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "lf1a2b3c4d5e"
down_revision: str | Sequence[str] | None = (
    "m1n2o3p4q5r8",
    "c2e5756285b4",
    "77540cb8b124",
    "c9d2f6",
    "d1e2f3a4b5c6",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "langfuse_binding"):
        op.create_table(
            "langfuse_binding",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("dept_id", sa.Uuid(), nullable=True),
            sa.Column("scope_type", sa.String(length=32), nullable=False),
            sa.Column("langfuse_org_id", sa.String(length=255), nullable=False),
            sa.Column("langfuse_project_id", sa.String(length=255), nullable=False),
            sa.Column("langfuse_project_name", sa.String(length=255), nullable=True),
            sa.Column("langfuse_host", sa.String(length=512), nullable=False),
            sa.Column("public_key_encrypted", sa.Text(), nullable=False),
            sa.Column("secret_key_encrypted", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_langfuse_binding_org_id_organization"),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"], name="fk_langfuse_binding_dept_id_department"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_langfuse_binding_created_by_user"),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"], name="fk_langfuse_binding_updated_by_user"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_langfuse_binding_org_id", "langfuse_binding", ["org_id"], unique=False)
        op.create_index("ix_langfuse_binding_dept_id", "langfuse_binding", ["dept_id"], unique=False)
        op.create_index("ix_langfuse_binding_scope_type", "langfuse_binding", ["scope_type"], unique=False)
        op.create_index("ix_langfuse_binding_langfuse_org_id", "langfuse_binding", ["langfuse_org_id"], unique=False)
        op.create_index(
            "ix_langfuse_binding_langfuse_project_id",
            "langfuse_binding",
            ["langfuse_project_id"],
            unique=False,
        )

    if _table_exists(bind, "langfuse_binding"):
        if not _has_index(bind, "langfuse_binding", "ix_langfuse_binding_active_org_admin"):
            op.create_index(
                "ix_langfuse_binding_active_org_admin",
                "langfuse_binding",
                ["org_id"],
                unique=True,
                postgresql_where=sa.text("scope_type = 'org_admin' AND is_active = true"),
            )
        if not _has_index(bind, "langfuse_binding", "ix_langfuse_binding_active_department"):
            op.create_index(
                "ix_langfuse_binding_active_department",
                "langfuse_binding",
                ["dept_id"],
                unique=True,
                postgresql_where=sa.text("scope_type = 'department' AND dept_id IS NOT NULL AND is_active = true"),
            )

    if not _table_exists(bind, "observability_provision_job"):
        op.create_table(
            "observability_provision_job",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("idempotency_key", sa.String(length=255), nullable=False),
            sa.Column("scope_type", sa.String(length=32), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=True),
            sa.Column("dept_id", sa.Uuid(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("payload_hash", sa.String(length=255), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_observability_job_org_id_organization"),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"], name="fk_observability_job_dept_id_department"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_observability_job_created_by_user"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key", name="uq_observability_job_idempotency_key"),
        )
        op.create_index(
            "ix_observability_job_idempotency_key",
            "observability_provision_job",
            ["idempotency_key"],
            unique=True,
        )
        op.create_index("ix_observability_job_status", "observability_provision_job", ["status"], unique=False)
        op.create_index("ix_observability_job_org_id", "observability_provision_job", ["org_id"], unique=False)
        op.create_index("ix_observability_job_dept_id", "observability_provision_job", ["dept_id"], unique=False)

    if not _table_exists(bind, "observability_schema_lock"):
        op.create_table(
            "observability_schema_lock",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("version_tag", sa.String(length=128), nullable=False),
            sa.Column("schema_fingerprint", sa.String(length=128), nullable=False),
            sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("version_tag", name="uq_observability_schema_lock_version_tag"),
        )
        op.create_index(
            "ix_observability_schema_lock_version_tag",
            "observability_schema_lock",
            ["version_tag"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "observability_schema_lock"):
        if _has_index(bind, "observability_schema_lock", "ix_observability_schema_lock_version_tag"):
            op.drop_index("ix_observability_schema_lock_version_tag", table_name="observability_schema_lock")
        op.drop_table("observability_schema_lock")

    if _table_exists(bind, "observability_provision_job"):
        for idx_name in (
            "ix_observability_job_dept_id",
            "ix_observability_job_org_id",
            "ix_observability_job_status",
            "ix_observability_job_idempotency_key",
        ):
            if _has_index(bind, "observability_provision_job", idx_name):
                op.drop_index(idx_name, table_name="observability_provision_job")
        op.drop_table("observability_provision_job")

    if _table_exists(bind, "langfuse_binding"):
        for idx_name in (
            "ix_langfuse_binding_active_department",
            "ix_langfuse_binding_active_org_admin",
            "ix_langfuse_binding_langfuse_project_id",
            "ix_langfuse_binding_langfuse_org_id",
            "ix_langfuse_binding_scope_type",
            "ix_langfuse_binding_dept_id",
            "ix_langfuse_binding_org_id",
        ):
            if _has_index(bind, "langfuse_binding", idx_name):
                op.drop_index(idx_name, table_name="langfuse_binding")
        op.drop_table("langfuse_binding")

