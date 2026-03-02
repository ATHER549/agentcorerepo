"""AgentCore Publishing API.

Handles deploying agents to UAT and PROD environments with version management,
snapshot freezing, shadow deployment support, and agent cloning.

Architecture:
    - agent_deployment_uat table: INSERT-based versioning for UAT (direct, no approval)
    - agent_deployment_prod table: INSERT-based versioning for PROD (approval flow for developers)
    - Each deployment creates a new row with a version number (v1, v2, v3...)
    - is_active flag controls which versions are serving traffic
    - Shadow deployment: multiple versions can be is_active=True simultaneously
    - Rollback: toggle is_active flags without creating new rows

Endpoints:
    POST   /publish/{agent_id}                   — **Unified publish** (UAT or PROD via env field)
    GET    /publish/{agent_id}/status             — Get deploy status across both envs
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from enum import Enum as PyEnum

from fastapi import APIRouter, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.approval_request.model import (
    ApprovalRequest,
)
from agentcore.services.database.models.folder.model import Folder
from agentcore.services.database.models.agent_deployment_prod.model import (
    AgentDeploymentProd,
    DeploymentPRODStatusEnum,
    ProdDeploymentLifecycleEnum,
    ProdDeploymentVisibilityEnum,
)
from agentcore.services.database.models.agent_deployment_uat.model import (
    AgentDeploymentUAT,
    DeploymentUATStatusEnum,
    DeploymentVisibilityEnum,
)
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.agent_registry.model import RegistryDeploymentEnvEnum
from agentcore.services.database.registry_service import sync_agent_registry

router = APIRouter(prefix="/publish", tags=["Publish"])


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

# Roles that can publish directly to PROD (others go through approval flow)
ADMIN_ROLES = {"admin", "super_admin", "root", "department_admin"}


# ═══════════════════════════════════════════════════════════════════════════
# Request / Response Schemas
# ═══════════════════════════════════════════════════════════════════════════


class PublishEnvironment(str, PyEnum):
    """Target environment for publishing."""
    uat = "uat"
    prod = "prod"


class DeployActionRequest(BaseModel):
    """Request body for updating a deployment record.

    Send the fields you want to change as key-value pairs.
    The backend validates the state transition and applies the update.

    Examples:
        Unpublish:  {"status": "UNPUBLISHED", "is_active": false}
        Activate:   {"status": "PUBLISHED",   "is_active": true}
        Deactivate: {"is_active": false}
        Republish:  {"status": "PUBLISHED",   "is_active": true}
    """
    status: str | None = Field(
        default=None,
        description="New status value: 'PUBLISHED' or 'UNPUBLISHED'. Omit to keep current status.",
    )
    is_active: bool | None = Field(
        default=None,
        description="Set the is_active flag. true = serving traffic, false = offline. Omit to keep current value.",
    )


class PublishRequest(BaseModel):
    """Unified request body for deploying an agent to UAT or PROD.

    The frontend sends all required context in a single payload.
    The backend decides whether to deploy directly or go through
    the approval flow based on (environment + user role).
    """

    department_id: UUID = Field(
        description="Department the agent belongs to",
    )
    department_admin_id: UUID | None = Field(
        default=None,
        description=(
            "Optional: department admin user ID. If omitted, backend resolves it from "
            "user_department_membership -> department.admin_user_id."
        ),
    )
    visibility: str = Field(
        default="PRIVATE",
        description="'PUBLIC' = discoverable by all in tenant; 'PRIVATE' = creator + admins only",
    )
    environment: PublishEnvironment = Field(
        description="Target environment: 'uat' or 'prod'",
    )
    publish_description: str | None = Field(
        default=None,
        description="Release notes / description for this deployment action",
    )
    promoted_from_uat_id: UUID | None = Field(
        default=None,
        description=(
            "Optional: UAT deployment ID to promote from. When set, the PROD "
            "snapshot is copied from this UAT record instead of agent.data. "
            "Only valid when environment='prod'."
        ),
    )


class CloneFromPublishRequest(BaseModel):
    """Request body for cloning an agent from a deployed snapshot."""

    project_id: UUID = Field(
        description="Target project (folder) to place the cloned agent into",
    )
    new_name: str | None = Field(
        default=None,
        description="Name for the cloned agent. If omitted, uses '<original_name> (Copy)'",
    )


class PublishRecordSummary(BaseModel):
    """Deployment record summary without snapshot (used in list & status endpoints).

    Deliberately excludes agent_snapshot for performance — use the
    /publish/{deploy_id}/snapshot endpoint to get the full frozen flow JSON.
    """

    id: UUID
    agent_id: UUID
    version_number: str
    agent_name: str
    agent_description: str | None = None
    publish_description: str | None = None
    published_by: UUID
    published_at: datetime
    is_active: bool
    status: str
    visibility: str
    error_message: str | None = None
    environment: str  # "uat" or "prod"
    promoted_from_uat_id: UUID | None = None

    class Config:
        from_attributes = True


class AgentPublishStatusResponse(BaseModel):
    """Combined deployment status across both environments for a single agent.

    Used by the UI to show deploy badges on agent cards:
        🟢 UAT (live)  |  🔵 PROD (live)  |  🟡 PROD (pending)
    """

    agent_id: UUID
    uat: PublishRecordSummary | None = None
    prod: PublishRecordSummary | None = None
    has_pending_approval: bool = False
    pending_requested_by: UUID | None = None
    latest_prod_status: str | None = None
    latest_review_decision: str | None = None
    latest_prod_published_by: UUID | None = None


class PublishSnapshotResponse(BaseModel):
    """Full deployment record including the frozen agent snapshot.

    Used for:
        - Testing/previewing in playground (works for chat AND autonomous agents)
        - Reviewing agent before approval
        - Inspecting a specific version's flow definition

    The agent_snapshot contains the complete flow JSON (nodes + edges) that the
    runtime can execute. This is identical to agent.data at the moment of deployment.
    """

    id: UUID
    agent_id: UUID
    environment: str  # "uat" or "prod"
    version_number: str
    agent_name: str
    agent_description: str | None = None
    agent_snapshot: dict
    publish_description: str | None = None
    published_by: UUID
    published_at: datetime
    status: str
    is_active: bool
    visibility: str


class CloneResponse(BaseModel):
    """Response after cloning a deployed agent into a new agent."""

    agent_id: UUID
    agent_name: str
    project_id: UUID
    cloned_from_publish_id: UUID
    environment_source: str  # "uat" or "prod"


class PublishActionResponse(BaseModel):
    """Generic response for deployment actions (deploy, unpublish, activate, deactivate)."""

    success: bool
    message: str
    publish_id: UUID
    environment: str
    status: str
    is_active: bool
    version_number: str
    promoted_from_uat_id: UUID | None = None

class ValidatePublishEmailResponse(BaseModel):
    """Validation response for publish recipient emails."""

    agent_id: UUID
    email: str
    department_id: UUID | None
    exists_in_department: bool
    message: str


class PublishContextResponse(BaseModel):
    """Resolved publish context for current user and agent tenant scope."""

    agent_id: UUID
    org_id: UUID
    department_id: UUID
    department_admin_id: UUID


async def _current_user_department_ids(session: DbSession, user_id: UUID) -> set[UUID]:
    rows = (
        await session.exec(
            select(UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    return set(rows)    


async def _resolve_publish_scope(
    session: DbSession,
    *,
    current_user: CurrentActiveUser,
    agent: Agent,
    requested_department_id: UUID | None = None,
    requested_department_admin_id: UUID | None = None,
) -> tuple[UUID, UUID]:
    """Resolve and validate publish department/admin in the agent's org tenant."""
    current_role = str(getattr(current_user, "role", "")).lower()
    is_org_wide_admin = current_role in {"root", "super_admin", "admin"}

    # Super/root admins may not have user_department_membership rows.
    # For these roles, resolve scope by requested department (or agent.dept_id),
    # while still enforcing tenant consistency.
    if is_org_wide_admin:
        resolved_department_id = requested_department_id or agent.dept_id
        if not resolved_department_id and agent.org_id:
            # For org-wide admins without department memberships, use a deterministic
            # fallback department from the agent's organization.
            fallback_department = (
                await session.exec(
                    select(Department)
                    .where(Department.org_id == agent.org_id)
                    .order_by(col(Department.id))
                )
            ).first()
            if fallback_department:
                resolved_department_id = fallback_department.id

        if not resolved_department_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "department_id is required for publish scope resolution when "
                    "no department could be inferred for this agent."
                ),
            )

        department = (
            await session.exec(
                select(Department).where(Department.id == resolved_department_id)
            )
        ).first()
        if not department:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Department {resolved_department_id} not found.",
            )

        # Keep publish within the agent's tenant if agent is already stitched.
        if agent.org_id and department.org_id != agent.org_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Department {resolved_department_id} is not part of organization {agent.org_id}."
                ),
            )

        # Stitch missing tenant fields from resolved department.
        if not agent.org_id:
            agent.org_id = department.org_id
        if not agent.dept_id:
            agent.dept_id = department.id
        session.add(agent)

        resolved_department_admin_id = department.admin_user_id
        if (
            requested_department_admin_id
            and requested_department_admin_id != resolved_department_admin_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"department_admin_id {requested_department_admin_id} does not match "
                    f"department admin {resolved_department_admin_id} for department {resolved_department_id}."
                ),
            )

        admin_user = (
            await session.exec(select(User).where(User.id == resolved_department_admin_id))
        ).first()
        if not admin_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Department admin user {resolved_department_admin_id} not found.",
            )

        return resolved_department_id, resolved_department_admin_id

    base_memberships = (
        await session.exec(
            select(UserDepartmentMembership).where(
                UserDepartmentMembership.user_id == current_user.id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    if not base_memberships:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Current user has no active department membership. "
                "Please map the user in user_department_membership first."
            ),
        )

    # If org isn't stitched on agent yet, derive it from publisher membership.
    if not agent.org_id:
        if requested_department_id:
            scoped = [m for m in base_memberships if m.department_id == requested_department_id]
            if not scoped:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"department_id {requested_department_id} is not mapped to publishing user "
                        f"{current_user.id}."
                    ),
                )
            selected = scoped[0]
        else:
            selected = sorted(base_memberships, key=lambda m: (str(m.org_id), str(m.department_id)))[0]

        agent.org_id = selected.org_id
        if not agent.dept_id:
            agent.dept_id = selected.department_id
        session.add(agent)

    memberships = [m for m in base_memberships if m.org_id == agent.org_id]
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current user has no active department mapping in the agent organization.",
        )

    allowed_dept_ids = {m.department_id for m in memberships}

    if requested_department_id is not None:
        if requested_department_id not in allowed_dept_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"department_id {requested_department_id} is not mapped to current user "
                    f"in organization {agent.org_id}."
                ),
            )
        resolved_department_id = requested_department_id
    elif agent.dept_id and agent.dept_id in allowed_dept_ids:
        resolved_department_id = agent.dept_id
    else:
        # Deterministic fallback when user has multiple departments.
        resolved_department_id = sorted(allowed_dept_ids, key=str)[0]

    department = (
        await session.exec(
            select(Department).where(
                Department.id == resolved_department_id,
                Department.org_id == agent.org_id,
            )
        )
    ).first()
    if not department:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Department {resolved_department_id} is not part of organization {agent.org_id}."
            ),
        )

    resolved_department_admin_id = department.admin_user_id
    if requested_department_admin_id and requested_department_admin_id != resolved_department_admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"department_admin_id {requested_department_admin_id} does not match "
                f"department admin {resolved_department_admin_id} for department {resolved_department_id}."
            ),
        )

    admin_user = (
        await session.exec(select(User).where(User.id == resolved_department_admin_id))
    ).first()
    if not admin_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Department admin user {resolved_department_admin_id} not found.",
        )

    return resolved_department_id, resolved_department_admin_id

