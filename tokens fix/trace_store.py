"""TraceStore: centralised trace fetching, enrichment, and caching.

Implements the "Fetch Once, Aggregate Many" pattern — all endpoints consume
the same cached enriched trace list so data is always consistent across tabs.
"""

import hashlib
import time
import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .parsing import (
    get_attr,
    get_trace_id,
    get_trace_observation_count,
    extract_trace_metrics,
    extract_trace_user_ids,
    parse_datetime,
    normalize_metadata,
    parse_observation,
    fetch_observations_for_trace,
    fetch_trace_by_id,
    observation_cache_key,
    call_with_rate_limit_retry,
    _OBSERVATIONS_CACHE,
    _REQUEST_OBSERVATIONS_CACHE,
)

from loguru import logger

# Cache for full-trace objects fetched during pre-enrichment.
# When the list API lacks token/cost/model data, we fetch individual traces
# and store them here so _build_enriched_traces can use the richer data.
_FULL_TRACE_CACHE: dict[str, Any] = {}

# ---------------------------------------------------------------------------
# EnrichedTrace — the single data structure all endpoints consume
# ---------------------------------------------------------------------------


@dataclass
class EnrichedTrace:
    """Pre-computed trace with all metrics.  No further Langfuse calls needed."""
    id: str
    name: str | None
    session_id: str | None
    user_id: str | None
    timestamp: datetime | None
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    latency_ms: float | None = None
    models: list[str] = field(default_factory=list)
    error_count: int = 0
    observation_count: int = 0
    level: str | None = None
    metadata: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    _raw: Any = field(default=None, repr=False)
    _client_idx: int = 0


# ---------------------------------------------------------------------------
# TraceStore
# ---------------------------------------------------------------------------

@dataclass
class _CacheEntry:
    traces: list[EnrichedTrace]
    truncated: bool
    created_at: float  # time.monotonic()


class TraceStore:
    """Process-level trace store with simple TTL cache.

    Replaces the 8 separate cache dictionaries + SWR infrastructure in the
    monolith with a single cache keyed on (scope_key, date_range, environment).
    """

    _cache: dict[str, _CacheEntry] = {}
    FRESH_TTL = 30.0
    MAX_TTL = 120.0
    MAX_ENTRIES = 50

    @classmethod
    def get_traces(
        cls,
        *,
        clients: list[Any],
        allowed_user_ids: set[str],
        scope_key: str,
        from_timestamp: datetime | None,
        to_timestamp: datetime | None,
        environment: str | None = None,
        search: str | None = None,
        fetch_all: bool = False,
        limit: int = 500,
    ) -> tuple[list[EnrichedTrace], bool]:
        """Return (enriched_traces, is_truncated). Cache hit or fresh fetch + enrich."""
        cache_key = cls._build_key(
            scope_key, from_timestamp, to_timestamp, environment, search, fetch_all, limit,
        )
        now = time.monotonic()

        cached = cls._cache.get(cache_key)
        if cached and (now - cached.created_at) <= cls.FRESH_TTL:
            return cached.traces, cached.truncated

        # Clear per-request full-trace cache
        _FULL_TRACE_CACHE.clear()

        # Fetch raw traces
        raw_traces = _fetch_scoped_traces(
            clients=clients,
            allowed_user_ids=allowed_user_ids,
            limit=limit,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            name=search,
            fetch_all=fetch_all,
            environment=environment,
        )

        is_truncated = (not fetch_all) and len(raw_traces) >= limit

        # Parallel observation enrichment
        _pre_enrich_traces(raw_traces, clients)

        # Build enriched traces
        enriched = _build_enriched_traces(raw_traces, clients)

        # Cache and return
        entry = _CacheEntry(traces=enriched, truncated=is_truncated, created_at=now)
        cls._cache[cache_key] = entry
        cls._evict_old(now)
        return enriched, is_truncated

    @classmethod
    def invalidate(cls) -> None:
        """Clear all cached data."""
        cls._cache.clear()

    @classmethod
    def _build_key(
        cls,
        scope_key: str,
        from_ts: datetime | None,
        to_ts: datetime | None,
        environment: str | None,
        search: str | None,
        fetch_all: bool,
        limit: int,
    ) -> str:
        from_s = from_ts.isoformat() if from_ts else ""
        to_s = to_ts.isoformat() if to_ts else ""
        return f"{scope_key}:{from_s}:{to_s}:{environment or 'all'}:{search or ''}:{int(fetch_all)}:{limit}"

    @classmethod
    def _evict_old(cls, now: float) -> None:
        # Remove expired entries
        expired_keys = [k for k, v in cls._cache.items() if (now - v.created_at) > cls.MAX_TTL]
        for k in expired_keys:
            cls._cache.pop(k, None)
        # Enforce max entries
        if len(cls._cache) > cls.MAX_ENTRIES:
            oldest_key = min(cls._cache, key=lambda k: cls._cache[k].created_at)
            cls._cache.pop(oldest_key, None)


