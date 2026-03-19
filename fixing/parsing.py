"""Parsing helpers for Langfuse trace/observation payloads.

Provides attribute extraction, datetime parsing, metric extraction from
trace-level fields, observation parsing, and observation fetching with
multi-tier caching.
"""

import json
import time
import random
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from .langfuse_client import is_v3_client
from .models import ObservationResponse

# ---------------------------------------------------------------------------
# Process-local observation caches
# ---------------------------------------------------------------------------
_OBSERVATIONS_CACHE: dict[str, dict[str, Any]] = {}
_OBSERVATIONS_CACHE_TTL_SECONDS = 60.0

# Request-scoped caches (cleared per API request)
_REQUEST_OBSERVATIONS_CACHE: dict[str, list] = {}
_REQUEST_METRICS_CACHE: dict[str, dict[str, Any]] = {}


def clear_request_caches() -> None:
    """Clear per-request caches (call once per API request)."""
    _REQUEST_OBSERVATIONS_CACHE.clear()
    _REQUEST_METRICS_CACHE.clear()


# ---------------------------------------------------------------------------
# Attribute helpers
# ---------------------------------------------------------------------------

def get_attr(obj: Any, *attrs: str, default: Any = None) -> Any:
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


def _enum_str(val: Any) -> str | None:
    """Convert a potentially-enum value to a plain string."""
    if val is None:
        return None
    if hasattr(val, "value"):
        return str(val.value)
    return str(val)


def parse_datetime(value: Any) -> datetime | None:
    """Parse datetime from various formats (always returns UTC-aware)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            return None
    return None


def calculate_latency_ms(start_time: Any, end_time: Any) -> float | None:
    """Calculate latency in milliseconds between two timestamps."""
    start = parse_datetime(start_time)
    end = parse_datetime(end_time)
    if start and end:
        return (end - start).total_seconds() * 1000
    return None


def normalize_metadata(metadata: Any) -> dict[str, Any]:
    """Normalize metadata into a dictionary."""
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


def compute_date_range(
    from_date: str | None,
    to_date: str | None,
    tz_offset: int | None,
    default_days: int | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Compute UTC date range from local date inputs with optional timezone offset."""
    from datetime import timedelta

    now_utc = datetime.now(timezone.utc)

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

        return local_from - timedelta(minutes=tz_offset), local_to - timedelta(minutes=tz_offset)

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


# ---------------------------------------------------------------------------
# Trace-level metric extraction
# ---------------------------------------------------------------------------

def extract_trace_user_ids(trace_obj: Any) -> set[str]:
    """Extract all possible user-id candidates from a trace."""
    user_ids: set[str] = set()

    direct_user = get_attr(trace_obj, "user_id", "userId", "sender", "user")
    if direct_user:
        user_ids.add(str(direct_user))

    metadata = normalize_metadata(get_attr(trace_obj, "metadata", "meta"))
    for key in ("user_id", "userId", "app_user_id", "created_by_user_id", "owner_user_id"):
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


def get_trace_id(trace: Any) -> str:
    return str(get_attr(trace, "id", "trace_id", "traceId", default="") or "")


def get_trace_observation_count(trace: Any) -> int:
    return int(get_attr(trace, "observation_count", "observationCount", default=0) or 0)


