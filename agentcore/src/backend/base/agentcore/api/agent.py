from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

import orjson
from aiofile import async_open
from anyio import Path
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from fastapi_pagination import Page, Params
from fastapi_pagination.ext.sqlmodel import apaginate
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlmodel import and_, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.api.utils import (
    CurrentActiveUser,
    DbSession,
    cascade_delete_agent,
    remove_api_keys,
    strip_sensitive_values_from_agent_data,
)
from agentcore.api.v1_schemas import AgentListCreate
from agentcore.helpers.user import get_user_by_agent_id_or_endpoint_name
from agentcore.initial_setup.constants import STARTER_FOLDER_NAME
from agentcore.logging import logger
from agentcore.services.database.models.agent.model import (
    AccessTypeEnum,
    Agent,
    AgentCreate,
    AgentHeader,
    AgentRead,
    AgentUpdate,
)
from agentcore.services.database.models.agent_edit_lock.model import AgentEditLock
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.database.models.folder.model import Folder
from agentcore.services.auth.permissions import normalize_role
from agentcore.services.deps import get_settings_service
from agentcore.utils.compression import compress_response

# build router
router = APIRouter(prefix="/agents", tags=["agents"])
AGENT_EDIT_LOCK_TTL = timedelta(minutes=30)


async def _verify_fs_path(path: str | None) -> None:
    if path:
        path_ = Path(path)
        if not await path_.exists():
            await path_.touch()


async def _save_agent_to_fs(agent: Agent) -> None:
    if agent.fs_path:
        async with async_open(agent.fs_path, "w") as f:
            try:
                await f.write(agent.model_dump_json())
            except OSError:
                logger.exception("Failed to write agent %s to path %s", agent.name, agent.fs_path)


