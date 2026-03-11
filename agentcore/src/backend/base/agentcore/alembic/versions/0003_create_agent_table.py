"""Create agent table

Revision ID: 0003
Revises: 0002
Create Date: 2026-02-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = "c3d5a9"
down_revision: Union[str, None] = "b2c4e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the enum type idempotently (handles leftover types from failed migrations)
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE access_type_enum AS ENUM ('PRIVATE', 'PUBLIC'); "
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$;"
    ))

    op.create_table(
        "agent",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("icon_bg_color", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("gradient", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("is_component", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column("webhook", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("endpoint_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("locked", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("mcp_enabled", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("action_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("action_description", sa.Text(), nullable=True),
        sa.Column("access_type", sa.Text(), nullable=False, server_default=sa.text("'PRIVATE'")),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("fs_path", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.UniqueConstraint("user_id", "name", name="unique_agent_name"),
        sa.UniqueConstraint("user_id", "endpoint_name", name="unique_agent_endpoint_name"),
    )
    # Cast to proper PostgreSQL enum type (drop default first — PG can't auto-cast text default to enum)
    op.execute(sa.text("ALTER TABLE agent ALTER COLUMN access_type DROP DEFAULT"))
    op.execute(sa.text(
        "ALTER TABLE agent ALTER COLUMN access_type TYPE access_type_enum "
        "USING access_type::access_type_enum"
    ))
    op.execute(sa.text("ALTER TABLE agent ALTER COLUMN access_type SET DEFAULT 'PRIVATE'"))
    op.create_index(op.f("ix_agent_name"), "agent", ["name"], unique=False)
    op.create_index(op.f("ix_agent_description"), "agent", ["description"], unique=False)
    op.create_index(op.f("ix_agent_endpoint_name"), "agent", ["endpoint_name"], unique=False)
    op.create_index(op.f("ix_agent_user_id"), "agent", ["user_id"], unique=False)
    op.create_index(op.f("ix_agent_project_id"), "agent", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_project_id"), table_name="agent")
    op.drop_index(op.f("ix_agent_user_id"), table_name="agent")
    op.drop_index(op.f("ix_agent_endpoint_name"), table_name="agent")
    op.drop_index(op.f("ix_agent_description"), table_name="agent")
    op.drop_index(op.f("ix_agent_name"), table_name="agent")
    op.drop_table("agent")
    op.execute(sa.text("DROP TYPE IF EXISTS access_type_enum"))
