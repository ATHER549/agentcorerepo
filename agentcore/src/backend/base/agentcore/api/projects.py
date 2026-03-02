import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

import orjson
from loguru import logger
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from fastapi_pagination import Params
from fastapi_pagination.ext.sqlmodel import apaginate
from sqlalchemy import func, or_, update
from sqlalchemy.orm import selectinload
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession, cascade_delete_agent, custom_params, remove_api_keys
from agentcore.api.agent import create_agent
from agentcore.api.v1_schemas import AgentListCreate
from agentcore.helpers.agent import generate_unique_agent_name
from agentcore.helpers.folders import generate_unique_folder_name
from agentcore.initial_setup.constants import STARTER_FOLDER_NAME
from agentcore.services.database.models.agent.model import Agent, AgentCreate, AgentRead
from agentcore.services.database.models.project.constants import DEFAULT_FOLDER_NAME as DEFAULT_PROJECT_NAME
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.project.model import (
    Project,
    ProjectCreate,
    ProjectRead,
    ProjectReadWithAgents,
    ProjectUpdate,
)
from agentcore.services.database.models.project.pagination_model import ProjectWithPaginatedAgents
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.auth.permissions import normalize_role

router = APIRouter(prefix="/projects", tags=["Projects"])


def _is_admin_role(role: str | None) -> bool:
    return role in {"super_admin", "department_admin", "root"}


async def _get_scope_memberships(session: DbSession, user_id: UUID) -> tuple[set[UUID], set[UUID]]:
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


def _excluded_higher_role_user_ids(role: str):
    """Return a subquery of user IDs whose projects should be hidden from the given role.

    Uses SQL-level normalization so all role name variants (e.g. "Root Admin",
    "root_admin", "root") are matched correctly.
    """
    normalized_db_role = func.lower(func.replace(User.role, " ", "_"))

    if role == "super_admin":
        # Super admin must NOT see root admin projects
        return select(User.id).where(normalized_db_role.in_(["root", "root_admin"]))

    if role == "department_admin":
        # Dept admin must NOT see root admin or super admin projects
        return select(User.id).where(
            normalized_db_role.in_(["root", "root_admin", "super_admin", "admin"])
        )

    return None


async def _build_project_visibility_statement(session: DbSession, current_user: CurrentActiveUser):
    own_condition = or_(Project.user_id == current_user.id, Project.owner_user_id == current_user.id)
    role = normalize_role(getattr(current_user, "role", None))

    if role == "root":
        return select(Project)

    excluded_ids = _excluded_higher_role_user_ids(role)

    if role == "super_admin":
        org_ids, _ = await _get_scope_memberships(session, current_user.id)
        if org_ids:
            org_user_subquery = (
                select(UserOrganizationMembership.user_id).where(
                    UserOrganizationMembership.org_id.in_(list(org_ids)),
                    UserOrganizationMembership.status.in_(["accepted", "active"]),
                )
            )
            stmt = select(Project).where(
                or_(
                    own_condition,
                    Project.org_id.in_(list(org_ids)),
                    Project.user_id.in_(org_user_subquery),
                    Project.owner_user_id.in_(org_user_subquery),
                ),
            )
            if excluded_ids is not None:
                stmt = stmt.where(~Project.user_id.in_(excluded_ids))
            return stmt
        return select(Project).where(own_condition)

    if role == "department_admin":
        _, dept_ids = await _get_scope_memberships(session, current_user.id)
        if dept_ids:
            dept_user_subquery = (
                select(UserDepartmentMembership.user_id).where(
                    UserDepartmentMembership.department_id.in_(list(dept_ids)),
                    UserDepartmentMembership.status == "active",
                )
            )
            stmt = select(Project).where(
                or_(
                    own_condition,
                    Project.dept_id.in_(list(dept_ids)),
                    Project.user_id.in_(dept_user_subquery),
                    Project.owner_user_id.in_(dept_user_subquery),
                ),
            )
            if excluded_ids is not None:
                stmt = stmt.where(~Project.user_id.in_(excluded_ids))
            return stmt
        return select(Project).where(own_condition)

    return select(Project).where(own_condition)