async def _resolve_tenant_scope_for_user(
    *,
    session: AsyncSession,
    user_id: UUID,
    requested_org_id: UUID | None = None,
    requested_dept_id: UUID | None = None,
) -> tuple[UUID | None, UUID | None]:
    memberships = (
        await session.exec(
            select(UserDepartmentMembership).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    if not memberships:
        # Do not block agent creation/open flow for users without mapped membership.
        return requested_org_id, requested_dept_id

    scoped = memberships
    if requested_org_id:
        scoped = [m for m in scoped if m.org_id == requested_org_id]
    if requested_dept_id:
        scoped = [m for m in scoped if m.department_id == requested_dept_id]

    if not scoped:
        # Fall back to the first active membership instead of blocking the user.
        scoped = memberships

    selected = sorted(scoped, key=lambda m: (str(m.org_id), str(m.department_id)))[0]
    return selected.org_id, selected.department_id


async def _get_scope_memberships(session: AsyncSession, user_id: UUID) -> tuple[set[UUID], set[UUID]]:
    org_rows = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == user_id,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
        )
    ).all()
    dept_rows = (
        await session.exec(
            select(UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    org_ids = {r if isinstance(r, UUID) else r[0] for r in org_rows}
    dept_ids = {r if isinstance(r, UUID) else r[0] for r in dept_rows}
    return org_ids, dept_ids


async def _build_agent_visibility_statement(session: AsyncSession, current_user: CurrentActiveUser):
    own_condition = Agent.user_id == current_user.id
    role = normalize_role(getattr(current_user, "role", None))

    if role == "root":
        return select(Agent)

    if role == "super_admin":
        org_ids, _ = await _get_scope_memberships(session, current_user.id)
        if org_ids:
            org_user_subquery = (
                select(UserOrganizationMembership.user_id).where(
                    UserOrganizationMembership.org_id.in_(list(org_ids)),
                    UserOrganizationMembership.status.in_(["accepted", "active"]),
                )
            )
            return select(Agent).where(
                or_(
                    own_condition,
                    Agent.org_id.in_(list(org_ids)),
                    Agent.user_id.in_(org_user_subquery),
                )
            )
        return select(Agent).where(own_condition)

    if role == "department_admin":
        _, dept_ids = await _get_scope_memberships(session, current_user.id)
        if dept_ids:
            dept_user_subquery = (
                select(UserDepartmentMembership.user_id).where(
                    UserDepartmentMembership.department_id.in_(list(dept_ids)),
                    UserDepartmentMembership.status == "active",
                )
            )
            return select(Agent).where(
                or_(
                    own_condition,
                    Agent.dept_id.in_(list(dept_ids)),
                    Agent.user_id.in_(dept_user_subquery),
                )
            )
        return select(Agent).where(own_condition)

    return select(Agent).where(own_condition)


async def _can_access_agent(session: AsyncSession, current_user: CurrentActiveUser, agent: Agent) -> bool:
    role = normalize_role(getattr(current_user, "role", None))
    if role == "root":
        return True

    if agent.user_id == current_user.id:
        return True

    if role == "super_admin":
        org_ids, _ = await _get_scope_memberships(session, current_user.id)
        if agent.org_id and agent.org_id in org_ids:
            return True
        if agent.user_id and org_ids:
            owner_membership = (
                await session.exec(
                    select(UserOrganizationMembership.id).where(
                        UserOrganizationMembership.user_id == agent.user_id,
                        UserOrganizationMembership.org_id.in_(list(org_ids)),
                        UserOrganizationMembership.status.in_(["accepted", "active"]),
                    )
                )
            ).first()
            if owner_membership:
                return True

    if role == "department_admin":
        _, dept_ids = await _get_scope_memberships(session, current_user.id)
        if agent.dept_id and agent.dept_id in dept_ids:
            return True
        if agent.user_id and dept_ids:
            owner_membership = (
                await session.exec(
                    select(UserDepartmentMembership.id).where(
                        UserDepartmentMembership.user_id == agent.user_id,
                        UserDepartmentMembership.department_id.in_(list(dept_ids)),
                        UserDepartmentMembership.status == "active",
                    )
                )
            ).first()
            if owner_membership:
                return True

    return False


async def _new_agent(
    *,
    session: AsyncSession,
    agent: AgentCreate,
    user_id: UUID,
):
    try:
        await _verify_fs_path(agent.fs_path)

        """Create a new agent."""
        if agent.user_id is None:
            agent.user_id = user_id

        resolved_org_id, resolved_dept_id = await _resolve_tenant_scope_for_user(
            session=session,
            user_id=user_id,
            requested_org_id=getattr(agent, "org_id", None),
            requested_dept_id=getattr(agent, "dept_id", None),
        )
        agent.org_id = resolved_org_id
        agent.dept_id = resolved_dept_id

        # First check if the agent.name is unique
        # there might be agents with name like: "Myagent", "Myagent (1)", "Myagent (2)"
        # so we need to check if the name is unique with `like` operator
        # if we find a agent with the same name, we add a number to the end of the name
        # based on the highest number found
        if (await session.exec(select(Agent).where(Agent.name == agent.name).where(Agent.user_id == user_id))).first():
            agents = (
                await session.exec(
                    select(Agent).where(Agent.name.like(f"{agent.name} (%")).where(Agent.user_id == user_id)  # type: ignore[attr-defined]
                )
            ).all()
            if agents:
                # Use regex to extract numbers only from agents that follow the copy naming pattern:
                # "{original_name} ({number})"
                # This avoids extracting numbers from the original agent name if it naturally contains parentheses
                #
                # Examples:
                # - For agent "My agent": matches "My agent (1)", "My agent (2)" → extracts 1, 2
                # - For agent "Analytics (Q1)": matches "Analytics (Q1) (1)" → extracts 1
                #   but does NOT match "Analytics (Q1)" → avoids extracting the original "1"
                extract_number = re.compile(rf"^{re.escape(agent.name)} \((\d+)\)$")
                numbers = []
                for _agent in agents:
                    result = extract_number.search(_agent.name)
                    if result:
                        numbers.append(int(result.groups(1)[0]))
                if numbers:
                    agent.name = f"{agent.name} ({max(numbers) + 1})"
                else:
                    agent.name = f"{agent.name} (1)"
            else:
                agent.name = f"{agent.name} (1)"

        db_agent = Agent.model_validate(agent, from_attributes=True)
        db_agent.updated_at = datetime.now(timezone.utc)

        # Keep agent tenancy aligned with the selected project so first-created
        # agents are immediately visible to admin scopes.
        if db_agent.project_id:
            selected_project = await session.get(Folder, db_agent.project_id)
            if selected_project:
                db_agent.org_id = selected_project.org_id or db_agent.org_id
                db_agent.dept_id = selected_project.dept_id or db_agent.dept_id

        # Strip sensitive values (API keys, secrets) and guarantee JSON-safe payload.
        if db_agent.data:
            db_agent.data = jsonable_encoder(strip_sensitive_values_from_agent_data(db_agent.data))

        if db_agent.project_id is None:
            raise HTTPException(status_code=400, detail="Project selection is required.")

        session.add(db_agent)
    except Exception as e:
        # If it is a validation error, return the error message
        if hasattr(e, "errors"):
            raise HTTPException(status_code=400, detail=str(e)) from e
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e)) from e

    return db_agent


@router.post("/", response_model=AgentRead, status_code=201)
async def create_agent(
    *,
    session: DbSession,
    agent: AgentCreate,
    current_user: CurrentActiveUser,
):
    try:
        db_agent = await _new_agent(session=session, agent=agent, user_id=current_user.id)
        await session.commit()
        await session.refresh(db_agent)

        await _save_agent_to_fs(db_agent)

    except Exception as e:
        logger.exception("Failed to create agent {}", getattr(agent, "id", None) or agent.name)
        if "UNIQUE constraint failed" in str(e):
            # Get the name of the column that failed
            columns = str(e).split("UNIQUE constraint failed: ")[1].split(".")[1].split("\n")[0]
            # UNIQUE constraint failed: agent.user_id, agent.name
            # or UNIQUE constraint failed: agent.name
            # if the column has id in it, we want the other column
            column = columns.split(",")[1] if "id" in columns.split(",")[0] else columns.split(",")[0]

            raise HTTPException(
                status_code=400, detail=f"{column.capitalize().replace('_', ' ')} must be unique"
            ) from e
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e)) from e
    return AgentRead.model_validate(db_agent, from_attributes=True)