# ═══════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/validate-email", response_model=ValidatePublishEmailResponse)
@router.post("/validate-email", response_model=ValidatePublishEmailResponse)
async def validate_publish_email(
    *,
    agent_id: UUID = Query(..., description="Agent ID"),
    email: str = Query(..., description="Recipient email to validate"),
    session: DbSession,
    current_user: CurrentActiveUser,
) -> ValidatePublishEmailResponse:
    """Validate that an email exists in the same department(s) as the current user."""
    normalized_email = str(email).strip().lower()
    if "@" not in normalized_email:
        raise HTTPException(status_code=400, detail="Invalid email format.")

    agent = await session.get(Agent, agent_id)
    if not agent or agent.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Agent not found.")

    current_user_dept_ids = await _current_user_department_ids(session, current_user.id)
    if not current_user_dept_ids:
        return ValidatePublishEmailResponse(
            agent_id=agent_id,
            email=normalized_email,
            department_id=None,
            exists_in_department=False,
            message="Current user has no active department mapping.",
        )

    user = (
        await session.exec(
            select(User).where(
                (User.username.ilike(normalized_email)) | (User.email.ilike(normalized_email)),
            )
        )
    ).first()

    if not user:
        return ValidatePublishEmailResponse(
            agent_id=agent_id,
            email=normalized_email,
            department_id=next(iter(current_user_dept_ids)),
            exists_in_department=False,
            message="Email not found in user table for this department.",
        )

    memberships = (
        await session.exec(
            select(UserDepartmentMembership).where(
                UserDepartmentMembership.user_id == user.id,
                UserDepartmentMembership.department_id.in_(list(current_user_dept_ids)),
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()

    exists_in_department = len(memberships) > 0
    resolved_department_id = memberships[0].department_id if memberships else next(iter(current_user_dept_ids))
    return ValidatePublishEmailResponse(
        agent_id=agent_id,
        email=normalized_email,
        department_id=resolved_department_id,
        exists_in_department=exists_in_department,
        message=(
            "Email found in this department."
            if exists_in_department
            else "Email exists, but not in this department."
        ),
    )


@router.get("/{agent_id}/context", response_model=PublishContextResponse, status_code=200)
async def get_publish_context(
    *,
    session: DbSession,
    agent_id: UUID,
    current_user: CurrentActiveUser,
) -> PublishContextResponse:
    """Return resolved tenant-safe publish context for the current user."""
    agent = await _get_agent_or_404(session, agent_id, current_user.id)
    if not agent.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent must belong to an organization before publishing.",
        )
    department_id, department_admin_id = await _resolve_publish_scope(
        session,
        current_user=current_user,
        agent=agent,
    )
    return PublishContextResponse(
        agent_id=agent.id,
        org_id=agent.org_id,
        department_id=department_id,
        department_admin_id=department_admin_id,
    )

async def _get_next_version_number(
    session: AsyncSession,
    agent_id: UUID,
    table_class: type[AgentDeploymentUAT] | type[AgentDeploymentProd],
) -> int:
    """Calculate the next version number for an agent in the given table.

    Finds the highest existing version number and returns max + 1.
    If no previous versions exist, returns 1.

    Args:
        session: Database session.
        agent_id: The agent to get next version for.
        table_class: AgentDeploymentUAT or AgentDeploymentProd model class.

    Returns:
        Next version number as int (1, 2, 3, ...).
    """
    stmt = select(table_class.version_number).where(table_class.agent_id == agent_id)
    results = (await session.exec(stmt)).all()

    if not results:
        return 1

    return max(results) + 1


async def _get_agent_or_404(
    session: AsyncSession,
    agent_id: UUID,
    user_id: UUID | None = None,
) -> Agent:
    """Fetch an agent by ID, optionally verifying ownership.

    Args:
        session: Database session.
        agent_id: The agent UUID.
        user_id: If provided, also verifies the agent belongs to this user.

    Returns:
        The Agent instance.

    Raises:
        HTTPException 404: If agent not found or does not belong to user.
    """
    stmt = select(Agent).where(Agent.id == agent_id)
    if user_id is not None:
        stmt = stmt.where(Agent.user_id == user_id)

    agent = (await session.exec(stmt)).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found" + (" or not owned by you" if user_id else ""),
        )
    return agent


async def _find_deploy_record(
    session: AsyncSession,
    deploy_id: UUID,
) -> tuple[AgentDeploymentUAT | AgentDeploymentProd, str]:
    """Find a deployment record in either the UAT or PROD table.

    UUIDs are globally unique, so there is no ambiguity searching both tables.

    Args:
        session: Database session.
        deploy_id: The deployment record UUID.

    Returns:
        Tuple of (record, environment_str) where environment_str is "uat" or "prod".

    Raises:
        HTTPException 404: If the deployment record is not found in either table.
    """
    uat_record = (await session.exec(
        select(AgentDeploymentUAT).where(AgentDeploymentUAT.id == deploy_id)
    )).first()
    if uat_record:
        return uat_record, "uat"

    prod_record = (await session.exec(
        select(AgentDeploymentProd).where(AgentDeploymentProd.id == deploy_id)
    )).first()
    if prod_record:
        return prod_record, "prod"

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Deployment record {deploy_id} not found in UAT or PROD",
    )


