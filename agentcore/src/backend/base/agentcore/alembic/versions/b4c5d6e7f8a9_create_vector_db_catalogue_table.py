"""create vector db catalogue table

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-02-19 11:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True) if op.get_bind().dialect.name == "postgresql" else sa.String(36)


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    null_org_expr = "CAST(NULL AS UUID)" if bind.dialect.name == "postgresql" else "NULL"
    cast_text = "CAST(:{name} AS TEXT)" if bind.dialect.name == "postgresql" else ":{name}"
    cast_varchar_255 = "CAST(:{name} AS VARCHAR(255))" if bind.dialect.name == "postgresql" else ":{name}"
    cast_varchar_100 = "CAST(:{name} AS VARCHAR(100))" if bind.dialect.name == "postgresql" else ":{name}"
    cast_varchar_50 = "CAST(:{name} AS VARCHAR(50))" if bind.dialect.name == "postgresql" else ":{name}"
    if not _table_exists(bind, "vector_db_catalogue"):
        op.create_table(
            "vector_db_catalogue",
            sa.Column("id", _uuid_type(), primary_key=True),
            sa.Column("org_id", _uuid_type(), nullable=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("provider", sa.String(length=100), nullable=False),
            sa.Column("deployment", sa.String(length=50), nullable=False),
            sa.Column("dimensions", sa.String(length=50), nullable=False),
            sa.Column("index_type", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("vector_count", sa.String(length=50), nullable=False),
            sa.Column("is_custom", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_by", _uuid_type(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_by", _uuid_type(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"], name="fk_vector_db_catalogue_org_id_organization"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_vector_db_catalogue_created_by_user"),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"], name="fk_vector_db_catalogue_updated_by_user"),
            sa.UniqueConstraint("org_id", "name", name="uq_vector_db_catalogue_org_name"),
        )
        op.create_index("ix_vector_db_catalogue_org_id", "vector_db_catalogue", ["org_id"])
        op.create_index("ix_vector_db_catalogue_provider", "vector_db_catalogue", ["provider"])

    # Seed existing static catalogue entry as a global row (org_id = NULL).
    bind.execute(
        sa.text(
            "INSERT INTO vector_db_catalogue ("
            "id, org_id, name, description, provider, deployment, dimensions, index_type, status, vector_count, is_custom"
            ") "
            f"SELECT :id, {null_org_expr}, {cast_varchar_255.format(name='name_insert')}, "
            f"{cast_text.format(name='description')}, {cast_varchar_100.format(name='provider')}, "
            f"{cast_varchar_50.format(name='deployment')}, {cast_varchar_50.format(name='dimensions')}, "
            f"{cast_varchar_100.format(name='index_type')}, {cast_varchar_50.format(name='status')}, "
            f"{cast_varchar_50.format(name='vector_count')}, :is_custom "
            "WHERE NOT EXISTS ("
            f"SELECT 1 FROM vector_db_catalogue WHERE org_id IS NULL AND name = {cast_varchar_255.format(name='name_where')}"
            ")"
        ),
        {
            "id": "8fb5f76a-8ed0-46c9-a65b-ec5ddf949001",
            "name_insert": "Pinecone (Azure SaaS)",
            "name_where": "Pinecone (Azure SaaS)",
            "description": "Fully managed vector database from Pinecone.",
            "provider": "Pinecone",
            "deployment": "SaaS",
            "dimensions": "1536",
            "index_type": "HNSW",
            "status": "connected",
            "vector_count": "2.4M",
            "is_custom": False,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "vector_db_catalogue"):
        op.drop_index("ix_vector_db_catalogue_provider", table_name="vector_db_catalogue")
        op.drop_index("ix_vector_db_catalogue_org_id", table_name="vector_db_catalogue")
        op.drop_table("vector_db_catalogue")