@router.get("/", response_model=list[AgentRead] | Page[AgentRead] | list[AgentHeader], status_code=200)
async def read_agents(
    *,
    current_user: CurrentActiveUser,
    session: DbSession,
    remove_example_agents: bool = False,
    components_only: bool = False,
    get_all: bool = True,
    project_id: UUID | None = None,
    params: Annotated[Params, Depends()],
    header_agents: bool = False,
):
    """Retrieve a list of agents with pagination support.

    Args:
        current_user (User): The current authenticated user.
        session (Session): The database session.
        settings_service (SettingsService): The settings service.
        components_only (bool, optional): Whether to return only components. Defaults to False.

        get_all (bool, optional): Whether to return all agents without pagination. Defaults to True.
        **This field must be True because of backward compatibility with the frontend - Release: 1.0.20**

        project_id (UUID, optional): The project ID. Defaults to None.
        params (Params): Pagination parameters.
        remove_example_agents (bool, optional): Whether to remove example agents. Defaults to False.
        header_agents (bool, optional): Whether to return only specific headers of the agents. Defaults to False.

    Returns:
        list[AgentRead] | Page[AgentRead] | list[AgentHeader]
        A list of agents or a paginated response containing the list of agents or a list of agent headers.
    """
    try:
        starter_folder = (await session.exec(select(Folder).where(Folder.name == STARTER_FOLDER_NAME))).first()
        starter_project_id = starter_folder.id if starter_folder else None

        stmt = await _build_agent_visibility_statement(session, current_user)

        if remove_example_agents:
            stmt = stmt.where(Agent.project_id != starter_project_id)

        if project_id:
            stmt = stmt.where(Agent.project_id == project_id)

        if get_all:
            agents = (await session.exec(stmt)).all()
            if remove_example_agents and starter_project_id:
                agents = [agent for agent in agents if agent.project_id != starter_project_id]
            if header_agents:
                # Convert to AgentHeader objects and compress the response
                agent_headers = [AgentHeader.model_validate(agent, from_attributes=True) for agent in agents]
                return compress_response(agent_headers)

            # Compress the full agents response
            return compress_response(agents)

        if project_id:
            stmt = stmt.where(Agent.project_id == project_id)

        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", category=DeprecationWarning, module=r"fastapi_pagination\.ext\.sqlalchemy"
            )
            return await apaginate(session, stmt, params=params)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _read_agent(
    session: AsyncSession,
    agent_id: UUID,
    user_id: UUID,
):
    """Read a agent."""
    stmt = select(Agent).where(Agent.id == agent_id).where(Agent.user_id == user_id)

    return (await session.exec(stmt)).first()