async def _can_access_project(session: DbSession, current_user: CurrentActiveUser, project: Project) -> bool:
    role = normalize_role(getattr(current_user, "role", None))
    if role == "root":
        return True
    if project.user_id == current_user.id or project.owner_user_id == current_user.id:
        return True

    # Deny access when the project owner has a higher role than the requester.
    if role in ("super_admin", "department_admin"):
        owner_id = project.user_id or project.owner_user_id
        if owner_id:
            owner_user = (await session.exec(select(User).where(User.id == owner_id))).first()
            if owner_user:
                owner_role = normalize_role(owner_user.role)
                if role == "super_admin" and owner_role == "root":
                    return False
                if role == "department_admin" and owner_role in ("root", "super_admin"):
                    return False

    if role == "super_admin":
        org_ids, _ = await _get_scope_memberships(session, current_user.id)
        if project.org_id and project.org_id in org_ids:
            return True
        owner_id = project.owner_user_id or project.user_id
        if owner_id and org_ids:
            owner_membership = (
                await session.exec(
                    select(UserOrganizationMembership.id).where(
                        UserOrganizationMembership.user_id == owner_id,
                        UserOrganizationMembership.org_id.in_(list(org_ids)),
                        UserOrganizationMembership.status.in_(["accepted", "active"]),
                    )
                )
            ).first()
            if owner_membership:
                return True

    if role == "department_admin":
        _, dept_ids = await _get_scope_memberships(session, current_user.id)
        if project.dept_id and project.dept_id in dept_ids:
            return True
        owner_id = project.owner_user_id or project.user_id
        if owner_id and dept_ids:
            owner_membership = (
                await session.exec(
                    select(UserDepartmentMembership.id).where(
                        UserDepartmentMembership.user_id == owner_id,
                        UserDepartmentMembership.department_id.in_(list(dept_ids)),
                        UserDepartmentMembership.status == "active",
                    )
                )
            ).first()
            if owner_membership:
                return True

    return False


@router.post("/", response_model=ProjectRead, status_code=201)
async def create_project(
    *,
    session: DbSession,
    project: ProjectCreate,
    current_user: CurrentActiveUser,
):
    try:
        new_project = Project.model_validate(project, from_attributes=True)
        new_project.user_id = current_user.id
        new_project.owner_user_id = current_user.id
        new_project.created_by = current_user.id
        new_project.updated_by = current_user.id

        # Default project tenancy scope from user's memberships.
        org_ids, dept_ids = await _get_scope_memberships(session, current_user.id)
        user_role = normalize_role(getattr(current_user, "role", None))

        if user_role != "root" and not org_ids:
            raise HTTPException(status_code=400, detail="No active organization mapping found for user.")

        if new_project.org_id is None and org_ids:
            new_project.org_id = sorted(org_ids, key=str)[0]
        if user_role in {"department_admin", "developer", "business_user"} and not dept_ids:
            raise HTTPException(status_code=400, detail="No active department mapping found for user.")
        if new_project.dept_id is None and dept_ids:
            new_project.dept_id = sorted(dept_ids, key=str)[0]
        # First check if the project.name is unique
        # there might be agents with name like: "Myagent", "Myagent (1)", "Myagent (2)"
        # so we need to check if the name is unique with `like` operator
        # if we find a agent with the same name, we add a number to the end of the name
        # based on the highest number found
        if (
            await session.exec(
                statement=select(Project).where(Project.name == new_project.name).where(Project.user_id == current_user.id)
            )
        ).first():
            project_results = await session.exec(
                select(Project).where(
                    Project.name.like(f"{new_project.name}%"),  # type: ignore[attr-defined]
                    Project.user_id == current_user.id,
                )
            )
            if project_results:
                project_names = [project.name for project in project_results]
                project_numbers = [int(name.split("(")[-1].split(")")[0]) for name in project_names if "(" in name]
                if project_numbers:
                    new_project.name = f"{new_project.name} ({max(project_numbers) + 1})"
                else:
                    new_project.name = f"{new_project.name} (1)"

        session.add(new_project)
        await session.commit()
        await session.refresh(new_project)

        if project.components_list:
            update_statement_components = (
                update(Agent).where(Agent.id.in_(project.components_list)).values(project_id=new_project.id)  # type: ignore[attr-defined]
            )
            await session.exec(update_statement_components)
            await session.commit()

        if project.agents_list:
            update_statement_agents = (
                update(Agent).where(Agent.id.in_(project.agents_list)).values(project_id=new_project.id)  # type: ignore[attr-defined]
            )
            await session.exec(update_statement_agents)
            await session.commit()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return new_project