def _record_to_summary(record: AgentDeploymentUAT | AgentDeploymentProd, environment: str) -> PublishRecordSummary:
    """Convert a UAT or PROD deployment record to a lightweight summary (no snapshot)."""
    return PublishRecordSummary(
        id=record.id,
        agent_id=record.agent_id,
        version_number=f"v{record.version_number}",
        agent_name=record.agent_name,
        agent_description=record.agent_description,
        publish_description=record.publish_description,
        published_by=record.deployed_by,
        published_at=record.deployed_at,
        is_active=record.is_active,
        status=record.status.value if hasattr(record.status, "value") else str(record.status),
        visibility=record.visibility.value if hasattr(record.visibility, "value") else str(record.visibility),
        error_message=record.error_message,
        environment=environment,
        promoted_from_uat_id=getattr(record, "promoted_from_uat_id", None),
    )




# ═══════════════════════════════════════════════════════════════════════════
# STATIC LIST ROUTES
# (defined FIRST so FastAPI matches them before parametric /{uuid} routes)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/uat", response_model=list[PublishRecordSummary], status_code=200)
async def list_uat_published_agents(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    active_only: bool | None = Query(None, description="true = only is_active=True; false = only is_active=False; omit = all"),
    status_filter: DeploymentUATStatusEnum | None = Query(None, alias="status", description="Filter by status"),
):
    """List all UAT-deployed agents.

    Used by the Control Panel to display UAT-deployed agent cards.

    Args:
        session: Async database session.
        current_user: The authenticated user.
        active_only: If true, only return currently active versions.
        status_filter: Optional filter for deployment status.

    Returns:
        List of deployment record summaries (without full snapshot for performance).
    """
    try:
        stmt = select(AgentDeploymentUAT)

        if active_only is not None:
            stmt = stmt.where(AgentDeploymentUAT.is_active == active_only)  # noqa: E712

        if status_filter:
            stmt = stmt.where(AgentDeploymentUAT.status == status_filter)

        stmt = stmt.order_by(col(AgentDeploymentUAT.deployed_at).desc())
        records = (await session.exec(stmt)).all()

        return [_record_to_summary(r, "uat") for r in records]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing UAT deployed agents: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/prod", response_model=list[PublishRecordSummary], status_code=200)