# ---------------------------------------------------------------------------
# Trace fetching from Langfuse
# ---------------------------------------------------------------------------

_TRACE_FETCH_CACHE: dict[str, dict[str, Any]] = {}
_TRACE_CACHE_TTL = 12.0
_TRACE_CACHE_STALE = 90.0


def _scoped_trace_cache_key(
    clients: list[Any],
    allowed_user_ids: set[str],
    from_timestamp: datetime | None,
    to_timestamp: datetime | None,
    name: str | None,
    limit: int,
    fetch_all: bool,
    environment: str | None,
) -> str:
    client_namespaces = sorted(
        str(getattr(c, "_trace_cache_namespace", "") or f"client:{id(c)}")
        for c in clients
    )
    user_hash = hashlib.sha256("|".join(sorted(allowed_user_ids)).encode()).hexdigest()[:12] if allowed_user_ids else "none"
    client_hash = hashlib.sha256("|".join(client_namespaces).encode()).hexdigest()[:12] if client_namespaces else "none"
    from_s = from_timestamp.isoformat() if from_timestamp else ""
    to_s = to_timestamp.isoformat() if to_timestamp else ""
    return f"scoped:{client_hash}:{user_hash}:{environment or 'all'}|{user_hash}|{from_s}|{to_s}|{name or ''}||0|{int(fetch_all)}"


def _response_to_traces(response: Any) -> list[Any]:
    if hasattr(response, "data"):
        return list(response.data or [])
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        return list(response.get("data", []) or [])
    return []


def _trace_quality_score(trace_obj: Any) -> tuple[int, int, int, int]:
    """Rank duplicate trace rows by data richness — higher is better."""
    obs_count = int(get_attr(trace_obj, "observation_count", "observationCount", default=0) or 0)
    total_tokens = int(get_attr(trace_obj, "totalTokens", "total_tokens", default=0) or 0)
    if total_tokens <= 0:
        in_tok = int(get_attr(trace_obj, "inputTokens", "input_tokens", "promptTokens", default=0) or 0)
        out_tok = int(get_attr(trace_obj, "outputTokens", "output_tokens", "completionTokens", default=0) or 0)
        total_tokens = in_tok + out_tok
    total_cost = float(get_attr(trace_obj, "calculated_total_cost", "calculatedTotalCost", "total_cost", "totalCost", default=0) or 0)
    has_io = 1 if (get_attr(trace_obj, "input") is not None or get_attr(trace_obj, "output") is not None) else 0
    return (obs_count, total_tokens, int(total_cost * 1_000_000), has_io)


