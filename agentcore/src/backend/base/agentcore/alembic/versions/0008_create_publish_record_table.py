"""Create publish_record table

Revision ID: 0008
Revises: 0007
Create Date: 2026-02-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = "b8c1f5"
down_revision: Union[str, None] = "a7b9e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the enum type idempotently (handles leftover types from failed migrations)
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE publish_status_enum AS ENUM ('ACTIVE', 'UNPUBLISHED', 'ERROR', 'PENDING'); "
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$;"
    ))

    op.create_table(
        "publish_record",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("platform_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("external_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("published_by", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("metadata_", sa.JSON(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["published_by"], ["user.id"]),
        sa.UniqueConstraint("agent_id", "platform", "platform_url", "status", name="unique_active_publication"),
    )
    # Cast to proper PostgreSQL enum type (drop default first — PG can't auto-cast text default to enum)
    op.execute(sa.text("ALTER TABLE publish_record ALTER COLUMN status DROP DEFAULT"))
    op.execute(sa.text(
        "ALTER TABLE publish_record ALTER COLUMN status TYPE publish_status_enum "
        "USING status::publish_status_enum"
    ))
    op.execute(sa.text("ALTER TABLE publish_record ALTER COLUMN status SET DEFAULT 'ACTIVE'"))
    op.create_index(op.f("ix_publish_record_agent_id"), "publish_record", ["agent_id"], unique=False)
    op.create_index(op.f("ix_publish_record_platform"), "publish_record", ["platform"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_publish_record_platform"), table_name="publish_record")
    op.drop_index(op.f("ix_publish_record_agent_id"), table_name="publish_record")
    op.drop_table("publish_record")
    op.execute(sa.text("DROP TYPE IF EXISTS publish_status_enum"))
