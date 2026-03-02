"""add knowledge base table and file link

Revision ID: i6d7e8f9a0b1
Revises: g4b5c6d7e8f9, h5c6d7e8f9a0
Create Date: 2026-02-19 22:05:00.000000
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "i6d7e8f9a0b1"
down_revision: str | Sequence[str] | None = ("g4b5c6d7e8f9", "h5c6d7e8f9a0")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_table_columns(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def _has_index(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return False
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _has_fk(bind, table_name: str, fk_name: str) -> bool:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return False
    return any(fk["name"] == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("knowledge_base"):
        op.create_table(
            "knowledge_base",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("org_id", sa.Uuid(), nullable=True),
            sa.Column("dept_id", sa.Uuid(), nullable=True),
            sa.Column("created_by", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_knowledge_base_created_by_user"),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"], name="fk_knowledge_base_dept_id_department"),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_knowledge_base_org_id_organization"),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_base")),
            sa.UniqueConstraint("org_id", "dept_id", "name", name="uq_kb_org_dept_name"),
        )

    if not _has_index(bind, "knowledge_base", "ix_knowledge_base_org_id"):
        op.create_index("ix_knowledge_base_org_id", "knowledge_base", ["org_id"], unique=False)
    if not _has_index(bind, "knowledge_base", "ix_knowledge_base_dept_id"):
        op.create_index("ix_knowledge_base_dept_id", "knowledge_base", ["dept_id"], unique=False)
    if not _has_index(bind, "knowledge_base", "ix_knowledge_base_created_by"):
        op.create_index("ix_knowledge_base_created_by", "knowledge_base", ["created_by"], unique=False)

    file_columns = _get_table_columns(bind, "file")
    if "knowledge_base_id" not in file_columns:
        op.add_column("file", sa.Column("knowledge_base_id", sa.Uuid(), nullable=True))

    if not _has_index(bind, "file", "ix_file_knowledge_base_id"):
        op.create_index("ix_file_knowledge_base_id", "file", ["knowledge_base_id"], unique=False)

    if not _has_fk(bind, "file", "fk_file_knowledge_base_id_knowledge_base"):
        op.create_foreign_key(
            "fk_file_knowledge_base_id_knowledge_base",
            "file",
            "knowledge_base",
            ["knowledge_base_id"],
            ["id"],
        )

    # Backfill tenant scope on legacy file rows from memberships when missing.
    bind.execute(
        sa.text(
            """
            UPDATE file f
            SET org_id = src.org_id
            FROM (
                SELECT DISTINCT ON (user_id) user_id, org_id
                FROM user_organization_membership
                WHERE status IN ('accepted', 'active')
                ORDER BY user_id, created_at ASC, org_id ASC
            ) src
            WHERE f.user_id = src.user_id
              AND f.org_id IS NULL
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE file f
            SET dept_id = src.department_id
            FROM (
                SELECT DISTINCT ON (user_id) user_id, department_id
                FROM user_department_membership
                WHERE status = 'active'
                ORDER BY user_id, created_at ASC, department_id ASC
            ) src
            WHERE f.user_id = src.user_id
              AND f.dept_id IS NULL
            """
        )
    )

    # Create KB records from legacy file path folder convention "<user_id>/<kb_name>/<filename>".
    rows = bind.execute(
        sa.text(
            """
            SELECT DISTINCT
                split_part(split_part(path, '/', 2), '/', 1) AS kb_name,
                org_id,
                dept_id,
                user_id
            FROM file
            WHERE position('/' in path) > 0
              AND split_part(split_part(path, '/', 2), '/', 1) <> ''
            """
        )
    ).fetchall()

    for row in rows:
        kb_name, org_id, dept_id, user_id = row
        existing = bind.execute(
            sa.text(
                """
                SELECT id
                FROM knowledge_base
                WHERE name = :name
                  AND org_id IS NOT DISTINCT FROM :org_id
                  AND dept_id IS NOT DISTINCT FROM :dept_id
                LIMIT 1
                """
            ),
            {"name": kb_name, "org_id": org_id, "dept_id": dept_id},
        ).fetchone()
        if existing:
            kb_id = existing[0]
        else:
            kb_id = uuid.uuid4()
            bind.execute(
                sa.text(
                    """
                    INSERT INTO knowledge_base (id, name, org_id, dept_id, created_by, created_at, updated_at)
                    VALUES (:id, :name, :org_id, :dept_id, :created_by, now(), now())
                    """
                ),
                {
                    "id": kb_id,
                    "name": kb_name,
                    "org_id": org_id,
                    "dept_id": dept_id,
                    "created_by": user_id,
                },
            )

        bind.execute(
            sa.text(
                """
                UPDATE file
                SET knowledge_base_id = :kb_id
                WHERE knowledge_base_id IS NULL
                  AND org_id IS NOT DISTINCT FROM :org_id
                  AND dept_id IS NOT DISTINCT FROM :dept_id
                  AND split_part(split_part(path, '/', 2), '/', 1) = :kb_name
                """
            ),
            {"kb_id": kb_id, "org_id": org_id, "dept_id": dept_id, "kb_name": kb_name},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_fk(bind, "file", "fk_file_knowledge_base_id_knowledge_base"):
        op.drop_constraint("fk_file_knowledge_base_id_knowledge_base", "file", type_="foreignkey")
    if _has_index(bind, "file", "ix_file_knowledge_base_id"):
        op.drop_index("ix_file_knowledge_base_id", table_name="file")

    file_columns = _get_table_columns(bind, "file")
    if "knowledge_base_id" in file_columns:
        op.drop_column("file", "knowledge_base_id")

    inspector = sa.inspect(bind)
    if inspector.has_table("knowledge_base"):
        if _has_index(bind, "knowledge_base", "ix_knowledge_base_created_by"):
            op.drop_index("ix_knowledge_base_created_by", table_name="knowledge_base")
        if _has_index(bind, "knowledge_base", "ix_knowledge_base_dept_id"):
            op.drop_index("ix_knowledge_base_dept_id", table_name="knowledge_base")
        if _has_index(bind, "knowledge_base", "ix_knowledge_base_org_id"):
            op.drop_index("ix_knowledge_base_org_id", table_name="knowledge_base")
        op.drop_table("knowledge_base")