def _fetch_scoped_traces(
    *,
    clients: list[Any],
    allowed_user_ids: set[str],
    limit: int,
    from_timestamp: datetime | None = None,
    to_timestamp: datetime | None = None,
    name: str | None = None,
    fetch_all: bool = False,
    environment: str | None = None,
) -> list[Any]:
    """Fetch traces from all scoped Langfuse clients, deduplicating by trace id."""
    if not clients or not allowed_user_ids:
        return []

    cache_key = _scoped_trace_cache_key(
        clients, allowed_user_ids, from_timestamp, to_timestamp, name, limit, fetch_all, environment,
    )
    now_mono = time.monotonic()
    cached_entry = _TRACE_FETCH_CACHE.get(cache_key)
    stale_traces: list[Any] = []
    if cached_entry:
        cached_age = now_mono - float(cached_entry.get("ts", 0))
        cached_traces = cached_entry.get("traces", []) or []
        if cached_age <= _TRACE_CACHE_TTL and cached_traces:
            return list(cached_traces)
        if cached_age <= _TRACE_CACHE_STALE and cached_traces:
            stale_traces = list(cached_traces)

    def _attach_client_idx(trace_obj: Any, idx: int) -> Any:
        try:
            setattr(trace_obj, "_agentcore_client_idx", idx)
        except Exception:
            if isinstance(trace_obj, dict):
                trace_obj["_agentcore_client_idx"] = idx
        return trace_obj

    combined: list[Any] = []
    seen_trace_positions: dict[str, int] = {}
    max_users = 200
    scoped_user_ids = sorted(allowed_user_ids)[:max_users]

    per_user_limit = max(100, min(limit, 500))
    if fetch_all:
        per_user_limit = 500

    # For broad admin scopes, use per-client broad fetch
    fanout_call_budget = len(clients) * len(scoped_user_ids)
    use_broad_fetch = fanout_call_budget > 24

    def _fetch_client_traces_broad(client_obj: Any, broad_limit: int) -> list[Any]:
        page_size = min(100, max(1, broad_limit))
        max_pages = max(1, (broad_limit + page_size - 1) // page_size)

        if hasattr(client_obj, "fetch_traces"):
            try:
                rows: list[Any] = []
                for page in range(1, max_pages + 1):
                    kwargs: dict[str, Any] = {"limit": page_size}
                    if from_timestamp:
                        kwargs["from_timestamp"] = from_timestamp
                    if to_timestamp:
                        kwargs["to_timestamp"] = to_timestamp
                    if name:
                        kwargs["name"] = name
                    if environment:
                        kwargs["environment"] = environment
                    resp = client_obj.fetch_traces(**kwargs, page=page)
                    page_rows = _response_to_traces(resp)
                    if not page_rows:
                        break
                    rows.extend(page_rows)
                    if len(rows) >= broad_limit:
                        break
                if rows:
                    return rows[:broad_limit]
            except Exception as exc:
                logger.debug("Broad fetch_traces failed: {}", exc)

        if hasattr(client_obj, "api"):
            api_obj = getattr(client_obj, "api")
            trace_api = getattr(api_obj, "trace", None) or getattr(api_obj, "traces", None)
            if trace_api and hasattr(trace_api, "list"):
                try:
                    rows = []
                    for page in range(1, max_pages + 1):
                        kwargs = {"limit": page_size, "page": page}
                        if from_timestamp:
                            kwargs["from_timestamp"] = from_timestamp
                        if to_timestamp:
                            kwargs["to_timestamp"] = to_timestamp
                        if name:
                            kwargs["name"] = name
                        if environment:
                            kwargs["environment"] = environment
                        resp = trace_api.list(**kwargs)
                        page_rows = _response_to_traces(resp)
                        if not page_rows:
                            break
                        rows.extend(page_rows)
                        if len(rows) >= broad_limit:
                            break
                    if rows:
                        return rows[:broad_limit]
                except Exception as exc:
                    logger.debug("Broad api.trace.list failed: {}", exc)

        return []

    if use_broad_fetch:
        broad_limit = 5000 if fetch_all else min(limit, 500)
        for client_idx, client in enumerate(clients):
            broad_traces = _fetch_client_traces_broad(client, broad_limit)
            for trace in broad_traces:
                extracted_uids = extract_trace_user_ids(trace)
                if extracted_uids and not extracted_uids.intersection(allowed_user_ids):
                    continue
                trace_id = str(get_attr(trace, "id", "trace_id", "traceId", default="") or "")
                if trace_id and trace_id in seen_trace_positions:
                    existing_idx = seen_trace_positions[trace_id]
                    if _trace_quality_score(trace) > _trace_quality_score(combined[existing_idx]):
                        combined[existing_idx] = _attach_client_idx(trace, client_idx)
                    continue
                if trace_id:
                    seen_trace_positions[trace_id] = len(combined)
                combined.append(_attach_client_idx(trace, client_idx))

        if combined:
            _cache_raw_traces(cache_key, combined)
            return combined

    # Per-user fan-out fallback
    for client_idx, client in enumerate(clients):
        for scoped_user_id in scoped_user_ids:
            traces = fetch_traces_from_langfuse(
                client, scoped_user_id,
                limit=per_user_limit,
                from_timestamp=from_timestamp,
                to_timestamp=to_timestamp,
                name=name,
                fetch_all=fetch_all,
                environment=environment,
            )
            for trace in traces:
                trace_id = str(get_attr(trace, "id", "trace_id", "traceId", default="") or "")
                if trace_id and trace_id in seen_trace_positions:
                    existing_idx = seen_trace_positions[trace_id]
                    if _trace_quality_score(trace) > _trace_quality_score(combined[existing_idx]):
                        combined[existing_idx] = _attach_client_idx(trace, client_idx)
                    continue
                if trace_id:
                    seen_trace_positions[trace_id] = len(combined)
                combined.append(_attach_client_idx(trace, client_idx))

    if combined:
        _cache_raw_traces(cache_key, combined)
        return combined

    if stale_traces:
        return stale_traces
    return combined


def fetch_traces_from_langfuse(
    client: Any,
    user_id: str,
    limit: int = 50,
    from_timestamp: datetime | None = None,
    to_timestamp: datetime | None = None,
    name: str | None = None,
    tags: list[str] | None = None,
    session_id: str | None = None,
    fetch_all: bool = False,
    _date_fallback_depth: int = 0,
    environment: str | None = None,
) -> list[Any]:
    """Fetch traces for a single user id from one client.

    The `tags`, `session_id`, and `_date_fallback_depth` parameters are
    accepted for backward compatibility but currently unused by the new
    trace-store pipeline.
    """
    effective_limit = 5000 if fetch_all else limit
    page_size = min(100, effective_limit)

    if hasattr(client, "fetch_traces"):
        try:
            all_traces: list[Any] = []
            max_pages = (effective_limit + page_size - 1) // page_size
            filter_kwargs: dict[str, Any] = {"user_id": user_id, "limit": page_size}
            if from_timestamp:
                filter_kwargs["from_timestamp"] = from_timestamp
            if to_timestamp:
                filter_kwargs["to_timestamp"] = to_timestamp
            if name:
                filter_kwargs["name"] = name
            if environment:
                filter_kwargs["environment"] = environment

            for page in range(1, max_pages + 1):
                response = call_with_rate_limit_retry(client.fetch_traces, **filter_kwargs, page=page)
                page_traces = _response_to_traces(response)
                if not page_traces:
                    break
                all_traces.extend(page_traces)

            if all_traces:
                return all_traces
        except Exception:
            pass

    # v3 fallback
    if hasattr(client, "api"):
        api_obj = getattr(client, "api")
        trace_api = getattr(api_obj, "trace", None) or getattr(api_obj, "traces", None)
        if trace_api and hasattr(trace_api, "list"):
            try:
                all_traces = []
                max_pages = (effective_limit + page_size - 1) // page_size
                for page in range(1, max_pages + 1):
                    kwargs: dict[str, Any] = {"user_id": user_id, "limit": page_size, "page": page}
                    if from_timestamp:
                        kwargs["from_timestamp"] = from_timestamp
                    if to_timestamp:
                        kwargs["to_timestamp"] = to_timestamp
                    if name:
                        kwargs["name"] = name
                    if environment:
                        kwargs["environment"] = environment
                    try:
                        response = call_with_rate_limit_retry(trace_api.list, **kwargs)
                    except TypeError:
                        break
                    page_traces = _response_to_traces(response)
                    if not page_traces:
                        break
                    all_traces.extend(page_traces)
                if all_traces:
                    filtered = [t for t in all_traces if str(user_id) in extract_trace_user_ids(t)]
                    return filtered if filtered else all_traces
            except Exception:
                pass

    return []


def _cache_raw_traces(cache_key: str, traces: list[Any]) -> None:
    _TRACE_FETCH_CACHE[cache_key] = {"ts": time.monotonic(), "traces": traces}
    if len(_TRACE_FETCH_CACHE) > 256:
        oldest_key = min(_TRACE_FETCH_CACHE.items(), key=lambda item: float(item[1].get("ts", 0)))[0]
        _TRACE_FETCH_CACHE.pop(oldest_key, None)


# ---------------------------------------------------------------------------
# Parallel observation pre-enrichment
# ---------------------------------------------------------------------------

def _pre_enrich_traces(
    traces: list[Any],
    scoped_clients: list[Any],
    *,
    max_workers: int = 25,
    max_enrichments: int = 300,
) -> None:
    """Pre-fetch observations in parallel for traces that lack trace-level token data."""
    if not traces or not scoped_clients:
        return
    primary_client = scoped_clients[0]

    needs_enrichment: list[tuple[str, Any]] = []
    for trace in traces:
        trace_id = get_trace_id(trace)
        if not trace_id:
            continue
        trace_client = _resolve_trace_client(trace, scoped_clients) or primary_client

        # Already cached?
        obs_key = observation_cache_key(trace_client, trace_id)
        if obs_key in _REQUEST_OBSERVATIONS_CACHE or trace_id in _REQUEST_OBSERVATIONS_CACHE:
            continue

        # Trace-level data already present? Only skip if tokens AND models are available.
        # Cost alone is not enough — Langfuse list API often returns cost but not tokens/models.
        tot, _, _, cost, _, mods, _ = extract_trace_metrics(trace)
        if tot > 0 and mods:
            continue

        needs_enrichment.append((trace_id, trace_client))

    if not needs_enrichment:
        logger.debug("pre_enrich: all {} traces already have trace-level data or are cached", len(traces))
        return

    if len(needs_enrichment) > max_enrichments:
        logger.info("pre_enrich: capping enrichment from {} to {} traces", len(needs_enrichment), max_enrichments)
        needs_enrichment = needs_enrichment[:max_enrichments]

    logger.info("pre_enrich: {}/{} traces need observation enrichment", len(needs_enrichment), len(traces))

    success_count = 0
    empty_count = 0
    error_count = 0

    def _fetch_one(args: tuple[str, Any]) -> str:
        """Returns 'ok', 'empty', or 'error'."""
        tid, client = args
        try:
            obs = fetch_observations_for_trace(client, tid)
            if not obs and len(scoped_clients) > 1:
                primary_key = observation_cache_key(client, tid)
                for fb_client in scoped_clients:
                    if fb_client is client:
                        continue
                    obs = fetch_observations_for_trace(fb_client, tid)
                    if obs:
                        _OBSERVATIONS_CACHE[primary_key] = {"ts": time.monotonic(), "observations": obs}
                        _REQUEST_OBSERVATIONS_CACHE[primary_key] = list(obs)
                        break
            # If still empty, try fetch_trace_by_id as last resort
            if not obs:
                try:
                    trace_obj = fetch_trace_by_id(client, tid)
                    if trace_obj:
                        embedded = get_attr(trace_obj, "observations", default=[])
                        if isinstance(embedded, (list, tuple)) and embedded:
                            obs = list(embedded)
                            obs_key = observation_cache_key(client, tid)
                            _OBSERVATIONS_CACHE[obs_key] = {"ts": time.monotonic(), "observations": obs}
                            _REQUEST_OBSERVATIONS_CACHE[obs_key] = list(obs)
                        else:
                            # Store the full trace — it may have usage_details/cost_details
                            # that the list API doesn't return
                            _FULL_TRACE_CACHE[tid] = trace_obj
                            # Check if this full trace has metrics the list version didn't
                            ft_tok, _, _, ft_cost, _, ft_models, _ = extract_trace_metrics(trace_obj)
                            if ft_tok > 0 or ft_cost > 0.0 or ft_models:
                                logger.debug("pre_enrich: full trace {} has metrics (tokens={}, cost={:.4f}, models={})",
                                             tid[:8], ft_tok, ft_cost, ft_models)
                                return "ok"
                except Exception:
                    pass
            return "ok" if obs else "empty"
        except Exception as exc:
            logger.debug("pre_enrich: failed to fetch observations for trace {}: {}", tid, exc)
            return "error"

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(needs_enrichment))) as pool:
        results = list(pool.map(_fetch_one, needs_enrichment))
        success_count = sum(1 for r in results if r == "ok")
        empty_count = sum(1 for r in results if r == "empty")
        error_count = sum(1 for r in results if r == "error")

    logger.info(
        "pre_enrich: completed — {} ok, {} empty, {} errors (out of {})",
        success_count, empty_count, error_count, len(needs_enrichment),
    )


