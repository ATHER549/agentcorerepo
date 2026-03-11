"""GET /metrics endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.auth.utils import get_current_active_user
from agentcore.services.database.models.user.model import User
from agentcore.services.deps import get_session

from ..aggregations import aggregate_metrics
from ..models import MetricsResponse
from ..parsing import clear_request_caches, compute_date_range
from ..scope import resolve_scope_context, scope_warning_payload
from ..trace_store import TraceStore

router = APIRouter()


@router.get("/metrics")
async def get_metrics(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    org_id: Annotated[UUID | None, Query(description="Organization scope")] = None,
    dept_id: Annotated[UUID | None, Query(description="Department scope")] = None,
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD)")] = None,
    search: Annotated[str | None, Query(description="Search by trace name")] = None,
    models: Annotated[str | None, Query(description="Filter by model names (comma-separated)")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC")] = None,
    include_model_breakdown: Annotated[bool, Query()] = True,
    fetch_all: Annotated[bool, Query(description="Fetch all traces (up to 5000)")] = False,
    environment: Annotated[str | None, Query(description="'uat' or 'production'")] = None,
) -> MetricsResponse:
    """Comprehensive aggregated metrics for enterprise dashboards."""
    clear_request_caches()

    try:
        allowed_user_ids, scoped_clients, scope_key, scope_warnings = await resolve_scope_context(
            session=session, current_user=current_user, org_id=org_id, dept_id=dept_id,
        )
        if not scoped_clients or not allowed_user_ids:
            return MetricsResponse(**scope_warning_payload(scope_warnings))

        from_ts, to_ts = compute_date_range(from_date, to_date, tz_offset, default_days=days)

        traces, truncated = TraceStore.get_traces(
            clients=scoped_clients,
            allowed_user_ids=allowed_user_ids,
            scope_key=scope_key,
            from_timestamp=from_ts,
            to_timestamp=to_ts,
            environment=environment,
            search=search,
            fetch_all=fetch_all,
        )

        metrics_dict = aggregate_metrics(traces, tz_offset=tz_offset)
        metrics_dict["truncated"] = truncated

        return MetricsResponse(
            **metrics_dict,
            **scope_warning_payload(scope_warnings),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch metrics: {e}")
