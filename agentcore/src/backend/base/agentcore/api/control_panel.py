"""AgentCore Control Panel API.
Provides dashboard statistics, recent activity history, and a live agent
management table (the "Agent Control Panel" page) for toggling is_active
(Start/Stop) and is_enabled (Enable/Disable) per deployed agent.

Endpoints:
    GET  /control-panel/stats            — Aggregate KPIs for the dashboard
    GET  /control-panel/history          — Recent deployment activity
    GET  /control-panel/agents           — Paginated agent table (UAT or PROD)
    POST /control-panel/agents/{id}/toggle — Toggle is_active or is_enabled
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum as PyEnum
import re
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import or_, true
from sqlmodel import col, func, select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.approval_request.model import (
    ApprovalRequest,
)
from agentcore.services.database.models.agent_deployment_prod.model import (
    AgentDeploymentProd,
    DeploymentPRODStatusEnum,
    ProdDeploymentLifecycleEnum,
    ProdDeploymentVisibilityEnum,
)
from agentcore.services.database.models.agent_deployment_uat.model import (
    AgentDeploymentUAT,
    DeploymentVisibilityEnum,
    DeploymentUATStatusEnum,
)
from agentcore.services.database.models.agent_registry.model import AgentRegistry, RegistryDeploymentEnvEnum
from agentcore.services.database.models.agent_publish_recipient.model import AgentPublishRecipient
from agentcore.services.database.models.transaction_uat.model import TransactionUATTable
from agentcore.services.database.models.transaction_prod.model import TransactionProdTable
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.agent.model import Agent, LifecycleStatusEnum
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.user.model import User
from agentcore.services.database.registry_service import sync_agent_registry

router = APIRouter(prefix="/control-panel", tags=["Control Panel"])


# ═══════════════════════════════════════════════════════════════════════════
# Response Schemas
# ═══════════════════════════════════════════════════════════════════════════


class EnvironmentStats(BaseModel):
    """Statistics for a single environment (UAT)."""

    total: int = 0
    published: int = 0
    unpublished: int = 0
    error: int = 0
    active: int = 0


class ProdStats(EnvironmentStats):
    """PROD-specific stats with pending approval count."""

    pending_approval: int = 0


class ControlPanelStatsResponse(BaseModel):
    """Aggregated statistics for the control panel dashboard.
    Contains counts broken down by environment and status,
    plus the number of pending approval requests.
    """

    uat: EnvironmentStats
    prod: ProdStats
    pending_approvals: int = 0


class RecentActivityItem(BaseModel):
    """Single item in the recent activity feed.
    Represents one deployment event across either environment.
    """

    id: UUID
    environment: str  # "uat" or "prod"
    agent_id: UUID
    agent_name: str
    version_number: str
    status: str
    is_active: bool
    published_by: UUID
    published_by_username: str | None = None
    published_at: datetime


# ── Agent Control Panel (list / toggle) schemas ──────────────────────────

class ControlPanelEnv(str, PyEnum):
    """Allowed environment values for the control panel."""
    UAT = "uat"
    PROD = "prod"


class ControlPanelAgentItem(BaseModel):
    """Single row in the Agent Control Panel table."""

    deploy_id: UUID
    agent_id: UUID
    agent_name: str
    agent_description: str | None = None
    version_number: str
    status: str
    visibility: str
    is_active: bool
    is_enabled: bool
    creator_name: str | None = None
    creator_email: str | None = None
    owner_name: str | None = None
    owner_count: int = 0
    owner_names: list[str] = []
    owner_emails: list[str] = []
    creator_department: str | None = None
    created_at: datetime
    deployed_at: datetime | None = None
    last_run: datetime | None = None      # placeholder – no model field yet
    failed_runs: int = 0                   # placeholder – no model field yet
    input_type: str = "autonomous"         # "chat" | "autonomous" | "file_processing" — from snapshot._input_type
    moved_to_prod: bool = False


class ControlPanelAgentsResponse(BaseModel):
    """Paginated response for the agent list."""

    items: list[ControlPanelAgentItem]
    total: int
    page: int
    size: int


class ToggleField(str, PyEnum):
    """Which boolean column to flip."""
    IS_ACTIVE = "is_active"
    IS_ENABLED = "is_enabled"


class ToggleRequest(BaseModel):
    """Body for the toggle endpoint."""
    field: ToggleField
    value: bool
    env: ControlPanelEnv


class ToggleResponse(BaseModel):
    """Confirmation after toggling."""
    deploy_id: UUID
    field: str
    new_value: bool
    registry_synced: bool = False


class SharingOptionsResponse(BaseModel):
    deploy_id: UUID
    agent_id: UUID
    department_id: UUID | None = None
    recipient_emails: list[str] = []


class SharingOptionsUpdateRequest(BaseModel):
    recipient_emails: list[str] = []


class PromoteFromUATRequest(BaseModel):
    visibility: str = "PRIVATE"
    publish_description: str | None = None
    recipient_emails: list[str] = []


class PromoteFromUATResponse(BaseModel):
    success: bool
    message: str
    publish_id: UUID
    environment: str
    status: str
    is_active: bool
    version_number: str


EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ADMIN_ROLES = {"root", "super_admin", "admin", "department_admin"}


def _normalize_email_list(raw_emails: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_email in raw_emails:
        email = str(raw_email).strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        normalized.append(email)
    return normalized


def _name_from_user(username: str | None, display_name: str | None, fallback_email: str | None = None) -> str:
    if display_name and str(display_name).strip():
        return str(display_name).strip()
    candidate = str(username or "").strip()
    if candidate and "@" not in candidate:
        return candidate
    email_source = str(fallback_email or candidate).strip()
    if email_source and "@" in email_source:
        return email_source.split("@", 1)[0]
    return candidate or "-"


def _email_from_user(username: str | None, email: str | None, fallback_email: str | None = None) -> str | None:
    explicit_email = str(email or "").strip()
    if explicit_email:
        return explicit_email
    user_name = str(username or "").strip()
    if "@" in user_name:
        return user_name
    fallback = str(fallback_email or "").strip()
    return fallback or None


async def _get_deployment_or_404(
    session: DbSession,
    deploy_id: UUID,
) -> tuple[AgentDeploymentUAT | AgentDeploymentProd, ControlPanelEnv]:
    uat_dep = (await session.exec(select(AgentDeploymentUAT).where(AgentDeploymentUAT.id == deploy_id))).first()
    if uat_dep:
        return uat_dep, ControlPanelEnv.UAT
    prod_dep = (await session.exec(select(AgentDeploymentProd).where(AgentDeploymentProd.id == deploy_id))).first()
    if prod_dep:
        return prod_dep, ControlPanelEnv.PROD
    raise HTTPException(status_code=404, detail="Deployment not found")


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/stats", response_model=ControlPanelStatsResponse, status_code=200)
async def get_control_panel_stats(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Get aggregated statistics for the control panel dashboard.

    Returns counts of deployed agents by environment and status.
    Includes:
        - UAT: total, published, unpublished, error, active count
        - PROD: total, published, unpublished, error, pending_approval, active count
        - Pending approvals count
    """
    try:
        # ─── UAT Stats ───────────────────────────────────────────
        uat_records = (await session.exec(select(AgentDeploymentUAT))).all()

        uat_stats = EnvironmentStats(
            total=len(uat_records),
            published=sum(1 for r in uat_records if r.status == DeploymentUATStatusEnum.PUBLISHED),
            unpublished=sum(1 for r in uat_records if r.status == DeploymentUATStatusEnum.UNPUBLISHED),
            error=sum(1 for r in uat_records if r.status == DeploymentUATStatusEnum.ERROR),
            active=sum(1 for r in uat_records if r.is_active),
        )

        # ─── PROD Stats ──────────────────────────────────────────
        prod_records = (await session.exec(select(AgentDeploymentProd))).all()

        prod_stats = ProdStats(
            total=len(prod_records),
            published=sum(1 for r in prod_records if r.status == DeploymentPRODStatusEnum.PUBLISHED),
            unpublished=sum(1 for r in prod_records if r.status == DeploymentPRODStatusEnum.UNPUBLISHED),
            error=sum(1 for r in prod_records if r.status == DeploymentPRODStatusEnum.ERROR),
            pending_approval=sum(
                1 for r in prod_records if r.status == DeploymentPRODStatusEnum.PENDING_APPROVAL
            ),
            active=sum(1 for r in prod_records if r.is_active),
        )

        # ─── Pending approvals count ─────────────────────────────
        pending_records = (await session.exec(
            select(ApprovalRequest).where(ApprovalRequest.decision == None)  # noqa: E711
        )).all()
        pending_count = len(pending_records)

        return ControlPanelStatsResponse(
            uat=uat_stats,
            prod=prod_stats,
            pending_approvals=pending_count,
        )

    except Exception as e:
        logger.error(f"Error getting control panel stats: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/history", response_model=list[RecentActivityItem], status_code=200)