# ---------------------------------------------------------------------------
# Build enriched traces from raw Langfuse traces
# ---------------------------------------------------------------------------

def _resolve_trace_client(trace: Any, clients: list[Any]) -> Any | None:
    if not clients:
        return None
    idx = get_attr(trace, "_agentcore_client_idx", default=None)
    try:
        idx_int = int(idx)
    except (TypeError, ValueError):
        idx_int = None
    if idx_int is not None and 0 <= idx_int < len(clients):
        return clients[idx_int]
    return clients[0]


def get_trace_metrics(
    client: Any,
    trace: Any,
    *,
    allow_observation_fallback: bool = True,
    fallback_budget: dict[str, int] | None = None,
    all_clients: list[Any] | None = None,
) -> dict[str, Any]:
    """Get trace metrics with smart observation fallback.

    Reads trace-level fields first. Only falls back to observations when
    trace-level data is COMPLETELY missing (zero tokens AND zero cost AND no
    models) and fallback_budget has remaining calls.
    """
    from .parsing import _REQUEST_METRICS_CACHE, _OBSERVATIONS_CACHE, _OBSERVATIONS_CACHE_TTL_SECONDS

    trace_id = get_trace_id(trace)
    now_mono = time.monotonic()

    # Extract from trace-level fields
    (total_tokens, input_tokens, output_tokens, total_cost, latency_ms, models, error_count) = extract_trace_metrics(trace)
    observation_count = get_trace_observation_count(trace)

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

    # Determine if observation fallback is needed.
    # Langfuse list API often returns cost but NOT tokens/models, so we must
    # fall back to observations whenever tokens or models are missing.
    needs_fallback = (
        allow_observation_fallback
        and bool(trace_id)
        and (metrics["total_tokens"] == 0 or not metrics["models"])
    )

    if not needs_fallback:
        logger.debug("get_trace_metrics: trace {} has full data (tokens={}, cost={:.4f}, models={})",
                     trace_id, metrics["total_tokens"], metrics["total_cost"], metrics["models"])
        return metrics

    logger.debug("get_trace_metrics: trace {} needs observation fallback (tokens={}, cost={:.4f}, models={})",
                 trace_id, metrics["total_tokens"], metrics["total_cost"], metrics["models"])

    # Check observation cache first (don't count cache hits against budget)
    _tid_s = str(trace_id) if trace_id else ""
    _obs_key = observation_cache_key(client, _tid_s) if _tid_s else ""
    _obs_in_cache = bool(_tid_s) and (
        _obs_key in _REQUEST_OBSERVATIONS_CACHE
        or _tid_s in _REQUEST_OBSERVATIONS_CACHE
        or bool(
            (_OBSERVATIONS_CACHE.get(_obs_key) or _OBSERVATIONS_CACHE.get(_tid_s))
            and (now_mono - float((_OBSERVATIONS_CACHE.get(_obs_key) or _OBSERVATIONS_CACHE.get(_tid_s) or {}).get("ts", 0))) <= _OBSERVATIONS_CACHE_TTL_SECONDS
        )
    )

    if not _obs_in_cache and fallback_budget is not None and fallback_budget.get("remaining", 0) <= 0:
        return metrics

    if trace_id:
        if fallback_budget is not None and not _obs_in_cache:
            fallback_budget["remaining"] = max(0, fallback_budget.get("remaining", 0) - 1)
        try:
            if all_clients and len(all_clients) > 1:
                raw_obs = _fetch_observations_with_fallback(client, all_clients, trace_id)
            else:
                raw_obs = fetch_observations_for_trace(client, trace_id)
            parsed_obs = [parse_observation(o) for o in raw_obs]
            if parsed_obs:
                obs_total = sum(o.total_tokens for o in parsed_obs)
                if obs_total > 0 or metrics["total_tokens"] == 0:
                    if metrics["total_tokens"] == 0:
                        metrics["total_tokens"] = int(sum(o.total_tokens for o in parsed_obs))
                    if metrics["input_tokens"] == 0 and metrics["output_tokens"] == 0:
                        metrics["input_tokens"] = int(sum(o.input_tokens for o in parsed_obs))
                        metrics["output_tokens"] = int(sum(o.output_tokens for o in parsed_obs))
                    if metrics["total_cost"] == 0.0:
                        metrics["total_cost"] = float(sum(o.total_cost for o in parsed_obs))
                    if metrics["latency_ms"] is None:
                        obs_latencies = [o.latency_ms for o in parsed_obs if o.latency_ms is not None]
                        if obs_latencies:
                            metrics["latency_ms"] = max(obs_latencies)
                    if not metrics["models"]:
                        metrics["models"] = list(dict.fromkeys(o.model for o in parsed_obs if o.model))
                    metrics["error_count"] = max(
                        metrics["error_count"],
                        sum(1 for o in parsed_obs if (o.level or "").upper() in {"ERROR", "WARNING"}),
                    )
                    metrics["observation_count"] = max(metrics["observation_count"], len(parsed_obs))
        except Exception:
            pass

    return metrics


