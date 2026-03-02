"""Restore model_registry_id on guardrail_catalogue

Revision ID: g9h0i1j2k3l4
Revises: f9d8c7b6a5e4
Create Date: 2026-02-27 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "g9h0i1j2k3l4"
down_revision: Union[str, None] = "f9d8c7b6a5e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE IF EXISTS guardrail_catalogue
            ADD COLUMN IF NOT EXISTS model_registry_id UUID;
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_guardrail_catalogue_model_registry_id
            ON guardrail_catalogue (model_registry_id);
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_guardrail_catalogue_model_registry_id_model_registry'
            ) THEN
                ALTER TABLE guardrail_catalogue
                    ADD CONSTRAINT fk_guardrail_catalogue_model_registry_id_model_registry
                    FOREIGN KEY (model_registry_id) REFERENCES model_registry (id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE IF EXISTS guardrail_catalogue
            DROP CONSTRAINT IF EXISTS fk_guardrail_catalogue_model_registry_id_model_registry;
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_guardrail_catalogue_model_registry_id;")
    op.execute("ALTER TABLE IF EXISTS guardrail_catalogue DROP COLUMN IF EXISTS model_registry_id;")