@router.get("/", response_model=list[ProjectRead], status_code=200)
async def read_projects(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    try:
        statement = await _build_project_visibility_statement(session, current_user)
        projects = (await session.exec(statement)).all()
        projects = [project for project in projects if project.name != STARTER_FOLDER_NAME]
        try:
            role = normalize_role(getattr(current_user, "role", None))
            creator_ids = {
                (project.created_by or project.owner_user_id or project.user_id)
                for project in projects
                if (project.created_by or project.owner_user_id or project.user_id)
            }

            creator_rows = []
            if creator_ids:
                creator_rows = (
                    await session.exec(
                        select(User.id, User.email, User.username).where(User.id.in_(list(creator_ids)))
                    )
                ).all()
            creator_email_map = {
                uid: (email or username) for uid, email, username in creator_rows
            }

            dept_map: dict[UUID, str] = {}
            if creator_ids and role in {"super_admin", "root", "department_admin"}:
                dept_rows = (
                    await session.exec(
                        select(UserDepartmentMembership.user_id, Department.name)
                        .join(Department, Department.id == UserDepartmentMembership.department_id)
                        .where(
                            UserDepartmentMembership.user_id.in_(list(creator_ids)),
                            UserDepartmentMembership.status == "active",
                        )
                    )
                ).all()
                for user_id, dept_name in dept_rows:
                    if user_id not in dept_map:
                        dept_map[user_id] = dept_name

            org_map: dict[UUID, str] = {}
            if creator_ids and role == "root":
                org_rows = (
                    await session.exec(
                        select(UserOrganizationMembership.user_id, Organization.name)
                        .join(Organization, Organization.id == UserOrganizationMembership.org_id)
                        .where(
                            UserOrganizationMembership.user_id.in_(list(creator_ids)),
                            UserOrganizationMembership.status.in_(["accepted", "active"]),
                        )
                    )
                ).all()
                for user_id, org_name in org_rows:
                    if user_id not in org_map:
                        org_map[user_id] = org_name

            result: list[ProjectRead] = []
            for project in projects:
                creator_id = project.created_by or project.owner_user_id or project.user_id
                is_own = (
                    creator_id is not None
                    and (
                        creator_id == current_user.id
                        or project.user_id == current_user.id
                        or project.owner_user_id == current_user.id
                    )
                )
                created_by_email = creator_email_map.get(creator_id) if creator_id else None
                department_name = dept_map.get(creator_id) if creator_id else None
                organization_name = org_map.get(creator_id) if creator_id else None

                if role in {"developer", "business_user"}:
                    created_by_email = None
                    department_name = None
                    organization_name = None
                elif role == "department_admin":
                    department_name = None
                    organization_name = None
                elif role == "super_admin":
                    organization_name = None

                # Root admin transcends orgs/depts; hide for own projects.
                if role == "root" and is_own:
                    organization_name = None
                    department_name = None

                result.append(
                    ProjectRead(
                        id=project.id,
                        name=project.name,
                        description=project.description,
                        auth_settings=project.auth_settings,
                        is_own_project=is_own,
                        created_by_email=created_by_email,
                        department_name=department_name,
                        organization_name=organization_name,
                    )
                )

            return sorted(result, key=lambda x: (x.name or "").lower())
        except Exception:
            logger.exception("read_projects: metadata enrichment failed, returning fallback without creator info")
            fallback = [
                ProjectRead(
                    id=project.id,
                    name=project.name,
                    description=project.description,
                    auth_settings=project.auth_settings,
                    is_own_project=(
                        project.user_id == current_user.id
                        or project.owner_user_id == current_user.id
                        or project.created_by == current_user.id
                    ),
                )
                for project in projects
            ]
            return sorted(fallback, key=lambda x: (x.name or "").lower())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{project_id}", response_model=ProjectWithPaginatedAgents | ProjectReadWithAgents, status_code=200)
async def read_project(
    *,
    session: DbSession,
    project_id: UUID,
    current_user: CurrentActiveUser,
    params: Annotated[Params | None, Depends(custom_params)],
    search: str = ""):
    try:
        project = (
            await session.exec(
                select(Project)
                .options(selectinload(Project.agents))
                .where(Project.id == project_id)
            )
        ).first()
    except Exception as e:
        if "No result found" in str(e):
            raise HTTPException(status_code=404, detail="Project not found") from e
        raise HTTPException(status_code=500, detail=str(e)) from e

    if not project or not await _can_access_project(session, current_user, project):
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        if params and params.page and params.size:
            stmt = select(Agent).where(Agent.project_id == project_id)
            current_role = normalize_role(getattr(current_user, "role", None))
            if current_role in {"developer", "business_user"}:
                stmt = stmt.where(Agent.user_id == current_user.id)
            elif current_role == "department_admin":
                _, dept_ids = await _get_scope_memberships(session, current_user.id)
                if dept_ids:
                    stmt = stmt.where(Agent.dept_id.in_(list(dept_ids)))
                else:
                    stmt = stmt.where(Agent.user_id == current_user.id)
            elif current_role == "super_admin":
                org_ids, _ = await _get_scope_memberships(session, current_user.id)
                if org_ids:
                    stmt = stmt.where(Agent.org_id.in_(list(org_ids)))
                else:
                    stmt = stmt.where(Agent.user_id == current_user.id)

            if Agent.updated_at is not None:
                stmt = stmt.order_by(Agent.updated_at.desc())  # type: ignore[attr-defined]
            if search:
                stmt = stmt.where(Agent.name.like(f"%{search}%"))  # type: ignore[attr-defined]
            import warnings

            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore", category=DeprecationWarning, module=r"fastapi_pagination\.ext\.sqlalchemy"
                )
                paginated_agents = await apaginate(session, stmt, params=params)

            return ProjectWithPaginatedAgents(project=ProjectRead.model_validate(project), agents=paginated_agents)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    current_role = normalize_role(getattr(current_user, "role", None))
    agents_in_scope = project.agents
    if current_role in {"developer", "business_user"}:
        agents_in_scope = [agent for agent in project.agents if agent.user_id == current_user.id]
    elif current_role == "department_admin":
        _, dept_ids = await _get_scope_memberships(session, current_user.id)
        if dept_ids:
            agents_in_scope = [agent for agent in project.agents if agent.dept_id in dept_ids]
        else:
            agents_in_scope = [agent for agent in project.agents if agent.user_id == current_user.id]
    elif current_role == "super_admin":
        org_ids, _ = await _get_scope_memberships(session, current_user.id)
        if org_ids:
            agents_in_scope = [agent for agent in project.agents if agent.org_id in org_ids]
        else:
            agents_in_scope = [agent for agent in project.agents if agent.user_id == current_user.id]

    return ProjectReadWithAgents(
        id=project.id,
        name=project.name,
        description=project.description,
        auth_settings=project.auth_settings,
        agents=agents_in_scope,
    )


