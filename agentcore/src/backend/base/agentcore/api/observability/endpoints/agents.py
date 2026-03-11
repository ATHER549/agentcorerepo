"""GET /agents and /agents/{agent_id} endpoints."""

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

from ..aggregations import aggregate_agents, match_trace_to_agent, user_agents_stmt
from ..models import (
    AgentDetailResponse,
    AgentListItem,
    AgentListResponse,
    DailyUsageItem,
    SessionListItem,
)
from ..parsing import clear_request_caches, compute_date_range
from ..scope import resolve_scope_context, scope_warning_payload
from ..trace_store import TraceStore

router = APIRouter()


@router.get("/agents")
async def get_user_agents(
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
) -> AgentListResponse:
    """Get all agents for the current user with aggregated metrics."""
    clear_request_caches()

    allowed_user_ids, scoped_clients, scope_key, scope_warnings = await resolve_scope_context(
        session=session, current_user=current_user, org_id=org_id, dept_id=dept_id,
    )
    if not scoped_clients:
        return AgentListResponse(
            agents=[], total=0, truncated=False, fetched_trace_count=0,
            **scope_warning_payload(scope_warnings),
        )

    try:
        scoped_user_uuids = _to_uuids(allowed_user_ids)

        # DB lookups
        agents_result = await session.exec(user_agents_stmt(scoped_user_uuids))
        user_agents = agents_result.all()
        agents_by_id = {str(f.id): f for f in user_agents}
        agents_by_name = {f.name: f for f in user_agents}

        folder_ids = set(f.folder_id for f in user_agents if f.folder_id)
        folders_by_id: dict[str, Folder] = {}
        if folder_ids:
            folders_result = await session.exec(select(Folder).where(Folder.id.in_(folder_ids)))
            folders_by_id = {str(f.id): f for f in folders_result.all()}

        agent_to_folder: dict[str, tuple[str | None, str | None]] = {}
        for agent in user_agents:
            fid = str(agent.folder_id) if agent.folder_id else None
            fname = folders_by_id.get(fid).name if fid and fid in folders_by_id else None
            agent_to_folder[str(agent.id)] = (fid, fname)

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

        agents_list = aggregate_agents(traces, agents_by_id, agents_by_name, agent_to_folder)
        total_count = len(agents_list)
        agents_list = agents_list[:limit]

        return AgentListResponse(
            agents=agents_list,
            total=total_count,
            truncated=truncated,
            fetched_trace_count=len(traces),
            **scope_warning_payload(scope_warnings),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching agents: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch agents: {e}")


@router.get("/agents/{agent_id}")
async def get_agent_detail(
    agent_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    org_id: Annotated[UUID | None, Query(description="Organization scope")] = None,
    dept_id: Annotated[UUID | None, Query(description="Department scope")] = None,
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD)")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC")] = None,
    environment: Annotated[str | None, Query(description="'uat' or 'production'")] = None,
) -> AgentDetailResponse:
    """Get detailed agent information including sessions and metrics breakdown."""
    clear_request_caches()

    allowed_user_ids, scoped_clients, scope_key, scope_warnings = await resolve_scope_context(
        session=session, current_user=current_user, org_id=org_id, dept_id=dept_id,
    )
    if not scoped_clients:
        raise HTTPException(status_code=404, detail=(scope_warnings[0] if scope_warnings else "Agent not found"))

    try:
        scoped_user_uuids = _to_uuids(allowed_user_ids)

        try:
            agent_uuid = UUID(agent_id)
            agent_result = await session.exec(
                select(Agent).where(Agent.id == agent_uuid, Agent.user_id.in_(scoped_user_uuids))
            )
            agent = agent_result.first()
        except ValueError:
            agent = None

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        agents_by_id = {str(agent.id): agent}
        agents_by_name = {agent.name: agent}

        from_ts, to_ts = compute_date_range(from_date, to_date, tz_offset, default_days=None)

        traces, _ = TraceStore.get_traces(
            clients=scoped_clients,
            allowed_user_ids=allowed_user_ids,
            scope_key=scope_key,
            from_timestamp=from_ts,
            to_timestamp=to_ts,
            environment=environment,
        )

        # Two-pass: identify sessions, then aggregate
        agent_sessions: set[str] = set()
        agent_trace_count = 0
        for t in traces:
            matched_fid, _ = match_trace_to_agent(t, agents_by_id, agents_by_name)
            if matched_fid == agent_id:
                agent_trace_count += 1
                if t.session_id:
                    agent_sessions.add(t.session_id)

        if agent_trace_count == 0:
            return AgentDetailResponse(
                agent_id=agent_id, agent_name=agent.name,
                **scope_warning_payload(scope_warnings),
            )

        total_tokens = input_tokens = output_tokens = 0
        total_cost = 0.0
        total_observations = 0
        latencies: list[float] = []
        models_used: dict[str, dict] = {}
        timestamps: list[datetime] = []
        sessions_data: dict[str, dict] = {}
        daily_data: dict[str, dict] = defaultdict(lambda: {"trace_count": 0, "observation_count": 0, "total_tokens": 0, "total_cost": 0.0})
        processed: set[str] = set()

        for t in traces:
            if t.id in processed:
                continue
            matched_fid, _ = match_trace_to_agent(t, agents_by_id, agents_by_name)
            is_agent_trace = matched_fid == agent_id
            if not is_agent_trace and not (t.session_id and t.session_id in agent_sessions):
                continue
            processed.add(t.id)

            total_tokens += t.total_tokens
            input_tokens += t.input_tokens
            output_tokens += t.output_tokens
            total_cost += t.total_cost
            total_observations += t.observation_count
            if t.latency_ms is not None:
                latencies.append(t.latency_ms)
            for model_name in t.models:
                if model_name not in models_used:
                    models_used[model_name] = {"tokens": 0, "cost": 0.0, "calls": 0}
                models_used[model_name]["tokens"] += t.total_tokens
                models_used[model_name]["cost"] += t.total_cost
                models_used[model_name]["calls"] += 1
            if t.timestamp:
                timestamps.append(t.timestamp)
                if tz_offset is not None:
                    date_str = (t.timestamp + timedelta(minutes=tz_offset)).strftime("%Y-%m-%d")
                else:
                    date_str = t.timestamp.strftime("%Y-%m-%d")
                if is_agent_trace:
                    daily_data[date_str]["trace_count"] += 1
                daily_data[date_str]["observation_count"] += t.observation_count
                daily_data[date_str]["total_tokens"] += t.total_tokens
                daily_data[date_str]["total_cost"] += t.total_cost

            if t.session_id:
                if t.session_id not in sessions_data:
                    sessions_data[t.session_id] = {
                        "trace_count": 0, "total_tokens": 0, "total_cost": 0.0,
                        "timestamps": [], "models": set(), "error_count": 0,
                    }
                sd = sessions_data[t.session_id]
                if is_agent_trace:
                    sd["trace_count"] += 1
                sd["total_tokens"] += t.total_tokens
                sd["total_cost"] += t.total_cost
                if t.timestamp:
                    sd["timestamps"].append(t.timestamp)
                sd["models"].update(t.models)
                sd["error_count"] += t.error_count

        sessions_list = []
        for sid, data in sessions_data.items():
            ts = data["timestamps"]
            err = int(data["error_count"])
            sessions_list.append(SessionListItem(
                session_id=sid, trace_count=data["trace_count"],
                total_tokens=data["total_tokens"], total_cost=data["total_cost"],
                first_trace_at=min(ts) if ts else None, last_trace_at=max(ts) if ts else None,
                models_used=list(data["models"]), error_count=err, has_errors=err > 0,
            ))
        sessions_list.sort(key=lambda s: s.last_trace_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        by_date = [
            DailyUsageItem(date=d, **data)
            for d, data in sorted(daily_data.items())
        ]

        return AgentDetailResponse(
            agent_id=agent_id,
            agent_name=agent.name,
            trace_count=agent_trace_count,
            session_count=len(agent_sessions),
            observation_count=total_observations,
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost=total_cost,
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else None,
            first_activity=min(timestamps) if timestamps else None,
            last_activity=max(timestamps) if timestamps else None,
            models_used=models_used,
            sessions=sessions_list,
            by_date=by_date,
            **scope_warning_payload(scope_warnings),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching agent detail: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch agent: {e}")


def _to_uuids(user_ids: set[str]) -> list[UUID]:
    uuids = []
    for uid in user_ids:
        try:
            uuids.append(UUID(uid))
        except Exception:
            continue
    return uuids
