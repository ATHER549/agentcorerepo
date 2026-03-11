"""create guardrail catalogue table

Revision ID: k8f9a0b1c2d3
Revises: j7e8f9a0b1c2
Create Date: 2026-02-20 16:10:00.000000
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "k8f9a0b1c2d3"
down_revision: str | Sequence[str] | None = "j7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_index(bind, table_name: str, index_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(idx["name"] == index_name for idx in sa.inspect(bind).get_indexes(table_name))


def _seed_default_guardrail(bind) -> None:
    existing = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM guardrail_catalogue
            WHERE org_id IS NULL AND dept_id IS NULL AND name = :name
            LIMIT 1
            """
        ),
        {"name": "NeMo Guardrails"},
    ).fetchone()
    if existing:
        return

    bind.execute(
        sa.text(
            """
            INSERT INTO guardrail_catalogue (
                id, name, description, provider, category, status, rules_count, is_custom,
                org_id, dept_id, created_at, updated_at
            ) VALUES (
                :id, :name, :description, :provider, :category, :status, :rules_count, :is_custom,
                NULL, NULL, now(), now()
            )
            """
        ),
        {
            "id": uuid.uuid4(),
            "name": "NeMo Guardrails",
            "description": "NVIDIA's programmable guardrails for LLM applications with content moderation and topic control",
            "provider": "NVIDIA",
            "category": "content-safety",
            "status": "active",
            "rules_count": 12,
            "is_custom": False,
        },
    )


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "guardrail_catalogue"):
        op.create_table(
            "guardrail_catalogue",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("provider", sa.String(length=100), nullable=False),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'active'")),
            sa.Column("rules_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("is_custom", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("org_id", sa.Uuid(), nullable=True),
            sa.Column("dept_id", sa.Uuid(), nullable=True),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("published_by", sa.Uuid(), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("(dept_id IS NULL) OR (org_id IS NOT NULL)", name="ck_guardrail_scope_consistency"),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_guardrail_catalogue_org_id_organization"),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"], name="fk_guardrail_catalogue_dept_id_department"),
            sa.ForeignKeyConstraint(
                ["org_id", "dept_id"],
                ["department.org_id", "department.id"],
                name="fk_guardrail_org_dept_department",
            ),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_guardrail_catalogue_created_by_user"),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"], name="fk_guardrail_catalogue_updated_by_user"),
            sa.ForeignKeyConstraint(["published_by"], ["user.id"], name="fk_guardrail_catalogue_published_by_user"),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_guardrail_catalogue")),
            sa.UniqueConstraint("org_id", "dept_id", "name", name="uq_guardrail_scope_name"),
        )

    if not _has_index(bind, "guardrail_catalogue", "ix_guardrail_catalogue_provider"):
        op.create_index("ix_guardrail_catalogue_provider", "guardrail_catalogue", ["provider"], unique=False)
    if not _has_index(bind, "guardrail_catalogue", "ix_guardrail_catalogue_category"):
        op.create_index("ix_guardrail_catalogue_category", "guardrail_catalogue", ["category"], unique=False)
    if not _has_index(bind, "guardrail_catalogue", "ix_guardrail_catalogue_status"):
        op.create_index("ix_guardrail_catalogue_status", "guardrail_catalogue", ["status"], unique=False)
    if not _has_index(bind, "guardrail_catalogue", "ix_guardrail_org_id"):
        op.create_index("ix_guardrail_org_id", "guardrail_catalogue", ["org_id"], unique=False)
    if not _has_index(bind, "guardrail_catalogue", "ix_guardrail_dept_id"):
        op.create_index("ix_guardrail_dept_id", "guardrail_catalogue", ["dept_id"], unique=False)
    if not _has_index(bind, "guardrail_catalogue", "ix_guardrail_org_dept"):
        op.create_index("ix_guardrail_org_dept", "guardrail_catalogue", ["org_id", "dept_id"], unique=False)

    _seed_default_guardrail(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "guardrail_catalogue"):
        return

    if _has_index(bind, "guardrail_catalogue", "ix_guardrail_org_dept"):
        op.drop_index("ix_guardrail_org_dept", table_name="guardrail_catalogue")
    if _has_index(bind, "guardrail_catalogue", "ix_guardrail_dept_id"):
        op.drop_index("ix_guardrail_dept_id", table_name="guardrail_catalogue")
    if _has_index(bind, "guardrail_catalogue", "ix_guardrail_org_id"):
        op.drop_index("ix_guardrail_org_id", table_name="guardrail_catalogue")
    if _has_index(bind, "guardrail_catalogue", "ix_guardrail_catalogue_status"):
        op.drop_index("ix_guardrail_catalogue_status", table_name="guardrail_catalogue")
    if _has_index(bind, "guardrail_catalogue", "ix_guardrail_catalogue_category"):
        op.drop_index("ix_guardrail_catalogue_category", table_name="guardrail_catalogue")
    if _has_index(bind, "guardrail_catalogue", "ix_guardrail_catalogue_provider"):
        op.drop_index("ix_guardrail_catalogue_provider", table_name="guardrail_catalogue")

    op.drop_table("guardrail_catalogue")
