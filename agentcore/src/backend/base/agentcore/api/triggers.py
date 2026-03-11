from uuid import UUID

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.trigger_config.crud import (
    create_trigger_config,
    delete_trigger_config,
    get_all_triggers,
    get_trigger_config_by_id,
    get_trigger_execution_logs,
    get_triggers_by_agent_id,
    toggle_trigger,
    update_trigger_config,
)
from agentcore.services.database.models.trigger_config.model import (
    TriggerConfigCreate,
    TriggerConfigRead,
    TriggerConfigUpdate,
    TriggerExecutionLogRead,
    TriggerTypeEnum,
)

router = APIRouter(prefix="/triggers", tags=["Triggers"])


class TriggerCreateRequest(BaseModel):
    trigger_type: TriggerTypeEnum
    trigger_config: dict
    environment: str = "dev"
    version: str | None = None
    deployment_id: UUID | None = None


class TriggerUpdateRequest(BaseModel):
    trigger_config: dict | None = None
    is_active: bool | None = None
    environment: str | None = None
    version: str | None = None


@router.get("/", status_code=200)
async def list_all_triggers(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    trigger_type: TriggerTypeEnum | None = None,
) -> list[dict]:
    """List trigger configurations visible to the current user (tenancy aware)."""
    from sqlmodel import select

    from agentcore.services.auth.permissions import normalize_role
    from agentcore.services.database.models.agent.model import Agent, AccessTypeEnum, LifecycleStatusEnum
    from agentcore.services.database.models.agent_deployment_prod.model import AgentDeploymentProd
    from agentcore.services.database.models.agent_deployment_uat.model import AgentDeploymentUAT
    from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
    from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership

    role = normalize_role(getattr(current_user, "role", "") or "")

    org_rows = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == current_user.id,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
        )
    ).all()
    dept_rows = (
        await session.exec(
            select(UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == current_user.id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()

    org_ids = {r if isinstance(r, UUID) else r[0] for r in org_rows}
    dept_ids = {r if isinstance(r, UUID) else r[0] for r in dept_rows}

    triggers = await get_all_triggers(session, trigger_type=trigger_type)
    result = []

    for t in triggers:
        agent = await session.get(Agent, t.agent_id)

        dep = None
        env = (t.environment or "").lower()
        if t.deployment_id and env == "prod":
            dep = await session.get(AgentDeploymentProd, t.deployment_id)
        elif t.deployment_id and env == "uat":
            dep = await session.get(AgentDeploymentUAT, t.deployment_id)

        # Resolve visibility/tenancy from deployment first; fallback to agent metadata.
        dep_org_id = dep.org_id if dep is not None else (agent.org_id if agent else None)
        dep_dept_id = dep.dept_id if dep is not None else (agent.dept_id if agent else None)
        is_owner = (
            t.created_by == current_user.id
            or (dep is not None and dep.deployed_by == current_user.id)
            or (agent is not None and agent.user_id == current_user.id)
        )

        if dep is not None:
            dep_visibility = str(dep.visibility.value if hasattr(dep.visibility, "value") else dep.visibility).upper()
            is_public = dep_visibility == "PUBLIC"
        else:
            is_public = bool(
                agent
                and agent.access_type == AccessTypeEnum.PUBLIC
                and agent.lifecycle_status == LifecycleStatusEnum.PUBLISHED
            )

        can_view = False
        if role == "root":
            can_view = True
        elif is_owner or is_public:
            can_view = True
        elif role == "super_admin":
            can_view = dep_org_id in org_ids if dep_org_id else False
        elif role == "department_admin":
            can_view = dep_dept_id in dept_ids if dep_dept_id else False
        else:
            # developer/business_user/consumer: scoped tenancy visibility
            can_view = (
                (dep_dept_id in dept_ids if dep_dept_id else False)
                or (dep_org_id in org_ids if dep_org_id else False)
            )

        if not can_view:
            continue

        row = TriggerConfigRead.model_validate(t).model_dump()

        # Use deployment-specific name so each version keeps its original deployed name.
        deploy_name = dep.agent_name if dep else None
        row["agent_name"] = deploy_name or (agent.name if agent else str(t.agent_id))
        result.append(row)

    return result


@router.get("/{agent_id}", status_code=200)
async def list_triggers_for_agent(
    *,
    session: DbSession,
    agent_id: UUID,
    active_only: bool = False,
    current_user: CurrentActiveUser,
) -> list[TriggerConfigRead]:
    """List all trigger configurations for an agent."""
    triggers = await get_triggers_by_agent_id(session, agent_id, active_only=active_only)
    return [TriggerConfigRead.model_validate(t) for t in triggers]


@router.post("/{agent_id}", status_code=201)
async def create_trigger(
    *,
    session: DbSession,
    agent_id: UUID,
    request: TriggerCreateRequest,
    current_user: CurrentActiveUser,
) -> TriggerConfigRead:
    """Create a new trigger configuration for an agent."""
    data = TriggerConfigCreate(
        agent_id=agent_id,
        deployment_id=request.deployment_id,
        trigger_type=request.trigger_type,
        trigger_config=request.trigger_config,
        environment=request.environment,
        version=request.version,
        created_by=current_user.id,
    )
    record = await create_trigger_config(session, data)

    # Register with the appropriate service
    try:
        await _register_trigger(record)
    except Exception as e:
        logger.warning(f"Failed to register trigger {record.id} with service: {e}")

    return TriggerConfigRead.model_validate(record)


@router.patch("/{trigger_id}", status_code=200)
async def update_trigger(
    *,
    session: DbSession,
    trigger_id: UUID,
    request: TriggerUpdateRequest,
    current_user: CurrentActiveUser,
) -> TriggerConfigRead:
    """Update a trigger configuration."""
    data = TriggerConfigUpdate(**request.model_dump(exclude_unset=True))
    record = await update_trigger_config(session, trigger_id, data)
    if not record:
        raise HTTPException(status_code=404, detail="Trigger not found")

    # Re-register with updated config
    try:
        await _unregister_trigger(trigger_id, record.trigger_type)
        if record.is_active:
            await _register_trigger(record)
    except Exception as e:
        logger.warning(f"Failed to re-register trigger {trigger_id}: {e}")

    return TriggerConfigRead.model_validate(record)


@router.delete("/{trigger_id}", status_code=204)
async def delete_trigger(
    *,
    session: DbSession,
    trigger_id: UUID,
    current_user: CurrentActiveUser,
) -> None:
    """Delete a trigger configuration."""
    record = await get_trigger_config_by_id(session, trigger_id)
    if not record:
        raise HTTPException(status_code=404, detail="Trigger not found")

    # Unregister from service
    try:
        await _unregister_trigger(trigger_id, record.trigger_type)
    except Exception as e:
        logger.warning(f"Failed to unregister trigger {trigger_id}: {e}")

    deleted = await delete_trigger_config(session, trigger_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Trigger not found")


@router.post("/{trigger_id}/toggle", status_code=200)
async def toggle_trigger_endpoint(
    *,
    session: DbSession,
    trigger_id: UUID,
    current_user: CurrentActiveUser,
) -> TriggerConfigRead:
    """Toggle a trigger's active status."""
    record = await toggle_trigger(session, trigger_id)
    if not record:
        raise HTTPException(status_code=404, detail="Trigger not found")

    # Register or unregister based on new state
    try:
        if record.is_active:
            await _register_trigger(record)
        else:
            await _unregister_trigger(trigger_id, record.trigger_type)
    except Exception as e:
        logger.warning(f"Failed to toggle trigger {trigger_id} registration: {e}")

    return TriggerConfigRead.model_validate(record)


@router.get("/{trigger_id}/logs", status_code=200)
async def get_trigger_logs(
    *,
    session: DbSession,
    trigger_id: UUID,
    limit: int = 50,
    current_user: CurrentActiveUser,
) -> list[TriggerExecutionLogRead]:
    """Get execution logs for a trigger."""
    logs = await get_trigger_execution_logs(session, trigger_id, limit=limit)
    return [TriggerExecutionLogRead.model_validate(log) for log in logs]


@router.post("/{trigger_id}/run-now", status_code=200)
async def run_trigger_now(
    *,
    session: DbSession,
    trigger_id: UUID,
    current_user: CurrentActiveUser,
) -> dict:
    """Fire a trigger immediately, regardless of its schedule."""
    import asyncio

    record = await get_trigger_config_by_id(session, trigger_id)
    if not record:
        raise HTTPException(status_code=404, detail="Trigger not found")

    try:
        if record.trigger_type == TriggerTypeEnum.SCHEDULE:
            # Execute immediately in background — _execute_trigger writes
            # "started" to DB right away so the frontend can see Running...
            from agentcore.services.deps import get_scheduler_service

            scheduler = get_scheduler_service()
            asyncio.create_task(
                scheduler._execute_trigger(
                    trigger_config_id=record.id,
                    agent_id=record.agent_id,
                    environment=record.environment,
                    version=record.version,
                )
            )
        elif record.trigger_type in (TriggerTypeEnum.FOLDER_MONITOR, TriggerTypeEnum.EMAIL_MONITOR):
            # For folder/email monitors, re-register to trigger an immediate scan
            await _register_trigger(record)
    except Exception as e:
        logger.exception(f"Failed to manually fire trigger {trigger_id}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": "Trigger fired manually"}


# ── Helper functions ─────────────────────────────────────────────────────


async def _register_trigger(record) -> None:
    """Register a trigger with the appropriate backend service."""
    from agentcore.services.deps import get_scheduler_service, get_trigger_service

    trigger_type = record.trigger_type
    config = record.trigger_config or {}

    if trigger_type == TriggerTypeEnum.SCHEDULE:
        scheduler = get_scheduler_service()
        schedule_type = config.get("schedule_type", "interval")
        cron_expression = config.get("cron_expression", "0 * * * *")
        interval_minutes = config.get("interval_minutes", 60)
        await scheduler.add_schedule(
            trigger_config_id=record.id,
            agent_id=record.agent_id,
            schedule_type=schedule_type,
            cron_expression=cron_expression,
            interval_minutes=interval_minutes,
            environment=record.environment,
            version=record.version or None,
        )

    elif trigger_type == TriggerTypeEnum.FOLDER_MONITOR:
        trigger_service = get_trigger_service()
        await trigger_service.register_folder_monitor(record)

    elif trigger_type == TriggerTypeEnum.EMAIL_MONITOR:
        trigger_service = get_trigger_service()
        await trigger_service.register_email_monitor(record)


async def _unregister_trigger(trigger_id: UUID, trigger_type: TriggerTypeEnum) -> None:
    """Unregister a trigger from its backend service."""
    from agentcore.services.deps import get_scheduler_service, get_trigger_service

    if trigger_type == TriggerTypeEnum.SCHEDULE:
        scheduler = get_scheduler_service()
        await scheduler.remove_schedule(trigger_id)
    else:
        trigger_service = get_trigger_service()
        await trigger_service.unregister(trigger_id)
