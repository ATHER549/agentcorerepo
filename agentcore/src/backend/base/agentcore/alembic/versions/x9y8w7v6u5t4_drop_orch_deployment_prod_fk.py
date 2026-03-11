"""Drop PROD-only FK on orch_conversation and orch_transaction deployment_id.

Both tables now store UAT and PROD deployment IDs, so the foreign key
constraint to agent_deployment_prod alone is incorrect.

Revision ID: x9y8w7v6u5t4
Revises: u7v8w9x0y1z2
Create Date: 2026-03-10

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "x9y8w7v6u5t4"
down_revision = "u7v8w9x0y1z2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop FK on orch_conversation.deployment_id -> agent_deployment_prod
    op.drop_constraint(
        "fk_orch_conversation_deployment_id_agent_deployment_prod",
        "orch_conversation",
        type_="foreignkey",
    )

    # Drop FK on orch_transaction.deployment_id -> agent_deployment_prod
    op.drop_constraint(
        "fk_orch_transaction_deployment_id_agent_deployment_prod",
        "orch_transaction",
        type_="foreignkey",
    )


def downgrade() -> None:
    op.create_foreign_key(
        "fk_orch_conversation_deployment_id_agent_deployment_prod",
        "orch_conversation",
        "agent_deployment_prod",
        ["deployment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_orch_transaction_deployment_id_agent_deployment_prod",
        "orch_transaction",
        "agent_deployment_prod",
        ["deployment_id"],
        ["id"],
        ondelete="SET NULL",
    )
