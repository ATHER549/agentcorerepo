"""create agent_publish_recipient table

Revision ID: m8n9o0p1q2r3
Revises: edf739ef6fa5
Create Date: 2026-03-10 14:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m8n9o0p1q2r3"
down_revision: str | Sequence[str] | None = "edf739ef6fa5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "agent_publish_recipient"):
        op.create_table(
            "agent_publish_recipient",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("agent_id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=True),
            sa.Column("dept_id", sa.Uuid(), nullable=False),
            sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
            sa.Column("recipient_email", sa.String(length=320), nullable=False),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"]),
            sa.ForeignKeyConstraint(["recipient_user_id"], ["user.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "agent_id",
                "dept_id",
                "recipient_email",
                name="uq_agent_publish_recipient_agent_dept_email",
            ),
        )

    if not _has_index(bind, "agent_publish_recipient", "ix_agent_publish_recipient_agent_id"):
        op.create_index(
            "ix_agent_publish_recipient_agent_id",
            "agent_publish_recipient",
            ["agent_id"],
            unique=False,
        )
    if not _has_index(bind, "agent_publish_recipient", "ix_agent_publish_recipient_org_id"):
        op.create_index(
            "ix_agent_publish_recipient_org_id",
            "agent_publish_recipient",
            ["org_id"],
            unique=False,
        )
    if not _has_index(bind, "agent_publish_recipient", "ix_agent_publish_recipient_dept_id"):
        op.create_index(
            "ix_agent_publish_recipient_dept_id",
            "agent_publish_recipient",
            ["dept_id"],
            unique=False,
        )
    if not _has_index(bind, "agent_publish_recipient", "ix_agent_publish_recipient_recipient_user_id"):
        op.create_index(
            "ix_agent_publish_recipient_recipient_user_id",
            "agent_publish_recipient",
            ["recipient_user_id"],
            unique=False,
        )
    if not _has_index(bind, "agent_publish_recipient", "ix_agent_publish_recipient_created_by"):
        op.create_index(
            "ix_agent_publish_recipient_created_by",
            "agent_publish_recipient",
            ["created_by"],
            unique=False,
        )
    if not _has_index(bind, "agent_publish_recipient", "ix_agent_publish_recipient_dept_email"):
        op.create_index(
            "ix_agent_publish_recipient_dept_email",
            "agent_publish_recipient",
            ["dept_id", "recipient_email"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "agent_publish_recipient"):
        return

    for index_name in (
        "ix_agent_publish_recipient_dept_email",
        "ix_agent_publish_recipient_created_by",
        "ix_agent_publish_recipient_recipient_user_id",
        "ix_agent_publish_recipient_dept_id",
        "ix_agent_publish_recipient_org_id",
        "ix_agent_publish_recipient_agent_id",
    ):
        if _has_index(bind, "agent_publish_recipient", index_name):
            op.drop_index(index_name, table_name="agent_publish_recipient")
    op.drop_table("agent_publish_recipient")
