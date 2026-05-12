"""add guardrail versioning

Creates the guardrail_version table for immutable versioned snapshots.
Migrates existing prod copies from guardrail_catalogue into guardrail_version
as v1 rows, then removes the environment-separation columns from
guardrail_catalogue (environment, source_guardrail_id, promoted_at,
promoted_by, prod_ref_count). Adds latest_version column.

Revision ID: 20260511_guardrail_versioning
Revises: 20260511_scope_file
Create Date: 2026-05-11 12:00:00.000000
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

logger = logging.getLogger("alembic.migration.20260511_guardrail_versioning")


revision: str = "20260511_guardrail_versioning"
down_revision: Union[str, Sequence[str], None] = "20260511_scope_file"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_index(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _has_unique_constraint(bind, table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(uc["name"] == constraint_name for uc in inspector.get_unique_constraints(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1. Create guardrail_version table ──
    if not _table_exists(bind, "guardrail_version"):
        op.create_table(
            "guardrail_version",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("guardrail_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("dept_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("guardrail_snapshot", sa.JSON(), nullable=False),
            sa.Column("guardrail_name", sa.String(255), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("status", sa.String(50), nullable=False, server_default="PUBLISHED"),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["guardrail_id"], ["guardrail_catalogue.id"], name="fk_guardrail_version_guardrail"),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_guardrail_version_org"),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"], name="fk_guardrail_version_dept"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_guardrail_version_created_by"),
            sa.UniqueConstraint("guardrail_id", "version_number", name="uq_guardrail_version_guardrail_version"),
        )
        op.create_index("ix_guardrail_version_guardrail_id", "guardrail_version", ["guardrail_id"])
        op.create_index("ix_guardrail_version_guardrail_active", "guardrail_version", ["guardrail_id", "is_active"])
        op.create_index("ix_guardrail_version_org_id", "guardrail_version", ["org_id"])
        op.create_index("ix_guardrail_version_dept_id", "guardrail_version", ["dept_id"])
        op.create_index("ix_guardrail_version_created_by", "guardrail_version", ["created_by"])

    # ── 2. Migrate existing prod copies → guardrail_version v1 ──
    #
    # Two cases:
    #   (a) prod copy with source_guardrail_id NOT NULL — link version to source
    #       UAT row, then DELETE the prod copy row.
    #   (b) "orphan" prod row with source_guardrail_id NULL (created before
    #       env-separation rolled out) — preserve the row as the canonical
    #       guardrail and attach a v1 version pointing back at itself. Do NOT
    #       delete; once the `environment` column is dropped it just becomes a
    #       regular guardrail with an active prod version.
    if _table_exists(bind, "guardrail_catalogue") and _has_column(bind, "guardrail_catalogue", "environment"):
        # (a) linked prod copies → version row attached to source UAT row
        op.execute(
            """
            INSERT INTO guardrail_version (
                id, guardrail_id, org_id, dept_id, version_number,
                guardrail_snapshot, guardrail_name, is_active, status,
                created_by, created_at, updated_at
            )
            SELECT
                gen_random_uuid(),
                gc_prod.source_guardrail_id,
                gc_prod.org_id,
                gc_prod.dept_id,
                1,
                jsonb_build_object(
                    'name', gc_prod.name,
                    'description', gc_prod.description,
                    'framework', gc_prod.framework,
                    'provider', gc_prod.provider,
                    'model_registry_id', gc_prod.model_registry_id::text,
                    'category', gc_prod.category,
                    'status', gc_prod.status,
                    'rules_count', gc_prod.rules_count,
                    'is_custom', gc_prod.is_custom,
                    'runtime_config', gc_prod.runtime_config,
                    'visibility', gc_prod.visibility,
                    'public_scope', gc_prod.public_scope,
                    'shared_user_ids', gc_prod.shared_user_ids,
                    'public_dept_ids', gc_prod.public_dept_ids
                ),
                gc_prod.name,
                TRUE,
                'PUBLISHED',
                COALESCE(gc_prod.promoted_by, gc_prod.created_by),
                COALESCE(gc_prod.promoted_at, gc_prod.created_at),
                COALESCE(gc_prod.promoted_at, gc_prod.updated_at)
            FROM guardrail_catalogue gc_prod
            WHERE gc_prod.environment = 'prod'
              AND gc_prod.source_guardrail_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM guardrail_version gv
                  WHERE gv.guardrail_id = gc_prod.source_guardrail_id
              )
            """
        )

        # (b) orphan prod rows (no source link) → self-version
        op.execute(
            """
            INSERT INTO guardrail_version (
                id, guardrail_id, org_id, dept_id, version_number,
                guardrail_snapshot, guardrail_name, is_active, status,
                created_by, created_at, updated_at
            )
            SELECT
                gen_random_uuid(),
                gc_prod.id,
                gc_prod.org_id,
                gc_prod.dept_id,
                1,
                jsonb_build_object(
                    'name', gc_prod.name,
                    'description', gc_prod.description,
                    'framework', gc_prod.framework,
                    'provider', gc_prod.provider,
                    'model_registry_id', gc_prod.model_registry_id::text,
                    'category', gc_prod.category,
                    'status', gc_prod.status,
                    'rules_count', gc_prod.rules_count,
                    'is_custom', gc_prod.is_custom,
                    'runtime_config', gc_prod.runtime_config,
                    'visibility', gc_prod.visibility,
                    'public_scope', gc_prod.public_scope,
                    'shared_user_ids', gc_prod.shared_user_ids,
                    'public_dept_ids', gc_prod.public_dept_ids
                ),
                gc_prod.name,
                TRUE,
                'PUBLISHED',
                COALESCE(gc_prod.promoted_by, gc_prod.created_by),
                COALESCE(gc_prod.promoted_at, gc_prod.created_at),
                COALESCE(gc_prod.promoted_at, gc_prod.updated_at)
            FROM guardrail_catalogue gc_prod
            WHERE gc_prod.environment = 'prod'
              AND gc_prod.source_guardrail_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM guardrail_version gv WHERE gv.guardrail_id = gc_prod.id
              )
            """
        )

        # If an orphan prod row collides on (org_id, dept_id, name) with a
        # surviving UAT row, suffix the orphan name so the new unique
        # constraint can be created. Operators can rename later.
        op.execute(
            """
            UPDATE guardrail_catalogue gc_prod
            SET name = gc_prod.name || ' (prod-orphan)'
            WHERE gc_prod.environment = 'prod'
              AND gc_prod.source_guardrail_id IS NULL
              AND EXISTS (
                  SELECT 1 FROM guardrail_catalogue gc_uat
                  WHERE gc_uat.environment = 'uat'
                    AND gc_uat.name = gc_prod.name
                    AND gc_uat.org_id IS NOT DISTINCT FROM gc_prod.org_id
                    AND gc_uat.dept_id IS NOT DISTINCT FROM gc_prod.dept_id
              )
            """
        )

        # Convert orphans to plain rows (they survive the env drop).
        op.execute(
            """
            UPDATE guardrail_catalogue
            SET environment = 'uat'
            WHERE environment = 'prod'
              AND source_guardrail_id IS NULL
            """
        )

        # Only delete linked prod copies — and only if their version row was
        # successfully created above.
        op.execute(
            """
            DELETE FROM guardrail_catalogue gc_prod
            WHERE gc_prod.environment = 'prod'
              AND gc_prod.source_guardrail_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM guardrail_version gv
                  WHERE gv.guardrail_id = gc_prod.source_guardrail_id
              )
            """
        )

    # ── 3. Add latest_version column ──
    if not _has_column(bind, "guardrail_catalogue", "latest_version"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("latest_version", sa.Integer(), nullable=False, server_default="0"),
        )
        op.execute(
            """
            UPDATE guardrail_catalogue gc
            SET latest_version = COALESCE(
                (SELECT MAX(gv.version_number) FROM guardrail_version gv WHERE gv.guardrail_id = gc.id),
                0
            )
            """
        )
        op.alter_column("guardrail_catalogue", "latest_version", server_default=None)

    # ── 4. Drop environment-separation columns ──

    if _has_unique_constraint(bind, "guardrail_catalogue", "uq_guardrail_scope_name_env"):
        op.drop_constraint("uq_guardrail_scope_name_env", "guardrail_catalogue", type_="unique")

    if not _has_unique_constraint(bind, "guardrail_catalogue", "uq_guardrail_scope_name"):
        op.create_unique_constraint(
            "uq_guardrail_scope_name",
            "guardrail_catalogue",
            ["org_id", "dept_id", "name"],
        )

    if _has_index(bind, "guardrail_catalogue", "ix_guardrail_source_guardrail_id"):
        op.drop_index("ix_guardrail_source_guardrail_id", "guardrail_catalogue")
    if _has_index(bind, "guardrail_catalogue", "ix_guardrail_catalogue_environment"):
        op.drop_index("ix_guardrail_catalogue_environment", "guardrail_catalogue")

    for col in ("prod_ref_count", "promoted_by", "promoted_at", "source_guardrail_id", "environment"):
        if _has_column(bind, "guardrail_catalogue", col):
            op.drop_column("guardrail_catalogue", col)


def downgrade() -> None:
    bind = op.get_bind()

    if not _has_column(bind, "guardrail_catalogue", "environment"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("environment", sa.String(10), nullable=False, server_default="uat"),
        )
    if not _has_column(bind, "guardrail_catalogue", "source_guardrail_id"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("source_guardrail_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if not _has_column(bind, "guardrail_catalogue", "promoted_at"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _has_column(bind, "guardrail_catalogue", "promoted_by"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("promoted_by", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if not _has_column(bind, "guardrail_catalogue", "prod_ref_count"):
        op.add_column(
            "guardrail_catalogue",
            sa.Column("prod_ref_count", sa.Integer(), nullable=False, server_default="0"),
        )

    if _has_unique_constraint(bind, "guardrail_catalogue", "uq_guardrail_scope_name"):
        op.drop_constraint("uq_guardrail_scope_name", "guardrail_catalogue", type_="unique")
    if not _has_unique_constraint(bind, "guardrail_catalogue", "uq_guardrail_scope_name_env"):
        op.create_unique_constraint(
            "uq_guardrail_scope_name_env",
            "guardrail_catalogue",
            ["org_id", "dept_id", "name", "environment"],
        )

    if not _has_index(bind, "guardrail_catalogue", "ix_guardrail_source_guardrail_id"):
        op.create_index("ix_guardrail_source_guardrail_id", "guardrail_catalogue", ["source_guardrail_id"])
    if not _has_index(bind, "guardrail_catalogue", "ix_guardrail_catalogue_environment"):
        op.create_index("ix_guardrail_catalogue_environment", "guardrail_catalogue", ["environment"])

    # NOTE: do NOT drop the `latest_version` column or the `guardrail_version`
    # table here. The backend's startup auto-fix loop
    # (DatabaseService.try_downgrade_upgrade_until_success in
    # services/database/service.py) calls `alembic downgrade -1` + `upgrade
    # heads` whenever `alembic check` reports drift between SQLModel and the
    # DB. If that loop walks back across this migration on every restart, a
    # destructive downgrade would wipe every promoted version row and every
    # bumped latest_version counter. The previous behaviour caused prod
    # guardrails to disappear after every backend restart.
    #
    # Leaving these intact is safe: the upgrade is idempotent
    # (`_table_exists`/`_has_column` guards) so re-upgrade after this
    # no-op-downgrade just sees them already present and moves on. Operators
    # who genuinely want to roll back the schema can run the corresponding
    # drops manually.
    logger.info(
        "[GUARDRAIL_VERSIONING] downgrade: preserving guardrail_version table "
        "and latest_version column to avoid data loss on startup auto-fix."
    )
