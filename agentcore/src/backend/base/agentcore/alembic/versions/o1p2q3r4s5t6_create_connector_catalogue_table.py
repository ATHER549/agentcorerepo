"""create connector_catalogue table

Revision ID: o1p2q3r4s5t6
Revises: n2o3p4q5r6s7
Create Date: 2025-02-24 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o1p2q3r4s5t6"
down_revision: Union[str, None] = "n2o3p4q5r6s7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connector_catalogue",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("dept_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database_name", sa.String(255), nullable=False),
        sa.Column("schema_name", sa.String(255), nullable=False, server_default="public"),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("ssl_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(50), nullable=False, server_default="disconnected"),
        sa.Column("tables_metadata", sa.JSON(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_custom", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_connector_org"),
        sa.ForeignKeyConstraint(["dept_id"], ["department.id"], name="fk_connector_dept"),
        sa.ForeignKeyConstraint(
            ["org_id", "dept_id"],
            ["department.org_id", "department.id"],
            name="fk_connector_org_dept_department",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_connector_created_by"),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], name="fk_connector_updated_by"),
        sa.ForeignKeyConstraint(["published_by"], ["user.id"], name="fk_connector_published_by"),
        sa.CheckConstraint("(dept_id IS NULL) OR (org_id IS NOT NULL)", name="ck_connector_scope_consistency"),
        sa.UniqueConstraint("org_id", "dept_id", "name", name="uq_connector_catalogue_scope_name"),
    )

    op.create_index("ix_connector_catalogue_org_id", "connector_catalogue", ["org_id"])
    op.create_index("ix_connector_catalogue_dept_id", "connector_catalogue", ["dept_id"])
    op.create_index("ix_connector_catalogue_provider", "connector_catalogue", ["provider"])
    op.create_index("ix_connector_catalogue_org_dept", "connector_catalogue", ["org_id", "dept_id"])


def downgrade() -> None:
    op.drop_index("ix_connector_catalogue_org_dept", table_name="connector_catalogue")
    op.drop_index("ix_connector_catalogue_provider", table_name="connector_catalogue")
    op.drop_index("ix_connector_catalogue_dept_id", table_name="connector_catalogue")
    op.drop_index("ix_connector_catalogue_org_id", table_name="connector_catalogue")
    op.drop_table("connector_catalogue")
