"""
Observability API Endpoints - Enterprise Edition

These endpoints provide user-isolated access to observability data from Langfuse.
Each user can only see their own traces, token usage, and cost metrics.

Features:
- Session-centric view with drill-down to traces
- Detailed trace view with observations/spans (LLM calls, tool calls)
- Token and cost tracking per model, session, and trace
- Latency metrics
- User isolation at all levels
"""

import os
import json
import time
import traceback
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Annotated, Any
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from loguru import logger
from pydantic import BaseModel, Field

from agentcore.services.auth.utils import get_current_active_user
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.agent.model import Agent as Agent
from agentcore.services.database.models.folder.model import Folder
from agentcore.services.deps import get_session
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


router = APIRouter(prefix="/observability", tags=["Observability"])


# Process-local caches to reduce repeated high-latency Langfuse calls.
_LANGFUSE_CLIENT_CACHE: dict[str, Any] = {"fingerprint": None, "client": None}
_TRACE_FETCH_CACHE: dict[str, dict[str, Any]] = {}
_TRACE_CACHE_TTL_SECONDS = 12.0
_TRACE_CACHE_STALE_SECONDS = 90.0
_TRACE_METRICS_CACHE: dict[str, dict[str, Any]] = {}
_TRACE_METRICS_CACHE_TTL_SECONDS = 60.0
# Cache for per-trace observations — avoids redundant Langfuse calls during the same session.
_OBSERVATIONS_CACHE: dict[str, dict[str, Any]] = {}
# SWR caches for list endpoints
_AGENTS_CACHE: dict[str, dict[str, Any]] = {}
_SESSIONS_CACHE: dict[str, dict[str, Any]] = {}
_PROJECTS_CACHE: dict[str, dict[str, Any]] = {}
_OBSERVATIONS_CACHE_TTL_SECONDS = 60.0

# Request-scoped observation cache (cleared per API request) to deduplicate within-request observation fetches
_REQUEST_OBSERVATIONS_CACHE: dict[str, list] = {}
_REQUEST_METRICS_CACHE: dict[str, dict[str, Any]] = {}


def _clear_request_caches() -> None:
    """Clear per-request caches (call once per API request to prevent stale data)."""
    global _REQUEST_OBSERVATIONS_CACHE, _REQUEST_METRICS_CACHE
    _REQUEST_OBSERVATIONS_CACHE.clear()
    _REQUEST_METRICS_CACHE.clear()


def _make_fallback_budget(total_traces: int, cap: int = 200) -> dict[str, int]:
    """Create a bounded observation-fallback budget for missing trace-level metrics.

    A higher budget improves token consistency across list endpoints when Langfuse
    traces are missing token/cost/model fields and require observation enrichment.
    """
    if total_traces <= 0:
        return {"remaining": 0}
    return {"remaining": min(cap, total_traces)}


# =============================================================================
# Stale-While-Revalidate (SWR) Configuration & Infrastructure
# =============================================================================

# SWR thresholds (in seconds) - all configurable
SWR_CONFIG = {
    "FRESH_SECONDS": 15,              # Data is fresh, return immediately no refresh
    "STALE_SECONDS": 60,              # Data is stale, return + trigger background refresh
    "EXPIRED_SECONDS": 300,           # Data is expired, wait for fresh fetch
    "MAX_CONCURRENT_FETCHES": 3,      # Prevent overwhelming Langfuse
    "FETCH_TIMEOUT": 30,              # Max time for background fetch
    "ENABLE_SWR": True,               # Feature flag to disable SWR
}

# Cache metadata storage (tracks when each cache entry was created)
_CACHE_METADATA: dict[str, dict[str, Any]] = {}

# Track in-progress background fetches (prevent duplicate fetches)
_BACKGROUND_FETCH_IN_PROGRESS: set[str] = set()

# Lock for concurrent access to _BACKGROUND_FETCH_IN_PROGRESS
_FETCH_LOCK = asyncio.Lock()


def _get_cache_metadata(cache_key: str) -> dict[str, Any]:
    """Get cache age and freshness info."""
    if cache_key not in _CACHE_METADATA:
        return {
            "cached_at": None,
            "age_seconds": float('inf'),
            "is_fresh": False,
            "is_stale": False,
            "is_expired": True,
        }
    
    meta = _CACHE_METADATA[cache_key]
    age_seconds = time.time() - meta["timestamp"]
    fresh_threshold = SWR_CONFIG["FRESH_SECONDS"]
    stale_threshold = SWR_CONFIG["STALE_SECONDS"]
    
    return {
        "cached_at": datetime.fromtimestamp(meta["timestamp"], tz=timezone.utc),
        "age_seconds": int(age_seconds),
        "is_fresh": age_seconds < fresh_threshold,
        "is_stale": fresh_threshold <= age_seconds < stale_threshold,
        "is_expired": age_seconds >= stale_threshold,
    }


def _update_cache_metadata(cache_key: str, data: Any) -> None:
    """Update cache metadata with current timestamp."""
    _CACHE_METADATA[cache_key] = {
        "timestamp": time.time(),
        "data_hash": hash(str(data)[:100]) if data else None,
    }


async def _mark_fetch_in_progress(cache_key: str) -> bool:
    """Mark a fetch as in progress. Return False if already in progress."""
    async with _FETCH_LOCK:
        if cache_key in _BACKGROUND_FETCH_IN_PROGRESS:
            return False
        _BACKGROUND_FETCH_IN_PROGRESS.add(cache_key)
        return True


async def _mark_fetch_complete(cache_key: str) -> None:
    """Mark fetch as complete."""
    async with _FETCH_LOCK:
        _BACKGROUND_FETCH_IN_PROGRESS.discard(cache_key)


# =============================================================================
# Response Models - Enterprise Grade
# =============================================================================

class ObservationResponse(BaseModel):
    """
    A single observation (span) within a trace.

    Observations represent individual operations like:
    - LLM calls (generation)
    - Tool/function calls
    - Retrieval operations
    - Custom spans
    """
    id: str
    trace_id: str
    name: str | None = None
    type: str | None = None  # "GENERATION", "SPAN", "EVENT"
    model: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    completion_start_time: datetime | None = None
    latency_ms: float | None = None  # Total latency in milliseconds
    time_to_first_token_ms: float | None = None
    # Token metrics
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    # Cost
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    # Data
    input: Any | None = None
    output: Any | None = None
    metadata: dict | None = None
    level: str | None = None  # "DEBUG", "DEFAULT", "WARNING", "ERROR"
    status_message: str | None = None
    parent_observation_id: str | None = None


class ScoreItem(BaseModel):
    """Evaluation score for a trace."""
    id: str
    name: str
    value: float
    source: str | None = None
    comment: str | None = None
    created_at: datetime | None = None


class TraceDetailResponse(BaseModel):
    """
    Detailed trace information with all observations.
    """
    id: str
    name: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    timestamp: datetime | None = None
    # Aggregated metrics from observations
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    latency_ms: float | None = None
    # Model breakdown
    models_used: list[str] = []
    # Observations (spans) within this trace
    observations: list[ObservationResponse] = []
    # Evaluation scores
    scores: list[ScoreItem] = []
    # Metadata
    input: Any | None = None
    output: Any | None = None
    metadata: dict | None = None
    tags: list[str] = []
    # Status
    level: str | None = None
    status: str | None = None


class TraceListItem(BaseModel):
    """Trace item for list views (lighter than full detail)."""
    id: str
    name: str | None = None
    session_id: str | None = None
    timestamp: datetime | None = None
    total_tokens: int = 0
    total_cost: float = 0.0
    latency_ms: float | None = None
    models_used: list[str] = []
    observation_count: int = 0
    level: str | None = None


class TracesListResponse(BaseModel):
    """List of traces with pagination info."""
    traces: list[TraceListItem]
    total: int
    page: int
    limit: int


class SessionDetailResponse(BaseModel):
    """
    Detailed session information with all traces.
    A session represents a chat conversation.
    """
    session_id: str
    trace_count: int = 0
    observation_count: int = 0
    # Aggregated metrics
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float | None = None
    # Time range
    first_trace_at: datetime | None = None
    last_trace_at: datetime | None = None
    duration_seconds: float | None = None
    # Model usage within session
    models_used: dict[str, dict] = {}  # model -> {tokens, cost, calls}
    # Traces in this session
    traces: list[TraceListItem] = []


class SessionListItem(BaseModel):
    """Session item for list views."""
    session_id: str
    trace_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float | None = None
    first_trace_at: datetime | None = None
    last_trace_at: datetime | None = None
    models_used: list[str] = []
    error_count: int = 0  # Count of ERROR/WARNING observations
    has_errors: bool = False  # Quick flag for UI


class SessionsListResponse(BaseModel):
    """List of sessions."""
    sessions: list[SessionListItem]
    total: int
    truncated: bool = False
    fetched_trace_count: int = 0


class ModelUsageItem(BaseModel):
    """Usage metrics for a specific model."""
    model: str
    call_count: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float | None = None


class DailyUsageItem(BaseModel):
    """Daily usage statistics."""
    date: str
    trace_count: int = 0
    observation_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0


class MetricsResponse(BaseModel):
    """
    Comprehensive aggregated metrics for enterprise dashboards.
    Includes cache metadata for client-side refresh indicators.
    """
    # Overview counts
    total_traces: int = 0
    total_observations: int = 0
    total_sessions: int = 0
    # Token metrics
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    # Cost metrics
    total_cost_usd: float = 0.0
    # Performance metrics
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    # Breakdown by model
    by_model: list[ModelUsageItem] = []
    # Breakdown by date (last 30 days)
    by_date: list[DailyUsageItem] = []
    # Top agents/traces by usage
    top_agents: list[dict] = []
    # Truncation info - lets UI know if data is incomplete
    truncated: bool = False
    fetched_trace_count: int = 0
    # Cache metadata (for SWR indicator in UI)
    cache_age_seconds: int | None = None
    cache_is_fresh: bool | None = None


class LangfuseStatusResponse(BaseModel):
    """Langfuse connection status."""
    connected: bool
    host: str | None = None
    message: str


# =============================================================================
# Helper Functions
# =============================================================================

def get_langfuse_client():
    """
    Get a Langfuse client using environment variables.
    Supports both Langfuse SDK v3 and v2.

    IMPORTANT: For data fetching (traces, observations), we use the Langfuse class
    directly, NOT get_client(). The get_client() is for OTEL-based tracing only.

    v3 expects env vars: LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL
    v2 expects env vars: LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_HOST

    Returns the Langfuse client instance with _is_v3 attribute set.
    """
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    # v3 uses LANGFUSE_BASE_URL, v2 uses LANGFUSE_HOST
    base_url = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")

    if not all([secret_key, public_key, base_url]):
        logger.warning("Langfuse credentials not configured. Need LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_BASE_URL (or LANGFUSE_HOST)")
        return None

    # Reuse an initialized client for the same credentials to avoid repeated
    # auth checks and connection setup on each request.
    fingerprint = f"{public_key}:{base_url}:{len(secret_key)}"
    cached = _LANGFUSE_CLIENT_CACHE.get("client")
    if cached is not None and _LANGFUSE_CLIENT_CACHE.get("fingerprint") == fingerprint:
        return cached

    try:
        # Use Langfuse class directly for data fetching (works in both v2 and v3)
        # Note: get_client() is for OTEL tracing, Langfuse() is for data access
        from langfuse import Langfuse

        # Ensure LANGFUSE_BASE_URL is set for v3 compatibility
        if not os.getenv("LANGFUSE_BASE_URL") and os.getenv("LANGFUSE_HOST"):
            os.environ["LANGFUSE_BASE_URL"] = os.getenv("LANGFUSE_HOST")

        client = Langfuse(
            secret_key=secret_key,
            public_key=public_key,
            host=base_url
        )

        # Detect v3 by checking SDK version + client capabilities.
        is_v3 = False
        sdk_version = "unknown"
        try:
            import langfuse
            sdk_version = getattr(langfuse, '__version__', 'unknown')
            # v3.x starts with 3.
            if sdk_version.startswith('3.'):
                is_v3 = True
            # Capability-based fallback (some builds may not expose __version__)
            if hasattr(client, 'api'):
                api_obj = getattr(client, 'api', None)
                if api_obj and (
                    hasattr(api_obj, 'trace')
                    or hasattr(api_obj, 'traces')
                    or hasattr(api_obj, 'observations')
                    or hasattr(api_obj, 'scores')
                ):
                    is_v3 = True
            if hasattr(client, 'auth_check'):
                # Keep this as secondary hint.
                is_v3 = True
        except Exception:
            # If version check fails, infer from capabilities.
            is_v3 = bool(
                hasattr(client, 'auth_check')
                or (
                    hasattr(client, 'api')
                    and (
                        hasattr(getattr(client, 'api', None), 'trace')
                        or hasattr(getattr(client, 'api', None), 'traces')
                    )
                )
            )

        client._is_v3 = is_v3
        client._sdk_version = sdk_version

        # Health check
        if is_v3:
            try:
                if client.auth_check():
                    logger.info(f"Using Langfuse SDK v3 ({sdk_version}) - auth_check passed")
                else:
                    logger.warning(f"Langfuse v3 ({sdk_version}) auth_check failed")
            except Exception as e:
                logger.debug(f"v3 auth_check error (continuing anyway): {e}")
        else:
            logger.info(f"Using Langfuse SDK v2 ({sdk_version})")

        _LANGFUSE_CLIENT_CACHE["fingerprint"] = fingerprint
        _LANGFUSE_CLIENT_CACHE["client"] = client
        return client

    except ImportError:
        logger.warning("Langfuse package not installed")
        _LANGFUSE_CLIENT_CACHE["fingerprint"] = None
        _LANGFUSE_CLIENT_CACHE["client"] = None
        return None
    except Exception as e:
        logger.error(f"Failed to create Langfuse client: {e}")
        _LANGFUSE_CLIENT_CACHE["fingerprint"] = None
        _LANGFUSE_CLIENT_CACHE["client"] = None
        return None


def is_v3_client(client) -> bool:
    """Check if the client is a Langfuse v3 client."""
    if getattr(client, '_is_v3', False):
        return True
    api_obj = getattr(client, 'api', None)
    return bool(
        hasattr(client, 'auth_check')
        or (
            api_obj
            and (
                hasattr(api_obj, 'trace')
                or hasattr(api_obj, 'traces')
                or hasattr(api_obj, 'observations')
                or hasattr(api_obj, 'scores')
            )
        )
    )


def _normalize_metadata(metadata: Any) -> dict[str, Any]:
    """Normalize metadata into a dictionary when possible."""
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _extract_trace_user_ids(trace_obj: Any) -> set[str]:
    """Extract all possible user-id candidates from a trace."""
    user_ids: set[str] = set()

    direct_user = get_attr(trace_obj, "user_id", "userId", "sender", "user")
    if direct_user:
        user_ids.add(str(direct_user))

    metadata = _normalize_metadata(get_attr(trace_obj, "metadata", "meta"))
    for key in (
        "user_id",
        "userId",
        "app_user_id",
        "created_by_user_id",
        "owner_user_id",
    ):
        value = metadata.get(key)
        if value:
            user_ids.add(str(value))

    tags = get_attr(trace_obj, "tags", "labels") or []
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, str):
                continue
            for prefix in ("user_id:", "app_user_id:", "created_by_user_id:"):
                if tag.startswith(prefix):
                    value = tag.split(":", 1)[1].strip()
                    if value:
                        user_ids.add(value)
    return user_ids


def _extract_trace_user_id(trace_obj: Any) -> str | None:
    """Extract one user id from a trace (best effort)."""
    user_ids = _extract_trace_user_ids(trace_obj)
    return next(iter(user_ids), None)


def get_attr(obj, *attrs, default=None):
    """Get attribute from object or dict, trying multiple attribute names."""
    for attr in attrs:
        if hasattr(obj, attr):
            val = getattr(obj, attr)
            if val is not None:
                return val
        if isinstance(obj, dict) and attr in obj:
            val = obj[attr]
            if val is not None:
                return val
    return default


def _enum_str(val) -> str | None:
    """Convert a potentially-enum value (e.g. Langfuse v3 ObservationType) to a plain string."""
    if val is None:
        return None
    if hasattr(val, 'value'):
        return str(val.value)
    return str(val)