@router.patch("/{project_id}", response_model=ProjectRead, status_code=200)
async def update_project(
    *,
    session: DbSession,
    project_id: UUID,
    project: ProjectUpdate,  # Assuming ProjectUpdate is a Pydantic model defining updatable fields
    current_user: CurrentActiveUser,
):
    try:
        existing_project = (await session.exec(select(Project).where(Project.id == project_id))).first()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    if not existing_project or not await _can_access_project(session, current_user, existing_project):
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        if project.name and project.name != existing_project.name:
            existing_project.name = project.name
            session.add(existing_project)
            await session.commit()
            await session.refresh(existing_project)
            return existing_project

        project_data = existing_project.model_dump(exclude_unset=True)
        for key, value in project_data.items():
            if key not in {"components", "agents"}:
                setattr(existing_project, key, value)
        session.add(existing_project)
        await session.commit()
        await session.refresh(existing_project)

        concat_project_components = project.components + project.agents

        agents_ids = (await session.exec(select(Agent.id).where(Agent.project_id == existing_project.id))).all()

        excluded_agents = list(set(agents_ids) - set(concat_project_components))

        my_collection_project = (
            await session.exec(select(Project).where(Project.name == DEFAULT_PROJECT_NAME))
        ).first()
        if my_collection_project:
            update_statement_my_collection = (
                update(Agent).where(Agent.id.in_(excluded_agents)).values(project_id=my_collection_project.id)  # type: ignore[attr-defined]
            )
            await session.exec(update_statement_my_collection)
            await session.commit()

        if concat_project_components:
            update_statement_components = (
                update(Agent).where(Agent.id.in_(concat_project_components)).values(project_id=existing_project.id)  # type: ignore[attr-defined]
            )
            await session.exec(update_statement_components)
            await session.commit()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return existing_project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    *,
    session: DbSession,
    project_id: UUID,
    current_user: CurrentActiveUser,
):
    try:
        project = (await session.exec(select(Project).where(Project.id == project_id))).first()
        if not project or not await _can_access_project(session, current_user, project):
            raise HTTPException(status_code=404, detail="Project not found")

        if _is_admin_role(getattr(current_user, "role", None)):
            agents = (await session.exec(select(Agent).where(Agent.project_id == project_id))).all()
        else:
            agents = (
                await session.exec(select(Agent).where(Agent.project_id == project_id, Agent.user_id == current_user.id))
            ).all()
        if len(agents) > 0:
            for agent in agents:
                await cascade_delete_agent(session, agent.id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    try:
        await session.delete(project)
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/download/{project_id}", status_code=200)
async def download_file(
    *,
    session: DbSession,
    project_id: UUID,
    current_user: CurrentActiveUser,
):
    """Download all agents from project as a zip file."""
    try:
        query = select(Project).where(Project.id == project_id)
        result = await session.exec(query)
        project = result.first()

        if not project or not await _can_access_project(session, current_user, project):
            raise HTTPException(status_code=404, detail="Project not found")

        agents_query = select(Agent).where(Agent.project_id == project_id)
        agents_result = await session.exec(agents_query)
        agents = [AgentRead.model_validate(agent, from_attributes=True) for agent in agents_result.all()]

        if not agents:
            raise HTTPException(status_code=404, detail="No agents found in project")

        agents_without_api_keys = [remove_api_keys(agent.model_dump()) for agent in agents]
        zip_stream = io.BytesIO()

        with zipfile.ZipFile(zip_stream, "w") as zip_file:
            for agent in agents_without_api_keys:
                agent_json = json.dumps(jsonable_encoder(agent))
                zip_file.writestr(f"{agent['name']}.json", agent_json.encode("utf-8"))

        zip_stream.seek(0)

        current_time = datetime.now(tz=timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
        filename = f"{current_time}_{project.name}_agents.zip"

        # URL encode filename handle non-ASCII (ex. Cyrillic)
        encoded_filename = quote(filename)

        return StreamingResponse(
            zip_stream,
            media_type="application/x-zip-compressed",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
        )

    except Exception as e:
        if "No result found" in str(e):
            raise HTTPException(status_code=404, detail="Project not found") from e
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/upload/", response_model=list[AgentRead], status_code=201)
async def upload_file(
    *,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
    current_user: CurrentActiveUser,
):
    """Upload agents from a file."""
    contents = await file.read()
    data = orjson.loads(contents)

    if not data:
        raise HTTPException(status_code=400, detail="No agents found in the file")

    project_name = await generate_unique_folder_name(data["folder_name"], current_user.id, session)

    data["folder_name"] = project_name

    project = ProjectCreate(name=data["folder_name"], description=data["folder_description"])

    new_project = Project.model_validate(project, from_attributes=True)
    new_project.id = None
    new_project.user_id = current_user.id
    session.add(new_project)
    await session.commit()
    await session.refresh(new_project)

    del data["folder_name"]
    del data["folder_description"]

    if "agents" in data:
        agent_list = AgentListCreate(agents=[AgentCreate(**agent) for agent in data["agents"]])
    else:
        raise HTTPException(status_code=400, detail="No agents found in the data")
    # Now we set the user_id for all agents
    for agent in agent_list.agents:
        agent_name = await generate_unique_agent_name(agent.name, current_user.id, session)
        agent.name = agent_name
        agent.user_id = current_user.id
        agent.project_id = new_project.id

    return await create_agent(session=session, agent_list=agent_list, current_user=current_user)
