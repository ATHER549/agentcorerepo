"""GET /status and /debug endpoints."""

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.auth.utils import get_current_active_user
from agentcore.services.database.models.user.model import User
from agentcore.services.deps import get_session

from ..langfuse_client import get_langfuse_client, is_v3_client
from ..models import LangfuseStatusResponse
from ..parsing import get_attr
from ..scope import resolve_scope_context

router = APIRouter()


@router.get("/status")
async def get_langfuse_status(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> LangfuseStatusResponse:
    """Check if Langfuse is connected and available."""
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL")
    try:
        _allowed_user_ids, scoped_clients, _scope_key, scope_warnings = await resolve_scope_context(
            session=session,
            current_user=current_user,
            enforce_filter_for_admin=False,
        )
    except Exception as exc:
        return LangfuseStatusResponse(connected=False, host=host, message=f"Cannot resolve observability scope: {exc}")

    if not scoped_clients:
        msg = " ".join(scope_warnings) if scope_warnings else "No scoped Langfuse binding found."
        return LangfuseStatusResponse(connected=False, host=host, message=msg)

    for scoped_client in scoped_clients:
        try:
            resolved_host = get_attr(scoped_client, "host", "_host", "base_url", "_base_url", default=None) or host
            if is_v3_client(scoped_client):
                if hasattr(scoped_client, "auth_check"):
                    if scoped_client.auth_check():
                        return LangfuseStatusResponse(
                            connected=True, host=resolved_host,
                            message="Langfuse connected successfully (scoped binding, SDK v3)",
                        )
                else:
                    return LangfuseStatusResponse(
                        connected=True, host=resolved_host,
                        message="Langfuse client initialized successfully (scoped binding)",
                    )
            else:
                from langfuse.api.core.request_options import RequestOptions
                scoped_client.client.health.health(request_options=RequestOptions(timeout_in_seconds=2))
                return LangfuseStatusResponse(
                    connected=True, host=resolved_host,
                    message="Langfuse connected successfully (scoped binding, SDK v2)",
                )
        except Exception:
            continue

    msg = " ".join(scope_warnings) if scope_warnings else "Scoped Langfuse bindings are configured but not reachable."
    return LangfuseStatusResponse(connected=False, host=host, message=msg)


@router.get("/debug")
async def debug_langfuse_data(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict:
    """Debug endpoint to diagnose observability data issues."""
    client = get_langfuse_client()
    if not client:
        return {"error": "Langfuse not configured"}

    result: dict[str, Any] = {
        "current_user_id": str(current_user.id),
        "langfuse_methods": [m for m in ("fetch_traces", "fetch_observations", "fetch_trace", "get_traces") if hasattr(client, m)],
        "all_traces_count": 0,
        "user_traces_count": 0,
        "sample_user_ids": [],
        "sample_traces": [],
        "errors": [],
    }

    try:
        if hasattr(client, "fetch_traces"):
            response = client.fetch_traces(limit=100)
            all_traces = response.data if hasattr(response, "data") else (response if isinstance(response, list) else response.get("data", []) if isinstance(response, dict) else [])
            result["all_traces_count"] = len(all_traces or [])
            user_ids = {str(get_attr(t, "user_id", "userId")) for t in (all_traces or []) if get_attr(t, "user_id", "userId")}
            result["sample_user_ids"] = list(user_ids)[:20]
            result["user_traces_count"] = sum(1 for t in (all_traces or []) if str(get_attr(t, "user_id", "userId") or "") == str(current_user.id))
    except Exception as e:
        result["errors"].append(f"fetch_traces error: {e}")

    return result
