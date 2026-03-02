"""add tenant scope columns

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-02-19 17:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True) if op.get_bind().dialect.name == "postgresql" else sa.String(36)


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def _has_index(bind, table_name: str, index_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(i["name"] == index_name for i in sa.inspect(bind).get_indexes(table_name))


def _has_fk(bind, table_name: str, fk_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(fk.get("name") == fk_name for fk in sa.inspect(bind).get_foreign_keys(table_name))


def _add_tenant_columns(bind, table_name: str, org_index: str, dept_index: Union[str, None] = None) -> None:
    if not _table_exists(bind, table_name):
        return
    if not _has_column(bind, table_name, "org_id"):
        op.add_column(table_name, sa.Column("org_id", _uuid_type(), nullable=True))
    if not _has_fk(bind, table_name, f"fk_{table_name}_org_id_organization"):
        op.create_foreign_key(
            f"fk_{table_name}_org_id_organization",
            table_name,
            "organization",
            ["org_id"],
            ["id"],
        )
    if not _has_index(bind, table_name, org_index):
        op.create_index(org_index, table_name, ["org_id"])

    if dept_index:
        if not _has_column(bind, table_name, "dept_id"):
            op.add_column(table_name, sa.Column("dept_id", _uuid_type(), nullable=True))
        if not _has_fk(bind, table_name, f"fk_{table_name}_dept_id_department"):
            op.create_foreign_key(
                f"fk_{table_name}_dept_id_department",
                table_name,
                "department",
                ["dept_id"],
                ["id"],
            )
        if not _has_index(bind, table_name, dept_index):
            op.create_index(dept_index, table_name, ["dept_id"])


def upgrade() -> None:
    bind = op.get_bind()

    _add_tenant_columns(bind, "agent", "ix_agent_org_id", "ix_agent_dept_id")
    _add_tenant_columns(bind, "file", "ix_file_org_id", "ix_file_dept_id")
    _add_tenant_columns(bind, "publish_record", "ix_publish_record_org_id", "ix_publish_record_dept_id")
    _add_tenant_columns(bind, "approval_request", "ix_approval_org", "ix_approval_dept")
    _add_tenant_columns(bind, "agent_bundle", "ix_agent_bundle_org", "ix_agent_bundle_dept")
    _add_tenant_columns(bind, "conversation", "ix_conversation_org_id", "ix_conversation_dept_id")
    _add_tenant_columns(bind, "conversation_uat", "ix_conversation_uat_org", "ix_conversation_uat_dept")
    _add_tenant_columns(bind, "conversation_prod", "ix_conversation_prod_org", "ix_conversation_prod_dept")
    _add_tenant_columns(bind, "transaction", "ix_transaction_org_id", "ix_transaction_dept_id")
    _add_tenant_columns(bind, "transaction_uat", "ix_transaction_uat_org", "ix_transaction_uat_dept")
    _add_tenant_columns(bind, "transaction_prod", "ix_transaction_prod_org", "ix_transaction_prod_dept")
    _add_tenant_columns(bind, "vertex_build", "ix_vertex_build_org_id", "ix_vertex_build_dept_id")
    _add_tenant_columns(bind, "evaluator", "ix_evaluator_org_id", "ix_evaluator_dept_id")
    _add_tenant_columns(bind, "agent_registry_rating", "ix_registry_rating_org", "ix_registry_rating_dept")

    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "UPDATE agent a "
                "SET org_id = p.org_id, dept_id = p.dept_id "
                "FROM project p WHERE a.project_id = p.id AND (a.org_id IS NULL OR a.dept_id IS NULL)"
            )
        )
        bind.execute(
            sa.text(
                "UPDATE publish_record pr "
                "SET org_id = a.org_id, dept_id = a.dept_id "
                "FROM agent a WHERE pr.agent_id = a.id AND (pr.org_id IS NULL OR pr.dept_id IS NULL)"
            )
        )
        bind.execute(
            sa.text(
                "UPDATE approval_request ar "
                "SET org_id = dp.org_id, dept_id = dp.dept_id "
                "FROM agent_deployment_prod dp "
                "WHERE ar.deployment_id = dp.id AND (ar.org_id IS NULL OR ar.dept_id IS NULL)"
            )
        )
        bind.execute(
            sa.text(
                "UPDATE agent_bundle ab "
                "SET org_id = d.org_id, dept_id = d.dept_id "
                "FROM agent_deployment_uat d "
                "WHERE ab.deployment_env = 'UAT' AND ab.deployment_id = d.id AND (ab.org_id IS NULL OR ab.dept_id IS NULL)"
            )
        )
        bind.execute(
            sa.text(
                "UPDATE agent_bundle ab "
                "SET org_id = d.org_id, dept_id = d.dept_id "
                "FROM agent_deployment_prod d "
                "WHERE ab.deployment_env = 'PROD' AND ab.deployment_id = d.id AND (ab.org_id IS NULL OR ab.dept_id IS NULL)"
            )
        )
        for table_name in ["conversation", "conversation_uat", "conversation_prod", "transaction", "transaction_uat", "transaction_prod", "vertex_build"]:
            qname = f'"{table_name}"' if table_name == "transaction" else table_name
            bind.execute(
                sa.text(
                    f"UPDATE {qname} t "
                    "SET org_id = a.org_id, dept_id = a.dept_id "
                    "FROM agent a WHERE t.agent_id = a.id AND (t.org_id IS NULL OR t.dept_id IS NULL)"
                )
            )
        bind.execute(
            sa.text(
                "UPDATE agent_registry_rating arr "
                "SET org_id = ar.org_id "
                "FROM agent_registry ar WHERE arr.registry_id = ar.id AND arr.org_id IS NULL"
            )
        )
        bind.execute(
            sa.text(
                "UPDATE file f "
                "SET org_id = udm.org_id, dept_id = udm.department_id "
                "FROM user_department_membership udm "
                "WHERE udm.user_id = f.user_id AND f.org_id IS NULL"
            )
        )
        bind.execute(
            sa.text(
                "UPDATE file f "
                "SET org_id = uom.org_id "
                "FROM user_organization_membership uom "
                "WHERE uom.user_id = f.user_id AND f.org_id IS NULL"
            )
        )
        bind.execute(
            sa.text(
                "UPDATE evaluator e "
                "SET org_id = udm.org_id, dept_id = udm.department_id "
                "FROM user_department_membership udm "
                "WHERE udm.user_id = e.user_id AND e.org_id IS NULL"
            )
        )
        bind.execute(
            sa.text(
                "UPDATE evaluator e "
                "SET org_id = uom.org_id "
                "FROM user_organization_membership uom "
                "WHERE uom.user_id = e.user_id AND e.org_id IS NULL"
            )
        )

    # Compatibility: if old index names exist from earlier local runs, replace them with model-aligned names.
    legacy_to_current = [
        ("conversation", "ix_conversation_org", "ix_conversation_org_id", ["org_id"]),
        ("conversation", "ix_conversation_dept", "ix_conversation_dept_id", ["dept_id"]),
        ("transaction", "ix_transaction_org", "ix_transaction_org_id", ["org_id"]),
        ("transaction", "ix_transaction_dept", "ix_transaction_dept_id", ["dept_id"]),
        ("vertex_build", "ix_vertex_build_org", "ix_vertex_build_org_id", ["org_id"]),
        ("vertex_build", "ix_vertex_build_dept", "ix_vertex_build_dept_id", ["dept_id"]),
    ]
    for table_name, old_idx, new_idx, columns in legacy_to_current:
        if _table_exists(bind, table_name) and _has_index(bind, table_name, old_idx) and not _has_index(bind, table_name, new_idx):
            op.drop_index(old_idx, table_name=table_name)
            op.create_index(new_idx, table_name, columns)


def downgrade() -> None:
    bind = op.get_bind()
    targets = [
        ("agent_registry_rating", "ix_registry_rating_org", "ix_registry_rating_dept"),
        ("evaluator", "ix_evaluator_org_id", "ix_evaluator_dept_id"),
        ("vertex_build", "ix_vertex_build_org_id", "ix_vertex_build_dept_id"),
        ("transaction_prod", "ix_transaction_prod_org", "ix_transaction_prod_dept"),
        ("transaction_uat", "ix_transaction_uat_org", "ix_transaction_uat_dept"),
        ("transaction", "ix_transaction_org_id", "ix_transaction_dept_id"),
        ("conversation_prod", "ix_conversation_prod_org", "ix_conversation_prod_dept"),
        ("conversation_uat", "ix_conversation_uat_org", "ix_conversation_uat_dept"),
        ("conversation", "ix_conversation_org_id", "ix_conversation_dept_id"),
        ("agent_bundle", "ix_agent_bundle_org", "ix_agent_bundle_dept"),
        ("approval_request", "ix_approval_org", "ix_approval_dept"),
        ("publish_record", "ix_publish_record_org_id", "ix_publish_record_dept_id"),
        ("file", "ix_file_org_id", "ix_file_dept_id"),
        ("agent", "ix_agent_org_id", "ix_agent_dept_id"),
    ]
    for table_name, org_idx, dept_idx in targets:
        if _table_exists(bind, table_name):
            legacy_pairs = {
                "conversation": ("ix_conversation_org", "ix_conversation_dept"),
                "transaction": ("ix_transaction_org", "ix_transaction_dept"),
                "vertex_build": ("ix_vertex_build_org", "ix_vertex_build_dept"),
            }
            if _has_fk(bind, table_name, f"fk_{table_name}_dept_id_department"):
                op.drop_constraint(f"fk_{table_name}_dept_id_department", table_name, type_="foreignkey")
            if _has_fk(bind, table_name, f"fk_{table_name}_org_id_organization"):
                op.drop_constraint(f"fk_{table_name}_org_id_organization", table_name, type_="foreignkey")
            if _has_index(bind, table_name, dept_idx):
                op.drop_index(dept_idx, table_name=table_name)
            if _has_index(bind, table_name, org_idx):
                op.drop_index(org_idx, table_name=table_name)
            if table_name in legacy_pairs:
                legacy_org, legacy_dept = legacy_pairs[table_name]
                if _has_index(bind, table_name, legacy_dept):
                    op.drop_index(legacy_dept, table_name=table_name)
                if _has_index(bind, table_name, legacy_org):
                    op.drop_index(legacy_org, table_name=table_name)
            if _has_column(bind, table_name, "dept_id"):
                op.drop_column(table_name, "dept_id")
            if _has_column(bind, table_name, "org_id"):
                op.drop_column(table_name, "org_id")
