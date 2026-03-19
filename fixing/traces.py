"""GET /traces and /traces/{trace_id} endpoints."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.auth.permissions import normalize_role
from agentcore.services.auth.utils import get_current_active_user
from agentcore.services.database.models.user.model import User
from agentcore.services.deps import get_session

from ..aggregations import traces_to_list_items
from ..langfuse_client import is_v3_client
from ..models import (
    ObservationResponse,
    ScoreItem,
    TraceDetailResponse,
    TracesListResponse,
)
from ..parsing import (
    clear_request_caches,
    compute_date_range,
    get_attr,
    parse_datetime,
    parse_observation,
    fetch_observations_for_trace,
    fetch_scores_for_trace,
    fetch_trace_by_id,
    call_with_rate_limit_retry,
    extract_trace_user_ids,
    _enum_str,
    observation_cache_key,
    _cache_and_return_observations,
)
from ..scope import resolve_scope_context, scope_warning_payload
from ..trace_store import (
    TraceStore,
    _resolve_trace_client,
    _trace_quality_score,
    get_trace_metrics,
    _fetch_observations_with_fallback,
    _TRACE_FETCH_CACHE,
)

router = APIRouter()


@router.get("/traces")
async def get_user_traces(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    page: Annotated[int, Query(ge=1)] = 1,
    session_id: Annotated[str | None, Query()] = None,
    org_id: Annotated[UUID | None, Query(description="Organization scope")] = None,
    dept_id: Annotated[UUID | None, Query(description="Department scope")] = None,
    from_date: Annotated[str | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Query(description="End date (YYYY-MM-DD)")] = None,
    environment: Annotated[str | None, Query(description="'uat' or 'production'")] = None,
    trace_scope: Annotated[str, Query(description="Trace scope: 'all', 'dept', or 'my'")] = "all",
) -> TracesListResponse:
    """Get traces for the current user with aggregated metrics."""
    clear_request_caches()

    try:
        allowed_user_ids, scoped_clients, scope_key, scope_warnings = await resolve_scope_context(
            session=session, current_user=current_user, org_id=org_id, dept_id=dept_id,
            trace_scope=trace_scope,
        )
        if not scoped_clients:
            return TracesListResponse(
                traces=[], total=0, page=page, limit=limit,
                **scope_warning_payload(scope_warnings),
            )

        now = datetime.now(timezone.utc)
        if to_date:
            to_ts = datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        else:
            to_ts = now
        if from_date:
            from_ts = datetime.strptime(from_date, "%Y-%m-%d").replace(hour=0, minute=0, second=0, tzinfo=timezone.utc)
        else:
            from_ts = now.replace(hour=0, minute=0, second=0, microsecond=0)

        traces, _truncated = TraceStore.get_traces(
            clients=scoped_clients,
            allowed_user_ids=allowed_user_ids,
            scope_key=scope_key,
            from_timestamp=from_ts,
            to_timestamp=to_ts,
            environment=environment,
            limit=min(limit * page + 50, 500),
        )

        if session_id:
            traces = [t for t in traces if t.session_id == session_id]

        items = traces_to_list_items(traces)
        total = len(items)
        start_idx = (page - 1) * limit
        paginated = items[start_idx:start_idx + limit]

        return TracesListResponse(
            traces=paginated, total=total, page=page, limit=limit,
            **scope_warning_payload(scope_warnings),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching traces: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch traces: {e}")


@router.get("/traces/{trace_id}")
async def get_trace_detail(
    trace_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    org_id: Annotated[UUID | None, Query(description="Organization scope")] = None,
    dept_id: Annotated[UUID | None, Query(description="Department scope")] = None,
    trace_scope: Annotated[str, Query(description="Trace scope: 'all', 'dept', or 'my'")] = "all",
) -> TraceDetailResponse:
    """Get detailed trace information including all observations (spans)."""
    clear_request_caches()

    allowed_user_ids, scoped_clients, _scope_key, scope_warnings = await resolve_scope_context(
        session=session, current_user=current_user, org_id=org_id, dept_id=dept_id,
        trace_scope=trace_scope,
    )
    if not scoped_clients:
        raise HTTPException(status_code=404, detail=(scope_warnings[0] if scope_warnings else "Trace not found"))

    try:
        trace = None
        trace_client: Any | None = None

        # Best-quality trace search across clients
        best_trace: Any | None = None
        best_client: Any | None = None
        best_score: tuple[int, int, int, int] = (-1, -1, -1, -1)

        _tid_str = str(trace_id)
        _tid_variants = [_tid_str]
        if "-" not in _tid_str and len(_tid_str) == 32:
            _tid_variants.append(f"{_tid_str[:8]}-{_tid_str[8:12]}-{_tid_str[12:16]}-{_tid_str[16:20]}-{_tid_str[20:]}")
        elif "-" in _tid_str:
            _tid_variants.append(_tid_str.replace("-", ""))

        # Check process cache first
        _norm_req_id = _tid_str.replace("-", "").lower()
        for _ck, _ce in list(_TRACE_FETCH_CACHE.items()):
            for _candidate in (_ce.get("traces", []) or []):
                _cid = str(get_attr(_candidate, "id", "trace_id", "traceId", default="") or "")
                if _cid.replace("-", "").lower() != _norm_req_id:
                    continue
                _cand_uids = extract_trace_user_ids(_candidate)
                if _cand_uids and set(_cand_uids).intersection(allowed_user_ids):
                    trace = _candidate
                    trace_client = _resolve_trace_client(_candidate, scoped_clients)
                    break
            if trace:
                break

        if not trace:
            logger.info(f"get_trace_detail: searching {len(scoped_clients)} client(s) for trace_id variants={_tid_variants}")
            for idx, cand_client in enumerate(scoped_clients):
                _api = getattr(cand_client, 'api', None)
                _api_attrs = [a for a in dir(_api) if not a.startswith('_')] if _api else []
                logger.info(
                    f"get_trace_detail: client[{idx}] type={type(cand_client).__name__}, "
                    f"has_fetch_trace={hasattr(cand_client, 'fetch_trace')}, "
                    f"is_v3={is_v3_client(cand_client)}, "
                    f"has_api={hasattr(cand_client, 'api')}, "
                    f"has_client={hasattr(cand_client, 'client')}, "
                    f"api_type={type(_api).__name__ if _api else 'None'}, "
                    f"api_has_trace={hasattr(_api, 'trace') if _api else False}, "
                    f"api_attrs={_api_attrs[:15]}"
                )
                for _tid_v in _tid_variants:
                    if hasattr(cand_client, "fetch_trace"):
                        try:
                            resp = call_with_rate_limit_retry(cand_client.fetch_trace, _tid_v)
                            _t = resp.data if hasattr(resp, "data") else resp
                            if _t:
                                s = _trace_quality_score(_t)
                                logger.info(f"get_trace_detail: client[{idx}] fetch_trace({_tid_v}) found trace, quality={s}")
                                if s > best_score:
                                    best_trace, best_client, best_score = _t, cand_client, s
                        except Exception as e:
                            logger.debug(f"get_trace_detail: client[{idx}] fetch_trace({_tid_v}) failed: {e}")
                    if is_v3_client(cand_client) and hasattr(cand_client, "api") and hasattr(cand_client.api, "trace"):
                        try:
                            _t = call_with_rate_limit_retry(cand_client.api.trace.get, _tid_v)
                            logger.info(f"get_trace_detail: client[{idx}] api.trace.get({_tid_v}) returned type={type(_t).__name__}, truthy={bool(_t)}")
                            if _t:
                                s = _trace_quality_score(_t)
                                logger.info(f"get_trace_detail: client[{idx}] api.trace.get({_tid_v}) found trace, quality={s}")
                                if s > best_score:
                                    best_trace, best_client, best_score = _t, cand_client, s
                        except Exception as e:
                            logger.info(f"get_trace_detail: client[{idx}] api.trace.get({_tid_v}) EXCEPTION: {type(e).__name__}: {e}")

        if best_trace is not None:
            trace = best_trace
            trace_client = best_client

        if not trace:
            logger.warning(f"get_trace_detail: trace {trace_id} NOT FOUND across {len(scoped_clients)} clients, allowed_user_ids={allowed_user_ids}")
            raise HTTPException(status_code=404, detail="Trace not found")
        if trace_client is None:
            trace_client = _resolve_trace_client(trace, scoped_clients) or scoped_clients[0]

        # Security check
        current_role = normalize_role(getattr(current_user, "role", None))
        trace_user_ids = extract_trace_user_ids(trace)
        if not trace_user_ids or not set(trace_user_ids).intersection(allowed_user_ids):
            # Check process cache for authorization
            authorized = False
            for _ck, _ce in list(_TRACE_FETCH_CACHE.items()):
                for _candidate in (_ce.get("traces", []) or []):
                    _cid = str(get_attr(_candidate, "id", "trace_id", "traceId", default="") or "")
                    if _cid.replace("-", "").lower() != _norm_req_id:
                        continue
                    _cand_uids = extract_trace_user_ids(_candidate)
                    if _cand_uids and set(_cand_uids).intersection(allowed_user_ids):
                        trace_user_ids = _cand_uids
                        authorized = True
                        break
                if authorized:
                    break
            if not authorized:
                if not trace_user_ids and current_role in {"root", "super_admin", "department_admin"}:
                    pass  # Allow admin access for traces without user metadata
                else:
                    raise HTTPException(status_code=404, detail="Trace not found")

        trace_user_id = (
            str(current_user.id) if str(current_user.id) in trace_user_ids
            else (next(iter(trace_user_ids)) if trace_user_ids else str(current_user.id))
        )

        resolved_trace_id = str(get_attr(trace, "id", "trace_id", "traceId", default=trace_id) or trace_id)
        logger.info(f"get_trace_detail: resolved_trace_id={resolved_trace_id}, trace_client_type={type(trace_client).__name__}")

        # Check for embedded observations
        _embedded_obs = get_attr(trace, "observations", default=None)
        _use_embedded = False
        if _embedded_obs and isinstance(_embedded_obs, (list, tuple)) and len(_embedded_obs) > 0:
            _parsed_preview = [parse_observation(o) for o in _embedded_obs]
            _use_embedded = any(p.total_tokens > 0 or (p.total_cost or 0.0) > 0.0 or bool(p.model) or bool(p.name) for p in _parsed_preview)

        if _use_embedded:
            raw_observations = list(_embedded_obs)
            _cache_and_return_observations(resolved_trace_id, raw_observations, cache_key=observation_cache_key(trace_client, resolved_trace_id))
            fetched_scores = await asyncio.to_thread(
                lambda: fetch_scores_for_trace(trace_client, resolved_trace_id, trace_user_id, limit=100)
            )
        else:
            obs_task = asyncio.create_task(asyncio.to_thread(
                lambda: fetch_observations_for_trace(trace_client, resolved_trace_id)
            ))
            scores_task = asyncio.create_task(asyncio.to_thread(
                lambda: fetch_scores_for_trace(trace_client, resolved_trace_id, trace_user_id, limit=100)
            ))
            raw_observations, fetched_scores = await asyncio.gather(obs_task, scores_task, return_exceptions=True)
            if isinstance(raw_observations, Exception):
                raw_observations = []
            if isinstance(fetched_scores, Exception):
                fetched_scores = []

            if not raw_observations and resolved_trace_id != str(trace_id):
                raw_observations = fetch_observations_for_trace(trace_client, str(trace_id))

            if not raw_observations and len(scoped_clients) > 1:
                for alt_client in scoped_clients:
                    if alt_client is trace_client:
                        continue
                    alt_obs = fetch_observations_for_trace(alt_client, resolved_trace_id)
                    if alt_obs:
                        raw_observations = alt_obs
                        trace_client = alt_client
                        break

        observations = sorted(
            [parse_observation(o) for o in (raw_observations or [])],
            key=lambda o: o.start_time or datetime.min.replace(tzinfo=timezone.utc),
        )

        # Aggregate from observations or fall back to trace-level
        if observations:
            total_tokens = sum(o.total_tokens for o in observations)
            input_tokens = sum(o.input_tokens for o in observations)
            output_tokens = sum(o.output_tokens for o in observations)
            total_cost = sum(o.total_cost for o in observations)
            models_used = list(set(o.model for o in observations if o.model))
        else:
            m = get_trace_metrics(trace_client, trace, allow_observation_fallback=True, all_clients=scoped_clients)
            total_tokens = int(m["total_tokens"])
            input_tokens = int(m["input_tokens"])
            output_tokens = int(m["output_tokens"])
            total_cost = float(m["total_cost"])
            models_used = list(m["models"])

        # Latency
        latency_ms = None
        if observations:
            starts = [o.start_time for o in observations if o.start_time]
            ends = [o.end_time for o in observations if o.end_time]
            if starts and ends:
                latency_ms = (max(ends) - min(starts)).total_seconds() * 1000
        if latency_ms is None:
            m = get_trace_metrics(trace_client, trace, allow_observation_fallback=False, all_clients=scoped_clients)
            latency_ms = m["latency_ms"]
            if not models_used:
                models_used = list(m["models"])

        # Merge scores
        scores: list[ScoreItem] = []
        try:
            embedded_scores = get_attr(trace, "scores", default=[]) or []
            logger.info(f"Trace {resolved_trace_id}: {len(embedded_scores)} embedded scores, {len(fetched_scores or [])} fetched scores")
            for idx, raw_score in enumerate(embedded_scores):
                logger.info(f"  embedded score[{idx}]: raw_type={type(raw_score).__name__}, repr={repr(raw_score)[:300]}")
                # Handle string entries — these are score IDs in Langfuse v3
                if isinstance(raw_score, str):
                    # Try parsing as JSON first
                    try:
                        parsed = json.loads(raw_score)
                        if isinstance(parsed, dict):
                            raw_score = parsed
                        else:
                            raise ValueError("not a dict")
                    except (json.JSONDecodeError, ValueError):
                        # It's a score ID — fetch the actual score object
                        score_id = raw_score.strip()
                        if score_id and trace_client:
                            fetched = False
                            api_obj = getattr(trace_client, "api", None)
                            if api_obj:
                                # Try multiple score API variants
                                for attr_name in ("score", "scores", "score_v_2"):
                                    score_api = getattr(api_obj, attr_name, None)
                                    if score_api and hasattr(score_api, "get"):
                                        try:
                                            fetched_score = call_with_rate_limit_retry(score_api.get, score_id)
                                            if fetched_score:
                                                raw_score = fetched_score
                                                logger.info(f"  embedded score[{idx}]: fetched via api.{attr_name}.get(ID={score_id}), type={type(raw_score).__name__}")
                                                fetched = True
                                                break
                                        except Exception as e:
                                            logger.debug(f"  embedded score[{idx}]: api.{attr_name}.get({score_id}) failed: {e}")
                            if not fetched:
                                # Score ID couldn't be resolved — the score_v_2.get with trace_id filter
                                # already found the scores via fetched_scores, so skip this embedded ID
                                logger.debug(f"  embedded score[{idx}]: could not fetch score ID={score_id}")
                                continue
                        else:
                            continue

                # Unwrap nested score object (v3 API may wrap in a 'score' key)
                score_obj = raw_score
                if hasattr(raw_score, "score") and raw_score.score is not None:
                    score_obj = raw_score.score
                elif isinstance(raw_score, dict) and "score" in raw_score and isinstance(raw_score["score"], dict):
                    score_obj = raw_score["score"]

                source = get_attr(score_obj, "source") or get_attr(raw_score, "source")
                if hasattr(source, "value"):
                    source = source.value

                score_name = str(get_attr(score_obj, "name", default="") or get_attr(raw_score, "name", default="Score") or "Score")
                score_value = get_attr(score_obj, "value", default=None)
                if score_value is None:
                    score_value = get_attr(raw_score, "value", default=0.0)
                score_value = float(score_value if score_value is not None else 0.0)

                logger.info(f"  embedded score[{idx}]: type={type(raw_score).__name__}, name={score_name}, value={score_value}")

                scores.append(ScoreItem(
                    id=str(get_attr(score_obj, "id", default="") or get_attr(raw_score, "id", default=str(idx + 1))),
                    name=score_name,
                    value=score_value,
                    source=str(source) if source is not None else None,
                    comment=get_attr(score_obj, "comment") or get_attr(raw_score, "comment"),
                    created_at=parse_datetime(get_attr(score_obj, "created_at", "createdAt", "timestamp") or get_attr(raw_score, "created_at", "createdAt", "timestamp")),
                ))
            merged = {s.id: s for s in scores if s.id}
            for score in (fetched_scores or []):
                merged[score.id] = score
            scores = sorted(merged.values(), key=lambda s: s.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            logger.info(f"  Final scores for trace {resolved_trace_id}: {[(s.name, s.value) for s in scores]}")
        except Exception as e:
            logger.warning(f"Error merging scores for trace {resolved_trace_id}: {e}")
            pass

        return TraceDetailResponse(
            id=resolved_trace_id,
            name=get_attr(trace, "name"),
            user_id=trace_user_id,
            session_id=get_attr(trace, "session_id", "sessionId"),
            timestamp=parse_datetime(get_attr(trace, "timestamp")),
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost=total_cost,
            latency_ms=latency_ms,
            models_used=models_used,
            observations=observations,
            scores=list(scores),
            input=get_attr(trace, "input"),
            output=get_attr(trace, "output"),
            metadata=get_attr(trace, "metadata"),
            tags=get_attr(trace, "tags", default=[]) or [],
            level=_enum_str(get_attr(trace, "level")),
            status=_enum_str(get_attr(trace, "status")),
            **scope_warning_payload(scope_warnings),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching trace detail: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch trace: {e}")
