"""Add orchestrator chat tables: orch_conversation and orch_transaction

Revision ID: j7k8l9m0n1o2
Revises: g1h2i3j4k5l6
Create Date: 2026-02-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = "j7k8l9m0n1o2"
down_revision: Union[str, None] = "g1h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── orch_conversation ───────────────────────────────────────────────
    op.create_table(
        "orch_conversation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("sender", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sender_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=True),
        sa.Column("error", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("properties", sa.JSON(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("content_blocks", sa.JSON(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("dept_id", sa.Uuid(), nullable=True),
        sa.Column(
            "deployment_id",
            sa.Uuid(),
            sa.ForeignKey("agent_deployment_prod.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dept_id"], ["department.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orch_conversation_session", "orch_conversation", ["session_id"])
    op.create_index("ix_orch_conversation_agent", "orch_conversation", ["agent_id"])
    op.create_index("ix_orch_conversation_user", "orch_conversation", ["user_id"])
    op.create_index("ix_orch_conversation_org", "orch_conversation", ["org_id"])
    op.create_index("ix_orch_conversation_dept", "orch_conversation", ["dept_id"])
    op.create_index("ix_orch_conversation_deployment", "orch_conversation", ["deployment_id"])

    # ── orch_transaction ────────────────────────────────────────────────
    op.create_table(
        "orch_transaction",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("vertex_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("target_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=True),
        sa.Column("outputs", sa.JSON(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("dept_id", sa.Uuid(), nullable=True),
        sa.Column(
            "deployment_id",
            sa.Uuid(),
            sa.ForeignKey("agent_deployment_prod.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dept_id"], ["department.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orch_transaction_agent", "orch_transaction", ["agent_id"])
    op.create_index("ix_orch_transaction_session", "orch_transaction", ["session_id"])
    op.create_index("ix_orch_transaction_org", "orch_transaction", ["org_id"])
    op.create_index("ix_orch_transaction_dept", "orch_transaction", ["dept_id"])
    op.create_index("ix_orch_transaction_deployment", "orch_transaction", ["deployment_id"])


def downgrade() -> None:
    op.drop_table("orch_transaction")
    op.drop_table("orch_conversation")
