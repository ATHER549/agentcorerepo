"""merge_hitl_mcp__branches

Revision ID: 84c14b0721d8
Revises: t6u7v8w9x0y1, z1a2b3c4d5e6
Create Date: 2026-03-04 12:17:48.431132

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.engine.reflection import Inspector
from agentcore.utils import migration


# revision identifiers, used by Alembic.
revision: str = '84c14b0721d8'
down_revision: Union[str, None] = ('t6u7v8w9x0y1', 'z1a2b3c4d5e6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return column_name in [c["name"] for c in sa.inspect(bind).get_columns(table_name)]


def upgrade() -> None:
    bind = op.get_bind()

    # The migration t3u4v5w6x7y8 (simplify_connector_visibility_schema) may
    # have run before o1p2q3r4s5t6 (create_connector_catalogue_table) because
    # they are on parallel branches.  When that happens t3u4v5w6x7y8 silently
    # skips because the table does not yet exist.  Ensure the columns are
    # present now that both branches have been merged.
    if _table_exists(bind, "connector_catalogue"):
        if not _has_column(bind, "connector_catalogue", "visibility"):
            op.add_column(
                "connector_catalogue",
                sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"),
            )
        if not _has_column(bind, "connector_catalogue", "public_scope"):
            op.add_column(
                "connector_catalogue",
                sa.Column("public_scope", sa.String(length=20), nullable=True),
            )
        if not _has_column(bind, "connector_catalogue", "shared_user_ids"):
            op.add_column(
                "connector_catalogue",
                sa.Column("shared_user_ids", sa.JSON(), nullable=True),
            )
        if not _has_column(bind, "connector_catalogue", "public_dept_ids"):
            op.add_column(
                "connector_catalogue",
                sa.Column("public_dept_ids", sa.JSON(), nullable=True),
            )


def downgrade() -> None:
    pass
