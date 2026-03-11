"""Add deployment architecture: org/dept/project + deployment tables + approval

Revision ID: 0009
Revises: 0007
Create Date: 2026-02-12

Changes:
  - user table: add department_name, department_admin, created_by, country
  - agent table: add org_id, dept_id, project_id, lifecycle_status,
                 cloned_from_deployment_id, deleted_at
  - New enum types for deployment, organization, department, project, lifecycle, etc.
  - New tables: organization, department, project
  - New tables: approval_request
  - New tables: agent_deployment_uat, agent_deployment_prod
  - New tables: agent_bundle, agent_registry
  - New tables: conversation_uat, conversation_prod, transaction_uat, transaction_prod
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = "c9d2f6"
down_revision: Union[str, None] = "a7b9e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def upgrade() -> None:
    bind = op.get_bind()
    # ===================================================================
    # 1. Create enum types (idempotent)
    # ===================================================================
    enums = [
        ("approval_decision_enum", "'APPROVED', 'REJECTED', 'CANCELLED'"),
        ("org_tier_enum", "'free', 'standard', 'enterprise'"),
        ("org_status_enum", "'active', 'suspended', 'deleted'"),
        ("dept_status_enum", "'active', 'archived'"),
        ("project_status_enum", "'active', 'archived', 'deleted'"),
        ("lifecycle_status_enum", "'DRAFT', 'PENDING_APPROVAL', 'PUBLISHED', 'DEPRECATED', 'ARCHIVED'"),
        ("deployment_uat_status_enum", "'PUBLISHED', 'UNPUBLISHED', 'ERROR'"),
        ("deployment_visibility_enum", "'PUBLIC', 'PRIVATE'"),
        ("deployment_lifecycle_enum", "'DRAFT', 'PUBLISHED', 'DEPRECATED', 'ARCHIVED'"),
        ("deployment_prod_status_enum", "'PENDING_APPROVAL', 'PUBLISHED', 'UNPUBLISHED', 'ERROR'"),
        ("prod_deployment_visibility_enum", "'PUBLIC', 'PRIVATE'"),
        ("prod_deployment_lifecycle_enum", "'DRAFT', 'PUBLISHED', 'DEPRECATED', 'ARCHIVED'"),
        ("deployment_env_enum", "'UAT', 'PROD'"),
        ("bundle_type_enum", "'model', 'mcp_server', 'guardrail', 'knowledge_base', 'vector_db', 'connector', 'tool', 'custom_component'"),
        ("registry_visibility_enum", "'PUBLIC', 'PRIVATE'"),
        ("registry_deployment_env_enum", "'UAT', 'PROD'"),
    ]
    for name, values in enums:
        op.execute(sa.text(
            f"DO $$ BEGIN "
            f"CREATE TYPE {name} AS ENUM ({values}); "
            f"EXCEPTION WHEN duplicate_object THEN null; "
            f"END $$;"
        ))

    # ===================================================================
    # 2. Add new columns to existing 'user' table
    #    Using IF NOT EXISTS to handle branch-merge scenarios where
    #    another migration branch may have already added some columns.
    # ===================================================================
    op.execute(sa.text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS department_name VARCHAR(255)'))
    op.execute(sa.text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS department_admin UUID'))
    op.execute(sa.text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS created_by UUID'))
    op.execute(sa.text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS country VARCHAR(100)'))

    # Foreign keys for new user columns (idempotent)
    op.execute(sa.text(
        "DO $$ BEGIN "
        'ALTER TABLE "user" ADD CONSTRAINT fk_user_department_admin '
        'FOREIGN KEY (department_admin) REFERENCES "user"(id); '
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$;"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        'ALTER TABLE "user" ADD CONSTRAINT fk_user_created_by '
        'FOREIGN KEY (created_by) REFERENCES "user"(id); '
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$;"
    ))

    # Index on country for multi-tenancy queries (idempotent)
    op.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_user_country ON "user" (country)'))
    op.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_user_department_name ON "user" (department_name)'))

    # Merged-history safety:
    # If organization already exists, equivalent tenancy/deployment schema has already been
    # introduced by another migration branch. Skip the legacy bootstrap in this revision.
    if _table_exists(bind, "organization"):
        return

    # ===================================================================
    # 3. Create 'organization' table
    # ===================================================================
    if not _table_exists(bind, "organization"):
        op.create_table(
            "organization",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("tier", sa.Text(), nullable=False, server_default=sa.text("'standard'")),
            sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
            sa.Column("owner_user_id", sa.Uuid(), nullable=False),
            sa.Column("created_by", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["owner_user_id"], ["user.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"]),
        )

        op.execute(sa.text(
            "ALTER TABLE organization ALTER COLUMN tier DROP DEFAULT; "
            "ALTER TABLE organization ALTER COLUMN tier TYPE org_tier_enum USING tier::org_tier_enum; "
            "ALTER TABLE organization ALTER COLUMN tier SET DEFAULT 'standard';"
        ))
        op.execute(sa.text(
            "ALTER TABLE organization ALTER COLUMN status DROP DEFAULT; "
            "ALTER TABLE organization ALTER COLUMN status TYPE org_status_enum USING status::org_status_enum; "
            "ALTER TABLE organization ALTER COLUMN status SET DEFAULT 'active';"
        ))

        op.create_index("ix_organization_name", "organization", ["name"], unique=True)

    # ===================================================================
    # 4. Create 'department' table
    # ===================================================================
    if not _table_exists(bind, "department"):
        op.create_table(
            "department",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("code", sa.String(length=50), nullable=True),
            sa.Column("parent_dept_id", sa.Uuid(), nullable=True),
            sa.Column("admin_user_id", sa.Uuid(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
            sa.Column("created_by", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
            sa.ForeignKeyConstraint(["parent_dept_id"], ["department.id"]),
            sa.ForeignKeyConstraint(["admin_user_id"], ["user.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"]),
            sa.UniqueConstraint("org_id", "name", name="uq_department_org_name"),
        )

        op.execute(sa.text(
            "ALTER TABLE department ALTER COLUMN status DROP DEFAULT; "
            "ALTER TABLE department ALTER COLUMN status TYPE dept_status_enum USING status::dept_status_enum; "
            "ALTER TABLE department ALTER COLUMN status SET DEFAULT 'active';"
        ))

        op.create_index("ix_department_org_id", "department", ["org_id"], unique=False)
        op.create_index("ix_department_admin_user_id", "department", ["admin_user_id"], unique=False)

    # ===================================================================
    # 5. Create 'project' table
    # ===================================================================
    if not _table_exists(bind, "project"):
        op.create_table(
            "project",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("org_id", sa.Uuid(), nullable=False),
            sa.Column("dept_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("parent_project_id", sa.Uuid(), nullable=True),
            sa.Column("owner_user_id", sa.Uuid(), nullable=False),
            sa.Column("tags", sa.JSON(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
            sa.Column("created_by", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
            sa.ForeignKeyConstraint(["dept_id"], ["department.id"]),
            sa.ForeignKeyConstraint(["parent_project_id"], ["project.id"]),
            sa.ForeignKeyConstraint(["owner_user_id"], ["user.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"]),
            sa.UniqueConstraint("dept_id", "name", name="uq_project_dept_name"),
        )

        op.execute(sa.text(
            "ALTER TABLE project ALTER COLUMN status DROP DEFAULT; "
            "ALTER TABLE project ALTER COLUMN status TYPE project_status_enum USING status::project_status_enum; "
            "ALTER TABLE project ALTER COLUMN status SET DEFAULT 'active';"
        ))

        op.create_index("ix_project_org_id", "project", ["org_id"], unique=False)
        op.create_index("ix_project_dept_id", "project", ["dept_id"], unique=False)
        op.create_index("ix_project_name", "project", ["name"], unique=False)
        op.create_index("ix_project_owner_user_id", "project", ["owner_user_id"], unique=False)

    # ===================================================================
    # 6. Create 'approval_request' table
    #    (created BEFORE agent_deployment_prod because prod has FK to it;
    #     deferred FK from approval_request → agent_deployment_prod added later)
    # ===================================================================
    op.create_table(
        "approval_request",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("agent_publish_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("request_to", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("visibility_requested", sa.Text(), nullable=False, server_default=sa.text("'PRIVATE'")),
        sa.Column("publish_description", sa.Text(), nullable=True),
        sa.Column("file_path", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["user.id"]),
        sa.ForeignKeyConstraint(["request_to"], ["user.id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["user.id"]),
    )

    # Cast decision to enum type
    op.execute(sa.text(
        "ALTER TABLE approval_request ALTER COLUMN decision TYPE approval_decision_enum "
        "USING decision::approval_decision_enum"
    ))

    # Cast visibility_requested to prod_deployment_visibility_enum
    op.execute(sa.text("ALTER TABLE approval_request ALTER COLUMN visibility_requested DROP DEFAULT"))
    op.execute(sa.text(
        "ALTER TABLE approval_request ALTER COLUMN visibility_requested TYPE prod_deployment_visibility_enum "
        "USING visibility_requested::prod_deployment_visibility_enum"
    ))
    op.execute(sa.text("ALTER TABLE approval_request ALTER COLUMN visibility_requested SET DEFAULT 'PRIVATE'"))

    # Indexes for approval_request
    op.create_index("ix_approval_request_to_decision", "approval_request", ["request_to", "decision"], unique=False)
    op.create_index("ix_approval_requested_by_decision", "approval_request", ["requested_by", "decision"], unique=False)
    op.create_index("ix_approval_reviewer_id", "approval_request", ["reviewer_id"], unique=False)
    op.create_index("ix_approval_agent_publish_id", "approval_request", ["agent_publish_id"], unique=False)

    # ===================================================================
    # 7. Create 'agent_deployment_uat' table
    # ===================================================================
    op.create_table(
        "agent_deployment_uat",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("agent_snapshot", sa.JSON(), nullable=False),
        sa.Column("agent_name", sa.String(length=255), nullable=False),
        sa.Column("agent_description", sa.Text(), nullable=True),
        sa.Column("publish_description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'PUBLISHED'")),
        sa.Column("lifecycle_step", sa.Text(), nullable=False, server_default=sa.text("'PUBLISHED'")),
        sa.Column("visibility", sa.Text(), nullable=False, server_default=sa.text("'PRIVATE'")),
        sa.Column("deployed_by", sa.Uuid(), nullable=False),
        sa.Column("deployed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["deployed_by"], ["user.id"]),
        sa.UniqueConstraint("agent_id", "version_number", name="uq_deployment_uat_agent_version"),
    )

    # Cast enum columns
    op.execute(sa.text(
        "ALTER TABLE agent_deployment_uat ALTER COLUMN status DROP DEFAULT; "
        "ALTER TABLE agent_deployment_uat ALTER COLUMN status TYPE deployment_uat_status_enum "
        "USING status::deployment_uat_status_enum; "
        "ALTER TABLE agent_deployment_uat ALTER COLUMN status SET DEFAULT 'PUBLISHED';"
    ))
    op.execute(sa.text(
        "ALTER TABLE agent_deployment_uat ALTER COLUMN lifecycle_step DROP DEFAULT; "
        "ALTER TABLE agent_deployment_uat ALTER COLUMN lifecycle_step TYPE deployment_lifecycle_enum "
        "USING lifecycle_step::deployment_lifecycle_enum; "
        "ALTER TABLE agent_deployment_uat ALTER COLUMN lifecycle_step SET DEFAULT 'PUBLISHED';"
    ))
    op.execute(sa.text(
        "ALTER TABLE agent_deployment_uat ALTER COLUMN visibility DROP DEFAULT; "
        "ALTER TABLE agent_deployment_uat ALTER COLUMN visibility TYPE deployment_visibility_enum "
        "USING visibility::deployment_visibility_enum; "
        "ALTER TABLE agent_deployment_uat ALTER COLUMN visibility SET DEFAULT 'PRIVATE';"
    ))

    op.create_index("ix_agent_deployment_uat_agent_id", "agent_deployment_uat", ["agent_id"], unique=False)
    op.create_index("ix_agent_deployment_uat_org_id", "agent_deployment_uat", ["org_id"], unique=False)
    op.create_index("ix_agent_deployment_uat_deployed_by", "agent_deployment_uat", ["deployed_by"], unique=False)
    op.create_index("ix_deployment_uat_status", "agent_deployment_uat", ["status"], unique=False)
    op.create_index("ix_deployment_uat_agent_active", "agent_deployment_uat", ["agent_id", "is_active"], unique=False)
    op.create_index("ix_deployment_uat_org", "agent_deployment_uat", ["org_id"], unique=False)
    op.create_index("ix_deployment_uat_lifecycle", "agent_deployment_uat", ["lifecycle_step"], unique=False)

    # ===================================================================
    # 8. Create 'agent_deployment_prod' table
    # ===================================================================
    op.create_table(
        "agent_deployment_prod",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("promoted_from_uat_id", sa.Uuid(), nullable=True),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("agent_snapshot", sa.JSON(), nullable=False),
        sa.Column("agent_name", sa.String(length=255), nullable=False),
        sa.Column("agent_description", sa.Text(), nullable=True),
        sa.Column("publish_description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'PENDING_APPROVAL'")),
        sa.Column("lifecycle_step", sa.Text(), nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("visibility", sa.Text(), nullable=False, server_default=sa.text("'PRIVATE'")),
        sa.Column("deployed_by", sa.Uuid(), nullable=False),
        sa.Column("deployed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["promoted_from_uat_id"], ["agent_deployment_uat.id"]),
        sa.ForeignKeyConstraint(["approval_id"], ["approval_request.id"]),
        sa.ForeignKeyConstraint(["deployed_by"], ["user.id"]),
        sa.UniqueConstraint("agent_id", "version_number", name="uq_deployment_prod_agent_version"),
    )

    # Cast enum columns
    op.execute(sa.text(
        "ALTER TABLE agent_deployment_prod ALTER COLUMN status DROP DEFAULT; "
        "ALTER TABLE agent_deployment_prod ALTER COLUMN status TYPE deployment_prod_status_enum "
        "USING status::deployment_prod_status_enum; "
        "ALTER TABLE agent_deployment_prod ALTER COLUMN status SET DEFAULT 'PENDING_APPROVAL';"
    ))
    op.execute(sa.text(
        "ALTER TABLE agent_deployment_prod ALTER COLUMN lifecycle_step DROP DEFAULT; "
        "ALTER TABLE agent_deployment_prod ALTER COLUMN lifecycle_step TYPE prod_deployment_lifecycle_enum "
        "USING lifecycle_step::prod_deployment_lifecycle_enum; "
        "ALTER TABLE agent_deployment_prod ALTER COLUMN lifecycle_step SET DEFAULT 'DRAFT';"
    ))
    op.execute(sa.text(
        "ALTER TABLE agent_deployment_prod ALTER COLUMN visibility DROP DEFAULT; "
        "ALTER TABLE agent_deployment_prod ALTER COLUMN visibility TYPE prod_deployment_visibility_enum "
        "USING visibility::prod_deployment_visibility_enum; "
        "ALTER TABLE agent_deployment_prod ALTER COLUMN visibility SET DEFAULT 'PRIVATE';"
    ))

    op.create_index("ix_agent_deployment_prod_agent_id", "agent_deployment_prod", ["agent_id"], unique=False)
    op.create_index("ix_agent_deployment_prod_org_id", "agent_deployment_prod", ["org_id"], unique=False)
    op.create_index("ix_agent_deployment_prod_deployed_by", "agent_deployment_prod", ["deployed_by"], unique=False)
    op.create_index("ix_agent_deployment_prod_promoted_from_uat_id", "agent_deployment_prod", ["promoted_from_uat_id"], unique=False)
    op.create_index("ix_agent_deployment_prod_approval_id", "agent_deployment_prod", ["approval_id"], unique=False)
    op.create_index("ix_deployment_prod_status", "agent_deployment_prod", ["status"], unique=False)
    op.create_index("ix_deployment_prod_agent_active", "agent_deployment_prod", ["agent_id", "is_active"], unique=False)
    op.create_index("ix_deployment_prod_org", "agent_deployment_prod", ["org_id"], unique=False)
    op.create_index("ix_deployment_prod_lifecycle", "agent_deployment_prod", ["lifecycle_step"], unique=False)
    op.create_index("ix_deployment_prod_approval", "agent_deployment_prod", ["approval_id"], unique=False)

    # ===================================================================
    # 9. Add deferred FK: approval_request.agent_publish_id → agent_deployment_prod.id
    # ===================================================================
    op.create_foreign_key(
        "fk_approval_agent_publish_id",
        "approval_request", "agent_deployment_prod",
        ["agent_publish_id"], ["id"],
    )

    # ===================================================================
    # 10. Create 'agent_bundle' table
    # ===================================================================
    op.create_table(
        "agent_bundle",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("deployment_id", sa.Uuid(), nullable=False),
        sa.Column("deployment_env", sa.Text(), nullable=False),
        sa.Column("bundle_type", sa.Text(), nullable=False),
        sa.Column("resource_name", sa.String(length=255), nullable=False),
        sa.Column("resource_config", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
    )

    op.execute(sa.text(
        "ALTER TABLE agent_bundle ALTER COLUMN deployment_env TYPE deployment_env_enum "
        "USING deployment_env::deployment_env_enum;"
    ))
    op.execute(sa.text(
        "ALTER TABLE agent_bundle ALTER COLUMN bundle_type TYPE bundle_type_enum "
        "USING bundle_type::bundle_type_enum;"
    ))

    op.create_index("ix_agent_bundle_agent_id", "agent_bundle", ["agent_id"], unique=False)
    op.create_index("ix_agent_bundle_deployment_id", "agent_bundle", ["deployment_id"], unique=False)
    op.create_index("ix_agent_bundle_created_by", "agent_bundle", ["created_by"], unique=False)
    op.create_index("ix_agent_bundle_deployment", "agent_bundle", ["deployment_id", "deployment_env"], unique=False)
    op.create_index("ix_agent_bundle_type", "agent_bundle", ["bundle_type"], unique=False)
    op.create_index("ix_agent_bundle_agent", "agent_bundle", ["agent_id"], unique=False)

    # ===================================================================
    # 11. Create 'agent_registry' table
    # ===================================================================
    op.create_table(
        "agent_registry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("agent_deployment_id", sa.Uuid(), nullable=False),
        sa.Column("deployment_env", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("visibility", sa.Text(), nullable=False, server_default=sa.text("'PRIVATE'")),
        sa.Column("listed_by", sa.Uuid(), nullable=False),
        sa.Column("listed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["listed_by"], ["user.id"]),
        sa.UniqueConstraint("agent_deployment_id", "deployment_env", name="uq_registry_deployment"),
    )

    op.execute(sa.text(
        "ALTER TABLE agent_registry ALTER COLUMN deployment_env TYPE registry_deployment_env_enum "
        "USING deployment_env::registry_deployment_env_enum;"
    ))
    op.execute(sa.text(
        "ALTER TABLE agent_registry ALTER COLUMN visibility DROP DEFAULT; "
        "ALTER TABLE agent_registry ALTER COLUMN visibility TYPE registry_visibility_enum "
        "USING visibility::registry_visibility_enum; "
        "ALTER TABLE agent_registry ALTER COLUMN visibility SET DEFAULT 'PRIVATE';"
    ))

    op.create_index("ix_agent_registry_agent_id", "agent_registry", ["agent_id"], unique=False)
    op.create_index("ix_agent_registry_agent_deployment_id", "agent_registry", ["agent_deployment_id"], unique=False)
    op.create_index("ix_agent_registry_org_id", "agent_registry", ["org_id"], unique=False)
    op.create_index("ix_agent_registry_listed_by", "agent_registry", ["listed_by"], unique=False)
    op.create_index("ix_agent_registry_org", "agent_registry", ["org_id"], unique=False)
    op.create_index("ix_agent_registry_visibility", "agent_registry", ["visibility"], unique=False)
    op.create_index("ix_agent_registry_deployment", "agent_registry", ["agent_deployment_id", "deployment_env"], unique=False)

    # ===================================================================
    # 12. Create 'conversation_uat' table
    # ===================================================================
    op.create_table(
        "conversation_uat",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("sender", sa.String(), nullable=False),
        sa.Column("sender_name", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("error", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("deployment_id", sa.Uuid(), nullable=True),
        sa.Column("files", sa.JSON(), nullable=True),
        sa.Column("properties", sa.JSON(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("content_blocks", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["deployment_id"], ["agent_deployment_uat.id"]),
    )

    op.create_index("ix_conversation_uat_session", "conversation_uat", ["session_id"], unique=False)
    op.create_index("ix_conversation_uat_agent_id", "conversation_uat", ["agent_id"], unique=False)
    op.create_index("ix_conversation_uat_deployment_id", "conversation_uat", ["deployment_id"], unique=False)
    op.create_index("ix_conversation_uat_agent", "conversation_uat", ["agent_id"], unique=False)
    op.create_index("ix_conversation_uat_deployment", "conversation_uat", ["deployment_id"], unique=False)

    # ===================================================================
    # 13. Create 'conversation_prod' table
    # ===================================================================
    op.create_table(
        "conversation_prod",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("sender", sa.String(), nullable=False),
        sa.Column("sender_name", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("error", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("deployment_id", sa.Uuid(), nullable=True),
        sa.Column("files", sa.JSON(), nullable=True),
        sa.Column("properties", sa.JSON(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("content_blocks", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["deployment_id"], ["agent_deployment_prod.id"]),
    )

    op.create_index("ix_conversation_prod_session", "conversation_prod", ["session_id"], unique=False)
    op.create_index("ix_conversation_prod_agent_id", "conversation_prod", ["agent_id"], unique=False)
    op.create_index("ix_conversation_prod_deployment_id", "conversation_prod", ["deployment_id"], unique=False)
    op.create_index("ix_conversation_prod_agent", "conversation_prod", ["agent_id"], unique=False)
    op.create_index("ix_conversation_prod_deployment", "conversation_prod", ["deployment_id"], unique=False)

    # ===================================================================
    # 14. Create 'transaction_uat' table
    # ===================================================================
    op.create_table(
        "transaction_uat",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("vertex_id", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=True),
        sa.Column("outputs", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("deployment_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["deployment_id"], ["agent_deployment_uat.id"]),
    )

    op.create_index("ix_transaction_uat_agent", "transaction_uat", ["agent_id"], unique=False)
    op.create_index("ix_transaction_uat_deployment", "transaction_uat", ["deployment_id"], unique=False)
    op.create_index("ix_transaction_uat_deployment_id", "transaction_uat", ["deployment_id"], unique=False)

    # ===================================================================
    # 15. Create 'transaction_prod' table
    # ===================================================================
    op.create_table(
        "transaction_prod",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("vertex_id", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=True),
        sa.Column("outputs", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("deployment_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["deployment_id"], ["agent_deployment_prod.id"]),
    )

    op.create_index("ix_transaction_prod_agent", "transaction_prod", ["agent_id"], unique=False)
    op.create_index("ix_transaction_prod_deployment", "transaction_prod", ["deployment_id"], unique=False)
    op.create_index("ix_transaction_prod_deployment_id", "transaction_prod", ["deployment_id"], unique=False)

    # ===================================================================
    # 16. Alter 'agent' table — add new columns
    # ===================================================================
    if _table_exists(bind, "agent") and not _has_column(bind, "agent", "org_id"):
        op.add_column("agent", sa.Column("org_id", sa.Uuid(), nullable=True))
    if _table_exists(bind, "agent") and not _has_column(bind, "agent", "dept_id"):
        op.add_column("agent", sa.Column("dept_id", sa.Uuid(), nullable=True))
    if _table_exists(bind, "agent") and not _has_column(bind, "agent", "project_id"):
        op.add_column("agent", sa.Column("project_id", sa.Uuid(), nullable=True))
    if _table_exists(bind, "agent") and not _has_column(bind, "agent", "lifecycle_status"):
        op.add_column("agent", sa.Column("lifecycle_status", sa.Text(), nullable=True))
    if _table_exists(bind, "agent") and not _has_column(bind, "agent", "cloned_from_deployment_id"):
        op.add_column("agent", sa.Column("cloned_from_deployment_id", sa.Uuid(), nullable=True))
    if _table_exists(bind, "agent") and not _has_column(bind, "agent", "deleted_at"):
        op.add_column("agent", sa.Column("deleted_at", sa.DateTime(), nullable=True))

    # Set default value for lifecycle_status for existing rows, then apply enum
    if _table_exists(bind, "agent") and _has_column(bind, "agent", "lifecycle_status"):
        op.execute(sa.text("UPDATE agent SET lifecycle_status = 'DRAFT' WHERE lifecycle_status IS NULL"))
        op.execute(sa.text("ALTER TABLE agent ALTER COLUMN lifecycle_status SET NOT NULL"))
        op.execute(sa.text(
            "ALTER TABLE agent ALTER COLUMN lifecycle_status TYPE lifecycle_status_enum "
            "USING lifecycle_status::lifecycle_status_enum;"
        ))
        op.execute(sa.text("ALTER TABLE agent ALTER COLUMN lifecycle_status SET DEFAULT 'DRAFT'"))

    # Add FKs and indexes
    if _table_exists(bind, "agent") and _table_exists(bind, "organization") and _has_column(bind, "agent", "org_id") and not _has_fk(bind, "agent", "fk_agent_org_id"):
        op.create_foreign_key("fk_agent_org_id", "agent", "organization", ["org_id"], ["id"])
    if _table_exists(bind, "agent") and _table_exists(bind, "department") and _has_column(bind, "agent", "dept_id") and not _has_fk(bind, "agent", "fk_agent_dept_id"):
        op.create_foreign_key("fk_agent_dept_id", "agent", "department", ["dept_id"], ["id"])
    if _table_exists(bind, "agent") and _table_exists(bind, "project") and _has_column(bind, "agent", "project_id") and not _has_fk(bind, "agent", "fk_agent_project_id"):
        op.create_foreign_key("fk_agent_project_id", "agent", "project", ["project_id"], ["id"])
    if _table_exists(bind, "agent") and _has_column(bind, "agent", "org_id") and not _has_index(bind, "agent", "ix_agent_org_id"):
        op.create_index("ix_agent_org_id", "agent", ["org_id"], unique=False)
    if _table_exists(bind, "agent") and _has_column(bind, "agent", "dept_id") and not _has_index(bind, "agent", "ix_agent_dept_id"):
        op.create_index("ix_agent_dept_id", "agent", ["dept_id"], unique=False)
    if _table_exists(bind, "agent") and _has_column(bind, "agent", "project_id") and not _has_index(bind, "agent", "ix_agent_project_id"):
        op.create_index("ix_agent_project_id", "agent", ["project_id"], unique=False)


def downgrade() -> None:
    """Reverse migration: drop all deployment architecture tables and columns."""

    # ===================================================================
    # 1. Revert 'agent' table changes
    # ===================================================================
    op.drop_constraint("fk_agent_project_id", "agent", type_="foreignkey")
    op.drop_constraint("fk_agent_dept_id", "agent", type_="foreignkey")
    op.drop_constraint("fk_agent_org_id", "agent", type_="foreignkey")
    op.drop_index("ix_agent_project_id", table_name="agent")
    op.drop_index("ix_agent_dept_id", table_name="agent")
    op.drop_index("ix_agent_org_id", table_name="agent")

    op.execute(sa.text(
        "ALTER TABLE agent ALTER COLUMN lifecycle_status DROP DEFAULT; "
        "ALTER TABLE agent ALTER COLUMN lifecycle_status TYPE text "
        "USING lifecycle_status::text;"
    ))
    op.drop_column("agent", "deleted_at")
    op.drop_column("agent", "cloned_from_deployment_id")
    op.drop_column("agent", "lifecycle_status")
    op.drop_column("agent", "project_id")
    op.drop_column("agent", "dept_id")
    op.drop_column("agent", "org_id")

    # ===================================================================
    # 2. Drop transaction tables
    # ===================================================================
    op.drop_index("ix_transaction_prod_deployment_id", table_name="transaction_prod")
    op.drop_index("ix_transaction_prod_deployment", table_name="transaction_prod")
    op.drop_index("ix_transaction_prod_agent", table_name="transaction_prod")
    op.drop_table("transaction_prod")

    op.drop_index("ix_transaction_uat_deployment_id", table_name="transaction_uat")
    op.drop_index("ix_transaction_uat_deployment", table_name="transaction_uat")
    op.drop_index("ix_transaction_uat_agent", table_name="transaction_uat")
    op.drop_table("transaction_uat")

    # ===================================================================
    # 3. Drop conversation tables
    # ===================================================================
    op.drop_index("ix_conversation_prod_deployment", table_name="conversation_prod")
    op.drop_index("ix_conversation_prod_deployment_id", table_name="conversation_prod")
    op.drop_index("ix_conversation_prod_agent", table_name="conversation_prod")
    op.drop_index("ix_conversation_prod_agent_id", table_name="conversation_prod")
    op.drop_index("ix_conversation_prod_session", table_name="conversation_prod")
    op.drop_table("conversation_prod")

    op.drop_index("ix_conversation_uat_deployment", table_name="conversation_uat")
    op.drop_index("ix_conversation_uat_deployment_id", table_name="conversation_uat")
    op.drop_index("ix_conversation_uat_agent", table_name="conversation_uat")
    op.drop_index("ix_conversation_uat_agent_id", table_name="conversation_uat")
    op.drop_index("ix_conversation_uat_session", table_name="conversation_uat")
    op.drop_table("conversation_uat")

    # ===================================================================
    # 4. Drop registry
    # ===================================================================
    op.drop_index("ix_agent_registry_deployment", table_name="agent_registry")
    op.drop_index("ix_agent_registry_visibility", table_name="agent_registry")
    op.drop_index("ix_agent_registry_org", table_name="agent_registry")
    op.drop_index("ix_agent_registry_org_id", table_name="agent_registry")
    op.drop_index("ix_agent_registry_listed_by", table_name="agent_registry")
    op.drop_index("ix_agent_registry_agent_deployment_id", table_name="agent_registry")
    op.drop_index("ix_agent_registry_agent_id", table_name="agent_registry")
    op.drop_table("agent_registry")

    # ===================================================================
    # 5. Drop bundle
    # ===================================================================
    op.drop_index("ix_agent_bundle_agent", table_name="agent_bundle")
    op.drop_index("ix_agent_bundle_type", table_name="agent_bundle")
    op.drop_index("ix_agent_bundle_deployment", table_name="agent_bundle")
    op.drop_index("ix_agent_bundle_created_by", table_name="agent_bundle")
    op.drop_index("ix_agent_bundle_deployment_id", table_name="agent_bundle")
    op.drop_index("ix_agent_bundle_agent_id", table_name="agent_bundle")
    op.drop_table("agent_bundle")

    # ===================================================================
    # 6. Drop deferred FK and deployment tables
    # ===================================================================
    op.drop_constraint("fk_approval_agent_publish_id", "approval_request", type_="foreignkey")

    op.drop_index("ix_deployment_prod_approval", table_name="agent_deployment_prod")
    op.drop_index("ix_deployment_prod_lifecycle", table_name="agent_deployment_prod")
    op.drop_index("ix_deployment_prod_org", table_name="agent_deployment_prod")
    op.drop_index("ix_deployment_prod_agent_active", table_name="agent_deployment_prod")
    op.drop_index("ix_deployment_prod_status", table_name="agent_deployment_prod")
    op.drop_index("ix_agent_deployment_prod_approval_id", table_name="agent_deployment_prod")
    op.drop_index("ix_agent_deployment_prod_promoted_from_uat_id", table_name="agent_deployment_prod")
    op.drop_index("ix_agent_deployment_prod_deployed_by", table_name="agent_deployment_prod")
    op.drop_index("ix_agent_deployment_prod_org_id", table_name="agent_deployment_prod")
    op.drop_index("ix_agent_deployment_prod_agent_id", table_name="agent_deployment_prod")
    op.drop_table("agent_deployment_prod")

    op.drop_index("ix_deployment_uat_lifecycle", table_name="agent_deployment_uat")
    op.drop_index("ix_deployment_uat_org", table_name="agent_deployment_uat")
    op.drop_index("ix_deployment_uat_agent_active", table_name="agent_deployment_uat")
    op.drop_index("ix_deployment_uat_status", table_name="agent_deployment_uat")
    op.drop_index("ix_agent_deployment_uat_deployed_by", table_name="agent_deployment_uat")
    op.drop_index("ix_agent_deployment_uat_org_id", table_name="agent_deployment_uat")
    op.drop_index("ix_agent_deployment_uat_agent_id", table_name="agent_deployment_uat")
    op.drop_table("agent_deployment_uat")

    # ===================================================================
    # 7. Drop approval_request
    # ===================================================================
    op.drop_index("ix_approval_agent_publish_id", table_name="approval_request")
    op.drop_index("ix_approval_reviewer_id", table_name="approval_request")
    op.drop_index("ix_approval_requested_by_decision", table_name="approval_request")
    op.drop_index("ix_approval_request_to_decision", table_name="approval_request")
    op.drop_table("approval_request")

    # ===================================================================
    # 8. Drop project, department, organization
    # ===================================================================
    op.drop_index("ix_project_owner_user_id", table_name="project")
    op.drop_index("ix_project_name", table_name="project")
    op.drop_index("ix_project_dept_id", table_name="project")
    op.drop_index("ix_project_org_id", table_name="project")
    op.drop_table("project")

    op.drop_index("ix_department_admin_user_id", table_name="department")
    op.drop_index("ix_department_org_id", table_name="department")
    op.drop_table("department")

    op.drop_index("ix_organization_name", table_name="organization")
    op.drop_table("organization")

    # ===================================================================
    # 9. Drop user columns & their FKs (idempotent for branch-merge safety)
    # ===================================================================
    op.execute(sa.text('DROP INDEX IF EXISTS ix_user_department_name'))
    op.execute(sa.text('DROP INDEX IF EXISTS ix_user_country'))
    op.execute(sa.text(
        "DO $$ BEGIN "
        'ALTER TABLE "user" DROP CONSTRAINT IF EXISTS fk_user_created_by; '
        "EXCEPTION WHEN undefined_object THEN null; "
        "END $$;"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        'ALTER TABLE "user" DROP CONSTRAINT IF EXISTS fk_user_department_admin; '
        "EXCEPTION WHEN undefined_object THEN null; "
        "END $$;"
    ))
    op.execute(sa.text('ALTER TABLE "user" DROP COLUMN IF EXISTS country'))
    op.execute(sa.text('ALTER TABLE "user" DROP COLUMN IF EXISTS created_by'))
    op.execute(sa.text('ALTER TABLE "user" DROP COLUMN IF EXISTS department_admin'))
    op.execute(sa.text('ALTER TABLE "user" DROP COLUMN IF EXISTS department_name'))

    # ===================================================================
    # 10. Drop enum types
    # ===================================================================
    op.execute(sa.text("DROP TYPE IF EXISTS approval_decision_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS registry_deployment_env_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS registry_visibility_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS bundle_type_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS deployment_env_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS prod_deployment_lifecycle_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS prod_deployment_visibility_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS deployment_prod_status_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS deployment_lifecycle_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS deployment_visibility_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS deployment_uat_status_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS lifecycle_status_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS project_status_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS dept_status_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS org_status_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS org_tier_enum"))
