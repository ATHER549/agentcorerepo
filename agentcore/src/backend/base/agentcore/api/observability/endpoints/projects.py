"""GET /projects and /projects/{project_id} endpoints."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.auth.utils import get_current_active_user
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.folder.model import Folder
from agentcore.services.database.models.user.model import User
from agentcore.services.deps import get_session

from ..aggregations import aggregate_projects, match_trace_to_agent, user_agents_stmt
from ..models import (
    AgentListItem,
    DailyUsageItem,
    ProjectDetailResponse,
    ProjectListResponse,
)
from ..parsing import clear_request_caches, compute_date_range
from ..scope import resolve_scope_context, scope_warning_payload
from ..trace_store import TraceStore

router = APIRouter()


@router.get("/projects")
async def get_user_projects(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    org_id: Annotated[UUID | None, Query(description="Organization scope")] = None,
    dept_id: Annotated[UUID | None, Query(description="Department scope")] = None,
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD)")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC")] = None,
    fetch_all: Annotated[bool, Query()] = False,
    environment: Annotated[str | None, Query(description="'uat' or 'production'")] = None,
) -> ProjectListResponse:
    """Get all projects (folders) with aggregated metrics."""
    clear_request_caches()

    allowed_user_ids, scoped_clients, scope_key, scope_warnings = await resolve_scope_context(
        session=session, current_user=current_user, org_id=org_id, dept_id=dept_id,
    )
    if not scoped_clients:
        return ProjectListResponse(
            projects=[], total=0, truncated=False, fetched_trace_count=0,
            **scope_warning_payload(scope_warnings),
        )

    try:
        scoped_user_uuids = _to_uuids(allowed_user_ids)

        # DB lookups
        folders_result = await session.exec(select(Folder).where(Folder.user_id.in_(scoped_user_uuids)))
        user_folders = folders_result.all()
        folders_by_id = {str(f.id): f for f in user_folders}

        agents_result = await session.exec(user_agents_stmt(scoped_user_uuids))
        user_agents = agents_result.all()
        agents_by_id = {str(f.id): f for f in user_agents}
        agents_by_name = {f.name: f for f in user_agents}
        agent_to_folder = {str(a.id): str(a.folder_id) for a in user_agents if a.folder_id}

        from_ts, to_ts = compute_date_range(from_date, to_date, tz_offset, default_days=None)

        traces, truncated = TraceStore.get_traces(
            clients=scoped_clients,
            allowed_user_ids=allowed_user_ids,
            scope_key=scope_key,
            from_timestamp=from_ts,
            to_timestamp=to_ts,
            environment=environment,
            fetch_all=fetch_all,
        )

        projects_list = aggregate_projects(traces, agents_by_id, agents_by_name, agent_to_folder, folders_by_id)
        total_count = len(projects_list)
        projects_list = projects_list[:limit]

        return ProjectListResponse(
            projects=projects_list,
            total=total_count,
            truncated=truncated,
            fetched_trace_count=len(traces),
            **scope_warning_payload(scope_warnings),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching projects: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch projects: {e}")


@router.get("/projects/{project_id}")
async def get_project_detail(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    org_id: Annotated[UUID | None, Query(description="Organization scope")] = None,
    dept_id: Annotated[UUID | None, Query(description="Department scope")] = None,
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD)")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC")] = None,
    environment: Annotated[str | None, Query(description="'uat' or 'production'")] = None,
) -> ProjectDetailResponse:
    """Get detailed project information including agents and metrics."""
    clear_request_caches()

    allowed_user_ids, scoped_clients, scope_key, scope_warnings = await resolve_scope_context(
        session=session, current_user=current_user, org_id=org_id, dept_id=dept_id,
    )
    if not scoped_clients:
        raise HTTPException(status_code=404, detail=(scope_warnings[0] if scope_warnings else "Project not found"))

    try:
        scoped_user_uuids = _to_uuids(allowed_user_ids)

        try:
            folder_uuid = UUID(project_id)
            folder_result = await session.exec(
                select(Folder).where(Folder.id == folder_uuid, Folder.user_id.in_(scoped_user_uuids))
            )
            folder = folder_result.first()
        except ValueError:
            folder = None

        if not folder:
            raise HTTPException(status_code=404, detail="Project not found")

        agents_stmt = user_agents_stmt(scoped_user_uuids).where(Agent.folder_id == folder.id)
        agents_result = await session.exec(agents_stmt)
        folder_agents = agents_result.all()
        agents_by_id = {str(f.id): f for f in folder_agents}
        agents_by_name = {f.name: f for f in folder_agents}

        if not folder_agents:
            return ProjectDetailResponse(
                project_id=project_id, project_name=folder.name,
                **scope_warning_payload(scope_warnings),
            )

        from_ts, to_ts = compute_date_range(from_date, to_date, tz_offset, default_days=None)

        traces, _ = TraceStore.get_traces(
            clients=scoped_clients,
            allowed_user_ids=allowed_user_ids,
            scope_key=scope_key,
            from_timestamp=from_ts,
            to_timestamp=to_ts,
            environment=environment,
        )

        # Aggregate
        agents_data: dict[str, dict] = {}
        total_traces = total_observations = total_tokens = input_tokens = output_tokens = 0
        total_cost = 0.0
        latencies: list[float] = []
        sessions: set[str] = set()
        timestamps: list[datetime] = []
        models_used: dict[str, dict] = {}
        daily_data: dict[str, dict] = defaultdict(lambda: {"trace_count": 0, "observation_count": 0, "total_tokens": 0, "total_cost": 0.0})

        for t in traces:
            matched_fid, matched_fname = match_trace_to_agent(t, agents_by_id, agents_by_name)
            if not matched_fid:
                continue

            total_traces += 1
            total_observations += t.observation_count
            total_tokens += t.total_tokens
            input_tokens += t.input_tokens
            output_tokens += t.output_tokens
            total_cost += t.total_cost
            if t.latency_ms is not None:
                latencies.append(t.latency_ms)
            if t.session_id:
                sessions.add(t.session_id)
            if t.timestamp:
                timestamps.append(t.timestamp)

            for model_name in t.models:
                if model_name not in models_used:
                    models_used[model_name] = {"tokens": 0, "cost": 0.0, "calls": 0}
                models_used[model_name]["tokens"] += t.total_tokens
                models_used[model_name]["cost"] += t.total_cost
                models_used[model_name]["calls"] += 1

            # Per-agent
            if matched_fid not in agents_data:
                agents_data[matched_fid] = {
                    "agent_name": matched_fname, "trace_count": 0, "sessions": set(),
                    "total_tokens": 0, "total_cost": 0.0, "models": set(),
                    "latencies": [], "timestamps": [],
                }
            ad = agents_data[matched_fid]
            ad["trace_count"] += 1
            ad["total_tokens"] += t.total_tokens
            ad["total_cost"] += t.total_cost
            ad["models"].update(t.models)
            if t.latency_ms is not None:
                ad["latencies"].append(t.latency_ms)
            if t.session_id:
                ad["sessions"].add(t.session_id)
            if t.timestamp:
                ad["timestamps"].append(t.timestamp)
                if tz_offset is not None:
                    date_str = (t.timestamp + timedelta(minutes=tz_offset)).strftime("%Y-%m-%d")
                else:
                    date_str = t.timestamp.strftime("%Y-%m-%d")
                daily_data[date_str]["trace_count"] += 1
                daily_data[date_str]["observation_count"] += t.observation_count
                daily_data[date_str]["total_tokens"] += t.total_tokens
                daily_data[date_str]["total_cost"] += t.total_cost

        agents_list = []
        for fid, data in agents_data.items():
            ts = data["timestamps"]
            lats = data["latencies"]
            agents_list.append(AgentListItem(
                agent_id=fid, agent_name=data["agent_name"],
                trace_count=data["trace_count"], session_count=len(data["sessions"]),
                total_tokens=data["total_tokens"], total_cost=data["total_cost"],
                avg_latency_ms=sum(lats) / len(lats) if lats else None,
                models_used=list(data["models"]),
                last_activity=max(ts) if ts else None,
            ))
        agents_list.sort(key=lambda a: a.last_activity or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        by_date = [DailyUsageItem(date=d, **data) for d, data in sorted(daily_data.items())]

        return ProjectDetailResponse(
            project_id=project_id,
            project_name=folder.name,
            agent_count=len(agents_data),
            trace_count=total_traces,
            session_count=len(sessions),
            observation_count=total_observations,
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost=total_cost,
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else None,
            first_activity=min(timestamps) if timestamps else None,
            last_activity=max(timestamps) if timestamps else None,
            models_used=models_used,
            agents=agents_list,
            by_date=by_date,
            **scope_warning_payload(scope_warnings),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching project detail: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch project: {e}")


def _to_uuids(user_ids: set[str]) -> list[UUID]:
    uuids = []
    for uid in user_ids:
        try:
            uuids.append(UUID(uid))
        except Exception:
            continue
    return uuids