@router.get("/{agent_id}", response_model=AgentRead, status_code=200)
async def read_agent(
    *,
    session: DbSession,
    agent_id: UUID,
    current_user: CurrentActiveUser,
):
    """Read a agent."""
    user_agent = (await session.exec(select(Agent).where(Agent.id == agent_id))).first()
    if not user_agent or not await _can_access_agent(session, current_user, user_agent):
        raise HTTPException(status_code=404, detail="agent not found")
    return AgentRead.model_validate(user_agent, from_attributes=True)


@router.post("/{agent_id}/session/acquire", status_code=200)
async def acquire_agent_session(
    *,
    session: DbSession,
    agent_id: UUID,
    current_user: CurrentActiveUser,
):
    user_agent = (await session.exec(select(Agent).where(Agent.id == agent_id))).first()
    if not user_agent or not await _can_access_agent(session, current_user, user_agent):
        raise HTTPException(status_code=404, detail="agent not found")

    now = datetime.now(timezone.utc)
    expires_at = now + AGENT_EDIT_LOCK_TTL

    lock_row = (await session.exec(select(AgentEditLock).where(AgentEditLock.agent_id == agent_id))).first()
    if lock_row:
        if lock_row.locked_by == current_user.id or lock_row.expires_at <= now:
            lock_row.locked_by = current_user.id
            lock_row.locked_at = now
            lock_row.expires_at = expires_at
            session.add(lock_row)
            await session.commit()
            return {"status": "acquired"}
        raise HTTPException(
            status_code=423,
            detail="This agent is currently opened by another user. Please try again later.",
        )

    try:
        session.add(
            AgentEditLock(
                agent_id=agent_id,
                locked_by=current_user.id,
                locked_at=now,
                expires_at=expires_at,
            )
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing_lock = (await session.exec(select(AgentEditLock).where(AgentEditLock.agent_id == agent_id))).first()
        if existing_lock and existing_lock.locked_by != current_user.id and existing_lock.expires_at > now:
            raise HTTPException(
                status_code=423,
                detail="This agent is currently opened by another user. Please try again later.",
            )
        if existing_lock:
            existing_lock.locked_by = current_user.id
            existing_lock.locked_at = now
            existing_lock.expires_at = expires_at
            session.add(existing_lock)
            await session.commit()
    return {"status": "acquired"}


@router.post("/{agent_id}/session/release", status_code=200)
async def release_agent_session(
    *,
    session: DbSession,
    agent_id: UUID,
    current_user: CurrentActiveUser,
):
    user_agent = (await session.exec(select(Agent).where(Agent.id == agent_id))).first()
    if not user_agent or not await _can_access_agent(session, current_user, user_agent):
        raise HTTPException(status_code=404, detail="agent not found")

    existing_lock = (await session.exec(select(AgentEditLock).where(AgentEditLock.agent_id == agent_id))).first()
    if existing_lock and existing_lock.locked_by == current_user.id:
        await session.delete(existing_lock)
        await session.commit()
    return {"status": "released"}


@router.get("/public_agent/{agent_id}", response_model=AgentRead, status_code=200)
async def read_public_agent(
    *,
    session: DbSession,
    agent_id: UUID,
):
    """Read a public agent."""
    access_type = (await session.exec(select(Agent.access_type).where(Agent.id == agent_id))).first()
    if access_type is not AccessTypeEnum.PUBLIC:
        raise HTTPException(status_code=403, detail="agent is not public")

    current_user = await get_user_by_agent_id_or_endpoint_name(str(agent_id))
    return await read_agent(session=session, agent_id=agent_id, current_user=current_user)


@router.patch("/{agent_id}", response_model=AgentRead, status_code=200)
async def update_agent(
    *,
    session: DbSession,
    agent_id: UUID,
    agent: AgentUpdate,
    current_user: CurrentActiveUser,
):
    """Update a agent."""
    settings_service = get_settings_service()
    try:
        db_agent = await _read_agent(
            session=session,
            agent_id=agent_id,
            user_id=current_user.id,
        )

        if not db_agent:
            raise HTTPException(status_code=404, detail="agent not found")

        update_data = agent.model_dump(exclude_unset=True, exclude_none=True)

        # Always strip sensitive values (API keys, secrets) from agent data before saving to DB
        if "data" in update_data and update_data["data"]:
            update_data["data"] = strip_sensitive_values_from_agent_data(update_data["data"])

        if settings_service.settings.remove_api_keys:
            update_data = remove_api_keys(update_data)

        for key, value in update_data.items():
            setattr(db_agent, key, value)

        await _verify_fs_path(db_agent.fs_path)

        db_agent.updated_at = datetime.now(timezone.utc)

        session.add(db_agent)
        await session.commit()
        await session.refresh(db_agent)

        await _save_agent_to_fs(db_agent)

    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            # Get the name of the column that failed
            columns = str(e).split("UNIQUE constraint failed: ")[1].split(".")[1].split("\n")[0]
            # UNIQUE constraint failed: agent.user_id, agent.name
            # or UNIQUE constraint failed: agent.name
            # if the column has id in it, we want the other column
            column = columns.split(",")[1] if "id" in columns.split(",")[0] else columns.split(",")[0]
            raise HTTPException(
                status_code=400, detail=f"{column.capitalize().replace('_', ' ')} must be unique"
            ) from e

        if hasattr(e, "status_code"):
            raise HTTPException(status_code=e.status_code, detail=str(e)) from e
        raise HTTPException(status_code=500, detail=str(e)) from e

    return AgentRead.model_validate(db_agent, from_attributes=True)


@router.delete("/{agent_id}", status_code=200)
async def delete_agent(
    *,
    session: DbSession,
    agent_id: UUID,
    current_user: CurrentActiveUser,
):
    """Delete a agent."""
    agent = await _read_agent(
        session=session,
        agent_id=agent_id,
        user_id=current_user.id,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")
    await cascade_delete_agent(session, agent.id)
    await session.commit()
    return {"message": "agent deleted successfully"}


@router.post("/batch/", response_model=list[AgentRead], status_code=201)
async def create_agents(
    *,
    session: DbSession,
    agent_list: AgentListCreate,
    current_user: CurrentActiveUser,
):
    """Create multiple new agents."""
    db_agents = []
    for agent in agent_list.agents:
        agent.user_id = current_user.id
        resolved_org_id, resolved_dept_id = await _resolve_tenant_scope_for_user(
            session=session,
            user_id=current_user.id,
            requested_org_id=getattr(agent, "org_id", None),
            requested_dept_id=getattr(agent, "dept_id", None),
        )
        agent.org_id = resolved_org_id
        agent.dept_id = resolved_dept_id
        db_agent = Agent.model_validate(agent, from_attributes=True)
        # Strip sensitive values (API keys, secrets) from agent data before saving to DB
        if db_agent.data:
            db_agent.data = strip_sensitive_values_from_agent_data(db_agent.data)
        session.add(db_agent)
        db_agents.append(db_agent)
    await session.commit()
    for db_agent in db_agents:
        await session.refresh(db_agent)
    return db_agents


@router.post("/upload/", response_model=list[AgentRead], status_code=201)
async def upload_file(
    *,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
    current_user: CurrentActiveUser,
    project_id: UUID | None = None,
):
    """Upload agents from a file."""
    contents = await file.read()
    data = orjson.loads(contents)
    response_list = []
    agent_list = AgentListCreate(**data) if "agents" in data else AgentListCreate(agents=[AgentCreate(**data)])
    # Now we set the user_id for all agents
    for agent in agent_list.agents:
        agent.user_id = current_user.id
        if project_id:
            agent.project_id = project_id
        response = await _new_agent(session=session, agent=agent, user_id=current_user.id)
        response_list.append(response)

    try:
        await session.commit()
        for db_agent in response_list:
            await session.refresh(db_agent)
            await _save_agent_to_fs(db_agent)
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            # Get the name of the column that failed
            columns = str(e).split("UNIQUE constraint failed: ")[1].split(".")[1].split("\n")[0]
            # UNIQUE constraint failed: agent.user_id, agent.name
            # or UNIQUE constraint failed: agent.name
            # if the column has id in it, we want the other column
            column = columns.split(",")[1] if "id" in columns.split(",")[0] else columns.split(",")[0]

            raise HTTPException(
                status_code=400, detail=f"{column.capitalize().replace('_', ' ')} must be unique"
            ) from e
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e)) from e

    return response_list


