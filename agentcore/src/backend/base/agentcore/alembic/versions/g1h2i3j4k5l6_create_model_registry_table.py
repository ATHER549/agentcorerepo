"""create model_registry table

Revision ID: g1h2i3j4k5l6
Revises: i6d7e8f9a0b1
Create Date: 2026-02-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, None] = "i6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=True),
        sa.Column("api_key_secret_ref", sa.Text(), nullable=True),
        sa.Column("environment", sa.String(), nullable=False, server_default=sa.text("'test'")),
        sa.Column("provider_config", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("capabilities", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("default_params", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_registry_provider", "model_registry", ["provider"])
    op.create_index("ix_model_registry_environment", "model_registry", ["environment"])


def downgrade() -> None:
    op.drop_index("ix_model_registry_environment", table_name="model_registry")
    op.drop_index("ix_model_registry_provider", table_name="model_registry")
    op.drop_table("model_registry")
