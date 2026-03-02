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
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel
from sqlmodel import col, func, select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.approval_request.model import (
    ApprovalRequest,
)
from agentcore.services.database.models.agent_deployment_prod.model import (
    AgentDeploymentProd,
    DeploymentPRODStatusEnum,
    ProdDeploymentVisibilityEnum,
)
from agentcore.services.database.models.agent_deployment_uat.model import (
    AgentDeploymentUAT,
    DeploymentVisibilityEnum,
    DeploymentUATStatusEnum,
)
from agentcore.services.database.models.agent_registry.model import RegistryDeploymentEnvEnum
from agentcore.services.database.models.transaction_uat.model import TransactionUATTable
from agentcore.services.database.models.transaction_prod.model import TransactionProdTable
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
    creator_department: str | None = None
    created_at: datetime
    deployed_at: datetime | None = None
    last_run: datetime | None = None      # placeholder – no model field yet
    failed_runs: int = 0                   # placeholder – no model field yet
    input_type: str = "autonomous"         # "chat" | "autonomous" | "file_processing" — from snapshot._input_type


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

        # ── Base query ──────────────────────────────────────────────
        stmt = (
            select(
                Model,
                User.username.label("creator_name"),  # type: ignore[attr-defined]
                User.department_name.label("creator_department"),  # type: ignore[attr-defined]
            )
            .outerjoin(User, Model.deployed_by == User.id)  # type: ignore[arg-type]
            .where(Model.status == published_status)  # type: ignore[arg-type]
            .where(
                (Model.visibility == public_visibility)  # type: ignore[arg-type]
                | (
                    (Model.visibility == private_visibility)  # type: ignore[arg-type]
                    & (Model.deployed_by == current_user.id)  # type: ignore[arg-type]
                )
            )
        )

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

        items: list[ControlPanelAgentItem] = []
        for row in rows:
            dep = row[0]  # deployment model instance
            creator = row[1]  # username or None
            department = row[2]  # department_name or None

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
                    creator_department=department,
                    created_at=dep.created_at,
                    deployed_at=dep.deployed_at,
                    last_run=last_run,
                    failed_runs=failed_runs,
                    input_type=_input_type,
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
        try:
            await sync_agent_registry(
                session=session,
                agent_id=dep.agent_id,
                org_id=dep.org_id,
                acted_by=current_user.id,
                deployment_env=registry_env,
            )
            registry_synced = True
        except Exception as sync_err:
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
