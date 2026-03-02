"""Backfill model_registry_id for existing guardrails

Revision ID: h1i2j3k4l5m6
Revises: g9h0i1j2k3l4
Create Date: 2026-02-28 12:45:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "h1i2j3k4l5m6"
down_revision: Union[str, None] = "g9h0i1j2k3l4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Backfill model_registry_id for guardrails that have NULL values.
    
    For each guardrail with NULL model_registry_id, find the first active model
    from model_registry that matches the guardrail's provider.
    """
    op.execute(
        """
        UPDATE guardrail_catalogue gc
        SET model_registry_id = subq.model_id
        FROM (
            SELECT DISTINCT ON (gc2.id)
                gc2.id as guardrail_id,
                mr.id as model_id
            FROM guardrail_catalogue gc2
            INNER JOIN model_registry mr ON gc2.provider = mr.provider
            WHERE gc2.model_registry_id IS NULL
                AND mr.is_active = true
            ORDER BY gc2.id, mr.created_at ASC
        ) subq
        WHERE gc.id = subq.guardrail_id;
        """
    )


def downgrade() -> None:
    """No downgrade - data migration."""
    pass