def extract_trace_metrics(trace: Any) -> tuple[int, int, int, float, float | None, list[str], int]:
    """Read aggregate metrics from trace-level fields without N+1 observation calls.

    Returns: (total_tokens, input_tokens, output_tokens, total_cost, latency_ms, models, error_count)
    """
    total_tokens = int(get_attr(trace, "totalTokens", "total_tokens", default=0) or 0)
    input_tokens = int(get_attr(trace, "inputTokens", "input_tokens", "promptTokens", default=0) or 0)
    output_tokens = int(get_attr(trace, "outputTokens", "output_tokens", "completionTokens", default=0) or 0)

    # Langfuse v3: usage_details
    usage_details = get_attr(trace, "usage_details", "usageDetails", default={}) or {}
    if not (input_tokens or output_tokens or total_tokens) and usage_details:
        if isinstance(usage_details, dict):
            input_tokens = int(usage_details.get("input", 0) or 0)
            output_tokens = int(usage_details.get("output", 0) or 0)
            total_tokens = int(usage_details.get("total", 0) or (input_tokens + output_tokens))
        elif hasattr(usage_details, "input"):
            input_tokens = int(getattr(usage_details, "input", 0) or 0)
            output_tokens = int(getattr(usage_details, "output", 0) or 0)
            total_tokens = int(getattr(usage_details, "total", 0) or (input_tokens + output_tokens))

    if not total_tokens and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    if total_tokens and input_tokens == 0 and output_tokens == 0:
        input_tokens = total_tokens

    total_cost = float(
        get_attr(trace, "calculated_total_cost", "calculatedTotalCost", "total_cost", "totalCost", default=0) or 0
    )

    # Langfuse v3: cost_details
    if total_cost == 0.0:
        cost_details = get_attr(trace, "cost_details", "costDetails", default={}) or {}
        if isinstance(cost_details, dict):
            total_cost = float(cost_details.get("total", 0) or 0)
            if total_cost == 0.0:
                total_cost = float(cost_details.get("input", 0) or 0) + float(cost_details.get("output", 0) or 0)

    # Latency
    latency_ms: float | None = None
    _latency_raw_ms = get_attr(trace, "latency_ms", "latencyMs", default=None)
    if _latency_raw_ms is not None:
        try:
            latency_ms = float(_latency_raw_ms)
        except (TypeError, ValueError):
            pass
    if latency_ms is None:
        _latency_secs = get_attr(trace, "latency", default=None)
        if _latency_secs is not None:
            try:
                latency_ms = float(_latency_secs) * 1000.0
            except (TypeError, ValueError):
                pass

    # Metadata-based usage fallback
    metadata = normalize_metadata(get_attr(trace, "metadata", "meta"))
    usage_from_metadata = metadata.get("agentcore_usage") or metadata.get("usage") or {}
    if isinstance(usage_from_metadata, str):
        usage_from_metadata = normalize_metadata(usage_from_metadata)

    if not (input_tokens or output_tokens or total_tokens) and isinstance(usage_from_metadata, dict):
        input_tokens = int(
            usage_from_metadata.get("input_tokens") or usage_from_metadata.get("input")
            or usage_from_metadata.get("prompt_tokens") or usage_from_metadata.get("prompt") or 0
        )
        output_tokens = int(
            usage_from_metadata.get("output_tokens") or usage_from_metadata.get("output")
            or usage_from_metadata.get("completion_tokens") or usage_from_metadata.get("completion") or 0
        )
        total_tokens = int(
            usage_from_metadata.get("total_tokens") or usage_from_metadata.get("total")
            or (input_tokens + output_tokens)
        )

    # Models
    models: list[str] = []
    model_candidates = [
        get_attr(trace, "model"),
        get_attr(trace, "model_name", "modelName"),
        metadata.get("model"),
        metadata.get("model_name"),
        metadata.get("generation_model"),
        metadata.get("provider_model"),
        usage_from_metadata.get("model") if isinstance(usage_from_metadata, dict) else None,
        usage_from_metadata.get("model_name") if isinstance(usage_from_metadata, dict) else None,
    ]
    for candidate in model_candidates:
        if candidate:
            value = str(candidate)
            if value not in models:
                models.append(value)

    level = str(get_attr(trace, "level", default="") or "").upper()
    error_count = 1 if level in {"ERROR", "WARNING"} else 0
    return total_tokens, input_tokens, output_tokens, total_cost, latency_ms, models, error_count


# ---------------------------------------------------------------------------
# Observation parsing
# ---------------------------------------------------------------------------