async def list_prod_published_agents(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    active_only: bool | None = Query(None, description="true = only is_active=True; false = only is_active=False; omit = all"),
    status_filter: DeploymentPRODStatusEnum | None = Query(None, alias="status", description="Filter by status"),
):
    """List all PROD-deployed agents.

    Used by the Control Panel and Agent Registry to display PROD-deployed agents.

    Args:
        session: Async database session.
        current_user: The authenticated user.
        active_only: If true, only return currently active versions.
        status_filter: Optional filter for deployment status.

    Returns:
        List of deployment record summaries (without full snapshot for performance).
    """
    try:
        stmt = select(AgentDeploymentProd)

        if active_only is not None:
            stmt = stmt.where(AgentDeploymentProd.is_active == active_only)  # noqa: E712

        if status_filter:
            stmt = stmt.where(AgentDeploymentProd.status == status_filter)

        stmt = stmt.order_by(col(AgentDeploymentProd.deployed_at).desc())
        records = (await session.exec(stmt)).all()

        return [_record_to_summary(r, "prod") for r in records]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing PROD deployed agents: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ═══════════════════════════════════════════════════════════════════════════
# UAT DEPLOYMENT ACTIONS (unified)
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/uat/{deploy_id}/action", response_model=PublishActionResponse, status_code=200)
async def uat_deploy_action(
    *,
    session: DbSession,
    deploy_id: UUID,
    body: DeployActionRequest,
    current_user: CurrentActiveUser,
):
    """Update a UAT deployment record.

    Send the fields you want to change as key-value pairs:

    | Goal        | Payload                                          |
    |-------------|--------------------------------------------------|
    | Unpublish   | `{"status": "UNPUBLISHED", "is_active": false}`   |
    | Activate    | `{"is_active": true}`                             |
    | Deactivate  | `{"is_active": false}`                            |
    | Republish   | `{"status": "PUBLISHED", "is_active": true}`      |

    Permission: deployer (owner) or admin/manager role.
    """
    try:
        record = (await session.exec(
            select(AgentDeploymentUAT).where(AgentDeploymentUAT.id == deploy_id)
        )).first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"UAT deployment record {deploy_id} not found",
            )

        new_status = body.status.upper() if body.status else None
        new_is_active = body.is_active
        current_status_val = record.status.value if hasattr(record.status, "value") else str(record.status)
        changes: list[str] = []

        # ── Validate & apply status change ──
        if new_status is not None and new_status != current_status_val:
            if new_status == "UNPUBLISHED":
                record.status = DeploymentUATStatusEnum.UNPUBLISHED
                # Force is_active=False when unpublishing (unless explicitly overridden)
                if new_is_active is None:
                    new_is_active = False
                changes.append("status → UNPUBLISHED")

            elif new_status == "PUBLISHED":
                if current_status_val != "UNPUBLISHED":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Cannot set status to PUBLISHED from '{current_status_val}'. "
                               f"Only UNPUBLISHED records can be republished.",
                    )
                # Deactivate other active versions for this agent (republish semantics)
                existing_active = (await session.exec(
                    select(AgentDeploymentUAT).where(
                        AgentDeploymentUAT.agent_id == record.agent_id,
                        AgentDeploymentUAT.id != record.id,
                        AgentDeploymentUAT.is_active == True,  # noqa: E712
                    )
                )).all()
                for rec in existing_active:
                    rec.is_active = False
                    session.add(rec)

                record.status = DeploymentUATStatusEnum.PUBLISHED
                if new_is_active is None:
                    new_is_active = True
                changes.append("status → PUBLISHED")

            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid status '{new_status}'. Allowed: PUBLISHED, UNPUBLISHED.",
                )

        # ── Validate & apply is_active change ──
        if new_is_active is not None and new_is_active != record.is_active:
            effective_status = (
                record.status.value if hasattr(record.status, "value") else str(record.status)
            )
            if new_is_active is True and effective_status != "PUBLISHED":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cannot activate a version with status '{effective_status}'. "
                           f"Only PUBLISHED versions can be activated.",
                )
            record.is_active = new_is_active
            changes.append(f"is_active → {new_is_active}")

        if not changes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No changes requested. Send at least one of: status, is_active.",
            )

        session.add(record)
        await session.commit()
        await session.refresh(record)

        # ─── Sync agent registry after any UAT change ──
        try:
            agent = (await session.exec(select(Agent).where(Agent.id == record.agent_id))).first()
            org_id = agent.org_id if agent else None
            await sync_agent_registry(
                session,
                agent_id=record.agent_id,
                org_id=org_id,
                acted_by=current_user.id,
                deployment_env=RegistryDeploymentEnvEnum.UAT,
            )
            await session.commit()
        except Exception as reg_err:
            logger.warning(f"Registry sync failed after update of UAT agent {record.agent_id}: {reg_err}")

        msg = f"UAT v{record.version_number} updated: {', '.join(changes)}"
        logger.info(f"{msg} | deploy_id={deploy_id} user={current_user.id}")

        return PublishActionResponse(
            success=True,
            message=msg,
            publish_id=record.id,
            environment="uat",
            status=record.status.value if hasattr(record.status, "value") else str(record.status),
            is_active=record.is_active,
            version_number=f"v{record.version_number}",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating UAT record {deploy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ═══════════════════════════════════════════════════════════════════════════
# PROD DEPLOYMENT ACTIONS (unified)
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/prod/{deploy_id}/action", response_model=PublishActionResponse, status_code=200)
async def prod_deploy_action(
    *,
    session: DbSession,
    deploy_id: UUID,
    body: DeployActionRequest,
    current_user: CurrentActiveUser,
):
    """Update a PROD deployment record.

    Send the fields you want to change as key-value pairs:

    | Goal        | Payload                                          |
    |-------------|--------------------------------------------------|
    | Unpublish   | `{"status": "UNPUBLISHED", "is_active": false}`   |
    | Activate    | `{"is_active": true}`                             |
    | Deactivate  | `{"is_active": false}`                            |
    | Republish   | `{"status": "PUBLISHED", "is_active": true}`      |

    Permission: any authenticated user.
    """
    try:
        record = (await session.exec(
            select(AgentDeploymentProd).where(AgentDeploymentProd.id == deploy_id)
        )).first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"PROD deployment record {deploy_id} not found",
            )

        new_status = body.status.upper() if body.status else None
        new_is_active = body.is_active
        current_status_val = record.status.value if hasattr(record.status, "value") else str(record.status)
        changes: list[str] = []

        # ── Validate & apply status change ──
        if new_status is not None and new_status != current_status_val:
            if new_status == "UNPUBLISHED":
                record.status = DeploymentPRODStatusEnum.UNPUBLISHED
                if new_is_active is None:
                    new_is_active = False
                changes.append("status → UNPUBLISHED")

            elif new_status == "PUBLISHED":
                if current_status_val != "UNPUBLISHED":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Cannot set status to PUBLISHED from '{current_status_val}'. "
                               f"Only UNPUBLISHED records can be republished.",
                    )
                # Shadow deployment: keep other active versions running.

                record.status = DeploymentPRODStatusEnum.PUBLISHED
                if new_is_active is None:
                    new_is_active = True
                changes.append("status → PUBLISHED")

            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid status '{new_status}'. Allowed: PUBLISHED, UNPUBLISHED.",
                )

        # ── Validate & apply is_active change ──
        if new_is_active is not None and new_is_active != record.is_active:
            effective_status = (
                record.status.value if hasattr(record.status, "value") else str(record.status)
            )
            if new_is_active is True and effective_status != "PUBLISHED":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cannot activate a version with status '{effective_status}'. "
                           f"Only PUBLISHED versions can be activated.",
                )
            record.is_active = new_is_active
            changes.append(f"is_active → {new_is_active}")

        if not changes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No changes requested. Send at least one of: status, is_active.",
            )

        session.add(record)
        await session.commit()
        await session.refresh(record)

        # ─── Sync agent registry after any PROD change ──
        try:
            agent = (await session.exec(select(Agent).where(Agent.id == record.agent_id))).first()
            org_id = agent.org_id if agent else None
            await sync_agent_registry(
                session,
                agent_id=record.agent_id,
                org_id=org_id,
                acted_by=current_user.id,
                deployment_env=RegistryDeploymentEnvEnum.PROD,
            )
            await session.commit()
        except Exception as reg_err:
            logger.warning(f"Registry sync failed after update of agent {record.agent_id}: {reg_err}")

        msg = f"PROD v{record.version_number} updated: {', '.join(changes)}"
        logger.info(f"{msg} | deploy_id={deploy_id} user={current_user.id}")

        return PublishActionResponse(
            success=True,
            message=msg,
            publish_id=record.id,
            environment="prod",
            status=record.status.value if hasattr(record.status, "value") else str(record.status),
            is_active=record.is_active,
            version_number=f"v{record.version_number}",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating PROD record {deploy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED PUBLISH ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/{agent_id}", response_model=PublishActionResponse, status_code=201)
async def publish_agent(
    *,
    session: DbSession,
    agent_id: UUID,
    body: PublishRequest,
    current_user: CurrentActiveUser,
):
    """Publish an agent to UAT or PROD (single unified endpoint).

    The frontend sends a single payload with all required context:
        - agent_id (path): which agent to publish
        - department_id: the department the agent belongs to
        - department_admin_id: the department admin to whom the request is directed
        - visibility: PUBLIC or PRIVATE
        - environment: "uat" or "prod"
        - publish_description: optional release notes

    Behaviour:
        **UAT** — always direct deploy for any role with publish permission.
        **PROD + admin/manager** — direct deploy, no approval needed.
        **PROD + developer** — creates a PENDING_APPROVAL record and an
        approval_request targeting the supplied department_admin_id.

    Returns:
        PublishActionResponse with the deployment record details.
    """
    try:
        print("*********************")
        print(current_user)

        agent = await _get_agent_or_404(session, agent_id, current_user.id)

        if not agent.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deploy agent with no flow data. Build the agent first.",
            )

        resolved_department_id, resolved_department_admin_id = await _resolve_publish_scope(
            session,
            current_user=current_user,
            agent=agent,
            requested_department_id=body.department_id,
            requested_department_admin_id=body.department_admin_id,
        )

        # Freeze snapshot — immutable copy of the current agent flow
        snapshot = agent.data.copy()
        env = body.environment.value  # "uat" or "prod"
        promoted_from_uat_id = body.promoted_from_uat_id

        # ── Validate & resolve UAT promotion ──
        if promoted_from_uat_id is not None:
            if env != "prod":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="promoted_from_uat_id is only valid when environment='prod'.",
                )
            uat_record = (await session.exec(
                select(AgentDeploymentUAT).where(AgentDeploymentUAT.id == promoted_from_uat_id)
            )).first()
            if not uat_record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"UAT deployment {promoted_from_uat_id} not found.",
                )
            if uat_record.agent_id != agent_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"UAT deployment {promoted_from_uat_id} belongs to agent {uat_record.agent_id}, "
                        f"not {agent_id}."
                    ),
                )
            # Use the UAT-tested snapshot instead of the current draft
            snapshot = uat_record.agent_snapshot.copy()
            logger.info(
                f"Promoting from UAT v{uat_record.version_number} ({promoted_from_uat_id}) "
                f"to PROD for agent {agent_id}"
            )

        # ── Derive agent input type from snapshot nodes ──────────
        _node_types = {n.get("data", {}).get("type") for n in snapshot.get("nodes", [])}
        if "ChatInput" in _node_types:
            snapshot["_input_type"] = "chat"
        elif _node_types & {"FolderMonitor", "FileTrigger"}:
            snapshot["_input_type"] = "file_processing"
        else:
            snapshot["_input_type"] = "autonomous"

        if env == "uat":
            # ─── UAT: always direct deploy ───────────────────────
            next_version = await _get_next_version_number(session, agent_id, AgentDeploymentUAT)

            visibility_enum = DeploymentVisibilityEnum(body.visibility.upper())

            new_record = AgentDeploymentUAT(
                agent_id=agent_id,
                org_id=agent.org_id,
                version_number=next_version,
                agent_snapshot=snapshot,
                agent_name=agent.name,
                agent_description=agent.description,
                publish_description=body.publish_description,
                deployed_by=current_user.id,
                deployed_at=datetime.now(timezone.utc),
                is_active=True,
                status=DeploymentUATStatusEnum.PUBLISHED,
                visibility=visibility_enum,
            )
            session.add(new_record)

            # Deactivate all previous versions for this agent
            existing_records = (await session.exec(
                select(AgentDeploymentUAT).where(
                    AgentDeploymentUAT.agent_id == agent_id,
                    AgentDeploymentUAT.id != new_record.id,
                    AgentDeploymentUAT.is_active == True,  # noqa: E712
                )
            )).all()
            for rec in existing_records:
                rec.is_active = False
                session.add(rec)

            await session.commit()
            await session.refresh(new_record)

            logger.info(
                f"Deployed agent '{agent.name}' ({agent_id}) to UAT as v{next_version} "
                f"by user {current_user.id} [dept={resolved_department_id}]"
            )

            # Sync FileTrigger nodes → auto-create trigger_config entries
            try:
                from agentcore.services.deps import get_trigger_service
                trigger_svc = get_trigger_service()
                await trigger_svc.sync_folder_monitors_for_agent(
                    session=session,
                    agent_id=agent_id,
                    environment="uat",
                    version=f"v{next_version}",
                    deployment_id=new_record.id,
                    flow_data=snapshot,
                    created_by=current_user.id,
                )
            except Exception as sched_err:
                logger.warning(f"FileTrigger sync failed for UAT deploy of {agent_id}: {sched_err}")

            # ─── Sync agent registry after UAT publish ──
            try:
                await sync_agent_registry(
                    session,
                    agent_id=agent_id,
                    org_id=agent.org_id,
                    acted_by=current_user.id,
                    deployment_env=RegistryDeploymentEnvEnum.UAT,
                )
                await session.commit()
            except Exception as reg_err:
                logger.warning(f"Registry sync failed after UAT publish of {agent_id}: {reg_err}")

            return PublishActionResponse(
                success=True,
                message=f"Agent '{agent.name}' deployed to UAT as v{next_version}",
                publish_id=new_record.id,
                environment="uat",
                status=new_record.status.value,
                is_active=True,
                version_number=f"v{next_version}",
            )

        else:
            # ─── PROD ────────────────────────────────────────────
            next_version = await _get_next_version_number(session, agent_id, AgentDeploymentProd)
            role = str(getattr(current_user, "role", "")).lower()
            is_admin = role in ADMIN_ROLES

            visibility_enum = ProdDeploymentVisibilityEnum(body.visibility.upper())

            if is_admin:
                # Admin/manager: direct deploy
                new_record = AgentDeploymentProd(
                    agent_id=agent_id,
                    org_id=agent.org_id,
                    promoted_from_uat_id=promoted_from_uat_id,
                    version_number=next_version,
                    agent_snapshot=snapshot,
                    agent_name=agent.name,
                    agent_description=agent.description,
                    publish_description=body.publish_description,
                    deployed_by=current_user.id,
                    deployed_at=datetime.now(timezone.utc),
                    is_active=True,
                    status=DeploymentPRODStatusEnum.PUBLISHED,
                    lifecycle_step=ProdDeploymentLifecycleEnum.PUBLISHED,
                    visibility=visibility_enum,
                )
                session.add(new_record)

                # Shadow deployment: keep previous versions active so
                # multiple versions can run side-by-side.

                await session.commit()
                await session.refresh(new_record)

                logger.info(
                    f"Admin direct-deployed agent '{agent.name}' ({agent_id}) to PROD "
                    f"as v{next_version} by {current_user.id} [dept={resolved_department_id}]"
                )

                # ─── Sync agent registry after PROD admin publish ──
                try:
                    await sync_agent_registry(
                        session,
                        agent_id=agent_id,
                        org_id=agent.org_id,
                        acted_by=current_user.id,
                        deployment_env=RegistryDeploymentEnvEnum.PROD,
                    )
                    await session.commit()
                except Exception as reg_err:
                    logger.warning(f"Registry sync failed after PROD publish of {agent_id}: {reg_err}")

                # Sync FileTrigger nodes → auto-create trigger_config entries
                try:
                    from agentcore.services.deps import get_trigger_service
                    trigger_svc = get_trigger_service()
                    await trigger_svc.sync_folder_monitors_for_agent(
                        session=session,
                        agent_id=agent_id,
                        environment="prod",
                        version=f"v{next_version}",
                        deployment_id=new_record.id,
                        flow_data=snapshot,
                        created_by=current_user.id,
                    )
                except Exception as fm_err:
                    logger.warning(f"FileTrigger sync failed for PROD deploy of {agent_id}: {fm_err}")

                return PublishActionResponse(
                    success=True,
                    message=f"Agent '{agent.name}' deployed to PROD as v{next_version}",
                    publish_id=new_record.id,
                    environment="prod",
                    status=DeploymentPRODStatusEnum.PUBLISHED.value,
                    is_active=True,
                    version_number=f"v{next_version}",
                    promoted_from_uat_id=promoted_from_uat_id,
                )

            else:
                # Developer: create PENDING_APPROVAL + approval_request
                new_record = AgentDeploymentProd(
                    agent_id=agent_id,
                    org_id=agent.org_id,
                    promoted_from_uat_id=promoted_from_uat_id,
                    version_number=next_version,
                    agent_snapshot=snapshot,
                    agent_name=agent.name,
                    agent_description=agent.description,
                    publish_description=body.publish_description,
                    deployed_by=current_user.id,
                    deployed_at=datetime.now(timezone.utc),
                    is_active=False,
                    status=DeploymentPRODStatusEnum.PENDING_APPROVAL,
                    visibility=visibility_enum,
                )
                session.add(new_record)
                await session.flush()  # get new_record.id

                # Create approval_request targeting the supplied department admin
                approval = ApprovalRequest(
                    agent_id=agent_id,
                    deployment_id=new_record.id,
                    org_id=agent.org_id,
                    dept_id=resolved_department_id,
                    requested_by=current_user.id,
                    request_to=resolved_department_admin_id,
                    requested_at=datetime.now(timezone.utc),
                    visibility_requested=visibility_enum,
                    publish_description=body.publish_description,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(approval)
                await session.flush()

                # Link approval back to deployment record
                new_record.approval_id = approval.id
                session.add(new_record)

                await session.commit()
                await session.refresh(new_record)

                logger.info(
                    f"Developer {current_user.id} submitted agent '{agent.name}' ({agent_id}) "
                    f"for PROD approval as v{next_version}. "
                    f"Approval sent to dept admin {resolved_department_admin_id} [dept={resolved_department_id}]"
                )

                return PublishActionResponse(
                    success=True,
                    message=f"Agent '{agent.name}' submitted for PROD approval as v{next_version}. "
                            f"Awaiting department admin review.",
                    publish_id=new_record.id,
                    environment="prod",
                    status=DeploymentPRODStatusEnum.PENDING_APPROVAL.value,
                    is_active=False,
                    version_number=f"v{next_version}",
                    promoted_from_uat_id=promoted_from_uat_id,
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deploying agent {agent_id} to {body.environment.value}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{agent_id}/status", response_model=AgentPublishStatusResponse, status_code=200)
async def get_agent_publish_status(
    *,
    session: DbSession,
    agent_id: UUID,
    current_user: CurrentActiveUser,
):
    """Get deployment status for an agent across both environments.

    Returns the latest active deployment record (if any) for UAT and PROD,
    plus whether there's a pending PROD approval.

    Used by the UI to show deploy badges on agent cards:
        🟢 UAT (live)  |  🔵 PROD (live)  |  🟡 PROD (pending)

    Args:
        session: Async database session.
        agent_id: UUID of the agent.
        current_user: The authenticated user.

    Returns:
        AgentPublishStatusResponse with UAT and PROD status.
    """
    try:
        # Get active UAT record (most recent)
        uat_record = (await session.exec(
            select(AgentDeploymentUAT).where(
                AgentDeploymentUAT.agent_id == agent_id,
                AgentDeploymentUAT.is_active == True,  # noqa: E712
            ).order_by(col(AgentDeploymentUAT.deployed_at).desc())
        )).first()

        # Get active PROD record (most recent)
        prod_record = (await session.exec(
            select(AgentDeploymentProd).where(
                AgentDeploymentProd.agent_id == agent_id,
                AgentDeploymentProd.is_active == True,  # noqa: E712
            ).order_by(col(AgentDeploymentProd.deployed_at).desc())
        )).first()

        # Check for any pending PROD approval
        pending = (await session.exec(
            select(AgentDeploymentProd).where(
                AgentDeploymentProd.agent_id == agent_id,
                AgentDeploymentProd.status == DeploymentPRODStatusEnum.PENDING_APPROVAL,
            )
            .order_by(col(AgentDeploymentProd.deployed_at).desc())
        )).first()

        latest_prod_any = (await session.exec(
            select(AgentDeploymentProd).where(
                AgentDeploymentProd.agent_id == agent_id,
            ).order_by(col(AgentDeploymentProd.deployed_at).desc())
        )).first()

        latest_decision: str | None = None
        if latest_prod_any and latest_prod_any.approval_id:
            latest_approval = await session.get(ApprovalRequest, latest_prod_any.approval_id)
            if latest_approval and latest_approval.decision is not None:
                latest_decision = (
                    latest_approval.decision.value
                    if hasattr(latest_approval.decision, "value")
                    else str(latest_approval.decision)
                )

        return AgentPublishStatusResponse(
            agent_id=agent_id,
            uat=_record_to_summary(uat_record, "uat") if uat_record else None,
            prod=_record_to_summary(prod_record, "prod") if prod_record else None,
            has_pending_approval=pending is not None,
            pending_requested_by=pending.deployed_by if pending else None,
            latest_prod_status=(
                latest_prod_any.status.value
                if latest_prod_any and hasattr(latest_prod_any.status, "value")
                else (str(latest_prod_any.status) if latest_prod_any else None)
            ),
            latest_review_decision=latest_decision,
            latest_prod_published_by=latest_prod_any.deployed_by if latest_prod_any else None,
        )

    except Exception as e:
        logger.error(f"Error getting deploy status for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{agent_id}/versions/{env}", response_model=list[PublishRecordSummary], status_code=200)
async def get_version_history(
    *,
    session: DbSession,
    agent_id: UUID,
    env: str,
    current_user: CurrentActiveUser,
):
    """Get version history for an agent in a specific environment.

    Returns all deployment records (all versions) for the given agent and environment,
    ordered by deployed_at descending (newest first).

    Args:
        session: Async database session.
        agent_id: UUID of the agent.
        env: Environment — must be 'uat' or 'prod'.
        current_user: The authenticated user.

    Returns:
        List of PublishRecordSummary objects representing the version timeline.

    Raises:
        400: Invalid environment value.
    """
    try:
        if env not in ("uat", "prod"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid environment '{env}'. Must be 'uat' or 'prod'.",
            )

        table_class = AgentDeploymentUAT if env == "uat" else AgentDeploymentProd
        stmt = (
            select(table_class)
            .where(table_class.agent_id == agent_id)
            .order_by(col(table_class.deployed_at).desc())
        )
        records = (await session.exec(stmt)).all()

        return [_record_to_summary(r, env) for r in records]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting version history for agent {agent_id} in {env}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{deploy_id}/snapshot", response_model=PublishSnapshotResponse, status_code=200)
async def get_publish_snapshot(
    *,
    session: DbSession,
    deploy_id: UUID,
    current_user: CurrentActiveUser,
):
    """Get the full frozen agent snapshot for a deployment record.

    Returns the complete flow JSON (nodes + edges) that was frozen at deploy time.
    This endpoint is used for:

    1. **Testing in playground** — Load the snapshot and run it as a temporary agent.
       Works for both regular **chat agents** AND **autonomous agents** because the
       snapshot contains the full flow definition that the runtime can execute.
       The frontend sends this snapshot to the existing chat/build API.

    2. **Reviewing before approval** — Dept Admin views the exact flow that will
       go live.

    3. **Inspecting a specific version** — Compare different versions' flow definitions.

    The endpoint searches both agent_deployment_uat and agent_deployment_prod tables
    (UUIDs are globally unique so there is no ambiguity).

    Args:
        session: Async database session.
        deploy_id: UUID of the deployment record (in either UAT or PROD table).
        current_user: The authenticated user.

    Returns:
        PublishSnapshotResponse with the full agent_snapshot dict.

    Raises:
        404: Deployment record not found in either table.
    """
    try:
        record, env = await _find_deploy_record(session, deploy_id)

        return PublishSnapshotResponse(
            id=record.id,
            agent_id=record.agent_id,
            environment=env,
            version_number=f"v{record.version_number}",
            agent_name=record.agent_name,
            agent_description=record.agent_description,
            agent_snapshot=record.agent_snapshot,
            publish_description=record.publish_description,
            published_by=record.deployed_by,
            published_at=record.deployed_at,
            status=record.status.value if hasattr(record.status, "value") else str(record.status),
            is_active=record.is_active,
            visibility=record.visibility.value if hasattr(record.visibility, "value") else str(record.visibility),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting snapshot for deployment {deploy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{deploy_id}/clone", response_model=CloneResponse, status_code=201)
async def clone_from_publish(
    *,
    session: DbSession,
    deploy_id: UUID,
    body: CloneFromPublishRequest,
    current_user: CurrentActiveUser,
):
    """Clone a deployed agent into a new agent (Copy on Edit pattern).

    Creates a brand-new agent in the agent table using the frozen snapshot from
    a deployment record. This is the "Copy on Edit" flow from the design.

    Sequence:
        1. Developer sees deployed agent in the Agent Registry
        2. Clicks "Copy" / "Edit" → selects target project (folder)
        3. System reads agent_snapshot from the deployment record
        4. INSERT new agent with:
           - user_id = current_user (NOT the original author)
           - project_id = selected project
           - data = frozen snapshot (the flow JSON)
           - name = original name + " (Copy)" or custom name
           - cloned_from_deployment_id = deployment record UUID (lineage tracking)
        5. User can now edit THEIR copy independently
        6. Original author's agent is UNTOUCHED

    Works for both chat agents and autonomous agents since the snapshot contains
    the complete flow definition.

    Args:
        session: Async database session.
        deploy_id: UUID of the deployment record to clone from.
        body: Clone configuration (project_id, optional new_name).
        current_user: The authenticated user who will own the clone.

    Returns:
        CloneResponse with the new agent's details.

    Raises:
        404: Deployment record not found or target folder not found.
        400: Snapshot has no usable flow data.
    """
    try:
        record, env = await _find_deploy_record(session, deploy_id)

        if not record.agent_snapshot:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Deployment record has no snapshot data to clone from",
            )

        # Verify target folder exists and belongs to user
        folder = (await session.exec(
            select(Folder).where(
                Folder.id == body.project_id,
                Folder.user_id == current_user.id,
            )
        )).first()
        if not folder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder {body.project_id} not found or not owned by you",
            )

        # Determine agent name with uniqueness handling
        base_name = body.new_name or f"{record.agent_name} (Copy)"

        existing = (await session.exec(
            select(Agent).where(Agent.name == base_name, Agent.user_id == current_user.id)
        )).first()

        if existing:
            like_pattern = f"{base_name} (%"
            copies = (await session.exec(
                select(Agent).where(
                    Agent.name.like(like_pattern),  # type: ignore[union-attr]
                    Agent.user_id == current_user.id,
                )
            )).all()
            if copies:
                extract_number = re.compile(rf"^{re.escape(base_name)} \((\d+)\)$")
                numbers = []
                for c in copies:
                    match = extract_number.search(c.name)
                    if match:
                        numbers.append(int(match.groups()[0]))
                if numbers:
                    base_name = f"{base_name} ({max(numbers) + 1})"
                else:
                    base_name = f"{base_name} (1)"
            else:
                base_name = f"{base_name} (1)"

        # Create the new agent from the snapshot
        new_agent = Agent(
            name=base_name,
            description=record.agent_description,
            data=record.agent_snapshot,
            user_id=current_user.id,
            project_id=body.project_id,
            cloned_from_deployment_id=deploy_id,
            updated_at=datetime.now(timezone.utc),
        )
        session.add(new_agent)
        await session.commit()
        await session.refresh(new_agent)

        logger.info(
            f"User {current_user.id} cloned agent from {env} deployment {deploy_id} → "
            f"new agent '{base_name}' ({new_agent.id})"
        )

        return CloneResponse(
            agent_id=new_agent.id,
            agent_name=new_agent.name,
            project_id=new_agent.project_id,
            cloned_from_publish_id=deploy_id,
            environment_source=env,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cloning from deployment {deploy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
