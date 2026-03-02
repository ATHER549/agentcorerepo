"""drop parent_id from project

Revision ID: b1c2d3e4f5a6
Revises: a9b7c6d5e4f3
Create Date: 2026-02-17 22:40:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a9b7c6d5e4f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safe for both states:
    # - DBs that still have parent_id (drops it)
    # - fresh DBs from updated 0002 (no-op)
    op.execute(sa.text("ALTER TABLE project DROP COLUMN IF EXISTS parent_id CASCADE"))


def downgrade() -> None:
    op.add_column("project", sa.Column("parent_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_project_parent_id_project",
        "project",
        "project",
        ["parent_id"],
        ["id"],
    )