def parse_observation(obs: Any) -> ObservationResponse:
    """Parse a Langfuse observation into our response model."""
    obs_id = get_attr(obs, "id", default="")
    trace_id = get_attr(obs, "trace_id", "traceId", default="")

    start_time = parse_datetime(get_attr(obs, "start_time", "startTime"))
    end_time = parse_datetime(get_attr(obs, "end_time", "endTime"))
    completion_start = parse_datetime(get_attr(obs, "completion_start_time", "completionStartTime"))

    latency_ms = calculate_latency_ms(start_time, end_time)
    ttft_ms = calculate_latency_ms(start_time, completion_start) if completion_start else None

    metadata = normalize_metadata(get_attr(obs, "metadata", "meta", default={}) or {})
    obs_output = get_attr(obs, "output")
    output_dict = obs_output if isinstance(obs_output, dict) else {}

    # --- Token extraction (multi-source) ---
    usage = get_attr(obs, "usage", default={})
    usage_details = get_attr(obs, "usage_details", "usageDetails", default={}) or {}

    if isinstance(usage, dict):
        input_tokens = usage.get("input") or usage.get("inputTokens") or usage.get("prompt_tokens") or 0
        output_tokens = usage.get("output") or usage.get("outputTokens") or usage.get("completion_tokens") or 0
        total_tokens = usage.get("total") or usage.get("totalTokens") or (input_tokens + output_tokens)
    elif hasattr(usage, "input"):
        input_tokens = usage.input or 0
        output_tokens = getattr(usage, "output", 0) or 0
        total_tokens = getattr(usage, "total", 0) or (input_tokens + output_tokens)
    else:
        input_tokens = get_attr(obs, "input_tokens", "inputTokens", "promptTokens", default=0)
        output_tokens = get_attr(obs, "output_tokens", "outputTokens", "completionTokens", default=0)
        total_tokens = input_tokens + output_tokens

    # Langfuse v3: usage_details
    if not (input_tokens or output_tokens or total_tokens) and usage_details:
        if isinstance(usage_details, dict):
            input_tokens = int(
                usage_details.get("input", 0) or usage_details.get("input_tokens", 0)
                or usage_details.get("prompt", 0) or usage_details.get("prompt_tokens", 0) or 0
            )
            output_tokens = int(
                usage_details.get("output", 0) or usage_details.get("output_tokens", 0)
                or usage_details.get("completion", 0) or usage_details.get("completion_tokens", 0) or 0
            )
            total_tokens = int(
                usage_details.get("total", 0) or usage_details.get("total_tokens", 0) or (input_tokens + output_tokens)
            )
        elif hasattr(usage_details, "input"):
            input_tokens = int(getattr(usage_details, "input", 0) or 0)
            output_tokens = int(getattr(usage_details, "output", 0) or 0)
            total_tokens = int(getattr(usage_details, "total", 0) or (input_tokens + output_tokens))

    # Agentcore metadata fallback
    usage_from_metadata = metadata.get("agentcore_usage")
    if isinstance(usage_from_metadata, str):
        usage_from_metadata = normalize_metadata(usage_from_metadata)
    if not isinstance(usage_from_metadata, dict):
        usage_from_metadata = {}
    if not usage_from_metadata and isinstance(metadata.get("usage"), dict):
        usage_from_metadata = metadata.get("usage") or {}

    if not (input_tokens or output_tokens or total_tokens) and usage_from_metadata:
        input_tokens = int(
            usage_from_metadata.get("input_tokens") or usage_from_metadata.get("inputTokens")
            or usage_from_metadata.get("prompt_tokens") or usage_from_metadata.get("input") or 0
        )
        output_tokens = int(
            usage_from_metadata.get("output_tokens") or usage_from_metadata.get("outputTokens")
            or usage_from_metadata.get("completion_tokens") or usage_from_metadata.get("output") or 0
        )
        total_tokens = int(
            usage_from_metadata.get("total_tokens") or usage_from_metadata.get("totalTokens")
            or usage_from_metadata.get("total") or (input_tokens + output_tokens)
        )

    # Output-embedded usage (LangChain/model-service style)
    output_usage = output_dict.get("usage") or output_dict.get("token_usage") or output_dict.get("usage_metadata") or {}
    if isinstance(output_usage, str):
        output_usage = normalize_metadata(output_usage)
    if not (input_tokens or output_tokens or total_tokens) and isinstance(output_usage, dict):
        input_tokens = int(
            output_usage.get("input") or output_usage.get("input_tokens")
            or output_usage.get("prompt_tokens") or output_usage.get("prompt") or 0
        )
        output_tokens = int(
            output_usage.get("output") or output_usage.get("output_tokens")
            or output_usage.get("completion_tokens") or output_usage.get("completion") or 0
        )
        total_tokens = int(
            output_usage.get("total") or output_usage.get("total_tokens") or (input_tokens + output_tokens)
        )

    # --- Cost extraction ---
    cost_details = get_attr(obs, "cost_details", "costDetails", default={}) or {}
    input_cost = float(get_attr(obs, "calculated_input_cost", "calculatedInputCost", "input_cost", "inputCost", default=0) or 0)
    output_cost = float(get_attr(obs, "calculated_output_cost", "calculatedOutputCost", "output_cost", "outputCost", default=0) or 0)
    total_cost = float(get_attr(obs, "calculated_total_cost", "calculatedTotalCost", "total_cost", "totalCost", default=0) or 0)
    if not total_cost and (input_cost or output_cost):
        total_cost = input_cost + output_cost

    if not (input_cost or output_cost or total_cost) and cost_details:
        if isinstance(cost_details, dict):
            input_cost = float(cost_details.get("input", 0) or cost_details.get("input_cost", 0) or cost_details.get("prompt", 0) or 0)
            output_cost = float(cost_details.get("output", 0) or cost_details.get("output_cost", 0) or cost_details.get("completion", 0) or 0)
            total_cost = float(cost_details.get("total", 0) or cost_details.get("total_cost", 0) or 0)
            if not total_cost and (input_cost or output_cost):
                total_cost = input_cost + output_cost

    if total_cost == 0.0:
        md_cost = metadata.get("total_cost") or metadata.get("cost") or output_dict.get("total_cost") or output_dict.get("cost")
        try:
            if md_cost is not None:
                total_cost = float(md_cost)
        except (TypeError, ValueError):
            pass

    # --- Model ---
    model = get_attr(obs, "model")
    if not model and usage_from_metadata:
        model = usage_from_metadata.get("model") or usage_from_metadata.get("model_name") or usage_from_metadata.get("generation_model")
    if not model:
        model = metadata.get("model") or metadata.get("model_name") or metadata.get("provider_model") or output_dict.get("model") or output_dict.get("model_name")

    return ObservationResponse(
        id=str(obs_id),
        trace_id=str(trace_id),
        name=get_attr(obs, "name"),
        type=_enum_str(get_attr(obs, "type")),
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
        input=get_attr(obs, "input"),
        output=get_attr(obs, "output"),
        metadata=metadata,
        level=_enum_str(get_attr(obs, "level")),
        status_message=get_attr(obs, "status_message", "statusMessage"),
        parent_observation_id=get_attr(obs, "parent_observation_id", "parentObservationId"),
    )