@router.delete("/")
async def delete_multiple_agent(
    agent_ids: list[UUID],
    user: CurrentActiveUser,
    db: DbSession,
):
    """Delete multiple agents by their IDs.

    Args:
        agent_ids (List[str]): The list of agent IDs to delete.
        user (User, optional): The user making the request. Defaults to the current active user.
        db (Session, optional): The database session.

    Returns:
        dict: A dictionary containing the number of agents deleted.

    """
    try:
        agents_to_delete = (
            await db.exec(select(Agent).where(col(Agent.id).in_(agent_ids)).where(Agent.user_id == user.id))
        ).all()
        for agent in agents_to_delete:
            await cascade_delete_agent(db, agent.id)

        await db.commit()
        return {"deleted": len(agents_to_delete)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/download/", status_code=200)
async def download_multiple_file(
    agent_ids: list[UUID],
    user: CurrentActiveUser,
    db: DbSession,
):
    """Download all agents as a zip file."""
    agents = (await db.exec(select(Agent).where(and_(Agent.user_id == user.id, Agent.id.in_(agent_ids))))).all()  # type: ignore[attr-defined]

    if not agents:
        raise HTTPException(status_code=404, detail="No agents found.")

    agents_without_api_keys = [remove_api_keys(agent.model_dump()) for agent in agents]

    if len(agents_without_api_keys) > 1:
        # Create a byte stream to hold the ZIP file
        zip_stream = io.BytesIO()

        # Create a ZIP file
        with zipfile.ZipFile(zip_stream, "w") as zip_file:
            for agent in agents_without_api_keys:
                # Convert the agent object to JSON
                agent_json = json.dumps(jsonable_encoder(agent))

                # Write the JSON to the ZIP file
                zip_file.writestr(f"{agent['name']}.json", agent_json)

        # Seek to the beginning of the byte stream
        zip_stream.seek(0)

        # Generate the filename with the current datetime
        current_time = datetime.now(tz=timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
        filename = f"{current_time}_agentcore_agents.zip"

        return StreamingResponse(
            zip_stream,
            media_type="application/x-zip-compressed",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    return agents_without_api_keys[0]


all_starter_folder_agents_response: Response | None = None


@router.get("/basic_examples/", response_model=list[AgentRead], status_code=200)
async def read_basic_examples(
    *,
    session: DbSession,
):
    """Retrieve a list of basic example agents.

    Args:
        session (Session): The database session.

    Returns:
        list[AgentRead]: A list of basic example agents.
    """
    try:
        global all_starter_folder_agents_response  # noqa: PLW0603

        if all_starter_folder_agents_response:
            return all_starter_folder_agents_response
        # Get the starter folder
        starter_folder = (await session.exec(select(Folder).where(Folder.name == STARTER_FOLDER_NAME))).first()

        if not starter_folder:
            return []

        # Get all agents in the starter folder
        all_starter_folder_agents = (await session.exec(select(Agent).where(Agent.project_id == starter_folder.id))).all()

        agent_reads = [AgentRead.model_validate(agent, from_attributes=True) for agent in all_starter_folder_agents]
        all_starter_folder_agents_response = compress_response(agent_reads)

        # Return compressed response using our utility function
        return all_starter_folder_agents_response  # noqa: TRY300

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
