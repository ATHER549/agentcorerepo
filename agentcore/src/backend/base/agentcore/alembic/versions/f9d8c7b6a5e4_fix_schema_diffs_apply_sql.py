"""Fix schema diffs with SQL IF EXISTS/IF NOT EXISTS

Revision ID: f9d8c7b6a5e4
Revises: e43f32eb5cb1
Create Date: 2026-02-27 01:10:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f9d8c7b6a5e4"
down_revision: Union[str, None] = "e43f32eb5cb1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure enum exists
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'kb_visibility_enum') THEN
                CREATE TYPE kb_visibility_enum AS ENUM ('PRIVATE', 'DEPARTMENT', 'ORGANIZATION');
            END IF;
        END $$;
        """
    )

    # Add knowledge_base.visibility if missing
    op.execute(
        """
        ALTER TABLE IF EXISTS knowledge_base
            ADD COLUMN IF NOT EXISTS visibility kb_visibility_enum DEFAULT 'PRIVATE' NOT NULL;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_knowledge_base_visibility
            ON knowledge_base (visibility);
        """
    )

    # Create agent_edit_lock if missing
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_edit_lock (
            agent_id UUID NOT NULL,
            locked_by UUID NOT NULL,
            locked_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT pk_agent_edit_lock PRIMARY KEY (agent_id),
            CONSTRAINT fk_agent_edit_lock_agent_id_agent FOREIGN KEY (agent_id) REFERENCES agent (id),
            CONSTRAINT fk_agent_edit_lock_locked_by_user FOREIGN KEY (locked_by) REFERENCES "user" (id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_agent_edit_lock_expires_at
            ON agent_edit_lock (expires_at);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_agent_edit_lock_locked_by
            ON agent_edit_lock (locked_by);
        """
    )

    # Create teams_app if missing
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS teams_app (
            agent_id UUID NOT NULL,
            teams_app_external_id TEXT,
            bot_app_id TEXT NOT NULL,
            bot_app_secret TEXT,
            manifest_version TEXT NOT NULL,
            display_name TEXT NOT NULL,
            short_description TEXT,
            status teams_publish_status_enum DEFAULT 'DRAFT' NOT NULL,
            published_by UUID NOT NULL,
            published_at TIMESTAMP,
            last_error TEXT,
            manifest_data JSON,
            id UUID NOT NULL,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            CONSTRAINT pk_teams_app PRIMARY KEY (id),
            CONSTRAINT fk_teams_app_agent_id_agent FOREIGN KEY (agent_id) REFERENCES agent (id),
            CONSTRAINT fk_teams_app_published_by_user FOREIGN KEY (published_by) REFERENCES "user" (id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_teams_app_agent_id
            ON teams_app (agent_id);
        """
    )

    # Remove deprecated agent columns
    op.execute("ALTER TABLE IF EXISTS agent DROP COLUMN IF EXISTS action_description;")
    op.execute("ALTER TABLE IF EXISTS agent DROP COLUMN IF EXISTS action_name;")
    op.execute("ALTER TABLE IF EXISTS agent DROP COLUMN IF EXISTS mcp_enabled;")

    # Keep guardrail_catalogue.model_registry_id intact.
    # This linkage is required to preserve guardrail runtime completeness across reloads.
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
    # Best-effort rollback (no-op for safety in this environment)
    pass
