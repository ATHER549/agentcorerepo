"""create timeout settings table

Revision ID: j7e8f9a0b1c2
Revises: i6d7e8f9a0b1
Create Date: 2026-02-20 15:20:00.000000
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "j7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "i6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_index(bind, table_name: str, index_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(idx["name"] == index_name for idx in sa.inspect(bind).get_indexes(table_name))


def _seed_defaults(bind) -> None:
    defaults = [
        {
            "setting_key": "session_timeout",
            "label": "Session Timeout",
            "value": "30",
            "unit": "min",
            "units": '["min", "hr"]',
            "description": "Session expiration duration",
            "setting_type": "input",
            "checked": None,
        },
        {
            "setting_key": "cookie_timeout",
            "label": "Cookie Timeout",
            "value": "7",
            "unit": "days",
            "units": '["days", "hr"]',
            "description": "Cookie lifetime",
            "setting_type": "input",
            "checked": None,
        },
        {
            "setting_key": "persistent_cookie",
            "label": "Persistent Cookie",
            "value": "",
            "unit": "",
            "units": "[]",
            "description": "Keep user logged in",
            "setting_type": "switch",
            "checked": True,
        },
        {
            "setting_key": "redis_ttl",
            "label": "Redis TTL",
            "value": "3600",
            "unit": "sec",
            "units": '["sec", "min"]',
            "description": "Default Redis object expiry",
            "setting_type": "input",
            "checked": None,
        },
    ]

    for item in defaults:
        exists = bind.execute(
            sa.text("SELECT 1 FROM timeout_settings WHERE setting_key = :setting_key LIMIT 1"),
            {"setting_key": item["setting_key"]},
        ).fetchone()
        if exists:
            continue

        bind.execute(
            sa.text(
                """
                INSERT INTO timeout_settings (
                    id, setting_key, label, value, unit, units, description,
                    setting_type, checked, created_at, updated_at
                ) VALUES (
                    :id, :setting_key, :label, :value, :unit, CAST(:units AS JSON), :description,
                    :setting_type, :checked, now(), now()
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "setting_key": item["setting_key"],
                "label": item["label"],
                "value": item["value"],
                "unit": item["unit"],
                "units": item["units"],
                "description": item["description"],
                "setting_type": item["setting_type"],
                "checked": item["checked"],
            },
        )


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "timeout_settings"):
        op.create_table(
            "timeout_settings",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("setting_key", sa.String(length=100), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=False),
            sa.Column("value", sa.String(length=100), nullable=True),
            sa.Column("unit", sa.String(length=20), nullable=True),
            sa.Column("units", sa.JSON(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("setting_type", sa.String(length=20), nullable=False),
            sa.Column("checked", sa.Boolean(), nullable=True),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_timeout_settings_created_by_user"),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"], name="fk_timeout_settings_updated_by_user"),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_timeout_settings")),
            sa.UniqueConstraint("setting_key", name="uq_timeout_settings_setting_key"),
        )

    if not _has_index(bind, "timeout_settings", "ix_timeout_settings_setting_key"):
        op.create_index("ix_timeout_settings_setting_key", "timeout_settings", ["setting_key"], unique=False)

    _seed_defaults(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "timeout_settings"):
        return

    if _has_index(bind, "timeout_settings", "ix_timeout_settings_setting_key"):
        op.drop_index("ix_timeout_settings_setting_key", table_name="timeout_settings")
    op.drop_table("timeout_settings")