def parse_datetime(value) -> datetime | None:
    """Parse datetime from various formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            # Langfuse may return naive datetimes that are effectively UTC.
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                # Treat timezone-naive payloads as UTC to avoid local-time drift in UI.
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except:
            return None
    return None


def calculate_latency_ms(start_time, end_time) -> float | None:
    """Calculate latency in milliseconds between two timestamps."""
    start = parse_datetime(start_time)
    end = parse_datetime(end_time)
    if start and end:
        return (end - start).total_seconds() * 1000
    return None


def _trace_cache_key(
    user_id: str,
    from_timestamp: datetime | None,
    to_timestamp: datetime | None,
    name: str | None,
    tags: list[str] | None,
    session_id: str | None = None,
    effective_limit: int | None = None,
    fetch_all: bool = False,
) -> str:
    tags_key = ",".join(sorted(tags or []))
    from_key = from_timestamp.isoformat() if from_timestamp else ""
    to_key = to_timestamp.isoformat() if to_timestamp else ""
    return (
        f"{user_id}|{from_key}|{to_key}|{name or ''}|{tags_key}|"
        f"{session_id or ''}|{effective_limit or 0}|{int(fetch_all)}"
    )


def _cache_traces(cache_key: str, traces: list[Any]) -> None:
    _TRACE_FETCH_CACHE[cache_key] = {
        "ts": time.monotonic(),
        "traces": traces,
    }
    # Bound memory use for long-running processes.
    if len(_TRACE_FETCH_CACHE) > 256:
        oldest_key = min(
            _TRACE_FETCH_CACHE.items(),
            key=lambda item: float(item[1].get("ts", 0)),
        )[0]
        _TRACE_FETCH_CACHE.pop(oldest_key, None)


def _cache_and_return_observations(trace_id: str, observations: list) -> list:
    """Store observations in the process-local cache then return them."""
    _OBSERVATIONS_CACHE[trace_id] = {
        "ts": time.monotonic(),
        "observations": observations,
    }
    if len(_OBSERVATIONS_CACHE) > 512:
        oldest_key = min(
            _OBSERVATIONS_CACHE.items(),
            key=lambda item: float(item[1].get("ts", 0)),
        )[0]
        _OBSERVATIONS_CACHE.pop(oldest_key, None)
    return observations


def _extract_trace_metrics(trace: Any) -> tuple[int, int, int, float, float | None, list[str], int]:
    """Read aggregate metrics from trace-level fields without N+1 observation calls."""
    total_tokens = int(get_attr(trace, "totalTokens", "total_tokens", default=0) or 0)
    input_tokens = int(get_attr(trace, "inputTokens", "input_tokens", "promptTokens", default=0) or 0)
    output_tokens = int(get_attr(trace, "outputTokens", "output_tokens", "completionTokens", default=0) or 0)
    if not total_tokens and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    if total_tokens and input_tokens == 0 and output_tokens == 0:
        # Trace-level input/output breakdown may be unavailable; preserve total.
        input_tokens = total_tokens

    total_cost = float(
        get_attr(
            trace,
            "calculated_total_cost",
            "calculatedTotalCost",
            "total_cost",
            "totalCost",
            default=0,
        )
        or 0
    )

    # Try explicit ms fields first (custom instrumentation may set these)
    latency_ms: float | None = None
    _latency_raw_ms = get_attr(trace, "latency_ms", "latencyMs", default=None)
    if _latency_raw_ms is not None:
        try:
            latency_ms = float(_latency_raw_ms)
        except (TypeError, ValueError):
            pass
    if latency_ms is None:
        # Langfuse native 'latency' field is in SECONDS — must multiply by 1000 to get ms
        _latency_secs = get_attr(trace, "latency", default=None)
        if _latency_secs is not None:
            try:
                latency_ms = float(_latency_secs) * 1000.0
            except (TypeError, ValueError):
                pass

    metadata = _normalize_metadata(get_attr(trace, "metadata", "meta"))
    models = []
    model_candidates = [
        get_attr(trace, "model"),
        metadata.get("model"),
        metadata.get("model_name"),
        metadata.get("generation_model"),
    ]
    for candidate in model_candidates:
        if candidate:
            value = str(candidate)
            if value not in models:
                models.append(value)

    level = str(get_attr(trace, "level", default="") or "").upper()
    error_count = 1 if level in {"ERROR", "WARNING"} else 0
    return total_tokens, input_tokens, output_tokens, total_cost, latency_ms, models, error_count


def _get_trace_id(trace: Any) -> str:
    return str(get_attr(trace, "id", "trace_id", "traceId", default="") or "")


def _get_trace_observation_count(trace: Any) -> int:
    return int(get_attr(trace, "observation_count", "observationCount", default=0) or 0)


# =============================================================================
# Background Fetch Tasks (for Stale-While-Revalidate)
# =============================================================================

async def _fetch_metrics_background(
    user_id: str,
    cache_key: str,
    from_timestamp: datetime,
    to_timestamp: datetime,
    search: str | None = None,
    models: str | None = None,
    include_model_breakdown: bool = False,
    fetch_all: bool = False,
) -> None:
    """
    Background task: Fetch fresh metrics from Langfuse asynchronously.
    Updates cache when complete. Non-blocking operation.
    """
    try:
        logger.debug(f"Background fetch started for {cache_key}")
        
        # Get Langfuse client
        client = get_langfuse_client()
        if not client:
            logger.warning(f"Langfuse client not available for background fetch: {cache_key}")
            return
        
        # Perform the expensive fetch from Langfuse
        raw_traces = fetch_traces_from_langfuse(
            client,
            user_id,
            limit=500,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            name=search,
            fetch_all=fetch_all,
        )

        # Do not overwrite an existing non-empty cache with an empty transient fetch.
        if not raw_traces and cache_key in _TRACE_METRICS_CACHE:
            logger.debug(f"Background fetch produced empty traces for {cache_key}; keeping existing cache")
            return
        
        # Build metrics from traces
        metrics_dict = _build_metrics_from_traces(
            raw_traces,
            models,
            include_model_breakdown=include_model_breakdown,
        )
        
        # Update cache with fresh data
        _TRACE_METRICS_CACHE[cache_key] = {
            "metrics": metrics_dict,
            "ts": time.monotonic(),
        }
        _update_cache_metadata(cache_key, metrics_dict)
        
        logger.debug(f"Background fetch completed for {cache_key}")
        
    except Exception as e:
        logger.error(f"Background fetch failed for {cache_key}: {str(e)[:200]}")
        # Don't raise - let cache remain stale rather than crash
    finally:
        await _mark_fetch_complete(cache_key)


async def _trigger_background_refresh(
    background_tasks: BackgroundTasks,
    cache_key: str,
    fetch_params: dict[str, Any],
    task_fn: Any = None,
) -> None:
    """
    Trigger background refresh if conditions are met:
    1. Data is stale (age between FRESH and STALE thresholds)
    2. Not already fetching
    3. Concurrent fetch limit not exceeded
    """
    cache_meta = _get_cache_metadata(cache_key)
    
    # Don't refresh if still fresh
    if cache_meta["is_fresh"]:
        return
    
    # Don't refresh if already in progress
    if cache_key in _BACKGROUND_FETCH_IN_PROGRESS:
        logger.debug(f"Background fetch already in progress for {cache_key}")
        return
    
    # Check concurrent fetch limit
    if len(_BACKGROUND_FETCH_IN_PROGRESS) >= SWR_CONFIG["MAX_CONCURRENT_FETCHES"]:
        logger.debug(f"Background fetch queue full ({len(_BACKGROUND_FETCH_IN_PROGRESS)}), skipping {cache_key}")
        return
    
    # Mark as in progress before adding task
    if not (await _mark_fetch_in_progress(cache_key)):
        return
    
    if task_fn is None:
        logger.debug(f"Background refresh not configured for {cache_key}")
        await _mark_fetch_complete(cache_key)
        return

    logger.debug(f"Triggering background refresh for {cache_key}")
    background_tasks.add_task(
        task_fn,
        **fetch_params
    )


def _build_metrics_from_traces(
    raw_traces: list[Any],
    models: str | None,
    include_model_breakdown: bool,
) -> dict[str, Any]:
    """
    Build metrics from traces (extracted from endpoint logic).
    This is the shared computation used by both sync and async paths.
    """
    # Parse model filter
    model_filter = None
    if models:
        model_filter = [m.strip() for m in models.split(",") if m.strip()]
    
    # Initialize accumulators
    total_traces = len(raw_traces)
    # Keep fallback bounded, but large enough to avoid zero-token dashboards
    # when trace-level usage is sparse (common in some Langfuse SDK paths).
    fallback_budget = _make_fallback_budget(total_traces)
    total_observations = 0
    total_tokens = 0
    input_tokens = 0
    output_tokens = 0
    total_cost = 0.0
    latencies = []
    sessions = set()
    
    model_data = defaultdict(lambda: {
        "call_count": 0, "total_tokens": 0, "input_tokens": 0,
        "output_tokens": 0, "total_cost": 0.0, "latencies": []
    })
    
    daily_data = defaultdict(lambda: {
        "trace_count": 0, "observation_count": 0, "total_tokens": 0, "total_cost": 0.0
    })
    
    agent_data = defaultdict(lambda: {
        "count": 0, "tokens": 0, "cost": 0.0
    })
    
    client = get_langfuse_client()
    
    for trace in raw_traces:
        trace_id = get_attr(trace, 'id')
        trace_name = get_attr(trace, 'name') or 'Unknown'
        session_id = get_attr(trace, 'session_id', 'sessionId')
        timestamp = parse_datetime(get_attr(trace, 'timestamp'))
        
        if session_id:
            sessions.add(session_id)
        
        date_str = timestamp.strftime('%Y-%m-%d') if timestamp else 'Unknown'
        daily_data[date_str]["trace_count"] += 1
        
        # Get trace metrics
        trace_metrics = _get_trace_metrics(
            client,
            trace,
            allow_observation_fallback=not include_model_breakdown,
            fallback_budget=fallback_budget,
        )
        
        trace_tokens = int(trace_metrics["total_tokens"])
        trace_input_tokens = int(trace_metrics["input_tokens"])
        trace_output_tokens = int(trace_metrics["output_tokens"])
        trace_cost = float(trace_metrics["total_cost"])
        trace_latency_ms = trace_metrics["latency_ms"]
        trace_models = list(trace_metrics["models"])
        
        # Aggregate overall metrics
        total_tokens += trace_tokens
        input_tokens += trace_input_tokens
        output_tokens += trace_output_tokens
        total_cost += trace_cost
        daily_data[date_str]["total_tokens"] += trace_tokens
        daily_data[date_str]["total_cost"] += trace_cost
        agent_data[trace_name]["count"] += 1
        agent_data[trace_name]["tokens"] += trace_tokens
        agent_data[trace_name]["cost"] += trace_cost
        
        if trace_latency_ms:
            latencies.append(trace_latency_ms)
        
        # Per-model aggregation from trace-level data (fast path)
        trace_obs_count = int(trace_metrics["observation_count"] or 0)
        total_observations += trace_obs_count
        daily_data[date_str]["observation_count"] += trace_obs_count
        
        for model_name in trace_models:
            model_data[model_name]["call_count"] += 1
            model_data[model_name]["total_tokens"] += trace_tokens
            model_data[model_name]["input_tokens"] += trace_input_tokens
            model_data[model_name]["output_tokens"] += trace_output_tokens
            model_data[model_name]["total_cost"] += trace_cost
            if trace_latency_ms:
                model_data[model_name]["latencies"].append(trace_latency_ms)
    
    # Calculate performance metrics
    avg_latency = None
    p95_latency = None
    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        sorted_latencies = sorted(latencies)
        p95_idx = int(len(sorted_latencies) * 0.95)
        p95_latency = sorted_latencies[min(p95_idx, len(sorted_latencies) - 1)]
    
    # Build model usage list
    by_model = []
    for model, data in model_data.items():
        avg_lat = sum(data["latencies"]) / len(data["latencies"]) if data["latencies"] else None
        by_model.append(ModelUsageItem(
            model=model,
            call_count=data["call_count"],
            total_tokens=data["total_tokens"],
            input_tokens=data["input_tokens"],
            output_tokens=data["output_tokens"],
            total_cost=data["total_cost"],
            avg_latency_ms=avg_lat,
        ))
    by_model.sort(key=lambda m: m.total_tokens, reverse=True)
    
    # Build daily usage list
    by_date = []
    for date, data in sorted(daily_data.items()):
        if date != 'Unknown':
            by_date.append(DailyUsageItem(
                date=date,
                trace_count=data["trace_count"],
                observation_count=data["observation_count"],
                total_tokens=data["total_tokens"],
                total_cost=data["total_cost"],
            ))
    by_date = by_date[-30:]  # Keep only last 30 days for background refresh
    
    # Build top agents
    top_agents = [
        {"name": name, "count": data["count"], "tokens": data["tokens"], "cost": data["cost"]}
        for name, data in sorted(agent_data.items(), key=lambda x: x[1]["count"], reverse=True)[:10]
    ]
    
    return {
        "total_traces": total_traces,
        "total_observations": total_observations,
        "total_sessions": len(sessions),
        "total_tokens": total_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_cost_usd": total_cost,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95_latency,
        "by_model": by_model,
        "by_date": by_date,
        "top_agents": top_agents,
        "truncated": False,
        "fetched_trace_count": total_traces,
    }


def _get_trace_metrics(
    client: Any,
    trace: Any,
    *,
    allow_observation_fallback: bool = True,
    fallback_budget: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Get trace metrics with smart fallback strategy.

    Smart fallback: Only fetch observations if trace-level metrics are COMPLETELY missing
    (not just partial). This avoids expensive observation fetches when we have partial data.

    Falls back to observations only if:
    - allow_observation_fallback=True AND
    - fallback_budget has remaining calls AND
    - NO trace-level metrics at all (zero tokens AND zero cost AND no models)
    """
    trace_id = _get_trace_id(trace)
    now_mono = time.monotonic()

    def _needs_enrichment(data: dict[str, Any]) -> bool:
        return (
            int(data.get("total_tokens") or 0) == 0
            and float(data.get("total_cost") or 0.0) == 0.0
            and not list(data.get("models") or [])
        )

    # Check request-scoped metrics cache first (within same request)
    if trace_id in _REQUEST_METRICS_CACHE:
        request_cached = dict(_REQUEST_METRICS_CACHE[trace_id])
        if not (allow_observation_fallback and trace_id and _needs_enrichment(request_cached)):
            return request_cached

    # Check process-level TTL cache
    if trace_id:
        cached = _TRACE_METRICS_CACHE.get(trace_id)
        if cached and (now_mono - float(cached.get("ts", 0))) <= _TRACE_METRICS_CACHE_TTL_SECONDS:
            result = dict(cached.get("metrics", {}))
            if not (allow_observation_fallback and _needs_enrichment(result)):
                _REQUEST_METRICS_CACHE[trace_id] = result
                return result

    (
        total_tokens,
        input_tokens,
        output_tokens,
        total_cost,
        latency_ms,
        models,
        error_count,
    ) = _extract_trace_metrics(trace)
    observation_count = _get_trace_observation_count(trace)

    metrics: dict[str, Any] = {
        "total_tokens": int(total_tokens or 0),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "total_cost": float(total_cost or 0.0),
        "latency_ms": latency_ms,
        "models": list(models),
        "error_count": int(error_count or 0),
        "observation_count": int(observation_count or 0),
    }

    # SMART FALLBACK: Only fetch observations if trace-level data is COMPLETELY missing
    # Don't fetch if we have any trace-level metrics (tokens or cost or models)
    needs_fallback = (
        allow_observation_fallback
        and bool(trace_id)
        and metrics["total_tokens"] == 0  # No tokens at all
        and metrics["total_cost"] == 0.0  # No cost at all
        and not metrics["models"]  # No models recorded
    )

    if needs_fallback and fallback_budget is not None and fallback_budget.get("remaining", 0) <= 0:
        needs_fallback = False

    if needs_fallback and trace_id:
        if fallback_budget is not None:
            fallback_budget["remaining"] = max(0, fallback_budget.get("remaining", 0) - 1)
        try:
            raw_observations = fetch_observations_for_trace(client, trace_id)
            parsed_obs = [parse_observation(obs) for obs in raw_observations]
            if parsed_obs:
                obs_total_tokens = sum(o.total_tokens for o in parsed_obs)
                obs_input_tokens = sum(o.input_tokens for o in parsed_obs)
                obs_output_tokens = sum(o.output_tokens for o in parsed_obs)
                obs_total_cost = sum(o.total_cost for o in parsed_obs)
                obs_latencies = [o.latency_ms for o in parsed_obs if o.latency_ms is not None]
                obs_models = []
                for obs in parsed_obs:
                    if obs.model and obs.model not in obs_models:
                        obs_models.append(obs.model)
                obs_error_count = sum(1 for o in parsed_obs if (o.level or "").upper() in {"ERROR", "WARNING"})

                # Fill only empty fields from observations
                if metrics["total_tokens"] == 0:
                    metrics["total_tokens"] = int(obs_total_tokens or 0)
                if metrics["input_tokens"] == 0 and metrics["output_tokens"] == 0:
                    metrics["input_tokens"] = int(obs_input_tokens or 0)
                    metrics["output_tokens"] = int(obs_output_tokens or 0)
                if metrics["total_cost"] == 0.0:
                    metrics["total_cost"] = float(obs_total_cost or 0.0)
                if metrics["latency_ms"] is None and obs_latencies:
                    metrics["latency_ms"] = max(obs_latencies)
                if not metrics["models"] and obs_models:
                    metrics["models"] = obs_models
                metrics["error_count"] = max(metrics["error_count"], int(obs_error_count or 0))
                metrics["observation_count"] = max(metrics["observation_count"], len(parsed_obs))
        except Exception:
            pass

    if trace_id:
        _TRACE_METRICS_CACHE[trace_id] = {
            "ts": now_mono,
            "metrics": metrics,
        }
        # Evict oldest if cache grows too large
        if len(_TRACE_METRICS_CACHE) > 1024:
            oldest_key = min(
                _TRACE_METRICS_CACHE.items(),
                key=lambda item: float(item[1].get("ts", 0)),
            )[0]
            _TRACE_METRICS_CACHE.pop(oldest_key, None)

    # Cache in request scope
    _REQUEST_METRICS_CACHE[trace_id] = metrics
    return metrics