async def get_recent_activity(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    limit: int = Query(20, ge=1, le=100, description="Max items to return"),
):
    """Get recent deployment activity across both environments.

    Returns the most recent deployment events sorted by deployed_at descending.
    Combines records from both UAT and PROD tables.
    """
    try:
        items: list[RecentActivityItem] = []

        # ─── UAT records ──────────────────────────────────────────
        uat_stmt = (
            select(AgentDeploymentUAT)
            .order_by(col(AgentDeploymentUAT.deployed_at).desc())
            .limit(limit)
        )
        uat_records = (await session.exec(uat_stmt)).all()

        for r in uat_records:
            user = (await session.exec(select(User).where(User.id == r.deployed_by))).first()
            items.append(RecentActivityItem(
                id=r.id,
                environment="uat",
                agent_id=r.agent_id,
                agent_name=r.agent_name,
                version_number=f"v{r.version_number}",
                status=r.status.value if hasattr(r.status, "value") else str(r.status),
                is_active=r.is_active,
                published_by=r.deployed_by,
                published_by_username=user.username if user else None,
                published_at=r.deployed_at,
            ))

        # ─── PROD records ─────────────────────────────────────────
        prod_stmt = (
            select(AgentDeploymentProd)
            .order_by(col(AgentDeploymentProd.deployed_at).desc())
            .limit(limit)
        )
        prod_records = (await session.exec(prod_stmt)).all()

        for r in prod_records:
            user = (await session.exec(select(User).where(User.id == r.deployed_by))).first()
            items.append(RecentActivityItem(
                id=r.id,
                environment="prod",
                agent_id=r.agent_id,
                agent_name=r.agent_name,
                version_number=f"v{r.version_number}",
                status=r.status.value if hasattr(r.status, "value") else str(r.status),
                is_active=r.is_active,
                published_by=r.deployed_by,
                published_by_username=user.username if user else None,
                published_at=r.deployed_at,
            ))

        # Sort combined list by published_at descending and limit
        items.sort(key=lambda x: x.published_at, reverse=True)
        return items[:limit]

    except Exception as e:
        logger.error(f"Error getting recent activity: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ═══════════════════════════════════════════════════════════════════════════
# Agent Control Panel – List & Toggle
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/agents", response_model=ControlPanelAgentsResponse, status_code=200)
async def list_control_panel_agents(
    session: DbSession,
    current_user: CurrentActiveUser,
    env: ControlPanelEnv = Query(ControlPanelEnv.UAT, description="Target environment"),
    search: str | None = Query(None, description="Filter by agent name (case-insensitive)"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> ControlPanelAgentsResponse:
    """Return a paginated list of deployed agents for the Agent Control Panel.

    Joined with the User table to surface creator name & department.
    """
    try:
        # Pick the right model
        Model = AgentDeploymentProd if env == ControlPanelEnv.PROD else AgentDeploymentUAT
        published_status = (
            DeploymentPRODStatusEnum.PUBLISHED
            if env == ControlPanelEnv.PROD
            else DeploymentUATStatusEnum.PUBLISHED
        )
        public_visibility = (
            ProdDeploymentVisibilityEnum.PUBLIC
            if env == ControlPanelEnv.PROD
            else DeploymentVisibilityEnum.PUBLIC
        )
        private_visibility = (
            ProdDeploymentVisibilityEnum.PRIVATE
            if env == ControlPanelEnv.PROD
            else DeploymentVisibilityEnum.PRIVATE
        )
        private_share_exists = (
            select(AgentPublishRecipient.id)
            .where(
                AgentPublishRecipient.agent_id == Model.agent_id,  # type: ignore[arg-type]
                AgentPublishRecipient.recipient_user_id == current_user.id,
                or_(
                    Model.dept_id.is_(None),  # type: ignore[attr-defined]
                    AgentPublishRecipient.dept_id == Model.dept_id,  # type: ignore[arg-type]
                ),
            )
            .exists()
        )
        dept_member_exists = (
            select(UserDepartmentMembership.id)
            .where(
                UserDepartmentMembership.user_id == current_user.id,
                UserDepartmentMembership.department_id == Model.dept_id,  # type: ignore[arg-type]
                UserDepartmentMembership.status == "active",
            )
            .exists()
        )

        # ── Base query ──────────────────────────────────────────────
        base_stmt = (
            select(
                Model,
                User.username.label("creator_username"),  # type: ignore[attr-defined]
                User.display_name.label("creator_display_name"),  # type: ignore[attr-defined]
                User.email.label("creator_email"),  # type: ignore[attr-defined]
                User.department_name.label("creator_department"),  # type: ignore[attr-defined]
            )
            .outerjoin(User, Model.deployed_by == User.id)  # type: ignore[arg-type]
            .where(Model.status == published_status)  # type: ignore[arg-type]
        )
        private_access_expr = (
            (Model.deployed_by == current_user.id)  # type: ignore[arg-type]
            | private_share_exists
        )
        if env == ControlPanelEnv.PROD:
            current_role = str(getattr(current_user, "role", "")).lower()
            prod_admin_public_roles = {"super_admin", "department_admin", "root"}
            if current_role in prod_admin_public_roles:
                # Admins should be able to see private PROD deployments in control panel.
                private_access_expr = private_access_expr | true()
            public_access_expr = private_access_expr | dept_member_exists
            stmt = base_stmt.where(
                (
                    (Model.visibility == public_visibility)  # type: ignore[arg-type]
                    & public_access_expr
                )
                | (
                    (Model.visibility == private_visibility)  # type: ignore[arg-type]
                    & private_access_expr
                )
            )
        else:
            stmt = base_stmt.where(
                (Model.visibility == public_visibility)  # type: ignore[arg-type]
                | (
                    (Model.visibility == private_visibility)  # type: ignore[arg-type]
                    & private_access_expr
                )
            )

        # Hide UAT rows when the same agent is already moved/running in PROD.
        if env == ControlPanelEnv.UAT:
            prod_exists_for_agent = (
                select(AgentDeploymentProd.id)
                .where(
                    AgentDeploymentProd.agent_id == AgentDeploymentUAT.agent_id,
                    AgentDeploymentProd.status.in_(
                        [
                            DeploymentPRODStatusEnum.PUBLISHED,
                            DeploymentPRODStatusEnum.PENDING_APPROVAL,
                        ]
                    ),
                )
                .exists()
            )
            stmt = stmt.where(~prod_exists_for_agent)

        # ── Search filter ──────────────────────────────────────────
        if search:
            stmt = stmt.where(col(Model.agent_name).ilike(f"%{search}%"))

        # ── Total count (before pagination) ────────────────────────
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = (await session.exec(count_stmt)).one()  # type: ignore[assignment]

        # ── Pagination + ordering ──────────────────────────────────
        offset = (page - 1) * size
        stmt = stmt.order_by(col(Model.deployed_at).desc()).offset(offset).limit(size)
        rows = (await session.exec(stmt)).all()

        # Build owner map from sharing table (agent_id + dept_id -> recipients)
        dep_pairs = {
            (str(row[0].agent_id), str(row[0].dept_id) if row[0].dept_id else None)
            for row in rows
        }
        dep_agent_ids = {pair[0] for pair in dep_pairs}
        owner_by_pair: dict[tuple[str, str | None], list[str]] = {}
        owner_emails_by_pair: dict[tuple[str, str | None], list[str]] = {}
        owner_by_agent: dict[str, list[str]] = {}
        owner_emails_by_agent: dict[str, list[str]] = {}
        if dep_pairs:
            agent_ids = list({UUID(pair[0]) for pair in dep_pairs})
            recipient_rows = (
                await session.exec(
                    select(AgentPublishRecipient, User)
                    .join(User, User.id == AgentPublishRecipient.recipient_user_id)
                    .where(AgentPublishRecipient.agent_id.in_(agent_ids))
                    .order_by(col(AgentPublishRecipient.updated_at).desc())
                )
            ).all()
            for recipient, owner_user in recipient_rows:
                key = (str(recipient.agent_id), str(recipient.dept_id) if recipient.dept_id else None)
                owner_label = _name_from_user(
                    owner_user.username,
                    owner_user.display_name,
                    recipient.recipient_email,
                )
                owner_email = _email_from_user(
                    owner_user.username,
                    owner_user.email,
                    recipient.recipient_email,
                )
                if key in dep_pairs:
                    owner_by_pair.setdefault(key, [])
                    owner_emails_by_pair.setdefault(key, [])
                    if owner_label not in owner_by_pair[key]:
                        owner_by_pair[key].append(owner_label)
                    if owner_email and owner_email not in owner_emails_by_pair[key]:
                        owner_emails_by_pair[key].append(owner_email)

                agent_key = str(recipient.agent_id)
                if agent_key in dep_agent_ids:
                    owner_by_agent.setdefault(agent_key, [])
                    owner_emails_by_agent.setdefault(agent_key, [])
                    if owner_label not in owner_by_agent[agent_key]:
                        owner_by_agent[agent_key].append(owner_label)
                    if owner_email and owner_email not in owner_emails_by_agent[agent_key]:
                        owner_emails_by_agent[agent_key].append(owner_email)

        items: list[ControlPanelAgentItem] = []
        for row in rows:
            dep = row[0]  # deployment model instance
            creator_username = row[1]
            creator_display_name = row[2]
            creator_email = row[3]
            creator = _name_from_user(creator_username, creator_display_name, creator_email)
            creator_email_value = _email_from_user(creator_username, creator_email)
            department = row[4]  # department_name or None
            owner_key = (str(dep.agent_id), str(dep.dept_id) if dep.dept_id else None)
            owners = owner_by_pair.get(owner_key, [])
            owner_emails = owner_emails_by_pair.get(owner_key, [])
            if not owners:
                owners = owner_by_agent.get(str(dep.agent_id), [])
                owner_emails = owner_emails_by_agent.get(str(dep.agent_id), [])

            # Query transaction table for last_run and failed_runs
            TxnModel = TransactionProdTable if env == ControlPanelEnv.PROD else TransactionUATTable

            last_run_result = (await session.exec(
                select(func.max(TxnModel.timestamp)).where(TxnModel.agent_id == dep.agent_id)
            )).first()
            last_run = last_run_result if last_run_result else None

            failed_count = (await session.exec(
                select(func.count()).where(
                    TxnModel.agent_id == dep.agent_id,
                    TxnModel.status == "error",
                )
            )).one()
            failed_runs = failed_count or 0

            # Read _input_type from the snapshot (set at publish time)
            snap = dep.agent_snapshot or {}
            _input_type = snap.get("_input_type", "autonomous")

            items.append(
                ControlPanelAgentItem(
                    deploy_id=dep.id,
                    agent_id=dep.agent_id,
                    agent_name=dep.agent_name,
                    agent_description=dep.agent_description,
                    version_number=f"v{dep.version_number}",
                    status=dep.status.value if hasattr(dep.status, "value") else str(dep.status),
                    visibility=dep.visibility.value if hasattr(dep.visibility, "value") else str(dep.visibility),
                    is_active=dep.is_active,
                    is_enabled=dep.is_enabled,
                    creator_name=creator,
                    creator_email=creator_email_value,
                    owner_name=owners[0] if owners else None,
                    owner_count=len(owners),
                    owner_names=owners,
                    owner_emails=owner_emails,
                    creator_department=department,
                    created_at=dep.created_at,
                    deployed_at=dep.deployed_at,
                    last_run=last_run,
                    failed_runs=failed_runs,
                    input_type=_input_type,
                    moved_to_prod=bool(env == ControlPanelEnv.PROD),
                )
            )

        return ControlPanelAgentsResponse(items=items, total=total, page=page, size=size)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing control panel agents: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/agents/{deploy_id}/toggle", response_model=ToggleResponse, status_code=200)
async def toggle_agent_field(
    deploy_id: UUID,
    body: ToggleRequest,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> ToggleResponse:
    """Toggle ``is_active`` (Start / Stop) or ``is_enabled`` (Enable / Disable)
    for a specific deployment.

    After updating the flag the registry is synced so that an agent which no
    longer meets all four qualifying conditions is automatically de‑listed.
    """
    try:
        Model = AgentDeploymentProd if body.env == ControlPanelEnv.PROD else AgentDeploymentUAT

        dep = (
            await session.exec(
                select(Model).where(Model.id == deploy_id)
            )
        ).first()

        if dep is None:
            raise HTTPException(status_code=404, detail="Deployment not found")

        # ── Apply the toggle ───────────────────────────────────────
        setattr(dep, body.field.value, body.value)
        dep.updated_at = datetime.now(timezone.utc)
        session.add(dep)
        await session.commit()
        await session.refresh(dep)

        # ── Sync registry ──────────────────────────────────────────
        registry_env = (
            RegistryDeploymentEnvEnum.PROD
            if body.env == ControlPanelEnv.PROD
            else RegistryDeploymentEnvEnum.UAT
        )
        registry_synced = False

        def _should_be_listed() -> bool:
            if body.env == ControlPanelEnv.PROD:
                return (
                    dep.is_active
                    and dep.is_enabled
                    and dep.status == DeploymentPRODStatusEnum.PUBLISHED
                    and dep.visibility == ProdDeploymentVisibilityEnum.PUBLIC
                )
            return (
                dep.is_active
                and dep.is_enabled
                and dep.status == DeploymentUATStatusEnum.PUBLISHED
                and dep.visibility == DeploymentVisibilityEnum.PUBLIC
            )

        async def _has_registry_row() -> bool:
            row = (
                await session.exec(
                    select(AgentRegistry).where(
                        AgentRegistry.agent_deployment_id == dep.id,
                        AgentRegistry.deployment_env == registry_env,
                    )
                )
            ).first()
            return row is not None

        try:
            # First pass sync
            await sync_agent_registry(
                session=session,
                agent_id=dep.agent_id,
                org_id=dep.org_id,
                acted_by=current_user.id,
                deployment_env=registry_env,
            )
            await session.commit()

            # Verify expected registry state. If mismatched, run one more sync pass.
            should_be_listed = _should_be_listed()
            is_listed = await _has_registry_row()
            if should_be_listed != is_listed:
                await sync_agent_registry(
                    session=session,
                    agent_id=dep.agent_id,
                    org_id=dep.org_id,
                    acted_by=current_user.id,
                    deployment_env=registry_env,
                )
                await session.commit()
                is_listed = await _has_registry_row()

            if should_be_listed != is_listed:
                raise RuntimeError(
                    f"Registry state mismatch after toggle for deployment {dep.id}: "
                    f"should_be_listed={should_be_listed}, is_listed={is_listed}"
                )

            registry_synced = True
        except Exception as sync_err:
            await session.rollback()
            logger.warning(f"Registry sync after toggle failed: {sync_err}")
        logger.info(
            f"Control-panel toggle: deploy_id={deploy_id} "
            f"field={body.field.value} → {body.value} (env={body.env.value}, "
            f"user={current_user.username})"
        )

        return ToggleResponse(
            deploy_id=dep.id,
            field=body.field.value,
            new_value=body.value,
            registry_synced=registry_synced,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling agent field: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/agents/{deploy_id}/sharing", response_model=SharingOptionsResponse, status_code=200)
async def get_agent_sharing_options(
    deploy_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> SharingOptionsResponse:
    try:
        deployment, _ = await _get_deployment_or_404(session, deploy_id)
        dept_id = deployment.dept_id
        if dept_id is None:
            agent = await session.get(Agent, deployment.agent_id)
            dept_id = agent.dept_id if agent else None

        rows = (
            await session.exec(
                select(AgentPublishRecipient)
                .where(
                    AgentPublishRecipient.agent_id == deployment.agent_id,
                    AgentPublishRecipient.dept_id == dept_id,
                )
                .order_by(col(AgentPublishRecipient.updated_at).desc())
            )
        ).all() if dept_id else []

        return SharingOptionsResponse(
            deploy_id=deploy_id,
            agent_id=deployment.agent_id,
            department_id=dept_id,
            recipient_emails=[row.recipient_email for row in rows],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching sharing options for deployment {deploy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/agents/{deploy_id}/sharing", response_model=SharingOptionsResponse, status_code=200)
async def update_agent_sharing_options(
    deploy_id: UUID,
    body: SharingOptionsUpdateRequest,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> SharingOptionsResponse:
    try:
        deployment, _ = await _get_deployment_or_404(session, deploy_id)
        current_role = str(getattr(current_user, "role", "")).lower()
        can_manage = current_role in ADMIN_ROLES or deployment.deployed_by == current_user.id
        if not can_manage:
            raise HTTPException(status_code=403, detail="You do not have permission to update sharing options.")

        dept_id = deployment.dept_id
        if dept_id is None:
            agent = await session.get(Agent, deployment.agent_id)
            dept_id = agent.dept_id if agent else None
        if dept_id is None:
            raise HTTPException(status_code=400, detail="Department is not resolved for this deployment.")

        normalized_emails = _normalize_email_list(body.recipient_emails)
        invalid_emails = [email for email in normalized_emails if not EMAIL_REGEX.match(email)]
        if invalid_emails:
            raise HTTPException(status_code=400, detail=f"Invalid email format: {', '.join(invalid_emails)}")

        now = datetime.now(timezone.utc)
        existing_rows = (
            await session.exec(
                select(AgentPublishRecipient).where(
                    AgentPublishRecipient.agent_id == deployment.agent_id,
                    AgentPublishRecipient.dept_id == dept_id,
                )
            )
        ).all()
        existing_by_email = {row.recipient_email: row for row in existing_rows}
        next_emails = set(normalized_emails)

        # Remove recipients that are no longer shared.
        for row in existing_rows:
            if row.recipient_email not in next_emails:
                await session.delete(row)

        if normalized_emails:
            user_rows = (
                await session.exec(
                    select(User).where(
                        or_(
                            func.lower(User.username).in_(normalized_emails),
                            func.lower(User.email).in_(normalized_emails),
                        )
                    )
                )
            ).all()
            users_by_email: dict[str, User] = {}
            for user in user_rows:
                if user.username:
                    users_by_email[str(user.username).strip().lower()] = user
                if user.email:
                    users_by_email[str(user.email).strip().lower()] = user

            missing_users = [email for email in normalized_emails if email not in users_by_email]
            if missing_users:
                raise HTTPException(status_code=400, detail=f"User not found for emails: {', '.join(missing_users)}")

            memberships = (
                await session.exec(
                    select(UserDepartmentMembership).where(
                        UserDepartmentMembership.user_id.in_([users_by_email[email].id for email in normalized_emails]),
                        UserDepartmentMembership.department_id == dept_id,
                        UserDepartmentMembership.status == "active",
                    )
                )
            ).all()
            allowed_user_ids = {membership.user_id for membership in memberships}
            invalid_membership = [
                email for email in normalized_emails if users_by_email[email].id not in allowed_user_ids
            ]
            if invalid_membership:
                raise HTTPException(
                    status_code=400,
                    detail=f"Users not in department: {', '.join(invalid_membership)}",
                )

            for email in normalized_emails:
                user = users_by_email[email]
                existing = existing_by_email.get(email)
                if existing:
                    existing.recipient_user_id = user.id
                    existing.updated_at = now
                    session.add(existing)
                    continue
                session.add(
                    AgentPublishRecipient(
                        agent_id=deployment.agent_id,
                        org_id=deployment.org_id,
                        dept_id=dept_id,
                        recipient_user_id=user.id,
                        recipient_email=email,
                        created_by=current_user.id,
                        created_at=now,
                        updated_at=now,
                    )
                )

        await session.commit()

        refreshed_rows = (
            await session.exec(
                select(AgentPublishRecipient)
                .where(
                    AgentPublishRecipient.agent_id == deployment.agent_id,
                    AgentPublishRecipient.dept_id == dept_id,
                )
                .order_by(col(AgentPublishRecipient.updated_at).desc())
            )
        ).all()

        return SharingOptionsResponse(
            deploy_id=deploy_id,
            agent_id=deployment.agent_id,
            department_id=dept_id,
            recipient_emails=[row.recipient_email for row in refreshed_rows],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating sharing options for deployment {deploy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/agents/{deploy_id}/promote", response_model=PromoteFromUATResponse, status_code=201)
async def promote_uat_to_prod(
    deploy_id: UUID,
    body: PromoteFromUATRequest,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> PromoteFromUATResponse:
    try:
        uat_dep = (
            await session.exec(
                select(AgentDeploymentUAT).where(AgentDeploymentUAT.id == deploy_id)
            )
        ).first()
        if not uat_dep:
            raise HTTPException(status_code=404, detail="UAT deployment not found.")
        if uat_dep.status != DeploymentUATStatusEnum.PUBLISHED:
            raise HTTPException(status_code=400, detail="Only PUBLISHED UAT deployments can be promoted.")

        agent = await session.get(Agent, uat_dep.agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found.")
        department_id = uat_dep.dept_id or agent.dept_id
        if not department_id:
            raise HTTPException(status_code=400, detail="Department is required for PROD promotion.")
        department = (await session.exec(select(Department).where(Department.id == department_id))).first()
        if not department:
            raise HTTPException(status_code=400, detail="Department not found for this deployment.")

        requested_visibility = str(body.visibility).strip().upper() or "PRIVATE"
        try:
            visibility_enum = ProdDeploymentVisibilityEnum(requested_visibility)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid visibility. Use PUBLIC or PRIVATE.") from exc
        normalized_recipient_emails = _normalize_email_list(body.recipient_emails or [])

        max_version = (
            await session.exec(
                select(func.max(AgentDeploymentProd.version_number)).where(
                    AgentDeploymentProd.agent_id == uat_dep.agent_id
                )
            )
        ).one()
        next_version = int(max_version or 0) + 1
        role = str(getattr(current_user, "role", "")).lower()
        is_admin = role in ADMIN_ROLES

        new_record = AgentDeploymentProd(
            agent_id=uat_dep.agent_id,
            org_id=uat_dep.org_id,
            dept_id=department_id,
            promoted_from_uat_id=uat_dep.id,
            version_number=next_version,
            agent_snapshot=(uat_dep.agent_snapshot or {}).copy(),
            agent_name=uat_dep.agent_name,
            agent_description=uat_dep.agent_description,
            publish_description=body.publish_description,
            deployed_by=current_user.id,
            deployed_at=datetime.now(timezone.utc),
            is_active=is_admin,
            status=(
                DeploymentPRODStatusEnum.PUBLISHED
                if is_admin
                else DeploymentPRODStatusEnum.PENDING_APPROVAL
            ),
            lifecycle_step=(
                ProdDeploymentLifecycleEnum.PUBLISHED
                if is_admin
                else ProdDeploymentLifecycleEnum.DRAFT
            ),
            visibility=visibility_enum,
        )
        session.add(new_record)
        await session.flush()

        if is_admin:
            agent.lifecycle_status = LifecycleStatusEnum.PUBLISHED
        else:
            agent.lifecycle_status = LifecycleStatusEnum.PENDING_APPROVAL
            approval = ApprovalRequest(
                agent_id=uat_dep.agent_id,
                deployment_id=new_record.id,
                org_id=uat_dep.org_id,
                dept_id=department_id,
                requested_by=current_user.id,
                request_to=department.admin_user_id,
                requested_at=datetime.now(timezone.utc),
                visibility_requested=visibility_enum,
                publish_description=body.publish_description,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(approval)
            await session.flush()
            new_record.approval_id = approval.id
            session.add(new_record)

        session.add(agent)

        if visibility_enum == ProdDeploymentVisibilityEnum.PRIVATE:
            invalid_emails = [email for email in normalized_recipient_emails if not EMAIL_REGEX.match(email)]
            if invalid_emails:
                raise HTTPException(status_code=400, detail=f"Invalid email format: {', '.join(invalid_emails)}")

            now = datetime.now(timezone.utc)
            existing_rows = (
                await session.exec(
                    select(AgentPublishRecipient).where(
                        AgentPublishRecipient.agent_id == uat_dep.agent_id,
                        AgentPublishRecipient.dept_id == department_id,
                    )
                )
            ).all()
            existing_by_email = {row.recipient_email: row for row in existing_rows}
            next_emails = set(normalized_recipient_emails)

            for row in existing_rows:
                if row.recipient_email not in next_emails:
                    await session.delete(row)

            if normalized_recipient_emails:
                user_rows = (
                    await session.exec(
                        select(User).where(
                            or_(
                                func.lower(User.username).in_(normalized_recipient_emails),
                                func.lower(User.email).in_(normalized_recipient_emails),
                            )
                        )
                    )
                ).all()
                users_by_email: dict[str, User] = {}
                for user in user_rows:
                    if user.username:
                        users_by_email[str(user.username).strip().lower()] = user
                    if user.email:
                        users_by_email[str(user.email).strip().lower()] = user

                missing_users = [
                    email for email in normalized_recipient_emails if email not in users_by_email
                ]
                if missing_users:
                    raise HTTPException(
                        status_code=400,
                        detail=f"User not found for emails: {', '.join(missing_users)}",
                    )

                memberships = (
                    await session.exec(
                        select(UserDepartmentMembership).where(
                            UserDepartmentMembership.user_id.in_(
                                [users_by_email[email].id for email in normalized_recipient_emails]
                            ),
                            UserDepartmentMembership.department_id == department_id,
                            UserDepartmentMembership.status == "active",
                        )
                    )
                ).all()
                allowed_user_ids = {membership.user_id for membership in memberships}
                invalid_membership = [
                    email
                    for email in normalized_recipient_emails
                    if users_by_email[email].id not in allowed_user_ids
                ]
                if invalid_membership:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Users not in department: {', '.join(invalid_membership)}",
                    )

                for email in normalized_recipient_emails:
                    user = users_by_email[email]
                    existing = existing_by_email.get(email)
                    if existing:
                        existing.recipient_user_id = user.id
                        existing.updated_at = now
                        session.add(existing)
                        continue
                    session.add(
                        AgentPublishRecipient(
                            agent_id=uat_dep.agent_id,
                            org_id=uat_dep.org_id,
                            dept_id=department_id,
                            recipient_user_id=user.id,
                            recipient_email=email,
                            created_by=current_user.id,
                            created_at=now,
                            updated_at=now,
                        )
                    )

        await session.commit()
        await session.refresh(new_record)

        if is_admin:
            try:
                await sync_agent_registry(
                    session=session,
                    agent_id=uat_dep.agent_id,
                    org_id=uat_dep.org_id,
                    acted_by=current_user.id,
                    deployment_env=RegistryDeploymentEnvEnum.PROD,
                )
                await session.commit()
            except Exception as sync_err:
                logger.warning(f"Registry sync failed for promoted PROD deploy {new_record.id}: {sync_err}")

        return PromoteFromUATResponse(
            success=True,
            message=(
                f"UAT {uat_dep.id} moved to PROD as v{next_version}"
                if is_admin
                else f"UAT {uat_dep.id} submitted for PROD approval as v{next_version}"
            ),
            publish_id=new_record.id,
            environment="prod",
            status=new_record.status.value if hasattr(new_record.status, "value") else str(new_record.status),
            is_active=new_record.is_active,
            version_number=f"v{next_version}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error promoting UAT deployment {deploy_id} to PROD: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
