"""remove knowledge base permissions from consumer role

Revision ID: q0r1s2t3u4v5
Revises: p9q0r1s2t3u4
Create Date: 2026-03-07 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "q0r1s2t3u4v5"
down_revision: str | Sequence[str] | None = "p9q0r1s2t3u4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


REMOVE_KEYS = ("view_knowledge_base", "add_new_knowledge")


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "role") or not _table_exists(bind, "permission") or not _table_exists(bind, "role_permission"):
        return

    role_row = bind.execute(
        sa.text("SELECT id FROM role WHERE name = :name"),
        {"name": "consumer"},
    ).fetchone()
    if not role_row:
        return

    role_id = str(role_row[0])
    perm_rows = bind.execute(
        sa.text("SELECT id FROM permission WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": list(REMOVE_KEYS)},
    ).fetchall()
    if not perm_rows:
        return

    perm_ids = [str(row[0]) for row in perm_rows]
    bind.execute(
        sa.text(
            "DELETE FROM role_permission "
            "WHERE role_id = :role_id AND permission_id IN :permission_ids"
        ).bindparams(sa.bindparam("permission_ids", expanding=True)),
        {"role_id": role_id, "permission_ids": perm_ids},
    )


def downgrade() -> None:
    # Intentionally non-destructive.
    return
