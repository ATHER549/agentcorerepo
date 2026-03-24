"""GET /sessions and /sessions/{session_id} endpoints."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.auth.utils import get_current_active_user
from agentcore.services.database.models.user.model import User
from agentcore.services.deps import get_session

from ..aggregations import aggregate_sessions
from ..models import (
    DailyUsageItem,
    SessionDetailResponse,
    SessionListItem,
    SessionsListResponse,
    TraceListItem,
)
from ..parsing import clear_request_caches, compute_date_range
from ..scope import resolve_scope_context, scope_warning_payload
from ..trace_store import TraceStore

router = APIRouter()


@router.get("/sessions")
async def get_user_sessions(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    org_id: Annotated[UUID | None, Query(description="Organization scope")] = None,
    dept_id: Annotated[UUID | None, Query(description="Department scope")] = None,
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD)")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC")] = None,
    search: Annotated[str | None, Query(description="Search by session ID")] = None,
    fetch_all: Annotated[bool, Query()] = False,
    environment: Annotated[str | None, Query(description="'uat' or 'production'")] = None,
    trace_scope: Annotated[str, Query(description="Trace scope: 'all', 'dept', or 'my'")] = "all",
) -> SessionsListResponse:
    """Get chat sessions with aggregated metrics."""
    clear_request_caches()

    try:
        allowed_user_ids, scoped_clients, scope_key, scope_warnings = await resolve_scope_context(
            session=session, current_user=current_user, org_id=org_id, dept_id=dept_id,
            trace_scope=trace_scope,
        )
        if not scoped_clients:
            return SessionsListResponse(
                sessions=[], total=0, truncated=False, fetched_trace_count=0,
                **scope_warning_payload(scope_warnings),
            )

        from_ts, to_ts = compute_date_range(from_date, to_date, tz_offset, default_days=1)

        traces, truncated = TraceStore.get_traces(
            clients=scoped_clients,
            allowed_user_ids=allowed_user_ids,
            scope_key=scope_key,
            from_timestamp=from_ts,
            to_timestamp=to_ts,
            environment=environment,
            fetch_all=fetch_all,
        )

        sessions_list = aggregate_sessions(traces, search=search)
        total_count = len(sessions_list)
        sessions_list = sessions_list[:limit]

        return SessionsListResponse(
            sessions=sessions_list,
            total=total_count,
            truncated=truncated,
            fetched_trace_count=len(traces),
            **scope_warning_payload(scope_warnings),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch sessions: {e}")


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    org_id: Annotated[UUID | None, Query(description="Organization scope")] = None,
    dept_id: Annotated[UUID | None, Query(description="Department scope")] = None,
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD)")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC")] = None,
    environment: Annotated[str | None, Query(description="'uat' or 'production'")] = None,
    trace_scope: Annotated[str, Query(description="Trace scope: 'all', 'dept', or 'my'")] = "all",
) -> SessionDetailResponse:
    """Get detailed session information including all traces."""
    clear_request_caches()

    allowed_user_ids, scoped_clients, scope_key, scope_warnings = await resolve_scope_context(
        session=session, current_user=current_user, org_id=org_id, dept_id=dept_id,
        trace_scope=trace_scope,
    )
    if not scoped_clients:
        raise HTTPException(status_code=404, detail=(scope_warnings[0] if scope_warnings else "Session not found"))

    try:
        from_ts, to_ts = compute_date_range(from_date, to_date, tz_offset, default_days=None)

        all_traces, _ = TraceStore.get_traces(
            clients=scoped_clients,
            allowed_user_ids=allowed_user_ids,
            scope_key=scope_key,
            from_timestamp=from_ts,
            to_timestamp=to_ts,
            environment=environment,
        )

        # Filter to this session
        session_traces = [t for t in all_traces if t.session_id == session_id]
        if not session_traces:
            raise HTTPException(status_code=404, detail="Session not found or has no traces in the selected date range")

        total_tokens = sum(t.total_tokens for t in session_traces)
        input_tokens = sum(t.input_tokens for t in session_traces)
        output_tokens = sum(t.output_tokens for t in session_traces)
        total_cost = sum(t.total_cost for t in session_traces)
        total_observations = sum(t.observation_count for t in session_traces)

        latencies = [t.latency_ms for t in session_traces if t.latency_ms is not None]
        avg_latency = sum(latencies) / len(latencies) if latencies else None

        timestamps = [t.timestamp for t in session_traces if t.timestamp]
        first_trace_at = min(timestamps) if timestamps else None
        last_trace_at = max(timestamps) if timestamps else None
        duration = (last_trace_at - first_trace_at).total_seconds() if first_trace_at and last_trace_at else None

        # Model breakdown
        models_used: dict[str, dict] = {}
        for t in session_traces:
            for model_name in t.models:
                if model_name not in models_used:
                    models_used[model_name] = {"tokens": 0, "cost": 0.0, "calls": 0}
                models_used[model_name]["tokens"] += t.total_tokens
                models_used[model_name]["cost"] += t.total_cost
                models_used[model_name]["calls"] += 1

        # Build trace list items
        trace_items = [
            TraceListItem(
                id=t.id, name=t.name, session_id=t.session_id,
                timestamp=t.timestamp, total_tokens=t.total_tokens,
                total_cost=t.total_cost, latency_ms=t.latency_ms,
                models_used=t.models, observation_count=t.observation_count,
                level=t.level,
            )
            for t in session_traces
        ]
        trace_items.sort(key=lambda t: t.timestamp or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        return SessionDetailResponse(
            session_id=session_id,
            trace_count=len(session_traces),
            observation_count=total_observations,
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost=total_cost,
            avg_latency_ms=avg_latency,
            first_trace_at=first_trace_at,
            last_trace_at=last_trace_at,
            duration_seconds=duration,
            models_used=models_used,
            traces=trace_items,
            **scope_warning_payload(scope_warnings),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching session detail: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch session: {e}")