# ---------------------------------------------------------------------------
# Rate-limit retry helper
# ---------------------------------------------------------------------------

def _is_rate_limited_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "too many requests" in text


def call_with_rate_limit_retry(method: Any, *args: Any, **kwargs: Any) -> Any:
    """Call Langfuse SDK method with bounded retry on 429 responses."""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return method(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if not _is_rate_limited_error(exc) or attempt >= 2:
                raise
            backoff = min(1.5, (0.2 * (2 ** attempt)) + random.uniform(0.0, 0.1))
            logger.debug("Langfuse rate-limited; retrying in {:.2f}s", backoff)
            time.sleep(backoff)
    if last_exc is not None:
        raise last_exc
    return None


# ---------------------------------------------------------------------------
# Cache key helpers
# ---------------------------------------------------------------------------

def observation_cache_key(client: Any | None, trace_id: str) -> str:
    """Build a cache key scoped to client/binding + trace id."""
    namespace = "default"
    if client is not None:
        namespace = str(
            get_attr(client, "_trace_cache_namespace", "_agentcore_binding_id", "host", "_host", "base_url", "_base_url", default="default") or "default"
        )
    return f"{namespace}:{trace_id}"


# ---------------------------------------------------------------------------
# Observation fetching (three-tier cache: request → process → API)
# ---------------------------------------------------------------------------

def _cache_and_return_observations(trace_id: str, observations: list, cache_key: str | None = None) -> list:
    """Store observations in the process-local cache then return them."""
    key = cache_key or trace_id
    _OBSERVATIONS_CACHE[key] = {"ts": time.monotonic(), "observations": observations}
    if len(_OBSERVATIONS_CACHE) > 512:
        oldest_key = min(_OBSERVATIONS_CACHE.items(), key=lambda item: float(item[1].get("ts", 0)))[0]
        _OBSERVATIONS_CACHE.pop(oldest_key, None)
    return observations


def fetch_observations_for_trace(client: Any, trace_id: str) -> list:
    """Fetch observations (spans) for a specific trace with three-tier cache."""
    trace_id_str = str(trace_id)
    obs_cache_key = observation_cache_key(client, trace_id_str)

    # Tier 1: Request-scoped cache
    if obs_cache_key in _REQUEST_OBSERVATIONS_CACHE:
        return list(_REQUEST_OBSERVATIONS_CACHE[obs_cache_key])
    if trace_id_str in _REQUEST_OBSERVATIONS_CACHE:
        return list(_REQUEST_OBSERVATIONS_CACHE[trace_id_str])

    # Tier 2: Process-local cache
    _now_mono = time.monotonic()
    _obs_cached = _OBSERVATIONS_CACHE.get(obs_cache_key) or _OBSERVATIONS_CACHE.get(trace_id_str)
    if _obs_cached and (_now_mono - float(_obs_cached.get("ts", 0))) <= _OBSERVATIONS_CACHE_TTL_SECONDS:
        result = list(_obs_cached.get("observations", []))
        _REQUEST_OBSERVATIONS_CACHE[obs_cache_key] = result
        return result

    # Tier 3: Langfuse API
    observations: list = []

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
        tid = str(trace_id)
        normalized_variants = [tid]
        if "-" in tid:
            normalized_variants.append(tid.replace("-", ""))
        elif len(tid) == 32:
            normalized_variants.append(f"{tid[:8]}-{tid[8:12]}-{tid[12:16]}-{tid[16:20]}-{tid[20:]}")

        variants = []
        for _tid in normalized_variants:
            variants.extend([
                {"trace_id": _tid, "limit": 100},
                {"traceId": _tid, "limit": 100},
                {"trace": _tid, "limit": 100},
            ])
        for kwargs in variants:
            try:
                rows = _response_to_list(call_with_rate_limit_retry(method, **kwargs))
                if rows:
                    return rows
            except TypeError as te:
                logger.debug("_try_call: TypeError with kwargs={}: {}", kwargs, te)
                continue
            except Exception as exc:
                logger.debug("_try_call: Exception with kwargs={}: {} ({})", kwargs, exc, type(exc).__name__)
                continue
        return []

    # Primary: fetch_observations()
    if hasattr(client, "fetch_observations"):
        try:
            observations = _try_call(client.fetch_observations)
            if observations:
                logger.debug("fetch_obs[{}]: got {} via fetch_observations()", trace_id_str[:8], len(observations))
                _REQUEST_OBSERVATIONS_CACHE[obs_cache_key] = list(observations)
                return _cache_and_return_observations(trace_id_str, observations, cache_key=obs_cache_key)
        except Exception as exc:
            logger.debug("fetch_obs[{}]: fetch_observations() failed: {}", trace_id_str[:8], exc)

    # v3 fallbacks
    if is_v3_client(client) and hasattr(client, "api"):
        for attr_name in ("observations", "observations_v_2"):
            obs_api = getattr(client.api, attr_name, None)
            if obs_api is None:
                continue
            for method_name in ("get_many", "list"):
                method = getattr(obs_api, method_name, None)
                if method is None:
                    continue
                try:
                    observations = _try_call(method)
                    if observations:
                        logger.debug("fetch_obs[{}]: got {} via api.{}.{}()", trace_id_str[:8], len(observations), attr_name, method_name)
                        _REQUEST_OBSERVATIONS_CACHE[obs_cache_key] = list(observations)
                        return _cache_and_return_observations(trace_id_str, observations, cache_key=obs_cache_key)
                except Exception as exc:
                    logger.debug("fetch_obs[{}]: api.{}.{}() failed: {}", trace_id_str[:8], attr_name, method_name, exc)

    # Direct client fallback
    if hasattr(client, "client") and hasattr(client.client, "observations"):
        try:
            observations = _try_call(client.client.observations.list)
            if observations:
                logger.debug("fetch_obs[{}]: got {} via client.client.observations.list()", trace_id_str[:8], len(observations))
                _REQUEST_OBSERVATIONS_CACHE[obs_cache_key] = list(observations)
                return _cache_and_return_observations(trace_id_str, observations, cache_key=obs_cache_key)
        except Exception as exc:
            logger.debug("fetch_obs[{}]: client.client.observations.list() failed: {}", trace_id_str[:8], exc)

    # Last fallback: embedded observations in trace detail
    try:
        trace_obj = fetch_trace_by_id(client, trace_id_str)
        embedded = get_attr(trace_obj, "observations", default=[]) if trace_obj else []
        if isinstance(embedded, (list, tuple)) and embedded:
            observations = list(embedded)
            logger.debug("fetch_obs[{}]: got {} via fetch_trace_by_id() embedded", trace_id_str[:8], len(observations))
            _REQUEST_OBSERVATIONS_CACHE[obs_cache_key] = list(observations)
            return _cache_and_return_observations(trace_id_str, observations, cache_key=obs_cache_key)
        elif trace_obj:
            # Even without embedded observations, try to extract metrics from the full trace
            logger.debug("fetch_obs[{}]: fetch_trace_by_id() returned trace but no embedded observations", trace_id_str[:8])
    except Exception as exc:
        logger.debug("fetch_obs[{}]: fetch_trace_by_id() fallback failed: {}", trace_id_str[:8], exc)

    # Cache non-empty only at process level; always cache at request level
    if observations:
        _cache_and_return_observations(trace_id_str, observations, cache_key=obs_cache_key)
    else:
        logger.info(
            "fetch_obs[{}]: ALL methods failed — returning empty (is_v3={}, has_api={}, has_fetch_obs={})",
            trace_id_str[:8],
            is_v3_client(client),
            hasattr(client, "api"),
            hasattr(client, "fetch_observations"),
        )
    _REQUEST_OBSERVATIONS_CACHE[obs_cache_key] = list(observations)
    return observations


def fetch_trace_by_id(client: Any, trace_id: str) -> Any | None:
    """Fetch a single trace by id with UUID formatting fallbacks."""
    tid = str(trace_id)
    id_variants = [tid]
    if "-" in tid:
        id_variants.append(tid.replace("-", ""))
    elif len(tid) == 32:
        id_variants.append(f"{tid[:8]}-{tid[8:12]}-{tid[12:16]}-{tid[16:20]}-{tid[20:]}")

    for tid_variant in id_variants:
        if hasattr(client, "fetch_trace"):
            try:
                response = call_with_rate_limit_retry(client.fetch_trace, tid_variant)
                trace_obj = response.data if hasattr(response, "data") else response
                if trace_obj:
                    return trace_obj
            except Exception:
                pass
        if hasattr(client, "api") and hasattr(client.api, "trace") and hasattr(client.api.trace, "get"):
            try:
                trace_obj = call_with_rate_limit_retry(client.api.trace.get, tid_variant)
                if trace_obj:
                    return trace_obj
            except Exception:
                pass
    return None


def fetch_scores_for_trace(client: Any, trace_id: str, user_id: str | None = None, limit: int = 100) -> list:
    # Langfuse API max limit is 100
    limit = min(limit, 100)
    """Fetch evaluation scores for a trace across Langfuse SDK variants."""
    from .models import ScoreItem

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

            # Debug: log raw score object to understand structure
            logger.info(
                f"fetch_scores_for_trace: raw score type={type(score).__name__}, "
                f"dir={[a for a in dir(score) if not a.startswith('_')]}, "
                f"repr={repr(score)[:500]}"
            )

            # Handle nested score objects (v3 API wraps score in a 'score' key)
            score_obj = score
            if hasattr(score, "score") and score.score is not None:
                score_obj = score.score
                logger.info(f"  Unwrapped nested score: type={type(score_obj).__name__}, repr={repr(score_obj)[:300]}")
            elif isinstance(score, dict) and "score" in score and isinstance(score["score"], dict):
                score_obj = score["score"]
                logger.info(f"  Unwrapped nested dict score: {score_obj}")

            score_name = str(get_attr(score_obj, "name", default="") or get_attr(score, "name", default="Score") or "Score")
            score_value = get_attr(score_obj, "value", default=None)
            if score_value is None:
                score_value = get_attr(score, "value", default=0.0)
            score_value = float(score_value if score_value is not None else 0.0)
            logger.info(f"  Parsed: name={score_name}, value={score_value}")

            scores.append(ScoreItem(
                id=score_id or str(len(scores) + 1),
                name=score_name,
                value=score_value,
                source=str(source) if source is not None else None,
                comment=get_attr(score_obj, "comment") or get_attr(score, "comment"),
                created_at=parse_datetime(get_attr(score_obj, "created_at", "createdAt", "timestamp") or get_attr(score, "created_at", "createdAt", "timestamp")),
            ))
            added += 1
        return added

    logger.info(f"fetch_scores_for_trace: trace_id={trace_id}, client_type={type(client).__name__}, has_api={hasattr(client, 'api')}")

    # Also try with and without dashes for trace_id
    trace_id_variants = [trace_id]
    if "-" in trace_id:
        trace_id_variants.append(trace_id.replace("-", ""))
    elif len(trace_id) == 32:
        trace_id_variants.append(f"{trace_id[:8]}-{trace_id[8:12]}-{trace_id[12:16]}-{trace_id[16:20]}-{trace_id[20:]}")

    # v3 API: score_v_2.get
    if hasattr(client, "api") and hasattr(client.api, "score_v_2"):
        for tid_variant in trace_id_variants:
            try:
                kwargs: dict[str, Any] = {"trace_id": tid_variant, "limit": limit}
                try:
                    kwargs["fields"] = "score,trace"
                    payload = call_with_rate_limit_retry(client.api.score_v_2.get, **kwargs)
                except TypeError:
                    kwargs.pop("fields", None)
                    payload = call_with_rate_limit_retry(client.api.score_v_2.get, **kwargs)
                logger.info(f"  score_v_2.get(trace_id={tid_variant}) returned: type={type(payload).__name__}, repr={repr(payload)[:500]}")
                _append_scores(payload, already_filtered_by_trace=True)
                if scores:
                    logger.info(f"  score_v_2.get: found {len(scores)} scores")
                    scores.sort(key=lambda s: s.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                    return scores
                logger.info(f"  score_v_2.get(trace_id={tid_variant}): 0 scores after parsing")
            except Exception as e:
                logger.info(f"  score_v_2.get(trace_id={tid_variant}) failed: {e}")

    # Legacy: fetch_scores
    if hasattr(client, "fetch_scores"):
        try:
            payload = call_with_rate_limit_retry(client.fetch_scores, trace_id=trace_id)
            logger.info(f"  fetch_scores returned: type={type(payload).__name__}, repr={repr(payload)[:500]}")
            _append_scores(payload)
            if scores:
                logger.info(f"  fetch_scores: found {len(scores)} scores")
                scores.sort(key=lambda s: s.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                return scores
            logger.info(f"  fetch_scores: 0 scores after parsing")
        except Exception as e:
            logger.info(f"  fetch_scores failed: {e}")

    # Retry without user filter
    if not scores and user_id:
        return fetch_scores_for_trace(client, trace_id=trace_id, user_id=None, limit=limit)

    scores.sort(key=lambda s: s.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return scores
