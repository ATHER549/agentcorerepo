"""Touch project.updated_at when agents change.

Revision ID: p0q1r2s3t4u5
Revises: b0c1d2e3f4g5
Create Date: 2026-03-11
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "p0q1r2s3t4u5"
down_revision = "b0c1d2e3f4g5"
branch_labels = None
depends_on = None


TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION touch_project_updated_at_from_agent()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.project_id IS NOT NULL THEN
            UPDATE project SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.project_id;
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        IF OLD.project_id IS NOT NULL THEN
            UPDATE project SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.project_id;
        END IF;
        RETURN OLD;
    ELSIF TG_OP = 'UPDATE' THEN
        IF NEW.project_id IS DISTINCT FROM OLD.project_id THEN
            IF OLD.project_id IS NOT NULL THEN
                UPDATE project SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.project_id;
            END IF;
            IF NEW.project_id IS NOT NULL THEN
                UPDATE project SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.project_id;
            END IF;
        ELSIF NEW.project_id IS NOT NULL THEN
            UPDATE project SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.project_id;
        END IF;
        RETURN NEW;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


TRIGGER_CREATE_SQL = """
DROP TRIGGER IF EXISTS touch_project_updated_at_from_agent ON agent;
CREATE TRIGGER touch_project_updated_at_from_agent
AFTER INSERT OR UPDATE OR DELETE ON agent
FOR EACH ROW EXECUTE FUNCTION touch_project_updated_at_from_agent();
"""


TRIGGER_DROP_SQL = """
DROP TRIGGER IF EXISTS touch_project_updated_at_from_agent ON agent;
DROP FUNCTION IF EXISTS touch_project_updated_at_from_agent();
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(TRIGGER_FUNCTION_SQL)
    op.execute(TRIGGER_CREATE_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(TRIGGER_DROP_SQL)
