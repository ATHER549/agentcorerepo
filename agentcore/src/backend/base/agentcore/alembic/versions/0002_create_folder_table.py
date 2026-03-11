"""Create project table (legacy folder model)

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = "b2c4e8"
down_revision: Union[str, None] = "a1b3f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("auth_settings", sa.JSON(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.UniqueConstraint("user_id", "name", name="unique_project_name"),
    )
    op.create_index(op.f("ix_project_name"), "project", ["name"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_project_name"), table_name="project")
    op.drop_table("project")