def fetch_traces_from_langfuse(
    client,
    user_id: str,
    limit: int = 50,
    from_timestamp: datetime | None = None,
    to_timestamp: datetime | None = None,
    name: str | None = None,
    tags: list[str] | None = None,
    session_id: str | None = None,
    fetch_all: bool = False,
) -> list:
    """
    Fetch traces from Langfuse using the appropriate SDK method.
    Supports both Langfuse SDK v3 and v2.

    In v3, the primary method is `fetch_traces()` which is a high-level convenience method
    that works the same as v2.

    Args:
        client: Langfuse client
        user_id: User ID to filter by
        limit: Maximum number of traces to fetch (ignored if fetch_all=True)
        from_timestamp: Start date filter (inclusive)
        to_timestamp: End date filter (inclusive)
        name: Filter traces by name (partial match)
        tags: Filter traces by tags
        session_id: Filter traces by session ID
        fetch_all: If True, paginate until ALL traces are fetched (up to safety cap of 5000)
    """
    trace_data = []
    # When fetch_all is True, use a high cap but still paginate
    effective_limit = 5000 if fetch_all else limit
    # Langfuse API has a max limit of 100 per request
    page_size = min(100, effective_limit)
    cache_key = _trace_cache_key(
        user_id,
        from_timestamp,
        to_timestamp,
        name,
        tags,
        session_id=session_id,
        effective_limit=effective_limit,
        fetch_all=fetch_all,
    )
    now_mono = time.monotonic()
    cached_entry = _TRACE_FETCH_CACHE.get(cache_key)
    stale_traces: list[Any] = []
    if cached_entry:
        cached_age = now_mono - float(cached_entry.get("ts", 0))
        cached_traces = cached_entry.get("traces", []) or []
        if cached_age <= _TRACE_CACHE_TTL_SECONDS and cached_traces:
            return list(cached_traces)[:effective_limit]
        if cached_age <= _TRACE_CACHE_STALE_SECONDS and cached_traces:
            stale_traces = list(cached_traces)

    sdk_version = getattr(client, '_sdk_version', 'unknown')
    logger.debug(f"Langfuse SDK version: {sdk_version}, is_v3: {is_v3_client(client)}")
    logger.debug(f"Looking for traces with user_id: {user_id}, limit={limit}, page_size={page_size}")
    if from_timestamp:
        logger.debug(f"  from_timestamp: {from_timestamp}")
    if to_timestamp:
        logger.debug(f"  to_timestamp: {to_timestamp}")
    if name:
        logger.debug(f"  name filter: {name}")

    # ==========================================================================
    # Primary method: fetch_traces() - works in both v2 and v3
    # ==========================================================================
    if hasattr(client, 'fetch_traces'):
        try:
            page = 1
            all_traces = []
            max_pages = (effective_limit + page_size - 1) // page_size

            filter_kwargs = {"user_id": user_id, "limit": page_size}
            if from_timestamp:
                filter_kwargs["from_timestamp"] = from_timestamp
            if to_timestamp:
                filter_kwargs["to_timestamp"] = to_timestamp
            if session_id:
                filter_kwargs["session_id"] = session_id
            if name:
                filter_kwargs["name"] = name
            if tags:
                filter_kwargs["tags"] = tags

            while page <= max_pages:
                logger.debug(f"Fetching page {page} with filters: {filter_kwargs}")
                response = client.fetch_traces(**filter_kwargs, page=page)

                page_traces = []
                if hasattr(response, 'data'):
                    page_traces = response.data or []
                elif isinstance(response, list):
                    page_traces = response
                elif isinstance(response, dict):
                    page_traces = response.get('data', [])

                logger.debug(f"Page {page} returned {len(page_traces)} traces")

                if not page_traces:
                    break

                all_traces.extend(page_traces)

                page += 1

            trace_data = all_traces
            logger.debug(f"fetch_traces returned {len(trace_data)} traces for user_id={user_id}")

            if trace_data:
                first = trace_data[0]
                logger.debug(f"Sample trace: type={type(first)}, user_id={get_attr(first, 'user_id', 'userId')}")
                _cache_traces(cache_key, trace_data)
                return trace_data

        except Exception as e:
            logger.warning(f"fetch_traces with user_id failed: {e}")
            logger.debug(traceback.format_exc())

    # ==========================================================================
    # Fallback for v3: Try api.trace.list/api.traces.list variants
    # ==========================================================================
    if hasattr(client, 'api'):
        api_obj = getattr(client, 'api')
        trace_api = None
        if hasattr(api_obj, 'trace'):
            trace_api = getattr(api_obj, 'trace')
        elif hasattr(api_obj, 'traces'):
            trace_api = getattr(api_obj, 'traces')

        if trace_api and hasattr(trace_api, 'list'):
            try:
                logger.debug("Trying v3 fallback: client.api.trace(s).list")
                all_traces = []
                page = 1
                used_variant: dict[str, Any] | None = None

                # Try both snake_case and camelCase filters for compatibility.
                filter_variants = [
                    {"user_id": user_id},
                    {"userId": user_id},
                    {},
                ]

                for variant in filter_variants:
                    all_traces = []
                    page = 1
                    max_scan_pages = max(1, (effective_limit + page_size - 1) // page_size)
                    while page <= max_scan_pages and len(all_traces) < effective_limit:
                        list_kwargs = {"limit": page_size, "page": page}
                        list_kwargs.update(variant)
                        if from_timestamp:
                            list_kwargs["from_timestamp"] = from_timestamp
                        if to_timestamp:
                            list_kwargs["to_timestamp"] = to_timestamp
                        if name:
                            list_kwargs["name"] = name
                        if tags:
                            list_kwargs["tags"] = tags
                        try:
                            response = trace_api.list(**list_kwargs)
                        except TypeError as e:
                            # Some SDK versions reject unknown keyword variants (e.g. userId).
                            logger.debug(f"trace_api.list rejected kwargs {list_kwargs.keys()}: {e}")
                            all_traces = []
                            break
                        except Exception as e:
                            logger.debug(f"trace_api.list failed for kwargs {list_kwargs.keys()}: {e}")
                            all_traces = []
                            break
                        page_traces = response.data if hasattr(response, 'data') else (
                            response if isinstance(response, list) else []
                        )
                        if not page_traces:
                            break
                        all_traces.extend(page_traces)
                        page += 1

                    if all_traces:
                        used_variant = variant
                        break

                # Apply client-side user filtering (handles traces where user_id is stored in metadata/tags).
                if all_traces:
                    trace_data = []
                    for trace_obj in all_traces:
                        extracted_uids = _extract_trace_user_ids(trace_obj)
                        if str(user_id) in extracted_uids:
                            trace_data.append(trace_obj)
                            continue
                        # If server-side user filter was accepted, keep rows with missing
                        # user metadata to avoid dropping valid traces returned by API.
                        if not extracted_uids and used_variant and ("user_id" in used_variant or "userId" in used_variant):
                            trace_data.append(trace_obj)
                else:
                    trace_data = []

                logger.debug(f"v3 api.trace(s).list returned {len(trace_data)} traces for user_id={user_id}")
                if trace_data:
                    _cache_traces(cache_key, trace_data)
                    return trace_data
            except Exception as e:
                logger.warning(f"v3 api.trace(s).list failed: {e}")


    # ==========================================================================
    # Fallback: fetch without user_id filter and filter manually
    # ==========================================================================
    max_pages = (effective_limit + page_size - 1) // page_size  # ceil division
    if hasattr(client, 'fetch_traces'):
        try:
            page = 1
            all_traces = []
            fallback_kwargs = {"limit": page_size}
            if from_timestamp:
                fallback_kwargs["from_timestamp"] = from_timestamp
            if to_timestamp:
                fallback_kwargs["to_timestamp"] = to_timestamp

            while page <= max_pages:
                logger.debug(f"Fallback fetching page {page} without user filter, limit={page_size}")
                response = client.fetch_traces(**fallback_kwargs, page=page)

                page_traces = []
                if hasattr(response, 'data'):
                    page_traces = response.data or []
                elif isinstance(response, list):
                    page_traces = response
                elif isinstance(response, dict):
                    page_traces = response.get('data', [])

                if not page_traces:
                    break

                all_traces.extend(page_traces)

                page += 1

            logger.debug(f"Fallback got {len(all_traces)} total traces, filtering by user_id={user_id}")

            # Filter by user_id
            trace_data = [t for t in all_traces if str(user_id) in _extract_trace_user_ids(t)]
            logger.debug(f"After user_id filter: {len(trace_data)} traces")

            # Apply client-side name filter if provided (partial match)
            if name and trace_data:
                name_lower = name.lower()
                trace_data = [t for t in trace_data if name_lower in (get_attr(t, 'name') or '').lower()]
                logger.debug(f"After name filter: {len(trace_data)} traces")

            if trace_data:
                _cache_traces(cache_key, trace_data)
                return trace_data
            elif all_traces:
                sample_uids = set(
                    str(next(iter(_extract_trace_user_ids(t)), '') or '')
                    for t in all_traces[:20]
                    if _extract_trace_user_id(t)
                )
                logger.warning(f"No traces for user_id={user_id}. Sample user_ids: {sample_uids}")

        except Exception as e:
            logger.warning(f"Fallback fetch_traces failed: {e}")

    # ==========================================================================
    # Last resort: Try direct client API (works for both v2 and v3)
    # ==========================================================================
    if hasattr(client, 'client') and hasattr(client.client, 'traces'):
        try:
            logger.debug(f"Attempting direct client.traces.list(user_id={user_id})")
            response = client.client.traces.list(user_id=user_id, limit=page_size)
            if hasattr(response, 'data'):
                trace_data = response.data or []
            elif isinstance(response, list):
                trace_data = response
            logger.debug(f"Direct traces API returned {len(trace_data)} traces")
            if trace_data:
                _cache_traces(cache_key, trace_data)
                return trace_data
        except Exception as e:
            logger.debug(f"Direct traces API failed: {e}")

    # Date-filter fallback: some SDK/API combinations return intermittent empty
    # results for date-filtered list calls. Retry without date filter and
    # apply the date window client-side.
    if not trace_data and (from_timestamp or to_timestamp):
        try:
            # Use a broader unfiltered fetch on fallback to avoid false-empty
            # windows (notably for narrow ranges like "today") when server-side
            # date filtering is flaky.
            fallback_limit = max(effective_limit, 1000)
            unfiltered = fetch_traces_from_langfuse(
                client,
                user_id=user_id,
                limit=fallback_limit,
                from_timestamp=None,
                to_timestamp=None,
                name=name,
                tags=tags,
                session_id=session_id,
                fetch_all=True,
            )
            if unfiltered:
                filtered: list[Any] = []
                for trace_obj in unfiltered:
                    ts = parse_datetime(get_attr(trace_obj, "timestamp"))
                    if from_timestamp and (not ts or ts < from_timestamp):
                        continue
                    if to_timestamp and (not ts or ts > to_timestamp):
                        continue
                    filtered.append(trace_obj)
                if filtered:
                    _cache_traces(cache_key, filtered)
                    return filtered[:effective_limit]
        except Exception as e:
            logger.debug(f"Date-filter fallback failed: {e}")

    if stale_traces:
        logger.debug("Using stale trace cache for user_id={} due empty/failed fresh fetch", user_id)
        return stale_traces[:effective_limit]

    # Cross-range fallback: if a date-filtered fetch is empty, try the most recent
    # non-empty trace cache for this user and filter by the current window.
    if not trace_data and (from_timestamp or to_timestamp):
        newest_user_cache: tuple[float, list[Any]] | None = None
        user_key_prefix = f"{user_id}|"
        for key, entry in _TRACE_FETCH_CACHE.items():
            if not key.startswith(user_key_prefix):
                continue
            entry_ts = float(entry.get("ts", 0))
            entry_traces = entry.get("traces", []) or []
            if not entry_traces:
                continue
            age = now_mono - entry_ts
            if age > _TRACE_CACHE_STALE_SECONDS:
                continue
            if newest_user_cache is None or entry_ts > newest_user_cache[0]:
                newest_user_cache = (entry_ts, entry_traces)

        if newest_user_cache is not None:
            _, fallback_traces = newest_user_cache
            filtered: list[Any] = []
            for trace_obj in fallback_traces:
                ts = parse_datetime(get_attr(trace_obj, "timestamp"))
                if from_timestamp and ts and ts < from_timestamp:
                    continue
                if to_timestamp and ts and ts > to_timestamp:
                    continue
                filtered.append(trace_obj)
                if len(filtered) >= effective_limit:
                    break
            if filtered:
                logger.debug(
                    "Using cross-range stale traces for user_id={} after empty filtered fetch (count={})",
                    user_id,
                    len(filtered),
                )
                return filtered

    logger.debug(f"All methods failed to fetch traces for user_id={user_id}")
    return trace_data


def fetch_observations_for_trace(client, trace_id: str) -> list:
    """
    Fetch observations (spans) for a specific trace.
    Supports both Langfuse SDK v3 and v2.

    Uses three-tier cache:
    1. Request-scoped cache (deduplicates within same API call)
    2. Process-local cache (TTL 60s, survives across requests)
    3. Langfuse API (slowest)
    """
    trace_id_str = str(trace_id)

    # Tier 1: Request-scoped cache (deduplicate within single API request)
    if trace_id_str in _REQUEST_OBSERVATIONS_CACHE:
        logger.debug(f"Request cache hit for observations: trace_id={trace_id_str}")
        return list(_REQUEST_OBSERVATIONS_CACHE[trace_id_str])

    # Tier 2: Check process-local cache to avoid redundant high-latency Langfuse calls
    _now_mono = time.monotonic()
    _obs_cached = _OBSERVATIONS_CACHE.get(trace_id_str)
    if _obs_cached and (_now_mono - float(_obs_cached.get("ts", 0))) <= _OBSERVATIONS_CACHE_TTL_SECONDS:
        logger.debug(f"Process cache hit for observations: trace_id={trace_id_str}")
        result = list(_obs_cached.get("observations", []))
        _REQUEST_OBSERVATIONS_CACHE[trace_id_str] = result
        return result

    observations = []

    def _response_to_list(response: Any) -> list:
        if hasattr(response, "data"):
            return response.data or []
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            return response.get("data", []) or []
        return []

    def _try_call(method: Any) -> list:
        if not callable(method):
            return []
        variants = [
            {"trace_id": trace_id, "limit": 100},
            {"traceId": trace_id, "limit": 100},
            {"trace": trace_id, "limit": 100},
        ]
        for kwargs in variants:
            try:
                rows = _response_to_list(method(**kwargs))
                if rows:
                    return rows
            except TypeError:
                continue
            except Exception:
                continue
        return []

    # Primary method: fetch_observations() - works in both v2 and v3
    if hasattr(client, 'fetch_observations'):
        try:
            observations = _try_call(client.fetch_observations)
            if observations:
                return _cache_and_return_observations(str(trace_id), observations)
        except Exception as e:
            logger.debug(f"fetch_observations failed for trace {trace_id}: {e}")

    # Fallback for v3: Try api.observations.get_many
    if is_v3_client(client) and hasattr(client, 'api') and hasattr(client.api, 'observations'):
        obs_client = client.api.observations
        if hasattr(obs_client, 'get_many'):
            try:
                observations = _try_call(obs_client.get_many)
                if observations:
                    return _cache_and_return_observations(str(trace_id), observations)
            except Exception as e:
                logger.debug(f"api.observations.get_many failed for trace {trace_id}: {e}")

        if hasattr(obs_client, 'list'):
            try:
                observations = _try_call(obs_client.list)
                if observations:
                    return _cache_and_return_observations(str(trace_id), observations)
            except Exception as e:
                logger.debug(f"api.observations.list failed for trace {trace_id}: {e}")

    # Fallback for v3: Try api.observations_v_2
    if is_v3_client(client) and hasattr(client, 'api') and hasattr(client.api, 'observations_v_2'):
        obs_v2_client = client.api.observations_v_2
        if hasattr(obs_v2_client, 'get_many'):
            try:
                observations = _try_call(obs_v2_client.get_many)
                if observations:
                    return _cache_and_return_observations(str(trace_id), observations)
            except Exception as e:
                logger.debug(f"api.observations_v_2.get_many failed for trace {trace_id}: {e}")

    # Fallback: Try direct client observations API
    if hasattr(client, 'client') and hasattr(client.client, 'observations'):
        try:
            observations = _try_call(client.client.observations.list)
            if observations:
                return _cache_and_return_observations(str(trace_id), observations)
        except Exception as e:
            logger.debug(f"client.client.observations.list failed for trace {trace_id}: {e}")

    # Only persist NON-EMPTY results in the 60s cache.
    # Empty results must NOT be cached persistently — if Langfuse returned nothing this request
    # (API hiccup, indexing lag, etc.) the next request should try fresh.
    # The request-scoped cache still deduplicates within the same API call.
    if observations:
        final_observations = _cache_and_return_observations(trace_id_str, observations)
    else:
        final_observations = observations
    _REQUEST_OBSERVATIONS_CACHE[trace_id_str] = list(final_observations)
    return final_observations


def fetch_scores_for_trace(client, trace_id: str, user_id: str | None = None, limit: int = 100) -> list[ScoreItem]:
    """Fetch evaluation scores for a trace across Langfuse SDK variants."""
    scores: list[ScoreItem] = []
    seen_ids: set[str] = set()

    def _append_scores(raw_payload: Any, *, already_filtered_by_trace: bool = False) -> int:
        raw_scores = raw_payload
        if hasattr(raw_payload, "data"):
            raw_scores = raw_payload.data
        elif isinstance(raw_payload, dict):
            raw_scores = raw_payload.get("data", [])

        if not raw_scores:
            return 0

        added = 0
        for score in raw_scores:
            score_trace_id = str(get_attr(score, "trace_id", "traceId", default="") or "")
            if not already_filtered_by_trace and score_trace_id and score_trace_id != str(trace_id):
                continue

            score_id = str(get_attr(score, "id", default="") or "")
            dedupe_key = score_id or f"{get_attr(score, 'name', default='score')}::{get_attr(score, 'timestamp', 'created_at', 'createdAt', default='')}"
            if dedupe_key in seen_ids:
                continue
            seen_ids.add(dedupe_key)

            source = get_attr(score, "source")
            if hasattr(source, "value"):
                source = source.value
            scores.append(
                ScoreItem(
                    id=score_id or str(len(scores) + 1),
                    name=str(get_attr(score, "name", default="Score") or "Score"),
                    value=float(get_attr(score, "value", default=0.0) or 0.0),
                    source=str(source) if source is not None else None,
                    comment=get_attr(score, "comment"),
                    created_at=parse_datetime(get_attr(score, "created_at", "createdAt", "timestamp")),
                )
            )
            added += 1
        return added

    # Method 0: v3 API score_v_2.get (most reliable in Langfuse v3)
    if hasattr(client, "api") and hasattr(client.api, "score_v_2"):
        try:
            kwargs: dict[str, Any] = {"trace_id": trace_id, "limit": limit}
            if user_id:
                kwargs["user_id"] = user_id
            try:
                kwargs["fields"] = "score,trace"
                payload = client.api.score_v_2.get(**kwargs)
            except TypeError:
                kwargs.pop("fields", None)
                payload = client.api.score_v_2.get(**kwargs)
            _append_scores(payload, already_filtered_by_trace=True)
        except Exception as e:
            logger.debug(f"api.score_v_2.get failed for trace {trace_id}: {e}")

    # Method 1: legacy SDK helper
    if hasattr(client, "fetch_scores"):
        try:
            _append_scores(client.fetch_scores(trace_id=trace_id))
        except Exception as e:
            logger.debug(f"fetch_scores failed for trace {trace_id}: {e}")

    # Method 2: direct client scores API (v2/v3 variants)
    if hasattr(client, "client") and hasattr(client.client, "scores"):
        try:
            kwargs: dict[str, Any] = {"trace_id": trace_id, "limit": limit}
            if user_id:
                kwargs["user_id"] = user_id
            try:
                payload = client.client.scores.list(**kwargs)
            except TypeError:
                kwargs.pop("user_id", None)
                payload = client.client.scores.list(**kwargs)
            _append_scores(payload, already_filtered_by_trace=True)
        except Exception as e:
            logger.debug(f"client.scores.list failed for trace {trace_id}: {e}")

    # Method 3: v3 REST resources under client.api.score(s).list where available.
    if hasattr(client, "api"):
        for attr in ("scores", "score"):
            score_api = getattr(client.api, attr, None)
            if not score_api or not hasattr(score_api, "list"):
                continue
            try:
                kwargs = {"trace_id": trace_id, "limit": limit}
                if user_id:
                    kwargs["user_id"] = user_id
                try:
                    payload = score_api.list(**kwargs)
                except TypeError:
                    kwargs.pop("user_id", None)
                    payload = score_api.list(**kwargs)
                _append_scores(payload, already_filtered_by_trace=True)
            except Exception as e:
                logger.debug(f"api.{attr}.list failed for trace {trace_id}: {e}")

    # Some providers/SDK variants do not persist user_id on scores even when the trace
    # belongs to the user. If the user-filtered fetch returns empty, retry by trace only.
    if not scores and user_id:
        logger.debug(
            "No scores found for trace {} with user_id filter {}; retrying without user filter",
            trace_id,
            user_id,
        )
        return fetch_scores_for_trace(client, trace_id=trace_id, user_id=None, limit=limit)

    scores.sort(key=lambda s: s.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return scores


def parse_observation(obs: Any) -> ObservationResponse:
    """Parse a Langfuse observation into our response model."""
    obs_id = get_attr(obs, 'id', default='')
    trace_id = get_attr(obs, 'trace_id', 'traceId', default='')

    start_time = parse_datetime(get_attr(obs, 'start_time', 'startTime'))
    end_time = parse_datetime(get_attr(obs, 'end_time', 'endTime'))
    completion_start = parse_datetime(get_attr(obs, 'completion_start_time', 'completionStartTime'))

    latency_ms = calculate_latency_ms(start_time, end_time)
    ttft_ms = calculate_latency_ms(start_time, completion_start) if completion_start else None

    metadata = _normalize_metadata(get_attr(obs, 'metadata', 'meta', default={}) or {})

    # Extract usage data
    # Langfuse v3: `usage` is deprecated; actual counts live in `usage_details`
    # (Dict[str, int] e.g. {"input": 100, "output": 50, "total": 150}).
    # Always read `usage` first for back-compat, then fall back to `usage_details`.
    usage = get_attr(obs, 'usage', default={})
    usage_details = get_attr(obs, 'usage_details', 'usageDetails', default={}) or {}
    if isinstance(usage, dict):
        input_tokens = usage.get('input') or usage.get('inputTokens') or usage.get('prompt_tokens') or 0
        output_tokens = usage.get('output') or usage.get('outputTokens') or usage.get('completion_tokens') or 0
        total_tokens = usage.get('total') or usage.get('totalTokens') or (input_tokens + output_tokens)
    elif hasattr(usage, 'input'):
        input_tokens = usage.input or 0
        output_tokens = getattr(usage, 'output', 0) or 0
        total_tokens = getattr(usage, 'total', 0) or (input_tokens + output_tokens)
    else:
        input_tokens = get_attr(obs, 'input_tokens', 'inputTokens', 'promptTokens', default=0)
        output_tokens = get_attr(obs, 'output_tokens', 'outputTokens', 'completionTokens', default=0)
        total_tokens = input_tokens + output_tokens

    # Langfuse v3 primary token source: usage_details dict wins when usage is empty/zero
    if not (input_tokens or output_tokens or total_tokens) and usage_details:
        if isinstance(usage_details, dict):
            input_tokens = int(usage_details.get('input', 0) or 0)
            output_tokens = int(usage_details.get('output', 0) or 0)
            total_tokens = int(usage_details.get('total', 0) or (input_tokens + output_tokens))
        elif hasattr(usage_details, 'input'):
            input_tokens = int(getattr(usage_details, 'input', 0) or 0)
            output_tokens = int(getattr(usage_details, 'output', 0) or 0)
            total_tokens = int(getattr(usage_details, 'total', 0) or (input_tokens + output_tokens))

    # Agentcore fallback: custom usage metadata emitted by components (e.g. NeMo block path)
    usage_from_metadata = metadata.get('agentcore_usage')
    if isinstance(usage_from_metadata, str):
        usage_from_metadata = _normalize_metadata(usage_from_metadata)
    if not isinstance(usage_from_metadata, dict):
        usage_from_metadata = {}

    if not (input_tokens or output_tokens or total_tokens) and usage_from_metadata:
        input_tokens = int(
            usage_from_metadata.get('input_tokens')
            or usage_from_metadata.get('inputTokens')
            or usage_from_metadata.get('prompt_tokens')
            or usage_from_metadata.get('input')
            or 0
        )
        output_tokens = int(
            usage_from_metadata.get('output_tokens')
            or usage_from_metadata.get('outputTokens')
            or usage_from_metadata.get('completion_tokens')
            or usage_from_metadata.get('output')
            or 0
        )
        total_tokens = int(
            usage_from_metadata.get('total_tokens')
            or usage_from_metadata.get('totalTokens')
            or usage_from_metadata.get('total')
            or (input_tokens + output_tokens)
        )

    # Extract cost data
    # Langfuse v3: `cost_details` (Dict[str, float]) is the primary source;
    # `calculated_*_cost` fields are deprecated but kept as fallback.
    cost_details = get_attr(obs, 'cost_details', 'costDetails', default={}) or {}
    input_cost = float(get_attr(obs,
        'calculated_input_cost', 'calculatedInputCost',
        'input_cost', 'inputCost', default=0) or 0)
    output_cost = float(get_attr(obs,
        'calculated_output_cost', 'calculatedOutputCost',
        'output_cost', 'outputCost', default=0) or 0)
    total_cost = float(get_attr(obs,
        'calculated_total_cost', 'calculatedTotalCost',
        'total_cost', 'totalCost', default=0) or 0)
    if not total_cost and (input_cost or output_cost):
        total_cost = input_cost + output_cost
    # Langfuse v3 primary cost source: cost_details wins when calculated fields are 0
    if not (input_cost or output_cost or total_cost) and cost_details:
        if isinstance(cost_details, dict):
            input_cost = float(cost_details.get('input', 0) or 0)
            output_cost = float(cost_details.get('output', 0) or 0)
            total_cost = float(cost_details.get('total', 0) or 0)
            if not total_cost and (input_cost or output_cost):
                total_cost = input_cost + output_cost

    model = get_attr(obs, 'model')
    if not model and usage_from_metadata:
        model = (
            usage_from_metadata.get('model')
            or usage_from_metadata.get('model_name')
            or usage_from_metadata.get('generation_model')
        )

    return ObservationResponse(
        id=str(obs_id),
        trace_id=str(trace_id),
        name=get_attr(obs, 'name'),
        type=_enum_str(get_attr(obs, 'type')),
        model=model,
        start_time=start_time,
        end_time=end_time,
        completion_start_time=completion_start,
        latency_ms=latency_ms,
        time_to_first_token_ms=ttft_ms,
        input_tokens=int(input_tokens or 0),
        output_tokens=int(output_tokens or 0),
        total_tokens=int(total_tokens or 0),
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=total_cost,
        input=get_attr(obs, 'input'),
        output=get_attr(obs, 'output'),
        metadata=metadata,
        level=_enum_str(get_attr(obs, 'level')),
        status_message=get_attr(obs, 'status_message', 'statusMessage'),
        parent_observation_id=get_attr(obs, 'parent_observation_id', 'parentObservationId'),
    )


def parse_trace_to_list_item(trace: Any, observations: list | None = None) -> TraceListItem:
    """Parse a trace into a list item (lighter format)."""
    trace_id = get_attr(trace, 'id', 'trace_id', 'traceId', default='')
    timestamp = parse_datetime(get_attr(trace, 'timestamp'))

    # If we have observations, aggregate from them
    total_tokens = 0
    total_cost = 0.0
    models_used = set()
    latencies = []

    if observations:
        for obs in observations:
            parsed = parse_observation(obs) if not isinstance(obs, ObservationResponse) else obs
            total_tokens += parsed.total_tokens
            total_cost += parsed.total_cost
            if parsed.model:
                models_used.add(parsed.model)
            if parsed.latency_ms:
                latencies.append(parsed.latency_ms)
    else:
        # Fall back to trace-level data
        total_tokens = get_attr(trace, 'totalTokens', 'total_tokens', default=0) or 0
        total_cost = float(get_attr(trace,
            'calculated_total_cost', 'calculatedTotalCost',
            'total_cost', 'totalCost', default=0) or 0)
        _lat_raw_ms = get_attr(trace, "latency_ms", "latencyMs", default=None)
        if _lat_raw_ms is not None:
            try:
                latencies.append(float(_lat_raw_ms))
            except (TypeError, ValueError):
                pass
        elif get_attr(trace, "latency", default=None) is not None:
            try:
                # Langfuse 'latency' field is in SECONDS — convert to ms
                latencies.append(float(get_attr(trace, "latency")) * 1000.0)
            except (TypeError, ValueError):
                pass

    # Calculate trace-level latency from first/last observation or trace times
    latency_ms = max(latencies) if latencies else None

    return TraceListItem(
        id=str(trace_id),
        name=get_attr(trace, 'name'),
        session_id=get_attr(trace, 'session_id', 'sessionId'),
        timestamp=timestamp,
        total_tokens=int(total_tokens),
        total_cost=total_cost,
        latency_ms=latency_ms,
        models_used=list(models_used),
        observation_count=len(observations) if observations else 0,
        level=get_attr(trace, 'level'),
    )


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("/status")
async def get_langfuse_status() -> LangfuseStatusResponse:
    """Check if Langfuse is connected and available."""
    host = os.getenv("LANGFUSE_HOST")
    client = get_langfuse_client()

    if not client:
        return LangfuseStatusResponse(
            connected=False,
            host=host,
            message="Langfuse not configured. Set LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_HOST in your .env file."
        )

    try:
        # v3 uses auth_check(), v2 uses client.health.health()
        if is_v3_client(client):
            # v3 health check uses auth_check()
            if client.auth_check():
                sdk_version = "v3"
                return LangfuseStatusResponse(
                    connected=True,
                    host=host,
                    message=f"Langfuse connected successfully (SDK {sdk_version})"
                )
            else:
                return LangfuseStatusResponse(
                    connected=False,
                    host=host,
                    message="Langfuse v3 auth_check() failed - check credentials"
                )
        else:
            # v2 health check
            from langfuse.api.core.request_options import RequestOptions
            client.client.health.health(request_options=RequestOptions(timeout_in_seconds=2))
            sdk_version = "v2"
            return LangfuseStatusResponse(
                connected=True,
                host=host,
                message=f"Langfuse connected successfully (SDK {sdk_version})"
            )
    except Exception as e:
        return LangfuseStatusResponse(
            connected=False,
            host=host,
            message=f"Cannot connect to Langfuse: {str(e)}"
        )


@router.get("/debug")
async def debug_langfuse_data(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict:
    """
    Debug endpoint to diagnose observability data issues.
    Shows raw data from Langfuse to help troubleshoot.
    """
    client = get_langfuse_client()
    if not client:
        return {"error": "Langfuse not configured"}

    result = {
        "current_user_id": str(current_user.id),
        "langfuse_methods": [],
        "all_traces_count": 0,
        "user_traces_count": 0,
        "sample_user_ids": [],
        "sample_traces": [],
        "errors": [],
    }

    # Check what methods are available
    for method in ['fetch_traces', 'fetch_observations', 'fetch_trace', 'get_traces']:
        if hasattr(client, method):
            result["langfuse_methods"].append(method)

    # Try to fetch all traces without filter
    try:
        if hasattr(client, 'fetch_traces'):
            response = client.fetch_traces(limit=100)
            all_traces = []
            if hasattr(response, 'data'):
                all_traces = response.data or []
            elif isinstance(response, list):
                all_traces = response
            elif isinstance(response, dict):
                all_traces = response.get('data', [])

            result["all_traces_count"] = len(all_traces)

            # Collect unique user_ids
            user_ids = set()
            for trace in all_traces:
                uid = get_attr(trace, 'user_id', 'userId')
                if uid:
                    user_ids.add(str(uid))

            result["sample_user_ids"] = list(user_ids)[:20]

            # Count traces for current user
            user_traces = [t for t in all_traces if str(get_attr(t, 'user_id', 'userId') or '') == str(current_user.id)]
            result["user_traces_count"] = len(user_traces)

            # Sample trace data (first 3 traces)
            for trace in all_traces[:3]:
                sample = {
                    "id": str(get_attr(trace, 'id', default=''))[:20],
                    "name": get_attr(trace, 'name'),
                    "user_id": str(get_attr(trace, 'user_id', 'userId') or ''),
                    "session_id": get_attr(trace, 'session_id', 'sessionId'),
                    "timestamp": str(get_attr(trace, 'timestamp', default=''))[:30],
                }
                result["sample_traces"].append(sample)

    except Exception as e:
        result["errors"].append(f"fetch_traces error: {str(e)}")
        result["errors"].append(traceback.format_exc())

    return result


@router.get("/debug/trace/{trace_id}")
async def debug_trace_detail(
    trace_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict:
    """
    Debug endpoint to see raw trace and observation data.
    Helps troubleshoot why trace details might not be showing.
    """
    client = get_langfuse_client()
    if not client:
        return {"error": "Langfuse not configured"}

    result = {
        "trace_id": trace_id,
        "current_user_id": str(current_user.id),
        "sdk_version": getattr(client, '_sdk_version', 'unknown'),
        "is_v3": is_v3_client(client),
        "trace_found": False,
        "trace_data": None,
        "observations_count": 0,
        "observations_sample": [],
        "errors": [],
    }

    # Fetch trace
    try:
        if hasattr(client, 'fetch_trace'):
            response = client.fetch_trace(trace_id)
            trace = response.data if hasattr(response, 'data') else response
            if trace:
                result["trace_found"] = True
                result["trace_data"] = {
                    "id": get_attr(trace, 'id'),
                    "name": get_attr(trace, 'name'),
                    "user_id": get_attr(trace, 'user_id', 'userId'),
                    "session_id": get_attr(trace, 'session_id', 'sessionId'),
                    "input": str(get_attr(trace, 'input'))[:200] if get_attr(trace, 'input') else None,
                    "output": str(get_attr(trace, 'output'))[:200] if get_attr(trace, 'output') else None,
                }
    except Exception as e:
        result["errors"].append(f"fetch_trace error: {str(e)}")

    # Fetch observations
    try:
        raw_observations = fetch_observations_for_trace(client, trace_id)
        result["observations_count"] = len(raw_observations)

        # Sample first 5 observations
        for obs in raw_observations[:5]:
            obs_sample = {
                "id": get_attr(obs, 'id'),
                "name": get_attr(obs, 'name'),
                "type": get_attr(obs, 'type'),
                "model": get_attr(obs, 'model'),
                "input_preview": str(get_attr(obs, 'input'))[:100] if get_attr(obs, 'input') else None,
                "output_preview": str(get_attr(obs, 'output'))[:100] if get_attr(obs, 'output') else None,
            }
            # Extract usage
            usage = get_attr(obs, 'usage', default={})
            if usage:
                if isinstance(usage, dict):
                    obs_sample["usage"] = usage
                elif hasattr(usage, '__dict__'):
                    obs_sample["usage"] = {k: v for k, v in usage.__dict__.items() if not k.startswith('_')}
            result["observations_sample"].append(obs_sample)
    except Exception as e:
        result["errors"].append(f"fetch_observations error: {str(e)}")
        result["errors"].append(traceback.format_exc())

    return result


@router.get("/traces")
async def get_user_traces(
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    page: Annotated[int, Query(ge=1)] = 1,
    session_id: Annotated[str | None, Query()] = None,
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD). Defaults to 7 days ago.")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD). Defaults to today.")] = None,
) -> TracesListResponse:
    """
    Get traces for the current user with aggregated metrics.

    OPTIMIZATION: Uses trace-level metrics only (no observation fetching).
    Observations are fetched only in detailed view (GET /traces/{trace_id}).

    Date filtering:
    - Defaults to last 7 days if no dates specified
    - Use from_date/to_date for custom ranges
    """
    _clear_request_caches()  # Clear per-request caches at start

    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        user_id = str(current_user.id)

        # Parse date range with sensible defaults (last 7 days)
        now = datetime.now(timezone.utc)
        if to_date:
            to_timestamp = datetime.strptime(to_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        else:
            to_timestamp = now

        if from_date:
            from_timestamp = datetime.strptime(from_date, "%Y-%m-%d").replace(
                hour=0, minute=0, second=0, tzinfo=timezone.utc
            )
        else:
            # Default to last 7 days
            from_timestamp = now - timedelta(days=7)

        # Fetch traces with date filter - request more than needed for filtering
        # but cap at a reasonable limit for performance
        fetch_limit = min(limit * page + 50, 200)  # Fetch enough for pagination + buffer
        raw_traces = fetch_traces_from_langfuse(
            client,
            user_id,
            limit=fetch_limit,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )

        # Filter by session if specified
        if session_id:
            raw_traces = [t for t in raw_traces if get_attr(t, 'session_id', 'sessionId') == session_id]

        # Parse traces with trace metrics helper; only falls back to observations for
        # missing metrics, avoiding persistent zero-token list rows.
        traces = []
        fallback_budget = {"remaining": min(30, max(5, len(raw_traces) // 4))}
        for trace in raw_traces:
            trace_id = get_attr(trace, 'id', 'trace_id', 'traceId')
            if not trace_id:
                continue

            trace_metrics = _get_trace_metrics(
                client,
                trace,
                allow_observation_fallback=True,
                fallback_budget=fallback_budget,
            )
            trace_item = TraceListItem(
                id=str(trace_id),
                name=get_attr(trace, 'name'),
                session_id=get_attr(trace, 'session_id', 'sessionId'),
                timestamp=parse_datetime(get_attr(trace, 'timestamp')),
                total_tokens=int(trace_metrics["total_tokens"]),
                total_cost=float(trace_metrics["total_cost"]),
                latency_ms=trace_metrics["latency_ms"],
                models_used=list(trace_metrics["models"]),
                observation_count=int(trace_metrics["observation_count"] or 0),
                level=get_attr(trace, 'level'),
            )
            traces.append(trace_item)

        # Sort by timestamp descending
        traces.sort(key=lambda t: t.timestamp or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        # Apply pagination
        total = len(traces)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_traces = traces[start_idx:end_idx]

        return TracesListResponse(
            traces=paginated_traces,
            total=total,
            page=page,
            limit=limit
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching traces: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch traces: {str(e)}")


@router.get("/traces/{trace_id}")
async def get_trace_detail(
    trace_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> TraceDetailResponse:
    """
    Get detailed trace information including all observations (spans).
    Shows the full execution timeline with LLM calls, tool calls, etc.

    Optimizations:
    - Parallelizes observation and score fetching
    - Uses request-scoped cache to avoid N+1 queries
    """
    _clear_request_caches()  # Clear per-request caches at start
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        logger.info(f"Fetching trace detail for trace_id={trace_id}, user_id={current_user.id}")

        # Fetch the trace - try fetch_trace first (works in both v2 and v3)
        trace = None

        # Primary: client.fetch_trace(trace_id)
        # Try both UUID formats: with and without hyphens (Langfuse SDKs differ on this).
        if hasattr(client, 'fetch_trace'):
            _tid_str = str(trace_id)
            _tid_variants: list[str] = [_tid_str]
            if '-' not in _tid_str and len(_tid_str) == 32:
                _tid_variants.append(f"{_tid_str[:8]}-{_tid_str[8:12]}-{_tid_str[12:16]}-{_tid_str[16:20]}-{_tid_str[20:]}")
            elif '-' in _tid_str:
                _tid_variants.append(_tid_str.replace('-', ''))
            for _tid_v in _tid_variants:
                try:
                    response = client.fetch_trace(_tid_v)
                    _t = response.data if hasattr(response, 'data') else response
                    if _t:
                        trace = _t
                        break
                except Exception as e:
                    logger.debug(f"fetch_trace({_tid_v!r}) failed: {e}")

        # Fallback for v3: client.api.trace.get(trace_id)
        if not trace and is_v3_client(client) and hasattr(client, 'api') and hasattr(client.api, 'trace'):
            try:
                trace = client.api.trace.get(trace_id)
            except Exception as e:
                logger.debug(f"v3 api.trace.get failed: {e}")

        # Fallback for v3: client.client.traces.get(trace_id)
        if not trace and is_v3_client(client) and hasattr(client, 'client') and hasattr(client.client, 'traces'):
            try:
                trace = client.client.traces.get(trace_id)
            except Exception as e:
                logger.debug(f"v3 traces.get failed: {e}")

        # Last resort: scan the in-process trace cache (no new API calls).
        # The trace is almost always cached from the session/agent list that the user
        # navigated from. Avoids the previous 300-trace API fetch (3 pages * ~3s = 9s).
        if not trace:
            _user_id_str = str(current_user.id)
            _norm_req_id = str(trace_id).replace('-', '').lower()
            for _ck, _ce in list(_TRACE_FETCH_CACHE.items()):
                if not _ck.startswith(f"{_user_id_str}|"):
                    continue
                for _candidate in (_ce.get("traces", []) or []):
                    _cid = str(get_attr(_candidate, "id", "trace_id", "traceId", default="") or "")
                    if _cid.replace('-', '').lower() == _norm_req_id:
                        _cand_uids = _extract_trace_user_ids(_candidate)
                        if not _cand_uids or _user_id_str in _cand_uids:
                            trace = _candidate
                            logger.debug(f"Found trace {trace_id} in process cache (no API call)")
                            break
                if trace:
                    break

        if not trace:
            raise HTTPException(status_code=404, detail="Trace not found")

        # Security check
        trace_user_ids = _extract_trace_user_ids(trace)
        if trace_user_ids and str(current_user.id) not in trace_user_ids:
            raise HTTPException(status_code=404, detail="Trace not found")
        trace_user_id = (
            str(current_user.id)
            if str(current_user.id) in trace_user_ids
            else (next(iter(trace_user_ids)) if trace_user_ids else None)
        )

        requested_trace_id = str(trace_id)
        resolved_trace_id = str(get_attr(trace, "id", "trace_id", "traceId", default=trace_id) or trace_id)
        if resolved_trace_id != requested_trace_id:
            logger.info(
                "Trace detail requested with trace_id={} resolved to canonical trace_id={}",
                requested_trace_id,
                resolved_trace_id,
            )

        # Fast path: the full trace object returned by fetch_trace() sometimes embeds
        # observations. Only use them if they carry meaningful data — in Langfuse v3 the
        # embedded objects may be lightweight summaries with usage=0 and name=None.
        # We validate by parsing the embedded obs and checking that at least one has a
        # non-zero token count or a real name before trusting the fast path.
        import asyncio
        _embedded_obs = get_attr(trace, "observations", default=None)
        _use_embedded = False
        if _embedded_obs and isinstance(_embedded_obs, (list, tuple)) and len(_embedded_obs) > 0:
            _parsed_preview = [parse_observation(o) for o in _embedded_obs]
            _has_tokens = any(p.total_tokens > 0 for p in _parsed_preview)
            _has_names = any(p.name for p in _parsed_preview)
            _use_embedded = _has_tokens or _has_names
            if not _use_embedded:
                logger.debug(
                    f"Trace {resolved_trace_id}: embedded obs have no names/tokens — "
                    "skipping fast path, fetching observations properly"
                )
        if _use_embedded:
            raw_observations: list = list(_embedded_obs)
            logger.debug(f"Trace {resolved_trace_id}: using {len(raw_observations)} embedded observations (no extra API call)")
            # Seed process cache so subsequent requests for same trace are instant
            _cache_and_return_observations(resolved_trace_id, raw_observations)
            fetched_scores_future = asyncio.create_task(asyncio.to_thread(
                lambda: fetch_scores_for_trace(client, resolved_trace_id, str(current_user.id), limit=200)
            ))
            fetched_scores = await fetched_scores_future
            if isinstance(fetched_scores, Exception):
                logger.warning(f"Failed to fetch scores: {fetched_scores}")
                fetched_scores = []
        else:
            # No embedded observations — fetch observations and scores in parallel
            obs_task = asyncio.create_task(asyncio.to_thread(
                lambda: fetch_observations_for_trace(client, resolved_trace_id)
            ))
            scores_task = asyncio.create_task(asyncio.to_thread(
                lambda: fetch_scores_for_trace(client, resolved_trace_id, str(current_user.id), limit=200)
            ))

            # Wait for both in parallel
            raw_observations, fetched_scores = await asyncio.gather(obs_task, scores_task, return_exceptions=True)

            # Handle exceptions from parallel tasks
            if isinstance(raw_observations, Exception):
                logger.warning(f"Failed to fetch observations: {raw_observations}")
                raw_observations = []
            if isinstance(fetched_scores, Exception):
                logger.warning(f"Failed to fetch scores: {fetched_scores}")
                fetched_scores = []

            # Fallback for alternative trace ID if nothing found
            if not raw_observations and resolved_trace_id != requested_trace_id:
                raw_observations = fetch_observations_for_trace(client, requested_trace_id)

        observations = [parse_observation(obs) for obs in (raw_observations or [])]

        # Sort observations by start time
        observations.sort(key=lambda o: o.start_time or datetime.min.replace(tzinfo=timezone.utc))

        # Aggregate metrics from observations
        total_tokens = sum(o.total_tokens for o in observations)
        input_tokens = sum(o.input_tokens for o in observations)
        output_tokens = sum(o.output_tokens for o in observations)
        total_cost = sum(o.total_cost for o in observations)
        models_used = list(set(o.model for o in observations if o.model))

        # Calculate trace latency
        latency_ms = None
        if observations:
            start_times = [o.start_time for o in observations if o.start_time]
            end_times = [o.end_time for o in observations if o.end_time]
            if start_times and end_times:
                latency_ms = (max(end_times) - min(start_times)).total_seconds() * 1000
        else:
            # Fallback to trace-level metrics if observations are unavailable
            trace_metrics = _get_trace_metrics(client, trace, allow_observation_fallback=False)
            total_tokens = int(trace_metrics["total_tokens"])
            input_tokens = int(trace_metrics["input_tokens"])
            output_tokens = int(trace_metrics["output_tokens"])
            total_cost = float(trace_metrics["total_cost"])
            latency_ms = trace_metrics["latency_ms"]
            if not models_used:
                models_used = list(trace_metrics["models"])

        # Merge and de-duplicate scores by id
        scores: list[ScoreItem] = []
        try:
            # Some SDK variants include scores in the trace payload directly
            embedded_scores = get_attr(trace, "scores", default=[]) or []
            if embedded_scores:
                scores.extend([
                    ScoreItem(
                        id=str(get_attr(score, "id", default=str(idx + 1))),
                        name=str(get_attr(score, "name", default="Score") or "Score"),
                        value=float(get_attr(score, "value", default=0.0) or 0.0),
                        source=(
                            str(get_attr(score, "source").value)
                            if hasattr(get_attr(score, "source"), "value")
                            else (str(get_attr(score, "source")) if get_attr(score, "source") is not None else None)
                        ),
                        comment=get_attr(score, "comment"),
                        created_at=parse_datetime(get_attr(score, "created_at", "createdAt", "timestamp")),
                    )
                    for idx, score in enumerate(embedded_scores)
                ])

            # Merge fetched scores with embedded ones, de-duplicate by id
            merged = {s.id: s for s in scores if s.id}
            for score in (fetched_scores or []):
                if score.id in merged:
                    merged[score.id] = score
                else:
                    merged[score.id] = score
            scores = list(merged.values())
            scores.sort(key=lambda s: s.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            logger.info(f"Trace detail {trace_id}: loaded {len(scores)} score(s)")
        except Exception as e:
            logger.warning(f"Error merging scores for trace {trace_id}: {e}")

        return TraceDetailResponse(
            id=resolved_trace_id,
            name=get_attr(trace, 'name'),
            user_id=trace_user_id,
            session_id=get_attr(trace, 'session_id', 'sessionId'),
            timestamp=parse_datetime(get_attr(trace, 'timestamp')),
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost=total_cost,
            latency_ms=latency_ms,
            models_used=models_used,
            observations=observations,
            scores=scores,
            input=get_attr(trace, 'input'),
            output=get_attr(trace, 'output'),
            metadata=get_attr(trace, 'metadata'),
            tags=get_attr(trace, 'tags', default=[]) or [],
            level=_enum_str(get_attr(trace, 'level')),
            status=_enum_str(get_attr(trace, 'status')),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching trace detail: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to fetch trace: {str(e)}")


@router.get("/sessions")
async def get_user_sessions(
    current_user: Annotated[User, Depends(get_current_active_user)],
    background_tasks: BackgroundTasks,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    # Filter parameters
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD). Defaults to 7 days ago.")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD). Defaults to today.")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC")] = None,
    search: Annotated[str | None, Query(description="Search by session ID or trace name")] = None,
    fetch_all: Annotated[bool, Query(description="Fetch all traces (up to 5000) instead of capped limit")] = False,
) -> SessionsListResponse:
    """
    Get chat sessions for the current user with aggregated metrics.

    STALE-WHILE-REVALIDATE CACHING STRATEGY:
    - Fresh cache (<15s old): Return immediately, no refresh
    - Stale cache (15-60s old): Return immediately, trigger background refresh
    - Expired cache (>60s old): Fetch fresh data (blocks briefly)

    OPTIMIZATION: Uses trace-level metrics only (no observation fetching).
    For detailed session data, use GET /sessions/{session_id}.

    Date filtering:
    - Defaults to last 7 days if no dates specified
    - Use from_date/to_date for custom ranges
    """
    _clear_request_caches()  # Clear per-request caches at start

    # Build cache key from stable parameters
    user_id = str(current_user.id)
    cache_key = f"sessions:{user_id}:{from_date}:{to_date}:{search}:{limit}:{tz_offset}:{fetch_all}"
    
    # Check cache status
    cache_meta = _get_cache_metadata(cache_key)
    
    # Cache checking logic (only if SWR enabled)
    if SWR_CONFIG["ENABLE_SWR"]:
        # === FRESH CACHE: Return immediately, no refresh ===
        if cache_meta["is_fresh"] and cache_key in _SESSIONS_CACHE:
            logger.debug(f"Sessions cache HIT (fresh) for {cache_key}, age={cache_meta['age_seconds']}s")
            cached = _SESSIONS_CACHE[cache_key]
            return SessionsListResponse(
                **cached["data"],
                fetched_trace_count=cached.get("fetched_trace_count", 0),
            )
        
        # === STALE CACHE: fetch fresh synchronously ===
        # We currently don't have a dedicated sessions background fetch task,
        # so returning stale data here can hide newly created traces.
        if cache_meta["is_stale"] and cache_key in _SESSIONS_CACHE:
            logger.debug(
                f"Sessions cache HIT (stale) for {cache_key}, age={cache_meta['age_seconds']}s; "
                "fetching fresh synchronously"
            )

    # === EXPIRED/MISSING CACHE: Fetch fresh data ===
    logger.debug(f"Sessions cache MISS for {cache_key}, fetching fresh data")
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        user_id = str(current_user.id)

        # Parse date filters with sensible defaults (last 7 days)
        from_timestamp, to_timestamp = _compute_date_range(
            from_date,
            to_date,
            tz_offset,
            default_days=7,
        )

        trace_limit = 500
        # Fetch traces with date filters
        raw_traces = fetch_traces_from_langfuse(
            client, user_id, limit=trace_limit,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            fetch_all=fetch_all,
        )

        is_truncated = (not fetch_all) and len(raw_traces) >= trace_limit

        # Group by session — use _get_trace_metrics which reads from the process-local
        # cache when already computed (e.g. by the /metrics endpoint), and falls back to
        # observations for traces missing trace-level token/cost fields (Langfuse v3).
        sessions_data: dict[str, dict] = {}
        fallback_budget = _make_fallback_budget(len(raw_traces))

        for trace in raw_traces:
            session_id = get_attr(trace, 'session_id', 'sessionId')
            if not session_id:
                continue

            timestamp = parse_datetime(get_attr(trace, 'timestamp'))

            trace_metrics = _get_trace_metrics(
                client,
                trace,
                allow_observation_fallback=True,
                fallback_budget=fallback_budget,
            )
            trace_tokens = int(trace_metrics["total_tokens"])
            trace_cost = float(trace_metrics["total_cost"])
            trace_latency_ms = trace_metrics["latency_ms"]
            trace_error_count = int(trace_metrics["error_count"])
            trace_models_list = list(trace_metrics["models"])

            if session_id not in sessions_data:
                sessions_data[session_id] = {
                    "session_id": session_id,
                    "trace_count": 0,
                    "total_tokens": 0,
                    "total_cost": 0.0,
                    "timestamps": [],
                    "models": set(),
                    "latencies": [],
                    "error_count": 0,
                }

            sessions_data[session_id]["trace_count"] += 1
            sessions_data[session_id]["total_tokens"] += trace_tokens
            sessions_data[session_id]["total_cost"] += trace_cost
            sessions_data[session_id]["models"].update(trace_models_list)
            sessions_data[session_id]["error_count"] += trace_error_count
            if trace_latency_ms is not None:
                sessions_data[session_id]["latencies"].append(trace_latency_ms)
            if timestamp:
                sessions_data[session_id]["timestamps"].append(timestamp)

        # Build response
        sessions = []
        for sid, data in sessions_data.items():
            timestamps = data["timestamps"]
            latencies = data["latencies"]
            avg_latency = (sum(latencies) / len(latencies)) if latencies else None
            error_count = int(data.get("error_count", 0))
            sessions.append(SessionListItem(
                session_id=sid,
                trace_count=data["trace_count"],
                total_tokens=data["total_tokens"],
                total_cost=data["total_cost"],
                avg_latency_ms=avg_latency,
                first_trace_at=min(timestamps) if timestamps else None,
                last_trace_at=max(timestamps) if timestamps else None,
                models_used=list(data["models"]),
                error_count=error_count,
                has_errors=error_count > 0,
            ))

        # Apply search filter (client-side search by session ID)
        if search:
            search_lower = search.lower()
            sessions = [s for s in sessions if search_lower in s.session_id.lower()]

        # Sort by last activity
        sessions.sort(key=lambda s: s.last_trace_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        total_count = len(sessions)
        sessions = sessions[:limit]

        # Build response
        response_data = {
            "sessions": sessions,
            "total": total_count,
            "truncated": is_truncated,
        }

        # Cache the result, but avoid caching empty date-filter windows to reduce
        # sticky false-empty UI states from intermittent upstream filtering issues.
        should_cache_response = not (
            total_count == 0 and (from_date or to_date)
        )
        if should_cache_response:
            cache_key = f"sessions:{user_id}:{from_date}:{to_date}:{search}:{limit}:{tz_offset}:{fetch_all}"
            if cache_key not in _SESSIONS_CACHE:
                _SESSIONS_CACHE[cache_key] = {}
            _SESSIONS_CACHE[cache_key]["data"] = response_data
            _SESSIONS_CACHE[cache_key]["fetched_trace_count"] = len(raw_traces)
            _update_cache_metadata(cache_key, response_data)

        return SessionsListResponse(
            sessions=sessions,
            total=total_count,
            truncated=is_truncated,
            fetched_trace_count=len(raw_traces),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch sessions: {str(e)}")


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD)")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC")] = None,
) -> SessionDetailResponse:
    """
    Get detailed session information including all traces and per-model breakdown.
    """
    _clear_request_caches()  # Clear per-request caches at start

    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        user_id = str(current_user.id)

        # Parse optional date filters with timezone-aware helper (must match list endpoints)
        from_timestamp, to_timestamp = _compute_date_range(
            from_date,
            to_date,
            tz_offset,
            default_days=None,
        )

        # Fetch traces by date window and filter by session_id client-side.
        # Relying on SDK/server-side session_id filtering can under-return traces
        # (often only root traces), which causes mismatch with session/agent tabs.
        raw_traces = fetch_traces_from_langfuse(
            client,
            user_id,
            limit=500,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            fetch_all=False,
        )

        # Filter to the requested session using the same semantics as list endpoints.
        session_traces = [t for t in raw_traces if get_attr(t, 'session_id', 'sessionId') == session_id]

        if not session_traces:
            raise HTTPException(status_code=404, detail="Session not found")

        # Process traces and collect metrics
        traces = []
        total_tokens = 0
        input_tokens = 0
        output_tokens = 0
        total_cost = 0.0
        total_observations = 0
        latencies = []
        models_used: dict[str, dict] = {}
        timestamps = []

        # Small fallback budget: only call observations if trace-level data is completely absent
        fallback_budget: dict[str, int] = {"remaining": min(3, len(session_traces))}

        for trace in session_traces:
            trace_id = _get_trace_id(trace)
            timestamp = parse_datetime(get_attr(trace, 'timestamp'))
            if timestamp:
                timestamps.append(timestamp)

            # Fast path: use trace-level metrics (already cached from session-list computation).
            # This avoids N sequential observation API calls (previously 10+ s per session click).
            trace_metrics = _get_trace_metrics(
                client, trace,
                allow_observation_fallback=True,
                fallback_budget=fallback_budget,
            )
            t_tokens = int(trace_metrics["total_tokens"])
            t_input = int(trace_metrics["input_tokens"])
            t_output = int(trace_metrics["output_tokens"])
            t_cost = float(trace_metrics["total_cost"])
            t_latency = trace_metrics["latency_ms"]
            t_models = list(trace_metrics["models"])
            t_obs_count = int(trace_metrics["observation_count"] or 0)

            total_tokens += t_tokens
            input_tokens += t_input
            output_tokens += t_output
            total_cost += t_cost
            total_observations += t_obs_count

            if t_latency:
                latencies.append(t_latency)

            for model in t_models:
                if model not in models_used:
                    models_used[model] = {"tokens": 0, "cost": 0.0, "calls": 0}
                models_used[model]["tokens"] += t_tokens
                models_used[model]["cost"] += t_cost
                models_used[model]["calls"] += 1

            trace_item = TraceListItem(
                id=str(trace_id),
                name=get_attr(trace, 'name'),
                session_id=get_attr(trace, 'session_id', 'sessionId'),
                timestamp=timestamp,
                total_tokens=t_tokens,
                total_cost=t_cost,
                latency_ms=t_latency,
                models_used=t_models,
                observation_count=t_obs_count,
                level=get_attr(trace, 'level'),
            )
            traces.append(trace_item)

        # Sort traces by timestamp
        traces.sort(key=lambda t: t.timestamp or datetime.min.replace(tzinfo=timezone.utc))

        # Calculate session duration
        duration = None
        if len(timestamps) >= 2:
            duration = (max(timestamps) - min(timestamps)).total_seconds()

        avg_latency = sum(latencies) / len(latencies) if latencies else None

        return SessionDetailResponse(
            session_id=session_id,
            trace_count=len(traces),
            observation_count=total_observations,
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost=total_cost,
            avg_latency_ms=avg_latency,
            first_trace_at=min(timestamps) if timestamps else None,
            last_trace_at=max(timestamps) if timestamps else None,
            duration_seconds=duration,
            models_used=models_used,
            traces=traces,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching session detail: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to fetch session: {str(e)}")


@router.get("/metrics")
async def get_user_metrics(
    current_user: Annotated[User, Depends(get_current_active_user)],
    background_tasks: BackgroundTasks,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    # Filter parameters
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD). Defaults to 7 days ago.")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD). Defaults to today.")] = None,
    search: Annotated[str | None, Query(description="Search by trace name")] = None,
    models: Annotated[str | None, Query(description="Comma-separated model names to filter")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC (e.g., 330 for IST)")] = None,
    include_model_breakdown: Annotated[bool, Query(description="Include per-model breakdown (slower)")] = False,
    fetch_all: Annotated[bool, Query(description="Fetch all traces (up to 5000) instead of capped limit")] = False,
) -> MetricsResponse:
    """
    Get comprehensive aggregated metrics for the current user.

    STALE-WHILE-REVALIDATE CACHING STRATEGY:
    - Fresh cache (<15s old): Return immediately, no refresh
    - Stale cache (15-60s old): Return immediately, trigger background refresh
    - Expired cache (>60s old): Fetch fresh data (blocks briefly)
    
    PERFORMANCE OPTIMIZATION:
    - By default, uses TRACE-LEVEL metrics only (fast, no observation fetching)
    - set include_model_breakdown=true ONLY if per-model detailed stats needed
    - Most responses will be instant (100-200ms from cache)

    Date filtering:
    - Defaults to last 7 days if no dates specified
    - Use from_date/to_date for custom ranges
    """
    _clear_request_caches()  # Clear per-request caches at start

    # If SWR is disabled, skip the caching logic
    if not SWR_CONFIG["ENABLE_SWR"]:
        return _fetch_metrics_sync(current_user, days, from_date, to_date, search, models, tz_offset, include_model_breakdown, fetch_all)
    
    user_id = str(current_user.id)
    
    # Build cache key from stable parameters
    cache_key = f"metrics:{user_id}:{from_date}:{to_date}:{days}:{search}:{models}:{include_model_breakdown}:{tz_offset}:{fetch_all}"
    
    # Check cache status
    cache_meta = _get_cache_metadata(cache_key)
    
    # === FRESH CACHE: Return immediately, no refresh ===
    if cache_meta["is_fresh"] and cache_key in _TRACE_METRICS_CACHE:
        logger.debug(f"Metrics cache HIT (fresh) for {cache_key}, age={cache_meta['age_seconds']}s")
        cached = _TRACE_METRICS_CACHE[cache_key]
        return MetricsResponse(
            **cached["metrics"],
            cache_age_seconds=cache_meta["age_seconds"],
            cache_is_fresh=True,
        )
    
    # === STALE CACHE: Return immediately + trigger background refresh ===
    if cache_meta["is_stale"] and cache_key in _TRACE_METRICS_CACHE:
        logger.debug(f"Metrics cache HIT (stale) for {cache_key}, age={cache_meta['age_seconds']}s, triggering refresh")
        cached = _TRACE_METRICS_CACHE[cache_key]
        
        # Parse date parameters for background task
        from_timestamp, to_timestamp = _compute_date_range(
            from_date,
            to_date,
            tz_offset,
            default_days=days,
        )
        
        # Trigger background refresh (non-blocking)
        await _trigger_background_refresh(
            background_tasks,
            cache_key,
            {
                "user_id": user_id,
                "cache_key": cache_key,
                "from_timestamp": from_timestamp,
                "to_timestamp": to_timestamp,
                "search": search,
                "models": models,
                "include_model_breakdown": include_model_breakdown,
                "fetch_all": fetch_all,
            },
            task_fn=_fetch_metrics_background,
        )
        
        return MetricsResponse(
            **cached["metrics"],
            cache_age_seconds=cache_meta["age_seconds"],
            cache_is_fresh=False,
        )
    
    # === EXPIRED CACHE: Return cached immediately + trigger background refresh ===
    if cache_meta["is_expired"] and cache_key in _TRACE_METRICS_CACHE:
        logger.debug(f"Metrics cache HIT (expired) for {cache_key}, serving cached and refreshing in background")
        cached = _TRACE_METRICS_CACHE[cache_key]

        from_timestamp, to_timestamp = _compute_date_range(
            from_date,
            to_date,
            tz_offset,
            default_days=days,
        )

        await _trigger_background_refresh(
            background_tasks,
            cache_key,
            {
                "user_id": user_id,
                "cache_key": cache_key,
                "from_timestamp": from_timestamp,
                "to_timestamp": to_timestamp,
                "search": search,
                "models": models,
                "include_model_breakdown": include_model_breakdown,
                "fetch_all": fetch_all,
            },
            task_fn=_fetch_metrics_background,
        )

        return MetricsResponse(
            **cached["metrics"],
            cache_age_seconds=cache_meta["age_seconds"],
            cache_is_fresh=False,
        )

    # === EXPIRED/MISSING CACHE: Fetch fresh data (blocks briefly) ===
    logger.debug(f"Metrics cache MISS for {cache_key}, fetching fresh data")
    
    # Fall back to synchronous fetch
    return _fetch_metrics_sync(current_user, days, from_date, to_date, search, models, tz_offset, include_model_breakdown, fetch_all)


def _compute_date_range(
    from_date: str | None,
    to_date: str | None,
    tz_offset: int | None,
    default_days: int | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Compute UTC date range from local date inputs with optional timezone offset."""
    now_utc = datetime.now(timezone.utc)

    # If no filters and no default, return None (no date filtering)
    if not from_date and not to_date and default_days is None:
        return None, None

    if tz_offset is not None:
        local_now = now_utc + timedelta(minutes=tz_offset)

        if to_date:
            try:
                local_to = datetime.strptime(to_date, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            except ValueError:
                local_to = local_now.replace(hour=23, minute=59, second=59, microsecond=0)
        else:
            local_to = local_now.replace(hour=23, minute=59, second=59, microsecond=0)

        if from_date:
            try:
                local_from = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                local_from = (local_now - timedelta(days=default_days or 0)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
        else:
            local_from = (local_now - timedelta(days=default_days or 0)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        from_timestamp = local_from - timedelta(minutes=tz_offset)
        to_timestamp = local_to - timedelta(minutes=tz_offset)
        return from_timestamp, to_timestamp

    # Fallback: treat dates as UTC
    if to_date:
        try:
            to_timestamp = datetime.strptime(to_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError:
            to_timestamp = now_utc
    else:
        to_timestamp = now_utc

    if from_date:
        try:
            from_timestamp = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            from_timestamp = now_utc - timedelta(days=default_days or 0)
    else:
        from_timestamp = now_utc - timedelta(days=default_days or 0)

    return from_timestamp, to_timestamp


def _fetch_metrics_sync(
    current_user: User,
    days: int,
    from_date: str | None,
    to_date: str | None,
    search: str | None,
    models: str | None,
    tz_offset: int | None,
    include_model_breakdown: bool,
    fetch_all: bool,
) -> MetricsResponse:
    """
    Synchronous metrics fetch (used when cache misses or SWR disabled).
    This is the actual computation that builds metrics from Langfuse.
    """
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        user_id = str(current_user.id)

        # Parse date filters with sensible defaults (last N days)
        from_timestamp, to_timestamp = _compute_date_range(
            from_date,
            to_date,
            tz_offset,
            default_days=days,
        )

        # Parse model filter
        model_filter = None
        if models:
            model_filter = [m.strip() for m in models.split(",") if m.strip()]

        # Fetch traces with date filters
        trace_limit = 500
        raw_traces = fetch_traces_from_langfuse(
            client,
            user_id,
            limit=trace_limit,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            name=search,
            fetch_all=fetch_all,
        )

        is_truncated = (not fetch_all) and len(raw_traces) >= trace_limit

        # Aggregate metrics
        total_traces = len(raw_traces)
        # Allocate fallback budget more conservatively to only fill critical data gaps
        fallback_budget = _make_fallback_budget(total_traces)
        total_observations = 0
        total_tokens = 0
        input_tokens = 0
        output_tokens = 0
        total_cost = 0.0
        latencies = []
        sessions = set()

        model_data: dict[str, dict] = defaultdict(lambda: {
            "call_count": 0, "total_tokens": 0, "input_tokens": 0,
            "output_tokens": 0, "total_cost": 0.0, "latencies": []
        })

        daily_data: dict[str, dict] = defaultdict(lambda: {
            "trace_count": 0, "observation_count": 0, "total_tokens": 0, "total_cost": 0.0
        })

        agent_data: dict[str, dict] = defaultdict(lambda: {
            "count": 0, "tokens": 0, "cost": 0.0
        })

        for trace in raw_traces:
            trace_id = get_attr(trace, 'id')
            trace_name = get_attr(trace, 'name') or 'Unknown'
            session_id = get_attr(trace, 'session_id', 'sessionId')
            timestamp = parse_datetime(get_attr(trace, 'timestamp'))

            if session_id:
                sessions.add(session_id)

            # Apply timezone offset if provided to get local date
            if timestamp and tz_offset is not None:
                local_timestamp = timestamp + timedelta(minutes=tz_offset)
                date_str = local_timestamp.strftime('%Y-%m-%d')
            else:
                date_str = timestamp.strftime('%Y-%m-%d') if timestamp else 'Unknown'
            daily_data[date_str]["trace_count"] += 1

            # OPTIMIZATION: Only fetch observations if explicitly requested
            # Smart fallback strategy: only fetch if trace has NO metrics data at all
            trace_metrics = _get_trace_metrics(
                client,
                trace,
                allow_observation_fallback=not include_model_breakdown,  # Disable fallback unless explicitly requested
                fallback_budget=fallback_budget,
            )
            trace_tokens = int(trace_metrics["total_tokens"])
            trace_input_tokens = int(trace_metrics["input_tokens"])
            trace_output_tokens = int(trace_metrics["output_tokens"])
            trace_cost = float(trace_metrics["total_cost"])
            trace_latency_ms = trace_metrics["latency_ms"]
            trace_models = list(trace_metrics["models"])

            # Best-effort model filter using trace-level model fields
            if model_filter and trace_models:
                if not any(model_name in model_filter for model_name in trace_models):
                    continue

            # ONLY fetch observations if user explicitly requested detailed breakdown
            if include_model_breakdown:
                try:
                    observations = fetch_observations_for_trace(client, str(trace_id))
                    parsed_obs = [parse_observation(obs) for obs in observations]
                except Exception:
                    parsed_obs = []

                # Replace trace-level totals with observation totals when available
                if parsed_obs:
                    trace_tokens = sum(obs.total_tokens for obs in parsed_obs)
                    trace_input_tokens = sum(obs.input_tokens for obs in parsed_obs)
                    trace_output_tokens = sum(obs.output_tokens for obs in parsed_obs)
                    trace_cost = sum(obs.total_cost for obs in parsed_obs)
                    if trace_latency_ms is None:
                        obs_latencies = [obs.latency_ms for obs in parsed_obs if obs.latency_ms]
                        if obs_latencies:
                            trace_latency_ms = max(obs_latencies)

                    total_observations += len(parsed_obs)
                    daily_data[date_str]["observation_count"] += len(parsed_obs)

                    # Per-model breakdown
                    for obs in parsed_obs:
                        if model_filter and obs.model and obs.model not in model_filter:
                            continue

                        if obs.latency_ms:
                            latencies.append(obs.latency_ms)

                        if obs.model:
                            model_data[obs.model]["call_count"] += 1
                            model_data[obs.model]["total_tokens"] += obs.total_tokens
                            model_data[obs.model]["input_tokens"] += obs.input_tokens
                            model_data[obs.model]["output_tokens"] += obs.output_tokens
                            model_data[obs.model]["total_cost"] += obs.total_cost
                            if obs.latency_ms:
                                model_data[obs.model]["latencies"].append(obs.latency_ms)
            else:
                # FAST PATH: Use trace-level aggregates (no observation fetching)
                trace_obs_count = int(trace_metrics["observation_count"] or 0)
                total_observations += trace_obs_count
                daily_data[date_str]["observation_count"] += trace_obs_count
                if trace_latency_ms:
                    latencies.append(trace_latency_ms)
                # Per-model aggregation from trace-level data
                for model_name in trace_models:
                    model_data[model_name]["call_count"] += 1
                    model_data[model_name]["total_tokens"] += trace_tokens
                    model_data[model_name]["input_tokens"] += trace_input_tokens
                    model_data[model_name]["output_tokens"] += trace_output_tokens
                    model_data[model_name]["total_cost"] += trace_cost
                    if trace_latency_ms:
                        model_data[model_name]["latencies"].append(trace_latency_ms)

            # Aggregate overall metrics
            total_tokens += trace_tokens
            input_tokens += trace_input_tokens
            output_tokens += trace_output_tokens
            total_cost += trace_cost
            daily_data[date_str]["total_tokens"] += trace_tokens
            daily_data[date_str]["total_cost"] += trace_cost
            agent_data[trace_name]["count"] += 1
            agent_data[trace_name]["tokens"] += trace_tokens
            agent_data[trace_name]["cost"] += trace_cost

        # Calculate performance metrics
        avg_latency = sum(latencies) / len(latencies) if latencies else None
        p95_latency = None
        if latencies:
            sorted_latencies = sorted(latencies)
            p95_idx = int(len(sorted_latencies) * 0.95)
            p95_latency = sorted_latencies[min(p95_idx, len(sorted_latencies) - 1)]

        # Build model usage list
        by_model = []
        for model, data in model_data.items():
            avg_lat = sum(data["latencies"]) / len(data["latencies"]) if data["latencies"] else None
            by_model.append(ModelUsageItem(
                model=model,
                call_count=data["call_count"],
                total_tokens=data["total_tokens"],
                input_tokens=data["input_tokens"],
                output_tokens=data["output_tokens"],
                total_cost=data["total_cost"],
                avg_latency_ms=avg_lat,
            ))
        by_model.sort(key=lambda m: m.total_tokens, reverse=True)

        # Build daily usage list
        by_date = []
        for date, data in sorted(daily_data.items()):
            if date != 'Unknown':
                by_date.append(DailyUsageItem(
                    date=date,
                    trace_count=data["trace_count"],
                    observation_count=data["observation_count"],
                    total_tokens=data["total_tokens"],
                    total_cost=data["total_cost"],
                ))
        if not (from_date or to_date):
            by_date = by_date[-days:]  # Keep only last N days for default window

        # Build top agents (aggregated by trace name)
        top_agents = [
            {"name": name, "count": data["count"], "tokens": data["tokens"], "cost": data["cost"]}
            for name, data in sorted(agent_data.items(), key=lambda x: x[1]["count"], reverse=True)[:10]
        ]

        logger.info(
            f"Metrics computed: traces={total_traces}, tokens={total_tokens}, cost=${total_cost:.2f}, "
            f"observation_fetch={'YES' if include_model_breakdown else 'NO'}"
        )

        # Cache the result with metadata
        cache_key = f"metrics:{user_id}:{from_date}:{to_date}:{days}:{search}:{models}:{include_model_breakdown}:{tz_offset}:{fetch_all}"
        metrics_dict = {
            "total_traces": total_traces,
            "total_observations": total_observations,
            "total_sessions": len(sessions),
            "total_tokens": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_cost_usd": total_cost,
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "by_model": by_model,
            "by_date": by_date,
            "top_agents": top_agents,
            "truncated": is_truncated,
            "fetched_trace_count": len(raw_traces),
        }
        # Avoid caching empty totals from transient Langfuse fetch failures.
        if total_traces > 0:
            _TRACE_METRICS_CACHE[cache_key] = {"metrics": metrics_dict, "ts": time.monotonic()}
            _update_cache_metadata(cache_key, metrics_dict)

        return MetricsResponse(
            total_traces=total_traces,
            total_observations=total_observations,
            total_sessions=len(sessions),
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost_usd=total_cost,
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95_latency,
            by_model=by_model,
            by_date=by_date,
            top_agents=top_agents,
            truncated=is_truncated,
            fetched_trace_count=len(raw_traces),
            cache_age_seconds=0,
            cache_is_fresh=True,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating metrics: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to calculate metrics: {str(e)}")


# =============================================================================
# Agent/Agent Response Models
# =============================================================================

class AgentListItem(BaseModel):
    """Agent/Agent item for list views."""
    agent_id: str
    agent_name: str | None = None
    project_id: str | None = None  # Folder ID
    project_name: str | None = None  # Folder name
    trace_count: int = 0
    session_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float | None = None
    models_used: list[str] = []
    last_activity: datetime | None = None
    error_count: int = 0  # Count of ERROR/WARNING level observations


class AgentListResponse(BaseModel):
    """List of agents/agents."""
    agents: list[AgentListItem]
    total: int
    truncated: bool = False
    fetched_trace_count: int = 0


class AgentDetailResponse(BaseModel):
    """Detailed agent/agent information."""
    agent_id: str
    agent_name: str | None = None
    trace_count: int = 0
    session_count: int = 0
    observation_count: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float | None = None
    first_activity: datetime | None = None
    last_activity: datetime | None = None
    models_used: dict[str, dict] = {}  # model -> {tokens, cost, calls}
    sessions: list[SessionListItem] = []
    by_date: list[DailyUsageItem] = []


# =============================================================================
# Project Response Models
# =============================================================================

class ProjectListItem(BaseModel):
    """Project item for list views."""
    project_id: str
    project_name: str | None = None
    agent_count: int = 0
    trace_count: int = 0
    session_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    last_activity: datetime | None = None


class ProjectListResponse(BaseModel):
    """List of projects."""
    projects: list[ProjectListItem]
    total: int
    truncated: bool = False
    fetched_trace_count: int = 0


class ProjectDetailResponse(BaseModel):
    """Detailed project information."""
    project_id: str
    project_name: str | None = None
    agent_count: int = 0
    trace_count: int = 0
    session_count: int = 0
    observation_count: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float | None = None
    first_activity: datetime | None = None
    last_activity: datetime | None = None
    models_used: dict[str, dict] = {}  # model -> {tokens, cost, calls}
    agents: list[AgentListItem] = []
    by_date: list[DailyUsageItem] = []


# =============================================================================
# Helper: Extract agent/project info from trace
# =============================================================================

# =============================================================================
# Agent/Agent Endpoints
# =============================================================================

def _is_vertex_trace(trace_name: str | None) -> bool:
    """Check if a trace name looks like a vertex-level trace (not a agent trace)."""
    if not trace_name:
        return False
    # Vertex traces typically have patterns like:
    # - vertex_build_ChatOutput-xxxxx
    # - vertex_...-xxxxx
    # - ChatOutput-xxxxx (component names with hash suffix)
    vertex_prefixes = ('vertex_', 'vertex_build_')
    if trace_name.startswith(vertex_prefixes):
        return True
    # Also filter out component-level traces that look like: ComponentName-hash
    # These have format: SomeName-5chars where the suffix is a hash
    if '-' in trace_name:
        parts = trace_name.rsplit('-', 1)
        if len(parts) == 2 and len(parts[1]) == 5 and parts[1].isalnum():
            # Likely a component trace like "ChatOutput-0f2wN"
            return True
    return False


def _match_trace_to_agent(trace, agents_by_id: dict, agents_by_name: dict) -> tuple[str | None, str | None]:
    """
    Match a trace to a agent using metadata or name matching.

    Returns: (agent_id, agent_name) or (None, None) if no match
    """
    trace_name = get_attr(trace, 'name')
    metadata = _normalize_metadata(get_attr(trace, 'metadata', default={}) or {})
    tags = get_attr(trace, 'tags', default=[]) or []

    agents_by_name_lower = {
        str(name).strip().lower(): agent
        for name, agent in agents_by_name.items()
        if name
    }

    # Method 1: Check metadata for agent_id (most reliable, even for vertex traces)
    agent_id_from_meta = metadata.get('agent_id') or metadata.get('agentId')
    agent_id_from_meta_str = str(agent_id_from_meta).strip() if agent_id_from_meta else None
    if agent_id_from_meta_str and agent_id_from_meta_str in agents_by_id:
        agent = agents_by_id[agent_id_from_meta_str]
        return str(agent.id), agent.name

    # Method 2: Check tags for agent_id
    for tag in tags:
        if isinstance(tag, str) and tag.startswith('agent_id:'):
            fid = str(tag.split(':', 1)[1]).strip()
            if fid in agents_by_id:
                agent = agents_by_id[fid]
                return str(agent.id), agent.name

    # Method 3: Use agent_name from metadata as a hint (also for vertex traces)
    agent_name_from_meta = metadata.get('agent_name') or metadata.get('agentName')
    if agent_name_from_meta:
        agent = agents_by_name.get(agent_name_from_meta)
        if agent:
            return str(agent.id), agent.name
        agent = agents_by_name_lower.get(str(agent_name_from_meta).strip().lower())
        if agent:
            return str(agent.id), agent.name

    # Skip vertex-level traces for name-based fallback only
    if _is_vertex_trace(trace_name):
        return None, None

    # Method 4: Match by trace name to agent name
    if trace_name:
        # Exact match
        if trace_name in agents_by_name:
            agent = agents_by_name[trace_name]
            return str(agent.id), agent.name
        trace_name_lower = str(trace_name).strip().lower()
        if trace_name_lower in agents_by_name_lower:
            agent = agents_by_name_lower[trace_name_lower]
            return str(agent.id), agent.name
        # Match "AgentName - UUID" format
        if ' - ' in trace_name:
            name_part = trace_name.rsplit(' - ', 1)[0]
            if name_part in agents_by_name:
                agent = agents_by_name[name_part]
                return str(agent.id), agent.name
            name_part_lower = str(name_part).strip().lower()
            if name_part_lower in agents_by_name_lower:
                agent = agents_by_name_lower[name_part_lower]
                return str(agent.id), agent.name

    return None, None


def _user_agents_stmt(user_id):
    """Build a user-agent query compatible with schemas that may not expose `is_component`."""
    stmt = select(Agent).where(Agent.user_id == user_id)
    is_component_col = getattr(Agent, "is_component", None)
    if is_component_col is not None:
        stmt = stmt.where((is_component_col == False) | (is_component_col.is_(None)))  # noqa: E712
    return stmt


@router.get("/agents")
async def get_user_agents(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _background_tasks: BackgroundTasks,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD)")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC")] = None,
    fetch_all: Annotated[bool, Query(description="Fetch all traces (up to 5000) instead of capped limit")] = False,
) -> AgentListResponse:
    """
    Get all agents/agents for the current user with aggregated metrics.

    STALE-WHILE-REVALIDATE CACHING STRATEGY:
    - Fresh cache (<15s old): Return immediately, no refresh
    - Stale cache (15-60s old): Return immediately, trigger background refresh
    - Expired cache (>60s old): Fetch fresh data (blocks briefly)

    Uses database agents as source of truth and matches traces to agents.
    """
    _clear_request_caches()  # Clear per-request caches at start

    # Build cache key from stable parameters
    user_id = str(current_user.id)
    cache_key = f"agents:{user_id}:{from_date}:{to_date}:{limit}:{tz_offset}:{fetch_all}"
    
    # Check cache status
    cache_meta = _get_cache_metadata(cache_key)
    
    # Cache checking logic (only if SWR enabled)
    if SWR_CONFIG["ENABLE_SWR"]:
        # === FRESH CACHE: Return immediately, no refresh ===
        if cache_meta["is_fresh"] and cache_key in _AGENTS_CACHE:
            logger.debug(f"Agents cache HIT (fresh) for {cache_key}, age={cache_meta['age_seconds']}s")
            cached = _AGENTS_CACHE[cache_key]
            return AgentListResponse(
                **cached["data"],
                fetched_trace_count=cached.get("fetched_trace_count", 0),
            )
        
        # === STALE CACHE: fetch fresh synchronously ===
        # Background refresh task is not configured for agents cache.
        # Returning stale values here can keep token counts at zero for too long.
        if cache_meta["is_stale"] and cache_key in _AGENTS_CACHE:
            logger.debug(
                f"Agents cache HIT (stale) for {cache_key}, age={cache_meta['age_seconds']}s; "
                "fetching fresh synchronously"
            )

    # === EXPIRED/MISSING CACHE: Fetch fresh data ===
    logger.debug(f"Agents cache MISS for {cache_key}, fetching fresh data")
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        user_id = str(current_user.id)
        logger.info(f"Fetching agents for user_id: {user_id}")

        # Get all user agents from database (source of truth)
        agents_result = await session.exec(_user_agents_stmt(current_user.id))
        user_agents = agents_result.all()

        # Build lookup dictionaries
        agents_by_id = {str(f.id): f for f in user_agents}
        agents_by_name = {f.name: f for f in user_agents}

        # Get all folders (projects) that contain these agents
        folder_ids = set(f.folder_id for f in user_agents if f.folder_id)
        folders_by_id: dict[str, Folder] = {}
        if folder_ids:
            folders_result = await session.exec(
                select(Folder).where(Folder.id.in_(folder_ids))
            )
            folders_by_id = {str(f.id): f for f in folders_result.all()}

        # Build agent_id to folder mapping
        agent_to_folder: dict[str, tuple[str | None, str | None]] = {}
        for agent in user_agents:
            folder_id = str(agent.folder_id) if agent.folder_id else None
            folder_name = folders_by_id.get(folder_id).name if folder_id and folder_id in folders_by_id else None
            agent_to_folder[str(agent.id)] = (folder_id, folder_name)

        logger.info(f"Found {len(user_agents)} agents in database for user")

        # Parse date filters (timezone-aware if tz_offset provided)
        from_timestamp, to_timestamp = _compute_date_range(
            from_date,
            to_date,
            tz_offset,
            default_days=None,
        )

        # Fetch all traces from Langfuse
        trace_limit = 500
        raw_traces = fetch_traces_from_langfuse(
            client, user_id, limit=trace_limit,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            fetch_all=fetch_all,
        )

        is_truncated = (not fetch_all) and len(raw_traces) >= trace_limit

        logger.info(f"Found {len(raw_traces)} traces from Langfuse")

        # Two-pass approach:
        # Pass 1: Identify which sessions belong to which agent (using agent-level traces)
        # Pass 2: Aggregate ALL traces in those sessions (including vertex traces for tokens)

        # Pass 1: Map sessions to agents
        session_to_agent: dict[str, tuple[str, str]] = {}
        agent_agent_traces: dict[str, list] = {}

        for trace in raw_traces:
            agent_id, agent_name = _match_trace_to_agent(trace, agents_by_id, agents_by_name)
            if agent_id:
                session_id = get_attr(trace, 'session_id', 'sessionId')
                if session_id:
                    session_to_agent[session_id] = (agent_id, agent_name)
                if agent_id not in agent_agent_traces:
                    agent_agent_traces[agent_id] = []
                agent_agent_traces[agent_id].append(trace)

        logger.info(f"Found {len(session_to_agent)} sessions mapped to agents")

        # Pass 2: Aggregate ALL traces by session, grouping by agent
        agents_data: dict[str, dict] = {}
        processed_traces: set[str] = set()
        fallback_budget = _make_fallback_budget(len(raw_traces))

        for trace in raw_traces:
            trace_id = get_attr(trace, 'id')
            if trace_id in processed_traces:
                continue
            processed_traces.add(trace_id)

            session_id = get_attr(trace, 'session_id', 'sessionId')
            timestamp = parse_datetime(get_attr(trace, 'timestamp'))

            # Determine which agent this trace belongs to
            agent_id = None
            agent_name = None

            # First check if this trace directly matches an agent
            matched_agent_id, matched_agent_name = _match_trace_to_agent(trace, agents_by_id, agents_by_name)
            if matched_agent_id:
                agent_id, agent_name = matched_agent_id, matched_agent_name
            # Otherwise, check if it's part of an agent's session (vertex traces)
            elif session_id and session_id in session_to_agent:
                agent_id, agent_name = session_to_agent[session_id]

            if not agent_id:
                continue  # Skip traces not associated with any agent

            trace_metrics = _get_trace_metrics(
                client,
                trace,
                allow_observation_fallback=True,
                fallback_budget=fallback_budget,
            )
            trace_tokens = int(trace_metrics["total_tokens"])
            trace_cost = float(trace_metrics["total_cost"])
            trace_latency_ms = trace_metrics["latency_ms"]
            trace_models = list(trace_metrics["models"])
            trace_error_count = int(trace_metrics["error_count"])
            models = set(trace_models)
            latencies = [trace_latency_ms] if trace_latency_ms is not None else []
            error_count = trace_error_count

            if agent_id not in agents_data:
                agents_data[agent_id] = {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "trace_count": 0,
                    "sessions": set(),
                    "total_tokens": 0,
                    "total_cost": 0.0,
                    "models": set(),
                    "latencies": [],
                    "timestamps": [],
                    "error_count": 0,
                }

            # Only count agent-level traces in trace_count (not vertex traces)
            if matched_agent_id:
                agents_data[agent_id]["trace_count"] += 1

            # But aggregate tokens/cost from ALL traces (including vertex)
            agents_data[agent_id]["total_tokens"] += trace_tokens
            agents_data[agent_id]["total_cost"] += trace_cost
            agents_data[agent_id]["models"].update(models)
            agents_data[agent_id]["latencies"].extend(latencies)
            agents_data[agent_id]["error_count"] += error_count
            if session_id:
                agents_data[agent_id]["sessions"].add(session_id)
            if timestamp:
                agents_data[agent_id]["timestamps"].append(timestamp)

        # Build response
        agents = []
        for fid, data in agents_data.items():
            timestamps = data["timestamps"]
            latencies = data["latencies"]
            avg_latency = sum(latencies) / len(latencies) if latencies else None

            # Get project info from agent_to_folder mapping
            project_id, project_name = agent_to_folder.get(fid, (None, None))

            agents.append(AgentListItem(
                agent_id=fid,
                agent_name=data["agent_name"],
                project_id=project_id,
                project_name=project_name,
                trace_count=data["trace_count"],
                session_count=len(data["sessions"]),
                total_tokens=data["total_tokens"],
                total_cost=data["total_cost"],
                avg_latency_ms=avg_latency,
                models_used=list(data["models"]),
                last_activity=max(timestamps) if timestamps else None,
                error_count=data.get("error_count", 0),
            ))

        # Sort by last activity
        agents.sort(key=lambda a: a.last_activity or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        total_count = len(agents)
        agents = agents[:limit]

        # Build response
        response_data = {
            "agents": agents,
            "total": total_count,
            "truncated": is_truncated,
        }

        # Cache the result, but avoid caching empty date-filter windows to reduce
        # sticky false-empty UI states from intermittent upstream filtering issues.
        should_cache_response = not (
            total_count == 0 and (from_date or to_date)
        )
        if should_cache_response:
            cache_key = f"agents:{user_id}:{from_date}:{to_date}:{limit}:{tz_offset}:{fetch_all}"
            if cache_key not in _AGENTS_CACHE:
                _AGENTS_CACHE[cache_key] = {}
            _AGENTS_CACHE[cache_key]["data"] = response_data
            _AGENTS_CACHE[cache_key]["fetched_trace_count"] = len(raw_traces)
            _update_cache_metadata(cache_key, response_data)

        return AgentListResponse(
            agents=agents,
            total=total_count,
            truncated=is_truncated,
            fetched_trace_count=len(raw_traces),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching agents: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to fetch agents: {str(e)}")


@router.get("/agents/{agent_id}")
async def get_agent_detail(
    agent_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD)")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC")] = None,
) -> AgentDetailResponse:
    """
    Get detailed agent/agent information including sessions and metrics breakdown.
    """
    _clear_request_caches()  # Clear per-request caches at start

    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        user_id = str(current_user.id)

        # Get agent from database to verify it exists and get its name
        from uuid import UUID as PyUUID
        try:
            agent_uuid = PyUUID(agent_id)
            agent_result = await session.exec(
                select(Agent).where(Agent.id == agent_uuid, Agent.user_id == current_user.id)
            )
            agent = agent_result.first()
        except ValueError:
            agent = None

        if not agent:
            raise HTTPException(status_code=404, detail="Agent/Agent not found")

        agent_name = agent.name

        # Build lookup for matching traces
        agents_by_id = {str(agent.id): agent}
        agents_by_name = {agent.name: agent}

        # Parse date filters with timezone correction — MUST use _compute_date_range
        # (not manual UTC parsing) so the window aligns with what project_detail and
        # the agents list show. Manual UTC parsing ignores tz_offset and produces a
        # window up to UTC_offset hours narrower, hiding timezone-boundary traces.
        from_timestamp, to_timestamp = _compute_date_range(
            from_date,
            to_date,
            tz_offset,
            default_days=None,
        )

        # Fetch all traces
        raw_traces = fetch_traces_from_langfuse(
            client, user_id, limit=500,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )

        # Two-pass approach for agent detail
        # Pass 1: Identify this agent's sessions
        agent_sessions: set[str] = set()
        agent_trace_count = 0
        for trace in raw_traces:
            matched_fid, _ = _match_trace_to_agent(trace, agents_by_id, agents_by_name)
            if matched_fid == agent_id:
                agent_trace_count += 1
                session_id = get_attr(trace, 'session_id', 'sessionId')
                if session_id:
                    agent_sessions.add(session_id)

        if agent_trace_count == 0:
            return AgentDetailResponse(
                agent_id=agent_id,
                agent_name=agent_name,
                trace_count=0,
                session_count=0,
                observation_count=0,
                total_tokens=0,
                input_tokens=0,
                output_tokens=0,
                total_cost=0.0,
                avg_latency_ms=None,
                first_activity=None,
                last_activity=None,
                models_used={},
                sessions=[],
                by_date=[],
            )

        # Pass 2: Process ALL traces that belong to this agent's sessions
        total_tokens = 0
        input_tokens = 0
        output_tokens = 0
        total_cost = 0.0
        total_observations = 0
        latencies = []
        models_used: dict[str, dict] = {}
        timestamps = []
        sessions_data: dict[str, dict] = {}
        daily_data: dict[str, dict] = defaultdict(lambda: {
            "trace_count": 0, "observation_count": 0, "total_tokens": 0, "total_cost": 0.0
        })
        processed_traces: set[str] = set()
        # Small observation fallback budget so metrics are accurate without hammering Langfuse.
        _agent_detail_fallback_budget: dict[str, int] = {"remaining": min(10, len(raw_traces) // 5)}

        for trace in raw_traces:
            trace_id = get_attr(trace, 'id')
            if trace_id in processed_traces:
                continue

            session_id = get_attr(trace, 'session_id', 'sessionId')
            timestamp = parse_datetime(get_attr(trace, 'timestamp'))

            # Check if this trace belongs to this agent
            is_agent_trace = False
            matched_fid, _ = _match_trace_to_agent(trace, agents_by_id, agents_by_name)
            if matched_fid == agent_id:
                is_agent_trace = True
            elif session_id and session_id in agent_sessions:
                # Vertex trace in this agent's session
                pass
            else:
                continue  # Not related to this agent

            processed_traces.add(trace_id)

            # Fast path: trace-level metrics (cached — zero extra API calls).
            # Mirrors the fix already applied to session_detail.
            t_metrics = _get_trace_metrics(
                client,
                trace,
                allow_observation_fallback=True,
                fallback_budget=_agent_detail_fallback_budget,
            )
            trace_tokens = int(t_metrics["total_tokens"])
            trace_input_tokens = int(t_metrics["input_tokens"])
            trace_output_tokens = int(t_metrics["output_tokens"])
            trace_cost = float(t_metrics["total_cost"])
            trace_latency = t_metrics["latency_ms"]
            trace_level_models: list[str] = list(t_metrics["models"])
            trace_obs_count = int(t_metrics.get("observation_count") or 0)
            trace_error_count = int(t_metrics.get("error_count") or 0)

            total_tokens += trace_tokens
            input_tokens += trace_input_tokens
            output_tokens += trace_output_tokens
            total_cost += trace_cost
            total_observations += trace_obs_count
            if trace_latency is not None:
                latencies.append(trace_latency)
            for model_name in trace_level_models:
                if model_name not in models_used:
                    models_used[model_name] = {"tokens": 0, "cost": 0.0, "calls": 0}
                models_used[model_name]["tokens"] += trace_tokens
                models_used[model_name]["cost"] += trace_cost
                models_used[model_name]["calls"] += 1

            if timestamp:
                timestamps.append(timestamp)
                # Apply timezone offset if provided
                if tz_offset is not None:
                    local_ts = timestamp + timedelta(minutes=tz_offset)
                    date_str = local_ts.strftime('%Y-%m-%d')
                else:
                    date_str = timestamp.strftime('%Y-%m-%d')
                if is_agent_trace:
                    daily_data[date_str]["trace_count"] += 1
                daily_data[date_str]["observation_count"] += trace_obs_count
                daily_data[date_str]["total_tokens"] += trace_tokens
                daily_data[date_str]["total_cost"] += trace_cost

            # Build session data
            if session_id:
                if session_id not in sessions_data:
                    sessions_data[session_id] = {
                        "session_id": session_id,
                        "trace_count": 0,
                        "total_tokens": 0,
                        "total_cost": 0.0,
                        "timestamps": [],
                        "models": set(),
                        "error_count": 0,
                    }
                if is_agent_trace:
                    sessions_data[session_id]["trace_count"] += 1
                sessions_data[session_id]["total_tokens"] += trace_tokens
                sessions_data[session_id]["total_cost"] += trace_cost
                if timestamp:
                    sessions_data[session_id]["timestamps"].append(timestamp)
                if trace_level_models:
                    sessions_data[session_id]["models"].update(trace_level_models)
                sessions_data[session_id]["error_count"] += trace_error_count

        # Build sessions list
        sessions = []
        for sid, data in sessions_data.items():
            ts = data["timestamps"]
            err_count = int(data.get("error_count", 0))
            sessions.append(SessionListItem(
                session_id=sid,
                trace_count=data["trace_count"],
                total_tokens=data["total_tokens"],
                total_cost=data["total_cost"],
                first_trace_at=min(ts) if ts else None,
                last_trace_at=max(ts) if ts else None,
                models_used=list(data["models"]),
                error_count=err_count,
                has_errors=err_count > 0,
            ))
        sessions.sort(key=lambda s: s.last_trace_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        # Build daily usage
        by_date = []
        for date, data in sorted(daily_data.items()):
            by_date.append(DailyUsageItem(
                date=date,
                trace_count=data["trace_count"],
                observation_count=data["observation_count"],
                total_tokens=data["total_tokens"],
                total_cost=data["total_cost"],
            ))

        avg_latency = sum(latencies) / len(latencies) if latencies else None

        return AgentDetailResponse(
            agent_id=agent_id,
            agent_name=agent_name,
            trace_count=agent_trace_count,
            session_count=len(agent_sessions),
            observation_count=total_observations,
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost=total_cost,
            avg_latency_ms=avg_latency,
            first_activity=min(timestamps) if timestamps else None,
            last_activity=max(timestamps) if timestamps else None,
            models_used=models_used,
            sessions=sessions,
            by_date=by_date,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching agent detail: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to fetch agent: {str(e)}")


# =============================================================================
# Project Endpoints
# =============================================================================

@router.get("/projects")
async def get_user_projects(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _background_tasks: BackgroundTasks,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD)")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC")] = None,
    fetch_all: Annotated[bool, Query(description="Fetch all traces (up to 5000) instead of capped limit")] = False,
) -> ProjectListResponse:
    """
    Get all projects (folders) for the current user with aggregated metrics.

    STALE-WHILE-REVALIDATE CACHING STRATEGY:
    - Fresh cache (<15s old): Return immediately, no refresh
    - Stale cache (15-60s old): Return immediately, trigger background refresh
    - Expired cache (>60s old): Fetch fresh data (blocks briefly)
    """
    _clear_request_caches()  # Clear per-request caches at start

    # Build cache key from stable parameters
    user_id = str(current_user.id)
    cache_key = f"projects:{user_id}:{from_date}:{to_date}:{limit}:{tz_offset}:{fetch_all}"
    
    # Check cache status
    cache_meta = _get_cache_metadata(cache_key)
    
    # Cache checking logic (only if SWR enabled)
    if SWR_CONFIG["ENABLE_SWR"]:
        # === FRESH CACHE: Return immediately, no refresh ===
        if cache_meta["is_fresh"] and cache_key in _PROJECTS_CACHE:
            logger.debug(f"Projects cache HIT (fresh) for {cache_key}, age={cache_meta['age_seconds']}s")
            cached = _PROJECTS_CACHE[cache_key]
            return ProjectListResponse(
                **cached["data"],
                fetched_trace_count=cached.get("fetched_trace_count", 0),
            )
        
        # === STALE CACHE: fetch fresh synchronously ===
        # Background refresh task is not configured for projects cache.
        # Returning stale values here can keep token counts at zero for too long.
        if cache_meta["is_stale"] and cache_key in _PROJECTS_CACHE:
            logger.debug(
                f"Projects cache HIT (stale) for {cache_key}, age={cache_meta['age_seconds']}s; "
                "fetching fresh synchronously"
            )

    # === EXPIRED/MISSING CACHE: Fetch fresh data ===
    logger.debug(f"Projects cache MISS for {cache_key}, fetching fresh data")
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        user_id = str(current_user.id)
        logger.info(f"Fetching projects for user_id: {user_id}")

        from_timestamp, to_timestamp = _compute_date_range(
            from_date,
            to_date,
            tz_offset,
            default_days=None,
        )

        # Get all user folders from database
        folders_result = await session.exec(
            select(Folder).where(Folder.user_id == current_user.id)
        )
        user_folders = folders_result.all()

        # Get all user agents
        agents_result = await session.exec(_user_agents_stmt(current_user.id))
        user_agents = agents_result.all()

        # Build folder lookup and agent-to-folder mapping
        folders_by_id = {str(f.id): f for f in user_folders}
        agent_to_folder: dict[str, str] = {}
        for agent in user_agents:
            if agent.folder_id:
                agent_to_folder[str(agent.id)] = str(agent.folder_id)

        agents_by_id = {str(f.id): f for f in user_agents}
        agents_by_name = {f.name: f for f in user_agents}

        # Fetch all traces
        trace_limit = 500
        raw_traces = fetch_traces_from_langfuse(
            client,
            user_id,
            limit=trace_limit,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            fetch_all=fetch_all,
        )

        is_truncated = (not fetch_all) and len(raw_traces) >= trace_limit

        fallback_budget = _make_fallback_budget(len(raw_traces))

        # Two-pass aggregation to match agent/session semantics:
        # 1) Identify project sessions via agent-level traces
        # 2) Include ALL traces in those sessions (including vertex/component traces)
        session_to_project: dict[str, str] = {}
        projects_data: dict[str, dict] = {}
        processed_traces: set[str] = set()

        # Pass 1: discover project sessions and count project trace_count from agent-level traces
        for trace in raw_traces:
            matched_fid, _ = _match_trace_to_agent(trace, agents_by_id, agents_by_name)
            if not matched_fid:
                continue

            folder_id = agent_to_folder.get(matched_fid)
            if not folder_id:
                continue

            session_id = get_attr(trace, 'session_id', 'sessionId')
            if session_id:
                session_to_project[session_id] = folder_id

            if folder_id not in projects_data:
                folder = folders_by_id.get(folder_id)
                projects_data[folder_id] = {
                    "project_id": folder_id,
                    "project_name": folder.name if folder else None,
                    "agents": set(),
                    "trace_count": 0,
                    "sessions": set(),
                    "total_tokens": 0,
                    "total_cost": 0.0,
                    "timestamps": [],
                }

            projects_data[folder_id]["agents"].add(matched_fid)
            projects_data[folder_id]["trace_count"] += 1

        # Pass 2: aggregate tokens/cost from all traces that belong to discovered project sessions
        for trace in raw_traces:
            trace_id = get_attr(trace, 'id')
            if trace_id in processed_traces:
                continue
            processed_traces.add(trace_id)

            session_id = get_attr(trace, 'session_id', 'sessionId')
            folder_id = session_to_project.get(session_id) if session_id else None
            if not folder_id:
                continue

            timestamp = parse_datetime(get_attr(trace, 'timestamp'))
            trace_metrics = _get_trace_metrics(
                client,
                trace,
                allow_observation_fallback=True,
                fallback_budget=fallback_budget,
            )
            trace_tokens = int(trace_metrics["total_tokens"])
            trace_cost = float(trace_metrics["total_cost"])

            projects_data[folder_id]["total_tokens"] += trace_tokens
            projects_data[folder_id]["total_cost"] += trace_cost
            if session_id:
                projects_data[folder_id]["sessions"].add(session_id)
            if timestamp:
                projects_data[folder_id]["timestamps"].append(timestamp)

        # Build response
        projects = []
        for pid, data in projects_data.items():
            timestamps = data["timestamps"]
            projects.append(ProjectListItem(
                project_id=pid,
                project_name=data["project_name"],
                agent_count=len(data["agents"]),
                trace_count=data["trace_count"],
                session_count=len(data["sessions"]),
                total_tokens=data["total_tokens"],
                total_cost=data["total_cost"],
                last_activity=max(timestamps) if timestamps else None,
            ))

        projects.sort(key=lambda p: p.last_activity or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        total_count = len(projects)
        projects = projects[:limit]

        # Build response
        response_data = {
            "projects": projects,
            "total": total_count,
            "truncated": is_truncated,
        }

        # Cache the result, but avoid caching empty date-filter windows to reduce
        # sticky false-empty UI states from intermittent upstream filtering issues.
        should_cache_response = not (
            total_count == 0 and (from_date or to_date)
        )
        if should_cache_response:
            cache_key = f"projects:{user_id}:{from_date}:{to_date}:{limit}:{tz_offset}:{fetch_all}"
            if cache_key not in _PROJECTS_CACHE:
                _PROJECTS_CACHE[cache_key] = {}
            _PROJECTS_CACHE[cache_key]["data"] = response_data
            _PROJECTS_CACHE[cache_key]["fetched_trace_count"] = len(raw_traces)
            _update_cache_metadata(cache_key, response_data)

        return ProjectListResponse(
            projects=projects,
            total=total_count,
            truncated=is_truncated,
            fetched_trace_count=len(raw_traces),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching projects: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to fetch projects: {str(e)}")


@router.get("/projects/{project_id}")
async def get_project_detail(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD)")] = None,
    tz_offset: Annotated[int | None, Query(description="Timezone offset in minutes from UTC")] = None,
) -> ProjectDetailResponse:
    """
    Get detailed project (folder) information including agents and metrics breakdown.
    """
    _clear_request_caches()  # Clear per-request caches at start

    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        user_id = str(current_user.id)

        # Get folder from database
        from uuid import UUID as PyUUID
        try:
            folder_uuid = PyUUID(project_id)
            folder_result = await session.exec(
                select(Folder).where(Folder.id == folder_uuid, Folder.user_id == current_user.id)
            )
            folder = folder_result.first()
        except ValueError:
            folder = None

        if not folder:
            raise HTTPException(status_code=404, detail="Project not found")

        project_name = folder.name

        # Get agents in this folder
        agents_stmt = _user_agents_stmt(current_user.id).where(Agent.folder_id == folder.id)
        agents_result = await session.exec(agents_stmt)
        folder_agents = agents_result.all()

        agents_by_id = {str(f.id): f for f in folder_agents}
        agents_by_name = {f.name: f for f in folder_agents}

        if not folder_agents:
            return ProjectDetailResponse(
                project_id=project_id,
                project_name=project_name,
                agent_count=0,
                trace_count=0,
                session_count=0,
                observation_count=0,
                total_tokens=0,
                input_tokens=0,
                output_tokens=0,
                total_cost=0.0,
                avg_latency_ms=None,
                first_activity=None,
                last_activity=None,
                models_used={},
                agents=[],
                by_date=[],
            )

        # Parse date filters with timezone awareness
        from_timestamp, to_timestamp = _compute_date_range(
            from_date,
            to_date,
            tz_offset,
            default_days=None,
        )

        # Fetch all traces
        raw_traces = fetch_traces_from_langfuse(client, user_id, limit=100,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )

        # Aggregate metrics
        agents_data: dict[str, dict] = {}
        total_traces = 0
        total_observations = 0
        total_tokens = 0
        input_tokens = 0
        output_tokens = 0
        total_cost = 0.0
        latencies = []
        sessions = set()
        timestamps = []
        models_used: dict[str, dict] = {}
        daily_data: dict[str, dict] = defaultdict(lambda: {
            "trace_count": 0, "observation_count": 0, "total_tokens": 0, "total_cost": 0.0
        })
        fallback_budget: dict[str, int] = {"remaining": min(80, max(10, len(raw_traces) // 4))}

        for trace in raw_traces:
            matched_fid, matched_fname = _match_trace_to_agent(trace, agents_by_id, agents_by_name)
            if not matched_fid:
                continue

            total_traces += 1
            trace_id = get_attr(trace, 'id')
            session_id = get_attr(trace, 'session_id', 'sessionId')
            timestamp = parse_datetime(get_attr(trace, 'timestamp'))

            if session_id:
                sessions.add(session_id)
            if timestamp:
                timestamps.append(timestamp)

            trace_metrics = _get_trace_metrics(
                client,
                trace,
                allow_observation_fallback=True,
                fallback_budget=fallback_budget,
            )
            trace_tokens = int(trace_metrics["total_tokens"])
            trace_input_tokens = int(trace_metrics["input_tokens"])
            trace_output_tokens = int(trace_metrics["output_tokens"])
            trace_cost = float(trace_metrics["total_cost"])
            trace_latency = trace_metrics["latency_ms"]
            trace_obs_count = int(trace_metrics.get("observation_count") or 0)
            trace_models = list(trace_metrics.get("models") or [])

            total_observations += trace_obs_count
            total_tokens += trace_tokens
            input_tokens += trace_input_tokens
            output_tokens += trace_output_tokens
            total_cost += trace_cost
            if trace_latency is not None:
                latencies.append(trace_latency)

            for model_name in trace_models:
                if model_name not in models_used:
                    models_used[model_name] = {"tokens": 0, "cost": 0.0, "calls": 0}
                models_used[model_name]["tokens"] += trace_tokens
                models_used[model_name]["cost"] += trace_cost
                models_used[model_name]["calls"] += 1

            # Per-agent aggregation
            if matched_fid not in agents_data:
                agents_data[matched_fid] = {
                    "agent_id": matched_fid,
                    "agent_name": matched_fname,
                    "trace_count": 0,
                    "sessions": set(),
                    "total_tokens": 0,
                    "total_cost": 0.0,
                    "models": set(),
                    "latencies": [],
                    "timestamps": [],
                }

            agents_data[matched_fid]["trace_count"] += 1
            agents_data[matched_fid]["total_tokens"] += trace_tokens
            agents_data[matched_fid]["total_cost"] += trace_cost
            agents_data[matched_fid]["models"].update(trace_models)
            if trace_latency is not None:
                agents_data[matched_fid]["latencies"].append(trace_latency)
            if session_id:
                agents_data[matched_fid]["sessions"].add(session_id)
            if timestamp:
                agents_data[matched_fid]["timestamps"].append(timestamp)
                # Apply timezone offset if provided
                if tz_offset is not None:
                    local_ts = timestamp + timedelta(minutes=tz_offset)
                    date_str = local_ts.strftime('%Y-%m-%d')
                else:
                    date_str = timestamp.strftime('%Y-%m-%d')
                daily_data[date_str]["trace_count"] += 1
                daily_data[date_str]["observation_count"] += trace_obs_count
                daily_data[date_str]["total_tokens"] += trace_tokens
                daily_data[date_str]["total_cost"] += trace_cost

        # Build agents list
        agents = []
        for fid, data in agents_data.items():
            ts = data["timestamps"]
            lats = data["latencies"]
            avg_lat = sum(lats) / len(lats) if lats else None
            agents.append(AgentListItem(
                agent_id=fid,
                agent_name=data["agent_name"],
                trace_count=data["trace_count"],
                session_count=len(data["sessions"]),
                total_tokens=data["total_tokens"],
                total_cost=data["total_cost"],
                avg_latency_ms=avg_lat,
                models_used=list(data["models"]),
                last_activity=max(ts) if ts else None,
            ))
        agents.sort(key=lambda a: a.last_activity or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        # Build daily usage
        by_date = []
        for date, data in sorted(daily_data.items()):
            by_date.append(DailyUsageItem(
                date=date,
                trace_count=data["trace_count"],
                observation_count=data["observation_count"],
                total_tokens=data["total_tokens"],
                total_cost=data["total_cost"],
            ))

        avg_latency = sum(latencies) / len(latencies) if latencies else None

        return ProjectDetailResponse(
            project_id=project_id,
            project_name=project_name,
            agent_count=len(agents_data),
            trace_count=total_traces,
            session_count=len(sessions),
            observation_count=total_observations,
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost=total_cost,
            avg_latency_ms=avg_latency,
            first_activity=min(timestamps) if timestamps else None,
            last_activity=max(timestamps) if timestamps else None,
            models_used=models_used,
            agents=agents,
            by_date=by_date,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching project detail: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to fetch project: {str(e)}")