def _fetch_observations_with_fallback(primary_client: Any, all_clients: list[Any], trace_id: str) -> list:
    """Fetch observations trying primary_client first, then other clients."""
    obs = fetch_observations_for_trace(primary_client, trace_id)
    if obs:
        return obs
    primary_key = observation_cache_key(primary_client, trace_id)
    for fb_client in all_clients:
        if fb_client is primary_client:
            continue
        obs = fetch_observations_for_trace(fb_client, trace_id)
        if obs:
            _OBSERVATIONS_CACHE[primary_key] = {"ts": time.monotonic(), "observations": obs}
            _REQUEST_OBSERVATIONS_CACHE[primary_key] = list(obs)
            return obs
    return []


def _build_enriched_traces(raw_traces: list[Any], clients: list[Any]) -> list[EnrichedTrace]:
    """Convert raw Langfuse trace objects into enriched traces."""
    enriched: list[EnrichedTrace] = []
    budget: dict[str, int] = {"remaining": min(500, max(100, len(raw_traces) * 2))}

    for trace in raw_traces:
        trace_id = get_trace_id(trace)
        if not trace_id:
            continue

        # If a richer full-trace was fetched during pre-enrichment, use it
        # for metric extraction instead of the list-API trace object
        effective_trace = _FULL_TRACE_CACHE.get(trace_id, trace)

        trace_client = _resolve_trace_client(trace, clients) or (clients[0] if clients else None)
        metrics = get_trace_metrics(
            trace_client, effective_trace,
            allow_observation_fallback=True,
            fallback_budget=budget,
            all_clients=clients,
        )

        user_ids = extract_trace_user_ids(trace)
        user_id = next(iter(user_ids), None)

        idx = get_attr(trace, "_agentcore_client_idx", default=0)
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = 0

        # Prefer our own UTC timestamp from trace metadata over Langfuse's
        # trace timestamp, which can be timezone-inconsistent across traces
        # (some arrive as UTC, others as server-local time without tz info).
        trace_metadata_raw = normalize_metadata(get_attr(trace, "metadata", "meta"))
        our_utc_ts = parse_datetime(trace_metadata_raw.get("trace_created_at_utc"))
        langfuse_ts = parse_datetime(get_attr(trace, "timestamp"))
        final_ts = our_utc_ts or langfuse_ts

        enriched.append(EnrichedTrace(
            id=trace_id,
            name=get_attr(trace, "name"),
            session_id=get_attr(trace, "session_id", "sessionId"),
            user_id=user_id,
            timestamp=final_ts,
            total_tokens=int(metrics["total_tokens"]),
            input_tokens=int(metrics["input_tokens"]),
            output_tokens=int(metrics["output_tokens"]),
            total_cost=float(metrics["total_cost"]),
            latency_ms=metrics["latency_ms"],
            models=list(metrics["models"]),
            error_count=int(metrics["error_count"]),
            observation_count=int(metrics["observation_count"] or 0),
            level=get_attr(trace, "level"),
            metadata=trace_metadata_raw,
            tags=get_attr(trace, "tags", default=[]) or [],
            _raw=trace,
            _client_idx=idx,
        ))

    with_tokens = sum(1 for t in enriched if t.total_tokens > 0)
    with_cost = sum(1 for t in enriched if t.total_cost > 0.0)
    with_models = sum(1 for t in enriched if t.models)
    logger.info(
        "build_enriched: {} traces — {} with tokens, {} with cost, {} with models (budget remaining: {})",
        len(enriched), with_tokens, with_cost, with_models, budget["remaining"],
    )
    return enriched
