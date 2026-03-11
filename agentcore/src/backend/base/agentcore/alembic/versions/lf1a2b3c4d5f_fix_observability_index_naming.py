"""fix observability index naming and constraints

Revision ID: lf1a2b3c4d5f
Revises: lf1a2b3c4d5e
Create Date: 2026-03-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "lf1a2b3c4d5f"
down_revision: str | Sequence[str] | None = "lf1a2b3c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def _has_constraint(bind, table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(bind)
    constraints = inspector.get_unique_constraints(table_name)
    return any(c.get("name") == constraint_name for c in constraints)


def upgrade() -> None:
    bind = op.get_bind()

    # Fix langfuse_binding: remove old scope_type index
    if _table_exists(bind, "langfuse_binding"):
        if _has_index(bind, "langfuse_binding", "ix_langfuse_binding_scope_type"):
            op.drop_index("ix_langfuse_binding_scope_type", table_name="langfuse_binding")

    # Fix observability_provision_job: rename indexes and fix constraints
    if _table_exists(bind, "observability_provision_job"):
        # Remove old indexes
        old_indexes = [
            "ix_observability_job_dept_id",
            "ix_observability_job_idempotency_key",
            "ix_observability_job_org_id",
            "ix_observability_job_status",
        ]
        for idx_name in old_indexes:
            if _has_index(bind, "observability_provision_job", idx_name):
                op.drop_index(idx_name, table_name="observability_provision_job")

        # Remove old unique constraint if it exists
        if _has_constraint(bind, "observability_provision_job", "uq_observability_job_idempotency_key"):
            op.drop_constraint("uq_observability_job_idempotency_key", table_name="observability_provision_job")

        # Add new indexes with corrected names
        op.create_index(
            "ix_observability_provision_job_dept_id",
            "observability_provision_job",
            ["dept_id"],
            unique=False,
        )
        op.create_index(
            "ix_observability_provision_job_idempotency_key",
            "observability_provision_job",
            ["idempotency_key"],
            unique=True,
        )
        op.create_index(
            "ix_observability_provision_job_org_id",
            "observability_provision_job",
            ["org_id"],
            unique=False,
        )
        op.create_index(
            "ix_observability_provision_job_status",
            "observability_provision_job",
            ["status"],
            unique=False,
        )

    # Fix observability_schema_lock: remove old version_tag constraint
    if _table_exists(bind, "observability_schema_lock"):
        if _has_constraint(bind, "observability_schema_lock", "uq_observability_schema_lock_version_tag"):
            op.drop_constraint("uq_observability_schema_lock_version_tag", table_name="observability_schema_lock")


def downgrade() -> None:
    bind = op.get_bind()

    # Revert observability_schema_lock changes
    if _table_exists(bind, "observability_schema_lock"):
        if not _has_constraint(bind, "observability_schema_lock", "uq_observability_schema_lock_version_tag"):
            op.create_unique_constraint(
                "uq_observability_schema_lock_version_tag",
                "observability_schema_lock",
                ["version_tag"],
            )

    # Revert observability_provision_job changes
    if _table_exists(bind, "observability_provision_job"):
        # Remove new indexes
        new_indexes = [
            "ix_observability_provision_job_dept_id",
            "ix_observability_provision_job_idempotency_key",
            "ix_observability_provision_job_org_id",
            "ix_observability_provision_job_status",
        ]
        for idx_name in new_indexes:
            if _has_index(bind, "observability_provision_job", idx_name):
                op.drop_index(idx_name, table_name="observability_provision_job")

        # Re-add old constraint
        if not _has_constraint(bind, "observability_provision_job", "uq_observability_job_idempotency_key"):
            op.create_unique_constraint(
                "uq_observability_job_idempotency_key",
                "observability_provision_job",
                ["idempotency_key"],
            )

        # Re-add old indexes
        op.create_index(
            "ix_observability_job_idempotency_key",
            "observability_provision_job",
            ["idempotency_key"],
            unique=True,
        )
        op.create_index("ix_observability_job_status", "observability_provision_job", ["status"], unique=False)
        op.create_index("ix_observability_job_org_id", "observability_provision_job", ["org_id"], unique=False)
        op.create_index("ix_observability_job_dept_id", "observability_provision_job", ["dept_id"], unique=False)

    # Revert langfuse_binding changes
    if _table_exists(bind, "langfuse_binding"):
        if not _has_index(bind, "langfuse_binding", "ix_langfuse_binding_scope_type"):
            op.create_index("ix_langfuse_binding_scope_type", "langfuse_binding", ["scope_type"], unique=False)
