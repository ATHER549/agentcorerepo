"""create release management tables

Revision ID: r9t0u1v2w3x4
Revises: abc123merge01
Create Date: 2026-03-10 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "r9t0u1v2w3x4"
down_revision: Union[str, Sequence[str], None] = "abc123merge01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_release",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("major", sa.Integer(), nullable=False),
        sa.Column("minor", sa.Integer(), nullable=False),
        sa.Column("patch", sa.Integer(), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_product_release_created_by_user"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("major", "minor", "patch", name="uq_product_release_semver"),
    )
    with op.batch_alter_table("product_release", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_product_release_version"), ["version"], unique=True)
        batch_op.create_index(batch_op.f("ix_product_release_start_date"), ["start_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_product_release_end_date"), ["end_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_product_release_created_by"), ["created_by"], unique=False)

    op.create_table(
        "release_package_snapshot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("version_spec", sa.String(length=255), nullable=True),
        sa.Column("package_type", sa.String(length=20), nullable=False),
        sa.Column("required_by", sa.JSON(), nullable=True),
        sa.Column("source", sa.JSON(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"], ["product_release.id"], name="fk_release_package_snapshot_release_id_product_release"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "release_id",
            "name",
            "package_type",
            name="uq_release_package_snapshot_release_name_type",
        ),
    )
    with op.batch_alter_table("release_package_snapshot", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_release_package_snapshot_release_id"), ["release_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_release_package_snapshot_name"), ["name"], unique=False)
        batch_op.create_index(batch_op.f("ix_release_package_snapshot_package_type"), ["package_type"], unique=False)

    with op.batch_alter_table("package", schema=None) as batch_op:
        batch_op.add_column(sa.Column("release_id", sa.Uuid(), nullable=True))
        batch_op.create_index(batch_op.f("ix_package_release_id"), ["release_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_package_release_id_product_release",
            "product_release",
            ["release_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("package", schema=None) as batch_op:
        batch_op.drop_constraint("fk_package_release_id_product_release", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_package_release_id"))
        batch_op.drop_column("release_id")

    with op.batch_alter_table("release_package_snapshot", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_release_package_snapshot_package_type"))
        batch_op.drop_index(batch_op.f("ix_release_package_snapshot_name"))
        batch_op.drop_index(batch_op.f("ix_release_package_snapshot_release_id"))
    op.drop_table("release_package_snapshot")

    with op.batch_alter_table("product_release", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_product_release_created_by"))
        batch_op.drop_index(batch_op.f("ix_product_release_end_date"))
        batch_op.drop_index(batch_op.f("ix_product_release_start_date"))
        batch_op.drop_index(batch_op.f("ix_product_release_version"))
    op.drop_table("product_release")
