"""finalize tier3 rbac schema

Revision ID: e7f8a9b0c1d2
Revises: d4e5f6a7b8c9
Create Date: 2026-02-18 00:40:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [column["name"] for column in inspector.get_columns(table_name)]


def upgrade() -> None:
    bind = op.get_bind()

    # role additions
    if _table_exists(bind, "role"):
        if not _has_column(bind, "role", "display_name"):
            op.add_column("role", sa.Column("display_name", sa.String(length=255), nullable=True))
        if not _has_column(bind, "role", "parent_role_id"):
            op.add_column("role", sa.Column("parent_role_id", sa.Uuid(), nullable=True))
            op.create_foreign_key("fk_role_parent_role_id_role", "role", "role", ["parent_role_id"], ["id"])
        if not _has_column(bind, "role", "is_active"):
            op.add_column("role", sa.Column("is_active", sa.Boolean(), nullable=True))
            bind.execute(sa.text("UPDATE role SET is_active = true WHERE is_active IS NULL"))
            with op.batch_alter_table("role") as batch_op:
                batch_op.alter_column("is_active", nullable=False)
        if not _has_column(bind, "role", "created_by"):
            op.add_column("role", sa.Column("created_by", sa.Uuid(), nullable=True))
            op.create_foreign_key("fk_role_created_by_user", "role", "user", ["created_by"], ["id"])
        if not _has_column(bind, "role", "updated_by"):
            op.add_column("role", sa.Column("updated_by", sa.Uuid(), nullable=True))
            op.create_foreign_key("fk_role_updated_by_user", "role", "user", ["updated_by"], ["id"])

    # permission additions
    if _table_exists(bind, "permission"):
        if not _has_column(bind, "permission", "category"):
            op.add_column("permission", sa.Column("category", sa.String(length=100), nullable=True))
        if not _has_column(bind, "permission", "is_system"):
            op.add_column("permission", sa.Column("is_system", sa.Boolean(), nullable=True))
            bind.execute(sa.text("UPDATE permission SET is_system = false WHERE is_system IS NULL"))
            with op.batch_alter_table("permission") as batch_op:
                batch_op.alter_column("is_system", nullable=False)
        if not _has_column(bind, "permission", "created_by"):
            op.add_column("permission", sa.Column("created_by", sa.Uuid(), nullable=True))
            op.create_foreign_key("fk_permission_created_by_user", "permission", "user", ["created_by"], ["id"])
        if not _has_column(bind, "permission", "updated_by"):
            op.add_column("permission", sa.Column("updated_by", sa.Uuid(), nullable=True))
            op.create_foreign_key("fk_permission_updated_by_user", "permission", "user", ["updated_by"], ["id"])

    # role_permission audit additions
    if _table_exists(bind, "role_permission"):
        if not _has_column(bind, "role_permission", "created_by"):
            op.add_column("role_permission", sa.Column("created_by", sa.Uuid(), nullable=True))
            op.create_foreign_key(
                "fk_role_permission_created_by_user", "role_permission", "user", ["created_by"], ["id"]
            )
        if not _has_column(bind, "role_permission", "created_at"):
            op.add_column("role_permission", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
            bind.execute(sa.text("UPDATE role_permission SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
            with op.batch_alter_table("role_permission") as batch_op:
                batch_op.alter_column("created_at", nullable=False)
        if not _has_column(bind, "role_permission", "updated_by"):
            op.add_column("role_permission", sa.Column("updated_by", sa.Uuid(), nullable=True))
            op.create_foreign_key(
                "fk_role_permission_updated_by_user", "role_permission", "user", ["updated_by"], ["id"]
            )
        if not _has_column(bind, "role_permission", "updated_at"):
            op.add_column("role_permission", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
            bind.execute(sa.text("UPDATE role_permission SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
            with op.batch_alter_table("role_permission") as batch_op:
                batch_op.alter_column("updated_at", nullable=False)

    # Seed missing roles used by the user story.
    if _table_exists(bind, "role"):
        bind.execute(
            sa.text(
                "INSERT INTO role (id, name, display_name, description, is_system, is_active, created_at, updated_at) "
                "SELECT :id, :name_val, :display_name, :description, :is_system, :is_active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM role WHERE name = :name_where)"
            ),
            {
                "id": "8e9b9f74-20b9-470f-bced-601f57f7a001",
                "name_val": "root",
                "name_where": "root",
                "display_name": "Root",
                "description": "Platform-level root administrator",
                "is_system": True,
                "is_active": True,
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO role (id, name, display_name, description, is_system, is_active, created_at, updated_at) "
                "SELECT :id, :name_val, :display_name, :description, :is_system, :is_active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM role WHERE name = :name_where)"
            ),
            {
                "id": "8e9b9f74-20b9-470f-bced-601f57f7a002",
                "name_val": "consumer",
                "name_where": "consumer",
                "display_name": "Consumer",
                "description": "Read/consume-level user",
                "is_system": True,
                "is_active": True,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "role"):
        bind.execute(sa.text("DELETE FROM role WHERE name IN ('root', 'consumer')"))

    if _table_exists(bind, "role_permission"):
        if _has_column(bind, "role_permission", "updated_at"):
            op.drop_column("role_permission", "updated_at")
        if _has_column(bind, "role_permission", "updated_by"):
            op.drop_constraint("fk_role_permission_updated_by_user", "role_permission", type_="foreignkey")
            op.drop_column("role_permission", "updated_by")
        if _has_column(bind, "role_permission", "created_at"):
            op.drop_column("role_permission", "created_at")
        if _has_column(bind, "role_permission", "created_by"):
            op.drop_constraint("fk_role_permission_created_by_user", "role_permission", type_="foreignkey")
            op.drop_column("role_permission", "created_by")

    if _table_exists(bind, "permission"):
        if _has_column(bind, "permission", "updated_by"):
            op.drop_constraint("fk_permission_updated_by_user", "permission", type_="foreignkey")
            op.drop_column("permission", "updated_by")
        if _has_column(bind, "permission", "created_by"):
            op.drop_constraint("fk_permission_created_by_user", "permission", type_="foreignkey")
            op.drop_column("permission", "created_by")
        if _has_column(bind, "permission", "is_system"):
            op.drop_column("permission", "is_system")
        if _has_column(bind, "permission", "category"):
            op.drop_column("permission", "category")

    if _table_exists(bind, "role"):
        if _has_column(bind, "role", "updated_by"):
            op.drop_constraint("fk_role_updated_by_user", "role", type_="foreignkey")
            op.drop_column("role", "updated_by")
        if _has_column(bind, "role", "created_by"):
            op.drop_constraint("fk_role_created_by_user", "role", type_="foreignkey")
            op.drop_column("role", "created_by")
        if _has_column(bind, "role", "is_active"):
            op.drop_column("role", "is_active")
        if _has_column(bind, "role", "parent_role_id"):
            op.drop_constraint("fk_role_parent_role_id_role", "role", type_="foreignkey")
            op.drop_column("role", "parent_role_id")
        if _has_column(bind, "role", "display_name"):
            op.drop_column("role", "display_name")
