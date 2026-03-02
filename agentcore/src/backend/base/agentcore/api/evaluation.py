"""
Evaluation API Endpoints - Enhanced Version

Features:
- User isolation (only access own scores/traces)
- Integration with existing observability
- LLM-as-a-Judge with proper trace fetching
- Proper error handling
"""

import os
import json
import asyncio
import time
import re
import csv
import io
from threading import Lock, Thread
from datetime import datetime, timezone, timedelta
from typing import Annotated, Any, List, Optional, Dict, Union
from collections import defaultdict
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File
from loguru import logger
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlalchemy import or_
from agentcore.services.deps import session_scope
# `agent` objects are stored as `Agent` in the DB; import AccessTypeEnum and
# alias `Agent` to `agent` so the rest of the module can keep using `agent`.
from agentcore.services.database.models.agent.model import AccessTypeEnum, Agent as agent

from agentcore.services.auth.utils import get_current_active_user
from agentcore.services.database.models.user.model import User
from agentcore.api.utils import DbSession
from agentcore.api.observability import fetch_traces_from_langfuse, fetch_scores_for_trace

# Try importing litellm for the judge
try:
    import litellm
    LITELLM_AVAILABLE = True
except ImportError:
    litellm = None
    LITELLM_AVAILABLE = False
    logger.warning("LiteLLM not installed. LLM Judge features will be disabled.")

# Try importing OpenAI as a fallback for the judge when LiteLLM isn't present
try:
    import openai
    OPENAI_AVAILABLE = True
except Exception:
    openai = None
    OPENAI_AVAILABLE = False

router = APIRouter(prefix="/evaluation", tags=["Evaluation"])

_LITELLM_STD_LOGGING_PATCHED = False
_DATASET_EXPERIMENT_JOBS: dict[str, dict[str, Any]] = {}
_DATASET_EXPERIMENT_JOBS_LOCK = Lock()
_SCORE_LIST_CACHE: dict[str, dict[str, Any]] = {}
_SCORE_LIST_CACHE_STALE_SECONDS = 90.0
# Pending-reviews response cache (per user_id)
_PENDING_REVIEWS_CACHE: dict[str, dict[str, Any]] = {}
_PENDING_REVIEWS_CACHE_TTL_SECONDS = 30.0
# Dataset list response cache (per user_id)
_DATASETS_LIST_CACHE: dict[str, dict[str, Any]] = {}
_DATASETS_LIST_CACHE_TTL_SECONDS = 60.0

# Persistent evaluator configs stored in the database (see Evaluator model)
from agentcore.services.database.models.evaluator.model import Evaluator  # noqa: E402


# =============================================================================
# Response Models
# =============================================================================

class ScoreResponse(BaseModel):
    """Represents a single evaluation score."""
    id: str
    trace_id: str
    agent_name: str | None = None
    name: str
    value: float
    source: str  # "ANNOTATION" (human), "API" (llm judge)
    comment: str | None = None
    user_id: str | None = None
    created_at: datetime | None = None
    observation_id: str | None = None
    config_id: str | None = None


class CreateScoreRequest(BaseModel):
    """Request to create a manual score (annotation)."""
    trace_id: str
    name: str
    value: float = Field(..., ge=0.0, le=1.0, description="Score between 0 and 1")
    comment: str | None = None
    observation_id: str | None = None


class JudgeConfig(BaseModel):
    """Saved judge configuration for reuse."""
    id: str | None = None
    name: str
    criteria: str
    model: str = "gpt-4o"
    # target: 'existing' -> evaluate matching existing traces now
    #         'new' -> save evaluator to apply to future traces (not executed immediately)
    target: str = Field("existing", description="'existing' or 'new'")
    # Filtering options to select traces
    trace_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    session_id: Optional[str] = None
    project_name: Optional[str] = None
    ts_from: Optional[str] = None  # ISO timestamp
    ts_to: Optional[str] = None
    user_id: str | None = None


class EvaluatorCreateRequest(BaseModel):
    name: str
    criteria: str
    model: str = "gpt-4o"
    preset_id: Optional[str] = None
    # target may be a single string ('existing'|'new') or a list like ['existing','new']
    target: Optional[Union[str, List[str]]] = Field(default="existing")
    # Ground truth for evaluation (required for some presets like 'correctness')
    ground_truth: Optional[str] = None
    # Optional filters for selecting traces when target includes 'existing'
    trace_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_ids: Optional[List[str]] = None
    agent_name: Optional[str] = None
    session_id: Optional[str] = None
    project_name: Optional[str] = None
    ts_from: Optional[str] = None  # ISO timestamp
    ts_to: Optional[str] = None
    model_api_key: Optional[str] = None


class EvaluatorResponse(BaseModel):
    id: str
    name: str
    criteria: str
    model: str
    user_id: str | None = None
    preset_id: Optional[str] = None
    agent_ids: Optional[List[str]] = None
    target: Optional[List[str]] = None
    ground_truth: Optional[str] = None
    trace_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    session_id: Optional[str] = None
    project_name: Optional[str] = None
    ts_from: Optional[str] = None
    ts_to: Optional[str] = None
    created_at: Optional[str] = None


class TraceForReview(BaseModel):
    """Trace info for annotation queue."""
    id: str
    name: str | None
    timestamp: datetime | None
    input: Any | None
    output: Any | None
    session_id: str | None
    agent_name: str | None
    has_scores: bool = False
    score_count: int = 0


class DatasetResponse(BaseModel):
    """Represents a Langfuse dataset."""
    id: str
    name: str
    description: str | None = None
    metadata: Any | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    item_count: int | None = None


class CreateDatasetRequest(BaseModel):
    """Request to create a dataset."""
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    metadata: Any | None = None


class DatasetItemResponse(BaseModel):
    """Represents a single dataset item."""
    id: str
    dataset_name: str
    status: str | None = None
    input: Any | None = None
    expected_output: Any | None = None
    metadata: Any | None = None
    source_trace_id: str | None = None
    source_observation_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CreateDatasetItemRequest(BaseModel):
    """Request to create a dataset item."""
    input: Any | None = None
    expected_output: Any | None = None
    metadata: Any | None = None
    source_trace_id: str | None = None
    source_observation_id: str | None = None
    trace_id: str | None = None
    use_trace_output_as_expected: bool = True


class DatasetCsvImportError(BaseModel):
    """CSV import error for one row."""
    row: int
    message: str


class DatasetCsvImportResponse(BaseModel):
    """CSV import summary for dataset items."""
    dataset_name: str
    total_rows: int
    created_count: int
    failed_count: int
    skipped_count: int = 0
    errors: list[DatasetCsvImportError] = Field(default_factory=list)


class DatasetRunResponse(BaseModel):
    """Represents a dataset experiment run."""
    id: str
    name: str
    description: str | None = None
    metadata: Any | None = None
    dataset_id: str | None = None
    dataset_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DatasetRunItemScoreResponse(BaseModel):
    """Score snapshot linked to a dataset run item trace."""
    id: str
    name: str
    value: float
    source: str
    comment: str | None = None
    created_at: datetime | None = None


class DatasetRunItemDetailResponse(BaseModel):
    """Detailed dataset run item response."""
    id: str
    dataset_item_id: str | None = None
    trace_id: str | None = None
    observation_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    trace_name: str | None = None
    trace_input: Any | None = None
    trace_output: Any | None = None
    score_count: int = 0
    scores: list[DatasetRunItemScoreResponse] = Field(default_factory=list)


class DatasetRunDetailResponse(BaseModel):
    """Detailed run payload including run items and associated traces/scores."""
    run: DatasetRunResponse
    item_count: int
    items: list[DatasetRunItemDetailResponse]


class RunDatasetExperimentRequest(BaseModel):
    """Request to run a Langfuse dataset experiment."""
    experiment_name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    agent_id: str | None = None
    generation_model: str | None = None
    generation_model_api_key: str | None = None
    evaluator_config_id: str | None = None
    preset_id: str | None = None
    evaluator_name: str | None = None
    criteria: str | None = None
    judge_model: str | None = None
    judge_model_api_key: str | None = None
    # Deprecated compatibility aliases
    model: str | None = None
    model_api_key: str | None = None


class DatasetExperimentEnqueueResponse(BaseModel):
    """Response when a dataset experiment is queued."""
    job_id: str
    dataset_name: str
    experiment_name: str
    status: str


class DatasetExperimentJobResponse(BaseModel):
    """Background dataset experiment job state."""
    job_id: str
    status: str
    dataset_name: str
    experiment_name: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result: Dict[str, Any] | None = None


# =============================================================================
# Helper Functions
# =============================================================================

def get_langfuse_client():
    """Get a Langfuse client using environment variables."""
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    base_url = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")

    if not all([secret_key, public_key, base_url]):
        return None

    try:
        from langfuse import Langfuse
        if not os.getenv("LANGFUSE_BASE_URL") and os.getenv("LANGFUSE_HOST"):
            os.environ["LANGFUSE_BASE_URL"] = os.getenv("LANGFUSE_HOST")

        client = Langfuse(
            secret_key=secret_key,
            public_key=public_key,
            host=base_url
        )
        api_obj = getattr(client, "api", None)
        client._is_v3 = bool(
            hasattr(client, "auth_check")
            or (
                api_obj
                and (
                    hasattr(api_obj, "trace")
                    or hasattr(api_obj, "traces")
                )
            )
        )
        return client
    except ImportError:
        logger.warning("Langfuse package not installed")
        return None
    except Exception as e:
        logger.error("Failed to create Langfuse client: {}", str(e))
        return None


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


def _ensure_litellm_logging_compatibility_patch() -> None:
    """Patch LiteLLM standard logging cold-storage hook to avoid proxy-only imports."""
    global _LITELLM_STD_LOGGING_PATCHED

    if not LITELLM_AVAILABLE or _LITELLM_STD_LOGGING_PATCHED:
        return

    try:
        from litellm.litellm_core_utils import litellm_logging as _litellm_logging

        setup_cls = getattr(_litellm_logging, "StandardLoggingPayloadSetup", None)
        if setup_cls is None or not hasattr(setup_cls, "_generate_cold_storage_object_key"):
            _LITELLM_STD_LOGGING_PATCHED = True
            return

        def _disabled_cold_storage_key(*args, **kwargs):
            return None

        setup_cls._generate_cold_storage_object_key = staticmethod(_disabled_cold_storage_key)
        _LITELLM_STD_LOGGING_PATCHED = True
        logger.debug("Applied LiteLLM logging compatibility patch: disabled cold-storage object key generation.")
    except Exception as exc:
        logger.debug("Could not apply LiteLLM logging compatibility patch: {}", str(exc))


def parse_trace_data(trace) -> Dict[str, Any]:
    """Extract and normalize trace data."""
    metadata = get_attr(trace, 'metadata', 'meta')
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            metadata = parsed if isinstance(parsed, dict) else metadata
        except Exception:
            pass

    top_level_user_id = get_attr(trace, 'user_id', 'userId', 'sender', 'user')
    metadata_user_id = None
    if isinstance(metadata, dict):
        metadata_user_id = (
            metadata.get("user_id")
            or metadata.get("userId")
            or metadata.get("app_user_id")
            or metadata.get("created_by_user_id")
            or metadata.get("owner_user_id")
        )

    top_level_session_id = get_attr(trace, 'session_id', 'sessionId')
    metadata_session_id = None
    if isinstance(metadata, dict):
        metadata_session_id = metadata.get("session_id") or metadata.get("sessionId")

    return {
        "id": get_attr(trace, 'id', 'trace_id', 'traceId'),
        "name": get_attr(trace, 'name', 'display_name', 'trace_name'),
        "timestamp": get_attr(trace, 'timestamp', 'createdAt', 'created_at'),
        "input": get_attr(trace, 'input', 'inputs', 'input_data', 'generation', 'query'),
        "output": get_attr(trace, 'output', 'outputs', 'generation', 'text_output', 'response'),
        "session_id": top_level_session_id or metadata_session_id,
        "user_id": top_level_user_id or metadata_user_id,
        "metadata": metadata,
        "tags": get_attr(trace, 'tags', 'labels'),
    }


def _as_dict(value: Any) -> dict[str, Any]:
    """Convert object-like values into plain dictionaries."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    if hasattr(value, "__dict__"):
        try:
            raw = dict(vars(value))
            return {k: v for k, v in raw.items() if not k.startswith("_")}
        except Exception:
            return {}
    return {}


def _parse_paginated_response(response: Any) -> tuple[list[Any], int | None]:
    """Extract rows + total from Langfuse paginated payload variants."""
    if response is None:
        return [], None

    rows: list[Any] = []
    total: int | None = None

    if isinstance(response, list):
        return response, len(response)

    if isinstance(response, dict):
        rows = list(response.get("data") or response.get("items") or [])
        meta = response.get("meta") or {}
        if isinstance(meta, dict):
            total = meta.get("total_items") or meta.get("total")
        if total is None:
            total = response.get("total")
        return rows, int(total) if total is not None else None

    if hasattr(response, "data"):
        rows = list(getattr(response, "data", []) or [])
        meta = getattr(response, "meta", None)
        if isinstance(meta, dict):
            total = meta.get("total_items") or meta.get("total")
        elif meta is not None:
            total = getattr(meta, "total_items", None) or getattr(meta, "total", None)
        return rows, int(total) if total is not None else None

    return [], None


def _dataset_owned_by_user(dataset_obj: Any, user_id: str) -> bool:
    """Best-effort user scoping for datasets via metadata."""
    metadata = get_attr(dataset_obj, "metadata", default=None)
    if not isinstance(metadata, dict):
        # Keep backward compatibility with datasets created before ownership metadata.
        return True

    owner = (
        metadata.get("app_user_id")
        or metadata.get("user_id")
        or metadata.get("owner_user_id")
        or metadata.get("created_by_user_id")
    )
    if owner is None:
        return True
    return str(owner) == str(user_id)


def _dataset_item_owned_by_user(item_obj: Any, user_id: str) -> bool:
    """Best-effort user scoping for dataset items via metadata."""
    metadata = get_attr(item_obj, "metadata", default=None)
    if not isinstance(metadata, dict):
        return True
    owner = (
        metadata.get("app_user_id")
        or metadata.get("user_id")
        or metadata.get("owner_user_id")
        or metadata.get("created_by_user_id")
    )
    if owner is None:
        return True
    return str(owner) == str(user_id)


def _merge_dataset_metadata(metadata: Any, *, user_id: str) -> dict[str, Any]:
    """Attach app metadata while preserving user-provided fields."""
    base = _as_dict(metadata)
    base.setdefault("app_user_id", str(user_id))
    base.setdefault("created_by_user_id", str(user_id))
    base.setdefault("created_via", "agentcore-evaluation")
    return base


def _parse_csv_json_cell(value: Any) -> Any | None:
    """Parse CSV cell into JSON when possible; keep plain text otherwise."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"null", "none"}:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text


def _parse_csv_bool_cell(value: Any, *, default: bool = True) -> bool:
    """Parse boolean CSV cells with safe defaults."""
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _get_row_value(row: dict[str, Any], *keys: str) -> Any | None:
    """Get first non-empty value from a CSV row by alias keys."""
    for key in keys:
        if key not in row:
            continue
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _create_dataset_item_for_user(
    *,
    client: Any,
    dataset_name: str,
    payload: CreateDatasetItemRequest,
    current_user_id: str,
    flush: bool = True,
) -> DatasetItemResponse:
    """Create one dataset item while enforcing user scoping and trace ownership."""
    item_input = payload.input
    expected_output = payload.expected_output
    source_trace_id = payload.source_trace_id

    if payload.trace_id:
        trace_raw = _fetch_trace_by_id(client, payload.trace_id)
        if not trace_raw:
            raise HTTPException(status_code=404, detail=f"Trace '{payload.trace_id}' not found")

        trace_dict = parse_trace_data(trace_raw)
        trace_user = _extract_trace_user_id(trace_dict)
        if trace_user and trace_user != str(current_user_id):
            raise HTTPException(status_code=403, detail="Trace does not belong to current user")

        if item_input is None:
            item_input = trace_dict.get("input")
        if expected_output is None and payload.use_trace_output_as_expected:
            expected_output = trace_dict.get("output")
        source_trace_id = source_trace_id or str(trace_dict.get("id") or payload.trace_id)

    if item_input is None and expected_output is None:
        raise HTTPException(
            status_code=400,
            detail="Provide input/expected_output or a trace_id to create a dataset item",
        )

    metadata = _merge_dataset_metadata(payload.metadata, user_id=str(current_user_id))
    if payload.trace_id:
        metadata.setdefault("trace_id", str(payload.trace_id))

    item = client.create_dataset_item(
        dataset_name=dataset_name,
        input=item_input,
        expected_output=expected_output,
        metadata=metadata,
        source_trace_id=source_trace_id,
        source_observation_id=payload.source_observation_id,
    )
    if flush and hasattr(client, "flush"):
        client.flush()
    return _dataset_item_to_response(item)


def _csv_row_to_dataset_item_request(row: dict[str, Any]) -> CreateDatasetItemRequest:
    """Map one CSV row to CreateDatasetItemRequest with flexible header aliases."""
    row_lower = {(str(k).strip().lower() if k is not None else ""): v for k, v in row.items()}
    item_input = _parse_csv_json_cell(
        _get_row_value(row_lower, "input", "query", "question", "prompt")
    )
    expected_output = _parse_csv_json_cell(
        _get_row_value(
            row_lower,
            "expected_output",
            "expected output",
            "ground_truth",
            "ground truth",
            "answer",
        )
    )
    metadata = _parse_csv_json_cell(_get_row_value(row_lower, "metadata"))
    source_trace_id = _get_row_value(
        row_lower,
        "source_trace_id",
        "source trace id",
        "source_trace",
    )
    source_observation_id = _get_row_value(
        row_lower,
        "source_observation_id",
        "source observation id",
        "source_observation",
    )
    trace_id = _get_row_value(row_lower, "trace_id", "trace id")
    use_trace_output_as_expected = _parse_csv_bool_cell(
        _get_row_value(row_lower, "use_trace_output_as_expected"),
        default=True,
    )
    return CreateDatasetItemRequest(
        input=item_input,
        expected_output=expected_output,
        metadata=metadata,
        source_trace_id=source_trace_id,
        source_observation_id=source_observation_id,
        trace_id=trace_id,
        use_trace_output_as_expected=use_trace_output_as_expected,
    )


def _dataset_to_response(dataset_obj: Any, *, item_count: int | None = None) -> DatasetResponse:
    """Serialize Langfuse dataset object to API response."""
    return DatasetResponse(
        id=str(get_attr(dataset_obj, "id", default="") or ""),
        name=str(get_attr(dataset_obj, "name", default="") or ""),
        description=get_attr(dataset_obj, "description", default=None),
        metadata=get_attr(dataset_obj, "metadata", default=None),
        created_at=get_attr(dataset_obj, "created_at", "createdAt", default=None),
        updated_at=get_attr(dataset_obj, "updated_at", "updatedAt", default=None),
        item_count=item_count,
    )


def _dataset_item_to_response(item_obj: Any) -> DatasetItemResponse:
    """Serialize Langfuse dataset item object to API response."""
    status = get_attr(item_obj, "status", default=None)
    if hasattr(status, "value"):
        status = status.value

    return DatasetItemResponse(
        id=str(get_attr(item_obj, "id", default="") or ""),
        dataset_name=str(get_attr(item_obj, "dataset_name", "datasetName", default="") or ""),
        status=str(status) if status is not None else None,
        input=get_attr(item_obj, "input", default=None),
        expected_output=get_attr(item_obj, "expected_output", "expectedOutput", default=None),
        metadata=get_attr(item_obj, "metadata", default=None),
        source_trace_id=get_attr(item_obj, "source_trace_id", "sourceTraceId", default=None),
        source_observation_id=get_attr(item_obj, "source_observation_id", "sourceObservationId", default=None),
        created_at=get_attr(item_obj, "created_at", "createdAt", default=None),
        updated_at=get_attr(item_obj, "updated_at", "updatedAt", default=None),
    )


def _dataset_run_to_response(run_obj: Any) -> DatasetRunResponse:
    """Serialize Langfuse dataset run object to API response."""
    return DatasetRunResponse(
        id=str(get_attr(run_obj, "id", default="") or ""),
        name=str(get_attr(run_obj, "name", default="") or ""),
        description=get_attr(run_obj, "description", default=None),
        metadata=get_attr(run_obj, "metadata", default=None),
        dataset_id=get_attr(run_obj, "dataset_id", "datasetId", default=None),
        dataset_name=get_attr(run_obj, "dataset_name", "datasetName", default=None),
        created_at=get_attr(run_obj, "created_at", "createdAt", default=None),
        updated_at=get_attr(run_obj, "updated_at", "updatedAt", default=None),
    )


def _dataset_run_item_to_detail_response(
    item_obj: Any,
    *,
    trace_dict: dict[str, Any] | None = None,
    scores: list[DatasetRunItemScoreResponse] | None = None,
) -> DatasetRunItemDetailResponse:
    """Serialize Langfuse dataset run item object to detailed response."""
    trace_dict = trace_dict or {}
    scores = scores or []
    trace_name = trace_dict.get("name")
    if trace_name is None:
        trace_name = get_attr(item_obj, "trace_name", "traceName", default=None)

    trace_input = trace_dict.get("input")
    if trace_input is None:
        trace_input = get_attr(item_obj, "input", default=None)

    trace_output = trace_dict.get("output")
    if trace_output is None:
        trace_output = get_attr(item_obj, "output", default=None)

    return DatasetRunItemDetailResponse(
        id=str(get_attr(item_obj, "id", default="") or ""),
        dataset_item_id=get_attr(item_obj, "dataset_item_id", "datasetItemId", default=None),
        trace_id=get_attr(item_obj, "trace_id", "traceId", default=None),
        observation_id=get_attr(item_obj, "observation_id", "observationId", default=None),
        created_at=get_attr(item_obj, "created_at", "createdAt", default=None),
        updated_at=get_attr(item_obj, "updated_at", "updatedAt", default=None),
        trace_name=str(trace_name) if trace_name is not None else None,
        trace_input=trace_input,
        trace_output=trace_output,
        score_count=len(scores),
        scores=scores,
    )


def _extract_run_item_evaluation_scores(item_obj: Any) -> list[DatasetRunItemScoreResponse]:
    """Extract evaluator scores directly from dataset run item payload."""
    rows: list[DatasetRunItemScoreResponse] = []
    evaluations = get_attr(item_obj, "evaluations", default=None) or []
    if not isinstance(evaluations, list):
        return rows

    for idx, evaluation in enumerate(evaluations, 1):
        value = get_attr(evaluation, "value", default=None)
        try:
            numeric_value = float(value)
        except Exception:
            continue
        rows.append(
            DatasetRunItemScoreResponse(
                id=str(get_attr(evaluation, "id", default=None) or f"run-eval-{idx}"),
                name=str(get_attr(evaluation, "name", default="Score") or "Score"),
                value=numeric_value,
                source="EXPERIMENT",
                comment=get_attr(evaluation, "comment", default=None),
                created_at=get_attr(evaluation, "created_at", "createdAt", default=None),
            )
        )
    return rows


def _set_dataset_experiment_job(job_id: str, **updates: Any) -> None:
    """Upsert in-memory dataset experiment job state."""
    with _DATASET_EXPERIMENT_JOBS_LOCK:
        current = _DATASET_EXPERIMENT_JOBS.get(job_id, {}).copy()
        current.update(updates)
        _DATASET_EXPERIMENT_JOBS[job_id] = current


def _get_dataset_experiment_job(job_id: str) -> dict[str, Any] | None:
    """Return a copy of in-memory dataset experiment job state."""
    with _DATASET_EXPERIMENT_JOBS_LOCK:
        current = _DATASET_EXPERIMENT_JOBS.get(job_id)
        return current.copy() if current else None


def _dataset_job_response(job_id: str, payload: dict[str, Any]) -> DatasetExperimentJobResponse:
    """Serialize internal dataset experiment job payload."""
    return DatasetExperimentJobResponse(
        job_id=job_id,
        status=str(payload.get("status") or "unknown"),
        dataset_name=str(payload.get("dataset_name") or ""),
        experiment_name=str(payload.get("experiment_name") or ""),
        started_at=payload.get("started_at"),
        finished_at=payload.get("finished_at"),
        error=payload.get("error"),
        result=payload.get("result"),
    )


def _to_text(value: Any) -> str:
    """Convert arbitrary payloads into compact text for prompts/inputs."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _build_experiment_evaluation(
    *,
    name: str,
    value: Any,
    comment: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Create a Langfuse experiment Evaluation object when available."""
    try:
        from langfuse import Evaluation as LangfuseEvaluation  # type: ignore

        kwargs: dict[str, Any] = {
            "name": name,
            "value": value,
            "comment": comment,
        }
        if metadata is not None:
            kwargs["metadata"] = metadata
        return LangfuseEvaluation(**kwargs)
    except Exception:
        return SimpleNamespace(name=name, value=value, comment=comment, metadata=metadata)


DATASET_PROMPT_CONTEXT_TEMPLATE = (
    "Input:\n"
    "Query: {{query}}\n"
    "Generation: {{generation}}\n"
    "Ground Truth: {{ground_truth}}"
)


def _ensure_dataset_prompt_template(criteria: str | None) -> str:
    """Ensure dataset judge criteria contains Query/Generation/Ground Truth placeholders."""
    base = str(criteria or "").strip()
    if not base:
        return DATASET_PROMPT_CONTEXT_TEMPLATE

    normalized = " ".join(base.lower().split())
    if "query: {{query}}" in normalized and "generation: {{generation}}" in normalized and "ground truth: {{ground_truth}}" in normalized:
        return base
    return f"{base}\n\n{DATASET_PROMPT_CONTEXT_TEMPLATE}"


def _render_dataset_judge_criteria(
    *,
    criteria: str | None,
    query: Any,
    generation: Any,
    ground_truth: Any,
) -> str:
    """Render criteria template placeholders with current dataset item values."""
    rendered = _ensure_dataset_prompt_template(criteria)
    replacements = {
        "{{query}}": _to_text(query) or "[EMPTY]",
        "{{generation}}": _to_text(generation) or "[EMPTY]",
        "{{ground_truth}}": _to_text(ground_truth) or "[NOT PROVIDED]",
    }
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    return rendered


def _extract_agent_output_from_run_response(run_response: Any) -> Any:
    """Best-effort extraction of final agent output from RunResponse variants."""
    outputs = get_attr(run_response, "outputs", default=None)
    if outputs is None and isinstance(run_response, dict):
        outputs = run_response.get("outputs")
    if not isinstance(outputs, list):
        if hasattr(run_response, "model_dump"):
            try:
                return run_response.model_dump()
            except Exception:
                return run_response
        return run_response

    text_candidates: list[str] = []
    value_candidates: list[Any] = []
    for run_output in outputs:
        result_entries = get_attr(run_output, "outputs", default=None)
        if not isinstance(result_entries, list):
            continue
        for result_data in result_entries:
            if result_data is None:
                continue
            messages = get_attr(result_data, "messages", default=None)
            if isinstance(messages, list):
                for msg in messages:
                    msg_value = get_attr(msg, "message", default=None)
                    if msg_value is not None:
                        value_candidates.append(msg_value)
                        if isinstance(msg_value, str) and msg_value.strip():
                            text_candidates.append(msg_value)

            output_map = get_attr(result_data, "outputs", default=None)
            if isinstance(output_map, dict):
                for output_entry in output_map.values():
                    out_value = get_attr(output_entry, "message", default=None)
                    if out_value is not None:
                        value_candidates.append(out_value)
                        if isinstance(out_value, str) and out_value.strip():
                            text_candidates.append(out_value)

            raw_result = get_attr(result_data, "results", default=None)
            if raw_result not in (None, "", {}, []):
                value_candidates.append(raw_result)

    if text_candidates:
        return text_candidates[-1]
    if value_candidates:
        return value_candidates[-1]
    if hasattr(run_response, "model_dump"):
        try:
            return run_response.model_dump()
        except Exception:
            pass
    return run_response


def _normalize_for_exact_match(value: Any) -> str:
    """Normalize values for exact-match evaluator comparison."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False).strip()
    except Exception:
        return str(value).strip()


def _run_async(coro):
    """Run coroutine in sync contexts, even if current thread already has a loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if not loop.is_running():
        return loop.run_until_complete(coro)

    container: dict[str, Any] = {}
    error_holder: dict[str, Exception] = {}

    def _runner():
        try:
            container["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            error_holder["error"] = exc

    t = Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    if "error" in error_holder:
        raise error_holder["error"]
    return container.get("value")


async def _run_dataset_item_with_agent(
    *,
    agent_payload: dict[str, Any],
    user_id: str,
    item_input: Any,
    session_id: str,
) -> Any:
    """Execute one dataset item input against a agent and return parsed output."""
    from agentcore.api.endpoints import simple_run_agent
    from agentcore.api.v1_schemas import SimplifiedAPIRequest

    agent_stub = SimpleNamespace(
        id=agent_payload["id"],
        name=agent_payload["name"],
        data=agent_payload["data"],
    )
    api_user_stub = SimpleNamespace(id=user_id)
    run_response = await simple_run_agent(
        agent=agent_stub,
        input_request=SimplifiedAPIRequest(
            input_value=_to_text(item_input),
            input_type="chat",
            output_type="chat",
            session_id=session_id,
        ),
        stream=False,
        api_key_user=api_user_stub,
    )
    return _extract_agent_output_from_run_response(run_response)


def _get_dataset_experiment_concurrency() -> int:
    """Resolve safe background concurrency for dataset experiments."""
    raw = str(os.getenv("EVALUATION_DATASET_MAX_CONCURRENCY") or "").strip()
    try:
        value = int(raw) if raw else 5
    except Exception:
        value = 5
    return max(1, min(20, value))


def _build_generation_messages(item_input: Any) -> list[dict[str, str]]:
    """Normalize dataset item input into chat-completion messages."""
    if isinstance(item_input, dict):
        maybe_messages = item_input.get("messages")
        if isinstance(maybe_messages, list):
            messages: list[dict[str, str]] = []
            for message in maybe_messages:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role") or "user")
                content = _to_text(message.get("content"))
                if content:
                    messages.append({"role": role, "content": content})
            if messages:
                return messages

        for key in ("query", "question", "prompt", "input", "message", "text"):
            if key in item_input and item_input.get(key) is not None:
                return [{"role": "user", "content": _to_text(item_input.get(key))}]

    return [{"role": "user", "content": _to_text(item_input) or ""}]


async def _call_openai_generation_completion(
    *,
    model_candidates: list[str],
    model_api_key: str | None,
    messages: list[dict[str, str]],
) -> tuple[str, str]:
    """Call OpenAI-compatible chat completion for generation with retries."""
    if openai is None:
        raise RuntimeError("OpenAI SDK not available")

    last_error: Exception | None = None
    for candidate_model in model_candidates:
        request_model = _model_name_for_openai_fallback(candidate_model)
        api_base = _resolve_api_base_for_model(candidate_model)
        api_key = _resolve_openai_fallback_api_key(candidate_model, explicit_api_key=model_api_key)
        if not api_key:
            env_names = ", ".join(_candidate_api_key_env_names(candidate_model))
            raise RuntimeError(
                f"No API key resolved for generation model '{candidate_model}'. "
                f"Provide model_api_key or set one of: {env_names}"
            )

        try:
            if hasattr(openai, "AsyncOpenAI"):
                client_kwargs: dict[str, Any] = {}
                if api_key:
                    client_kwargs["api_key"] = api_key
                if api_base:
                    client_kwargs["base_url"] = api_base
                async_client = openai.AsyncOpenAI(**client_kwargs)
                try:
                    resp = await async_client.chat.completions.create(
                        model=request_model,
                        messages=messages,
                    )
                finally:
                    close_func = getattr(async_client, "close", None)
                    if callable(close_func):
                        try:
                            await close_func()
                        except Exception:
                            pass
            elif hasattr(openai, "OpenAI"):
                client_kwargs = {}
                if api_key:
                    client_kwargs["api_key"] = api_key
                if api_base:
                    client_kwargs["base_url"] = api_base

                def _sync_call_v1():
                    sync_client = openai.OpenAI(**client_kwargs)
                    try:
                        return sync_client.chat.completions.create(
                            model=request_model,
                            messages=messages,
                        )
                    finally:
                        close_func = getattr(sync_client, "close", None)
                        if callable(close_func):
                            try:
                                close_func()
                            except Exception:
                                pass

                resp = await asyncio.to_thread(_sync_call_v1)
            else:
                if api_key:
                    openai.api_key = api_key
                if api_base:
                    openai.api_base = api_base
                chat_completion = getattr(openai, "ChatCompletion", None)
                if chat_completion and hasattr(chat_completion, "acreate"):
                    resp = await chat_completion.acreate(
                        model=request_model,
                        messages=messages,
                    )
                elif chat_completion and hasattr(chat_completion, "create"):

                    def _sync_call_legacy():
                        return chat_completion.create(
                            model=request_model,
                            messages=messages,
                        )

                    resp = await asyncio.to_thread(_sync_call_legacy)
                else:
                    raise RuntimeError("OpenAI SDK does not expose a supported chat completion API")

            content = _extract_openai_chat_content(resp)
            return content, request_model
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("Generation call failed for model={}: {}", candidate_model, str(exc))
            if _is_openai_retryable_model_error(exc):
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("Generation call failed without response")


async def _dataset_generate_with_model(
    *,
    model: str,
    model_api_key: str | None,
    item_input: Any,
) -> tuple[Any, str]:
    """Generate output for one dataset item via configured LLM model."""
    messages = _build_generation_messages(item_input)
    model_candidates = _build_litellm_model_candidates(model, model_api_key)
    if not model_candidates:
        raise RuntimeError("Invalid generation model configuration")

    if LITELLM_AVAILABLE:
        _ensure_litellm_logging_compatibility_patch()
        last_error: Exception | None = None
        for candidate_model in model_candidates:
            kwargs: Dict[str, Any] = {
                "model": candidate_model,
                "messages": messages,
                "no-log": True,
            }
            if model_api_key:
                kwargs["api_key"] = model_api_key
            api_base = _resolve_api_base_for_model(candidate_model)
            if api_base:
                kwargs["api_base"] = api_base
            try:
                response = await litellm.acompletion(**kwargs)
                content = response.choices[0].message.content
                return content if content is not None else "", candidate_model
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("LiteLLM generation failed for model={}: {}", candidate_model, str(exc))
                if _is_litellm_retryable_model_error(exc):
                    continue
                raise
        if last_error:
            raise last_error
        raise RuntimeError("LiteLLM generation failed without response")

    content, used_model = await _call_openai_generation_completion(
        model_candidates=model_candidates,
        model_api_key=model_api_key,
        messages=messages,
    )
    return content, used_model


async def _dataset_llm_evaluate(
    *,
    criteria: str,
    model: str,
    model_api_key: str | None,
    item_input: Any,
    output: Any,
    expected_output: Any,
) -> tuple[float, str, str]:
    """Run LLM-as-a-judge for one dataset item output and return normalized score."""
    query_text = _to_text(item_input) or "[EMPTY]"
    generation_text = _to_text(output) or "[EMPTY]"
    ground_truth_text = _to_text(expected_output) or "[NOT PROVIDED]"
    rendered_criteria = _render_dataset_judge_criteria(
        criteria=criteria,
        query=item_input,
        generation=output,
        ground_truth=expected_output,
    )

    system_prompt = (
        "You are an impartial AI judge evaluating an assistant output. "
        "Given criteria, query, generation, and ground truth, assign a score between 0 and 5 inclusive. "
        "Return JSON with keys score_0_5 and reason."
    )
    user_prompt = f"""### Criteria
{rendered_criteria}

### Input
Query: {query_text}
Generation: {generation_text}
Ground Truth: {ground_truth_text}

Respond ONLY with valid JSON:
{{
  "score_0_5": number,
  "reason": "short explanation"
}}
"""

    model_candidates = _build_litellm_model_candidates(model, model_api_key)
    if not model_candidates:
        raise RuntimeError("Invalid judge model configuration")

    content: str | None = None
    used_model = model_candidates[0]
    if LITELLM_AVAILABLE:
        _ensure_litellm_logging_compatibility_patch()
        last_error: Exception | None = None
        for candidate_model in model_candidates:
            kwargs: Dict[str, Any] = {
                "model": candidate_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "no-log": True,
            }
            if model_api_key:
                kwargs["api_key"] = model_api_key
            api_base = _resolve_api_base_for_model(candidate_model)
            if api_base:
                kwargs["api_base"] = api_base

            try:
                response = await litellm.acompletion(**kwargs)
                content = response.choices[0].message.content
                used_model = candidate_model
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if _is_litellm_retryable_model_error(exc):
                    continue
                raise

        if content is None:
            if last_error:
                raise last_error
            raise RuntimeError("LLM evaluator failed without response")
    else:
        content, used_model = await _call_openai_judge_completion(
            model_candidates=model_candidates,
            model_api_key=model_api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    payload = str(content or "").strip()
    if payload.startswith("```json"):
        payload = payload[7:]
    if payload.startswith("```"):
        payload = payload[3:]
    if payload.endswith("```"):
        payload = payload[:-3]
    payload = payload.strip()
    decoded = json.loads(payload)
    raw_score = decoded.get("score_0_5", decoded.get("score", 0))
    score_0_5 = max(0.0, min(5.0, float(raw_score)))
    reason = str(decoded.get("reason") or "No reason provided")
    return score_0_5 / 5.0, reason, used_model


def _list_all_datasets_for_user(client: Any, user_id: str, *, max_rows: int = 500) -> list[Any]:
    """Fetch datasets and apply best-effort user scoping."""
    collected: list[Any] = []
    if hasattr(client, "api") and hasattr(client.api, "datasets") and hasattr(client.api.datasets, "list"):
        page = 1
        page_size = min(100, max_rows)
        while len(collected) < max_rows:
            try:
                response = client.api.datasets.list(page=page, limit=page_size)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Dataset list via api.datasets.list failed at page {}: {}", page, str(exc))
                break

            rows, _ = _parse_paginated_response(response)
            if not rows:
                break
            collected.extend(rows)
            if len(rows) < page_size:
                break
            page += 1

    filtered = [dataset for dataset in collected if _dataset_owned_by_user(dataset, user_id)]
    filtered.sort(
        key=lambda dataset: _parse_trace_timestamp(get_attr(dataset, "created_at", "createdAt", default=None))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return filtered[:max_rows]


def _fetch_dataset_items_page(client: Any, dataset_name: str, page: int, limit: int) -> tuple[list[Any], int]:
    """Fetch one page of dataset items using SDK-compatible APIs."""
    if hasattr(client, "api") and hasattr(client.api, "dataset_items") and hasattr(client.api.dataset_items, "list"):
        response = client.api.dataset_items.list(dataset_name=dataset_name, page=page, limit=limit)
        rows, total = _parse_paginated_response(response)
        return rows, int(total) if total is not None else len(rows)

    dataset = client.get_dataset(dataset_name)
    rows = list(getattr(dataset, "items", []) or [])
    total_rows = len(rows)
    start = (page - 1) * limit
    return rows[start:start + limit], total_rows


def _fetch_dataset_runs_page(client: Any, dataset_name: str, page: int, limit: int) -> tuple[list[Any], int]:
    """Fetch one page of dataset runs using SDK-compatible APIs."""
    if hasattr(client, "get_dataset_runs"):
        response = client.get_dataset_runs(dataset_name=dataset_name, page=page, limit=limit)
        rows, total = _parse_paginated_response(response)
        return rows, int(total) if total is not None else len(rows)

    if hasattr(client, "api") and hasattr(client.api, "datasets") and hasattr(client.api.datasets, "get_runs"):
        response = client.api.datasets.get_runs(dataset_name=dataset_name, page=page, limit=limit)
        rows, total = _parse_paginated_response(response)
        return rows, int(total) if total is not None else len(rows)

    return [], 0


def _find_dataset_run_by_id(
    client: Any,
    *,
    dataset_name: str,
    run_id: str,
    max_scan: int = 1000,
) -> Any | None:
    """Find dataset run object by id using paginated scans."""
    page_size = min(100, max_scan)
    scanned = 0
    page = 1
    while scanned < max_scan:
        rows, _ = _fetch_dataset_runs_page(client, dataset_name, page, page_size)
        if not rows:
            break
        for row in rows:
            if str(get_attr(row, "id", default="") or "") == str(run_id):
                return row
        scanned += len(rows)
        if len(rows) < page_size:
            break
        page += 1
    return None


def _fetch_dataset_run_items(
    client: Any,
    *,
    dataset_name: str,
    dataset_id: str | None,
    run_name: str,
    item_limit: int,
) -> list[Any]:
    """Fetch run items for a dataset run."""
    if hasattr(client, "api") and hasattr(client.api, "datasets") and hasattr(client.api.datasets, "get_run"):
        try:
            run_with_items = client.api.datasets.get_run(dataset_name=dataset_name, run_name=run_name)
            run_items = get_attr(run_with_items, "dataset_run_items", "datasetRunItems", default=[]) or []
            return list(run_items)[:item_limit]
        except Exception as exc:  # noqa: BLE001
            logger.debug("api.datasets.get_run failed for dataset={} run={}: {}", dataset_name, run_name, str(exc))

    if (
        dataset_id
        and hasattr(client, "api")
        and hasattr(client.api, "dataset_run_items")
        and hasattr(client.api.dataset_run_items, "list")
    ):
        page = 1
        page_size = min(100, item_limit)
        collected: list[Any] = []
        while len(collected) < item_limit:
            response = client.api.dataset_run_items.list(
                dataset_id=dataset_id,
                run_name=run_name,
                page=page,
                limit=page_size,
            )
            rows, _ = _parse_paginated_response(response)
            if not rows:
                break
            collected.extend(rows)
            if len(rows) < page_size:
                break
            page += 1
        return collected[:item_limit]

    return []


def _fetch_all_dataset_items(
    client: Any,
    *,
    dataset_name: str,
    max_rows: int = 5000,
) -> list[Any]:
    """Fetch dataset items across pages with a hard safety cap."""
    collected: list[Any] = []
    page = 1
    page_size = min(100, max_rows)
    while len(collected) < max_rows:
        rows, _ = _fetch_dataset_items_page(client, dataset_name, page, page_size)
        if not rows:
            break
        collected.extend(rows)
        if len(rows) < page_size:
            break
        page += 1
    return collected[:max_rows]


def _fetch_all_dataset_runs(
    client: Any,
    *,
    dataset_name: str,
    max_rows: int = 2000,
) -> list[Any]:
    """Fetch dataset runs across pages with a hard safety cap."""
    collected: list[Any] = []
    page = 1
    page_size = min(100, max_rows)
    while len(collected) < max_rows:
        rows, _ = _fetch_dataset_runs_page(client, dataset_name, page, page_size)
        if not rows:
            break
        collected.extend(rows)
        if len(rows) < page_size:
            break
        page += 1
    return collected[:max_rows]


def _fetch_dataset_item_by_id(client: Any, item_id: str) -> Any | None:
    """Fetch one dataset item by id if SDK exposes a direct getter."""
    if hasattr(client, "api") and hasattr(client.api, "dataset_items") and hasattr(client.api.dataset_items, "get"):
        try:
            return client.api.dataset_items.get(id=item_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("dataset_items.get failed for item_id={}: {}", item_id, str(exc))
    return None


def _delete_dataset_item(client: Any, item_id: str) -> None:
    """Delete one dataset item via SDK-compatible APIs."""
    if hasattr(client, "api") and hasattr(client.api, "dataset_items") and hasattr(client.api.dataset_items, "delete"):
        client.api.dataset_items.delete(id=item_id)
        return
    raise RuntimeError("Dataset item deletion is not supported by current Langfuse SDK")


def _delete_dataset_run(client: Any, *, dataset_name: str, run_name: str) -> None:
    """Delete one dataset run via SDK-compatible APIs."""
    if hasattr(client, "delete_dataset_run"):
        client.delete_dataset_run(dataset_name=dataset_name, run_name=run_name)
        return
    if hasattr(client, "api") and hasattr(client.api, "datasets") and hasattr(client.api.datasets, "delete_run"):
        client.api.datasets.delete_run(dataset_name=dataset_name, run_name=run_name)
        return
    raise RuntimeError("Dataset run deletion is not supported by current Langfuse SDK")

_KNOWN_LITELLM_PROVIDERS = {
    "openai",
    "azure",
    "anthropic",
    "groq",
    "gemini",
    "google",
    "vertex_ai",
    "bedrock",
    "openrouter",
    "mistral",
    "cohere",
    "huggingface",
    "ollama",
    "togetherai",
    "fireworks_ai",
    "xai",
    "replicate",
    "perplexity",
    "sambanova",
    "deepseek",
    "watsonx",
}


def _split_known_provider_prefix(model: str) -> tuple[str | None, str]:
    """Split known LiteLLM provider prefix from model string if present."""
    value = str(model or "").strip()
    if not value or "/" not in value:
        return None, value
    prefix, tail = value.split("/", 1)
    if prefix.strip().lower() in _KNOWN_LITELLM_PROVIDERS:
        return prefix.strip().lower(), tail.strip()
    return None, value


def _infer_litellm_provider(model: str, api_key: str | None = None) -> str | None:
    """Infer LiteLLM provider from model/API key/environment."""
    explicit_provider = os.getenv("LITELLM_DEFAULT_PROVIDER")
    if explicit_provider:
        value = explicit_provider.strip().lower()
        if value:
            return value

    prefixed_provider, _ = _split_known_provider_prefix(model)
    if prefixed_provider:
        return prefixed_provider

    key = str(api_key or "").strip()
    if key.startswith("gsk_"):
        return "groq"
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith("sk-or-"):
        return "openrouter"
    if key.startswith("hf_"):
        return "huggingface"
    if key.startswith("xai-"):
        return "xai"
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith("sk-"):
        return "openai"

    model_lower = str(model or "").strip().lower()
    if not model_lower:
        return None
    if model_lower.startswith(("gpt-", "o1", "o3", "o4", "text-embedding-")):
        return "openai"
    if "claude" in model_lower:
        return "anthropic"
    if "gemini" in model_lower:
        return "gemini"
    return None


def _normalize_model_name_for_provider(model_name: str, provider_hint: str | None = None) -> str:
    """Normalize human-entered model names into provider-friendly ids."""
    value = str(model_name or "").strip()
    if not value:
        return value

    lowered = value.lower()
    if lowered.startswith("models/"):
        value = value.split("/", 1)[1].strip()

    provider = (provider_hint or "").strip().lower()
    if provider in {"gemini", "google", "vertex_ai"}:
        # Gemini/Google model ids are slug-like (e.g. gemini-2.5-flash-lite).
        value = value.replace("_", "-")
        value = re.sub(r"\s+", "-", value.strip())
        value = re.sub(r"[^A-Za-z0-9._:\-]", "-", value)
        value = re.sub(r"-{2,}", "-", value).strip("-").lower()
        return value

    # Generic cleanup for obvious display labels containing spaces.
    if " " in value:
        compact = re.sub(r"\s+", "-", value.strip())
        compact = re.sub(r"[^A-Za-z0-9._:/\-]", "-", compact)
        compact = re.sub(r"-{2,}", "-", compact).strip("-")
        if compact:
            return compact
    return value


def _build_model_name_variants(model_name: str, provider_hint: str | None = None) -> list[str]:
    """Build ordered model-name variants from a user-entered model field."""
    raw = str(model_name or "").strip()
    if not raw:
        return []

    variants: list[str] = []
    normalized = _normalize_model_name_for_provider(raw, provider_hint)
    if normalized and normalized != raw:
        variants.append(normalized)
    variants.append(raw)

    if "/" in raw:
        _, tail = raw.split("/", 1)
        tail = tail.strip()
        if tail:
            tail_normalized = _normalize_model_name_for_provider(tail, provider_hint)
            if tail_normalized and tail_normalized not in variants:
                variants.append(tail_normalized)
            if tail not in variants:
                variants.append(tail)

    deduped: list[str] = []
    seen: set[str] = set()
    for value in variants:
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _build_litellm_model_candidates(model: str, api_key: str | None = None) -> list[str]:
    """Build model candidates for LiteLLM retries with provider inference."""
    raw = str(model or "").strip()
    if not raw:
        return []

    provider, raw_tail = _split_known_provider_prefix(raw)
    inferred_provider = _infer_litellm_provider(raw, api_key)
    provider_hint = provider or inferred_provider
    candidates: list[str] = []

    def add_candidate(value: str) -> None:
        value = value.strip()
        if value and value not in candidates:
            candidates.append(value)

    if provider:
        tail_variants = _build_model_name_variants(raw_tail, provider_hint=provider)
        for tail in tail_variants:
            add_candidate(f"{provider}/{tail}")
        add_candidate(raw)
    else:
        name_variants = _build_model_name_variants(raw, provider_hint=provider_hint)
        if inferred_provider:
            for name in name_variants:
                add_candidate(f"{inferred_provider}/{name}")
        for name in name_variants:
            add_candidate(name)

    # OpenAI-compatible fallback for custom model names when base URL is configured.
    openai_base = os.getenv("OPENAI_API_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    if not provider and openai_base:
        for name in _build_model_name_variants(raw, provider_hint="openai"):
            add_candidate(f"openai/{name}")

    return candidates


def _is_litellm_provider_error(exc: Exception) -> bool:
    """Return True when LiteLLM error indicates provider/model prefix mismatch."""
    message = str(exc).lower()
    return (
        "llm provider not provided" in message
        or "pass in the llm provider" in message
        or "provider not found" in message
        or "unknown provider" in message
    )


def _is_litellm_retryable_model_error(exc: Exception) -> bool:
    """Return True when retrying with alternate model candidates may succeed."""
    if _is_litellm_provider_error(exc):
        return True

    message = str(exc).lower()
    return (
        "unexpected model name format" in message
        or "generatecontentrequest.model" in message
        or "invalid_argument" in message
        or "invalid model" in message
        or "model not found" in message
        or "unknown model" in message
    )


def _resolve_api_base_for_model(model: str) -> str | None:
    """Resolve provider-specific API base from environment when available."""
    provider, _ = _split_known_provider_prefix(model)
    # Global override first.
    global_base = os.getenv("LITELLM_API_BASE")
    if global_base:
        return global_base

    if provider == "openai":
        return os.getenv("OPENAI_API_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    if provider == "groq":
        return os.getenv("GROQ_API_BASE_URL") or os.getenv("GROQ_BASE_URL") or "https://api.groq.com/openai/v1"
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_API_BASE_URL")
    if provider == "openrouter":
        return os.getenv("OPENROUTER_API_BASE_URL") or "https://openrouter.ai/api/v1"
    if provider in {"gemini", "google", "vertex_ai"}:
        return (
            os.getenv("GEMINI_API_BASE_URL")
            or os.getenv("GOOGLE_API_BASE_URL")
            or os.getenv("VERTEX_API_BASE_URL")
            or "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
    return None


def _resolve_openai_fallback_api_key(model: str, explicit_api_key: str | None = None) -> str | None:
    """Resolve API key for OpenAI SDK fallback based on model/provider."""
    value = str(explicit_api_key or "").strip()
    if value:
        return value

    provider = _infer_litellm_provider(model)
    env_by_provider: dict[str, list[str]] = {
        "openai": ["OPENAI_API_KEY"],
        "azure": ["AZURE_OPENAI_API_KEY", "OPENAI_API_KEY"],
        "groq": ["GROQ_API_KEY"],
        "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "vertex_ai": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "anthropic": ["ANTHROPIC_API_KEY"],
        "openrouter": ["OPENROUTER_API_KEY"],
    }

    env_names = env_by_provider.get(provider or "", [])
    if not env_names:
        env_names = ["OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY"]
    for env_name in env_names:
        env_value = str(os.getenv(env_name) or "").strip()
        if env_value:
            return env_value
    return None


def _candidate_api_key_env_names(model: str) -> list[str]:
    """Return likely API key environment variables for the model provider."""
    provider = _infer_litellm_provider(model)
    mapping: dict[str, list[str]] = {
        "openai": ["OPENAI_API_KEY"],
        "azure": ["AZURE_OPENAI_API_KEY", "OPENAI_API_KEY"],
        "groq": ["GROQ_API_KEY"],
        "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "vertex_ai": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "anthropic": ["ANTHROPIC_API_KEY"],
        "openrouter": ["OPENROUTER_API_KEY"],
    }
    return mapping.get(provider or "", ["OPENAI_API_KEY"])


def _model_name_for_openai_fallback(model: str) -> str:
    """Strip provider prefixes (e.g. 'groq/') for OpenAI-compatible SDK calls."""
    _, tail = _split_known_provider_prefix(model)
    value = tail.strip() if tail else str(model or "").strip()
    return value or str(model or "").strip()


def _is_openai_retryable_model_error(exc: Exception) -> bool:
    """Return True when retrying with another model candidate may succeed."""
    message = str(exc).lower()
    return (
        "model not found" in message
        or "unknown model" in message
        or "invalid model" in message
        or "does not exist" in message
        or "unexpected model name format" in message
        or "llm provider not provided" in message
        or "provider not found" in message
        or "generatecontentrequest.model" in message
    )


def _is_openai_response_format_error(exc: Exception) -> bool:
    """Return True when provider rejects JSON response_format."""
    message = str(exc).lower()
    return "response_format" in message or "json_object" in message


def _extract_openai_chat_content(resp: Any) -> str:
    """Extract message content from OpenAI chat completion response variants."""
    choices = resp.get("choices", []) if isinstance(resp, dict) else getattr(resp, "choices", [])
    if not choices:
        raise RuntimeError("OpenAI judge returned no choices")

    first_choice = choices[0]
    if isinstance(first_choice, dict):
        message = first_choice.get("message", {}) or {}
        content = message.get("content")
    else:
        message = getattr(first_choice, "message", None)
        content = getattr(message, "content", None) if message is not None else None

    if isinstance(content, list):
        # Some OpenAI-compatible providers return structured content blocks.
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
            else:
                text = getattr(part, "text", None)
            if text:
                text_parts.append(str(text))
        content = "".join(text_parts)

    if content is None:
        raise RuntimeError("OpenAI judge returned empty content")
    return str(content)


async def _call_openai_judge_completion(
    *,
    model_candidates: list[str],
    model_api_key: str | None,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, str]:
    """Call OpenAI SDK (v1/v2 or legacy) with retries across model candidates."""
    if openai is None:
        raise RuntimeError("OpenAI SDK not available")

    last_error: Exception | None = None
    for candidate_model in model_candidates:
        request_model = _model_name_for_openai_fallback(candidate_model)
        api_base = _resolve_api_base_for_model(candidate_model)
        api_key = _resolve_openai_fallback_api_key(candidate_model, explicit_api_key=model_api_key)
        if not api_key:
            env_names = ", ".join(_candidate_api_key_env_names(candidate_model))
            raise RuntimeError(
                f"No API key resolved for judge model '{candidate_model}'. "
                f"Provide model_api_key or set one of: {env_names}"
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            if hasattr(openai, "AsyncOpenAI"):
                client_kwargs: dict[str, Any] = {}
                if api_key:
                    client_kwargs["api_key"] = api_key
                if api_base:
                    client_kwargs["base_url"] = api_base
                async_client = openai.AsyncOpenAI(**client_kwargs)
                try:
                    resp = await async_client.chat.completions.create(
                        model=request_model,
                        messages=messages,
                        response_format={"type": "json_object"},
                    )
                except Exception as response_format_exc:
                    if not _is_openai_response_format_error(response_format_exc):
                        raise
                    resp = await async_client.chat.completions.create(
                        model=request_model,
                        messages=messages,
                    )
                finally:
                    close_func = getattr(async_client, "close", None)
                    if callable(close_func):
                        try:
                            await close_func()
                        except Exception:
                            pass
            elif hasattr(openai, "OpenAI"):
                client_kwargs = {}
                if api_key:
                    client_kwargs["api_key"] = api_key
                if api_base:
                    client_kwargs["base_url"] = api_base

                def _sync_call_v1():
                    sync_client = openai.OpenAI(**client_kwargs)
                    try:
                        try:
                            return sync_client.chat.completions.create(
                                model=request_model,
                                messages=messages,
                                response_format={"type": "json_object"},
                            )
                        except Exception as response_format_exc:
                            if not _is_openai_response_format_error(response_format_exc):
                                raise
                            return sync_client.chat.completions.create(
                                model=request_model,
                                messages=messages,
                            )
                    finally:
                        close_func = getattr(sync_client, "close", None)
                        if callable(close_func):
                            try:
                                close_func()
                            except Exception:
                                pass

                resp = await asyncio.to_thread(_sync_call_v1)
            else:
                if api_key:
                    openai.api_key = api_key
                if api_base:
                    openai.api_base = api_base

                chat_completion = getattr(openai, "ChatCompletion", None)
                if chat_completion and hasattr(chat_completion, "acreate"):
                    resp = await chat_completion.acreate(
                        model=request_model,
                        messages=messages,
                    )
                elif chat_completion and hasattr(chat_completion, "create"):
                    def _sync_call_legacy():
                        return chat_completion.create(
                            model=request_model,
                            messages=messages,
                        )

                    resp = await asyncio.to_thread(_sync_call_legacy)
                else:
                    raise RuntimeError("OpenAI SDK does not expose a supported chat completion API")

            content = _extract_openai_chat_content(resp)
            return content, request_model
        except Exception as e:
            last_error = e
            logger.warning("OpenAI judge call failed for model={}: {}", candidate_model, str(e))
            if _is_openai_retryable_model_error(e):
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("OpenAI judge call failed without a response")


def _submit_score_to_langfuse(
    client: Any,
    *,
    trace_id: str,
    name: str,
    value: float,
    comment: str | None = None,
    observation_id: str | None = None,
    source: str | None = None,
) -> None:
    """Submit score using SDK-compatible method across Langfuse versions."""
    payload: Dict[str, Any] = {
        "trace_id": trace_id,
        "name": name,
        "value": value,
        "comment": comment,
    }
    if observation_id:
        payload["observation_id"] = observation_id
    if source:
        payload["source"] = source

    payload_variants = [payload]
    if "source" in payload:
        payload_variants.append({k: v for k, v in payload.items() if k != "source"})
    if "observation_id" in payload:
        payload_variants.append({k: v for k, v in payload.items() if k != "observation_id"})
    if "source" in payload and "observation_id" in payload:
        payload_variants.append({k: v for k, v in payload.items() if k not in {"source", "observation_id"}})

    def _call_with_compatible_kwargs(func) -> bool:
        last_error: TypeError | None = None
        for kwargs in payload_variants:
            try:
                func(**kwargs)
                return True
            except TypeError as exc:
                last_error = exc
        if last_error:
            raise last_error
        return False

    # v2-style helper
    if hasattr(client, "score"):
        if _call_with_compatible_kwargs(client.score):
            return

    # v3-style helper
    if hasattr(client, "create_score"):
        if _call_with_compatible_kwargs(client.create_score):
            return

    # Direct API fallbacks (SDK internals)
    if hasattr(client, "api"):
        api_obj = getattr(client, "api")
        for attr in ("score", "scores"):
            score_api = getattr(api_obj, attr, None)
            if score_api and hasattr(score_api, "create"):
                if _call_with_compatible_kwargs(score_api.create):
                    return

    if hasattr(client, "client") and hasattr(client.client, "scores"):
        scores_client = client.client.scores
        if hasattr(scores_client, "create"):
            if _call_with_compatible_kwargs(scores_client.create):
                return

    raise RuntimeError("No supported score submission method found on Langfuse client")


def _extract_trace_run_id(trace_dict: Dict[str, Any]) -> str | None:
    """Extract run identifier from trace metadata/tags."""
    metadata = trace_dict.get("metadata")
    if isinstance(metadata, dict):
        run_id = metadata.get("run_id") or metadata.get("runId")
        if run_id:
            return str(run_id)

    tags = trace_dict.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("run_id:"):
                value = tag.split(":", 1)[1].strip()
                if value:
                    return value
    return None


def _extract_trace_user_id(trace_dict: Dict[str, Any]) -> str | None:
    """Extract user id from top-level fields or metadata/tags."""
    user_id = trace_dict.get("user_id")
    if user_id:
        return str(user_id)

    metadata = trace_dict.get("metadata")
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            metadata = parsed if isinstance(parsed, dict) else metadata
        except Exception:
            pass
    if isinstance(metadata, dict):
        value = (
            metadata.get("user_id")
            or metadata.get("userId")
            or metadata.get("app_user_id")
            or metadata.get("created_by_user_id")
            or metadata.get("owner_user_id")
        )
        if value:
            return str(value)

    tags = trace_dict.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, str):
                continue
            for prefix in ("user_id:", "app_user_id:", "created_by_user_id:"):
                if tag.startswith(prefix):
                    value = tag.split(":", 1)[1].strip()
                    if value:
                        return value
    return None


def _normalize_agent_id(agent_id: str | None) -> str | None:
    """Normalize agent identifiers from UI/API inputs."""
    if not agent_id:
        return None
    value = str(agent_id).strip()
    if value.startswith("lb:"):
        value = value.split("lb:", 1)[1]
    return value or None


def _normalize_targets(target: Union[str, List[str], None]) -> List[str]:
    """Normalize target input to a lowercase list."""
    if target is None:
        return ["existing"]
    if isinstance(target, str):
        values = [target]
    elif isinstance(target, list):
        values = target
    else:
        values = []
    normalized = [str(t).strip().lower() for t in values if str(t).strip()]
    return list(dict.fromkeys(normalized))


def _normalize_agent_ids(agent_ids: Optional[List[str]]) -> List[str]:
    """Normalize and de-duplicate agent ids."""
    if not agent_ids:
        return []
    normalized: List[str] = []
    for agent_id in agent_ids:
        value = _normalize_agent_id(agent_id)
        if value:
            normalized.append(value)
    return list(dict.fromkeys(normalized))


def _extract_trace_agent_id(trace_dict: Dict[str, Any]) -> str | None:
    """Extract agent id from trace metadata/tags."""
    metadata = trace_dict.get("metadata")
    if isinstance(metadata, dict):
        agent_id = _normalize_agent_id(metadata.get("agent_id") or metadata.get("agentId"))
        if agent_id:
            return agent_id

    tags = trace_dict.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("agent_id:"):
                agent_id = _normalize_agent_id(tag.split(":", 1)[1])
                if agent_id:
                    return agent_id
    return None


def _extract_trace_agent_name(trace_dict: Dict[str, Any]) -> str | None:
    """Extract agent name from trace metadata/tags/name."""
    metadata = trace_dict.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("agent_name") or metadata.get("agentName")
        if value:
            return str(value)

    tags = trace_dict.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("agent_name:"):
                return tag.split(":", 1)[1]

    name = trace_dict.get("name")
    return str(name) if name else None


def _extract_trace_project_name(trace_dict: Dict[str, Any]) -> str | None:
    """Extract project name from trace metadata/tags."""
    metadata = trace_dict.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("project_name") or metadata.get("projectName")
        if value:
            return str(value)

    tags = trace_dict.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("project_name:"):
                return tag.split(":", 1)[1]
    return None


def _parse_trace_timestamp(value: Any) -> datetime | None:
    """Parse trace timestamp from datetime/string/epoch variants."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        epoch = float(value)
        # Handle millisecond epoch values.
        if epoch > 10_000_000_000:
            epoch = epoch / 1000.0
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    try:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _trace_matches_evaluator_filters(
    trace_dict: Dict[str, Any],
    *,
    trace_id: str | None = None,
    session_id: str | None = None,
    agent_id: str | None = None,
    agent_ids: Optional[List[str]] = None,
    agent_name: str | None = None,
    project_name: str | None = None,
    ts_from: datetime | None = None,
    ts_to: datetime | None = None,
) -> bool:
    """Check whether a trace satisfies evaluator filters."""
    trace_trace_id = str(trace_dict.get("id") or "")
    trace_run_id = _extract_trace_run_id(trace_dict)
    trace_session_id = str(trace_dict.get("session_id") or "")
    trace_agent_id = _extract_trace_agent_id(trace_dict)
    trace_agent_name = _extract_trace_agent_name(trace_dict) or ""
    trace_project_name = _extract_trace_project_name(trace_dict) or ""
    trace_ts = _parse_trace_timestamp(trace_dict.get("timestamp"))

    normalized_agent_id = _normalize_agent_id(agent_id)
    normalized_agent_ids = set(_normalize_agent_ids(agent_ids))

    if trace_id and str(trace_id) not in {trace_trace_id, str(trace_run_id or "")}:
        return False
    if session_id and str(session_id) != trace_session_id:
        return False

    # Strict agent filtering: if filters are present and trace does not expose a matching agent_id, reject.
    if normalized_agent_id:
        if not trace_agent_id or trace_agent_id != normalized_agent_id:
            return False
    if normalized_agent_ids:
        if not trace_agent_id or trace_agent_id not in normalized_agent_ids:
            return False

    if agent_name and agent_name.lower() not in trace_agent_name.lower():
        return False
    if project_name and project_name.lower() not in trace_project_name.lower():
        return False

    if ts_from and trace_ts and trace_ts < ts_from:
        return False
    if ts_to and trace_ts and trace_ts > ts_to:
        return False
    if (ts_from or ts_to) and trace_ts is None:
        return False

    return True


def _parse_iso_datetime_or_400(value: str | None, field_name: str) -> datetime | None:
    """Parse ISO datetime and raise HTTP 400 on invalid values."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}. Use ISO datetime format.")


def _fetch_trace_by_id(client, trace_id: str) -> Any | None:
    """Fetch a trace by id using available SDK methods."""
    if not trace_id:
        return None

    fetch_methods = [
        ("fetch_trace", lambda: client.fetch_trace(trace_id)),
        ("client.traces.get", lambda: client.client.traces.get(trace_id)),
        ("api.trace.get", lambda: client.api.trace.get(trace_id)),
    ]

    for method_name, method in fetch_methods:
        try:
            if method_name == "fetch_trace" and not hasattr(client, "fetch_trace"):
                continue
            if method_name == "client.traces.get":
                if not (hasattr(client, "client") and hasattr(client.client, "traces")):
                    continue
            if method_name == "api.trace.get":
                if not (hasattr(client, "api") and hasattr(client.api, "trace")):
                    continue

            response = method()
            if response is None:
                continue
            return response.data if hasattr(response, "data") else response
        except Exception as e:
            logger.debug(
                "Trace fetch via {} failed for trace_id={}: {}",
                method_name,
                trace_id,
                str(e),
            )

    return None


def _choose_trace_candidate(
    traces: List[Any],
    *,
    requested_trace_id: str,
    user_id: str,
    session_id: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    project_name: str | None = None,
    timestamp: datetime | None = None,
) -> Dict[str, Any] | None:
    """Choose the best matching trace from a list using contextual scoring."""
    normalized_agent_id = _normalize_agent_id(agent_id)
    requested_session = str(session_id) if session_id else None
    requested_agent_name = str(agent_name).lower() if agent_name else None
    requested_project_name = str(project_name).lower() if project_name else None
    requested_user_id = str(user_id) if user_id else None

    scored_candidates: List[tuple[float, Dict[str, Any]]] = []
    for raw_trace in traces or []:
        trace_dict = parse_trace_data(raw_trace)
        candidate_trace_id = str(trace_dict.get("id") or "")
        if not candidate_trace_id:
            continue

        candidate_user_id = str(_extract_trace_user_id(trace_dict) or "")
        candidate_session_id = str(trace_dict.get("session_id") or "")
        candidate_agent_id = _extract_trace_agent_id(trace_dict)
        candidate_agent_name = (_extract_trace_agent_name(trace_dict) or "").lower()
        candidate_project_name = (_extract_trace_project_name(trace_dict) or "").lower()
        candidate_run_id = _extract_trace_run_id(trace_dict)
        candidate_ts = _parse_trace_timestamp(trace_dict.get("timestamp"))

        # Keep user isolation strict if the trace payload includes user id.
        if requested_user_id and candidate_user_id and candidate_user_id != requested_user_id:
            continue

        # Exclude explicit conflicts for session/agent when candidate provides those fields.
        if requested_session and candidate_session_id and candidate_session_id != requested_session:
            continue
        if normalized_agent_id and candidate_agent_id and candidate_agent_id != normalized_agent_id:
            continue
        if requested_project_name and candidate_project_name and requested_project_name not in candidate_project_name:
            continue

        score = 0.0
        if requested_trace_id and candidate_trace_id == requested_trace_id:
            score += 500.0
        if requested_trace_id and candidate_run_id and str(candidate_run_id) == requested_trace_id:
            score += 450.0
        if requested_session and candidate_session_id == requested_session:
            score += 140.0
        if normalized_agent_id and candidate_agent_id == normalized_agent_id:
            score += 120.0
        if requested_agent_name and requested_agent_name in candidate_agent_name:
            score += 50.0
        if requested_project_name and requested_project_name in candidate_project_name:
            score += 35.0

        if timestamp and candidate_ts:
            delta_seconds = abs((candidate_ts - timestamp).total_seconds())
            if delta_seconds <= 2:
                score += 100.0
            elif delta_seconds <= 10:
                score += 80.0
            elif delta_seconds <= 30:
                score += 60.0
            elif delta_seconds <= 120:
                score += 40.0
            elif delta_seconds <= 600:
                score += 15.0
            else:
                score -= 20.0

        scored_candidates.append((score, trace_dict))

    if not scored_candidates:
        return None

    scored_candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_trace = scored_candidates[0]

    # Confidence gate to avoid evaluating the wrong trace.
    enough_context = bool(
        (session_id and str(best_trace.get("session_id") or "") == str(session_id))
        or (
            normalized_agent_id
            and _extract_trace_agent_id(best_trace)
            and _extract_trace_agent_id(best_trace) == normalized_agent_id
        )
        or (
            requested_trace_id
            and (
                str(best_trace.get("id") or "") == requested_trace_id
                or _extract_trace_run_id(best_trace) == requested_trace_id
            )
        )
    )
    if not enough_context and best_score < 180.0:
        return None

    return best_trace


async def _resolve_trace_for_judge(
    client,
    *,
    trace_id: str,
    user_id: str,
    session_id: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    project_name: str | None = None,
    timestamp: datetime | None = None,
    max_attempts: int = 8,
) -> tuple[str | None, Dict[str, Any] | None]:
    """Resolve the canonical Langfuse trace id and trace payload for judging."""
    trace_id = str(trace_id)
    resolved_timestamp = _parse_trace_timestamp(timestamp) or datetime.now(timezone.utc)

    for attempt in range(1, max_attempts + 1):
        # Step 1: direct fetch by id (fast-path for existing traces)
        fetched_trace = _fetch_trace_by_id(client, trace_id)
        if fetched_trace:
            trace_dict = parse_trace_data(fetched_trace)
            fetched_id = str(trace_dict.get("id") or trace_id)
            fetched_user_id = str(trace_dict.get("user_id") or "")
            if not fetched_user_id or fetched_user_id == str(user_id):
                return fetched_id, trace_dict
            logger.warning(
                f"Resolved trace {fetched_id} belongs to different user_id={fetched_user_id}; expected={user_id}"
            )

        # Step 2: fallback lookup by context among user traces.
        window_minutes = min(2 + (attempt * 3), 30)
        from_ts = resolved_timestamp - timedelta(minutes=window_minutes)
        to_ts = resolved_timestamp + timedelta(minutes=window_minutes)
        try:
            traces = fetch_traces_from_langfuse(
                client,
                user_id=str(user_id),
                limit=200,
                from_timestamp=from_ts,
                to_timestamp=to_ts,
            )
        except Exception as e:
            logger.debug(
                "Context trace lookup failed for trace_ref={} attempt={}/{}: {}",
                trace_id,
                attempt,
                max_attempts,
                str(e),
            )
            traces = []

        candidate = _choose_trace_candidate(
            traces,
            requested_trace_id=trace_id,
            user_id=str(user_id),
            session_id=session_id,
            agent_id=agent_id,
            agent_name=agent_name,
            project_name=project_name,
            timestamp=resolved_timestamp,
        )
        if candidate:
            return str(candidate.get("id")), candidate

        # final wide search without strict time window in case ingestion lag is high
        if attempt == max_attempts:
            try:
                traces = fetch_traces_from_langfuse(
                    client,
                    user_id=str(user_id),
                    limit=400,
                )
                candidate = _choose_trace_candidate(
                    traces,
                    requested_trace_id=trace_id,
                    user_id=str(user_id),
                    session_id=session_id,
                    agent_id=agent_id,
                    agent_name=agent_name,
                    project_name=project_name,
                    timestamp=resolved_timestamp,
                )
                if candidate:
                    return str(candidate.get("id")), candidate
            except Exception as e:
                logger.debug("Wide trace lookup failed for trace_ref={}: {}", trace_id, str(e))

        await asyncio.sleep(min(0.5 * attempt, 3.0))

    return None, None


async def run_llm_judge_task(
    client,
    trace_id: str,
    criteria: str,
    score_name: str,
    model: str,
    user_id: str,
    model_api_key: str | None = None,
    preset_id: str | None = None,
    ground_truth: str | None = None,
    session_id: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    project_name: str | None = None,
    timestamp: datetime | None = None,
):
    """Background task to run LLM judge."""
    if not LITELLM_AVAILABLE and not OPENAI_AVAILABLE:
        logger.error("LiteLLM not installed and OpenAI SDK not available, cannot run judge")
        return

    try:
        # 1. Resolve canonical trace id and fetch trace payload.
        logger.info(
            f"Resolving trace for evaluation: trace_ref={trace_id}, session_id={session_id}, agent_id={agent_id}"
        )
        resolved_trace_id, trace_dict = await _resolve_trace_for_judge(
            client,
            trace_id=str(trace_id),
            user_id=str(user_id),
            session_id=session_id,
            agent_id=agent_id,
            agent_name=agent_name,
            project_name=project_name,
            timestamp=timestamp,
            max_attempts=3,
        )
        if not resolved_trace_id or not trace_dict:
            logger.error(
                f"Judge failed: could not resolve trace for trace_ref={trace_id}, "
                f"user_id={user_id}, session_id={session_id}, agent_id={agent_id}"
            )
            return
        if resolved_trace_id != str(trace_id):
            logger.info(f"Resolved trace_ref={trace_id} to canonical trace_id={resolved_trace_id}")
        trace_input = trace_dict.get('input', '')
        trace_output = trace_dict.get('output', '')

        # Convert to string if needed
        if not isinstance(trace_input, str):
            trace_input = json.dumps(trace_input)
        if not isinstance(trace_output, str):
            trace_output = json.dumps(trace_output)

        # 2. Construct Prompt
        if ground_truth:
            system_prompt = (
                "You are an impartial AI judge evaluating an AI assistant's interaction. "
                "You will be given the Input (User Query), the Output (AI Response), and the Ground Truth (Expected Answer). "
                "Your task is to evaluate the Output against the Ground Truth based strictly on the provided Criteria. "
                "Provide a score between 0.0 (worst) and 1.0 (perfect) and explain your reasoning."
            )
        else:
            system_prompt = (
                "You are an impartial AI judge evaluating an AI assistant's interaction. "
                "You will be given the Input (User Query) and the Output (AI Response). "
                "Your task is to evaluate the Output based strictly on the provided Criteria. "
                "Provide a score between 0.0 (worst) and 1.0 (perfect) and explain your reasoning."
            )
        
        if ground_truth:
            user_prompt = f"""### Criteria
{criteria}

### Input
{trace_input}

### Ground Truth (Expected Answer)
{ground_truth}

### Output (Actual Response)
{trace_output}

### Instructions
Evaluate the Output by comparing it to the Ground Truth based on the Criteria.
Provide a numeric score between 0 and 5 inclusive (0 worst, 5 best).
Respond with a JSON object containing:
- "score_0_5": A number between 0 and 5.
- "reason": A concise explanation of your scoring (1-3 sentences).

Respond ONLY with valid JSON, no markdown formatting."""
        else:
            user_prompt = f"""### Criteria
{criteria}

### Input
{trace_input}

### Output
{trace_output}

### Instructions
Evaluate the Output based on the Criteria.
Provide a numeric score between 0 and 5 inclusive (0 worst, 5 best).
Respond with a JSON object containing:
- "score_0_5": A number between 0 and 5.
- "reason": A concise explanation of your scoring (1-3 sentences).

Respond ONLY with valid JSON, no markdown formatting."""

        # 3. Call LLM (with provider/model normalization retries)
        model_candidates = _build_litellm_model_candidates(model, model_api_key)
        if not model_candidates:
            logger.error(f"Judge failed: invalid empty model for trace_ref={trace_id}")
            return

        logger.info(f"Calling LLM judge with model candidates: {model_candidates}")

        # If LiteLLM is available, prefer it (supports provider/model resolution).
        if LITELLM_AVAILABLE:
            _ensure_litellm_logging_compatibility_patch()

            # Reduce noisy/proxy-related logger side effects in worker context.
            try:
                litellm.suppress_debug_info = True
                litellm.turn_off_message_logging = True
                litellm.logging = False
            except Exception:
                pass

            response = None
            used_model = model_candidates[0]
            last_error: Exception | None = None

            for candidate_model in model_candidates:
                acall_kwargs = dict(
                    model=candidate_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format={"type": "json_object"},
                )
                acall_kwargs["no-log"] = True
                if model_api_key:
                    acall_kwargs["api_key"] = model_api_key

                api_base = _resolve_api_base_for_model(candidate_model)
                if api_base:
                    acall_kwargs["api_base"] = api_base

                try:
                    response = await litellm.acompletion(**acall_kwargs)
                    used_model = candidate_model
                    break
                except Exception as e:
                    last_error = e
                    logger.warning("LLM judge call failed for model={}: {}", candidate_model, str(e))
                    if _is_litellm_retryable_model_error(e):
                        continue
                    raise

            if response is None:
                if last_error:
                    raise last_error
                raise RuntimeError("LLM judge call failed without a response")

            content = response.choices[0].message.content

        else:
            # Fallback to OpenAI SDK if available.
            content, used_model = await _call_openai_judge_completion(
                model_candidates=model_candidates,
                model_api_key=model_api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

        # Clean up markdown code blocks if present
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        result = json.loads(content)

        # Extract 0-5 score and reason
        raw_score = result.get("score_0_5") if result.get("score_0_5") is not None else result.get("score")
        try:
            score_0_5 = float(raw_score)
        except Exception:
            score_0_5 = 0.0
        reason = result.get("reason", "No reason provided")

        # Clamp to 0-5
        score_0_5 = max(0.0, min(5.0, score_0_5))

        # Normalize to 0-1 for Langfuse value field but include raw in comment
        normalized_value = score_0_5 / 5.0

        # 4. Submit Score to Langfuse
        logger.info(f"Submitting score to Langfuse: {score_name} raw={score_0_5} normalized={normalized_value}")
        score_comment_data = {
            "criteria": criteria,
            "model": used_model,
            "requested_model": model,
            "reason": reason,
            "source": "llm-judge",
            "raw_score_0_5": score_0_5,
            "preset_id": preset_id,
            "requested_trace_id": str(trace_id),
            "resolved_trace_id": str(resolved_trace_id),
        }
        if ground_truth:
            score_comment_data["ground_truth"] = ground_truth
        score_comment = json.dumps(score_comment_data)
        _submit_score_to_langfuse(
            client,
            trace_id=str(resolved_trace_id),
            name=score_name,
            value=normalized_value,
            comment=score_comment,
        )
        
        # Flush to ensure immediate send
        if hasattr(client, "flush"):
            client.flush()
        
        logger.info(
            f"Judge completed for trace_ref={trace_id}, trace_id={resolved_trace_id}: "
            f"{score_name}={normalized_value}"
        )

    except json.JSONDecodeError as e:
        logger.error("LLM Judge JSON parsing error for trace_ref={}: {}", trace_id, str(e))
        logger.error("Response content: {}", content)
    except Exception as e:
        logger.error("LLM Judge error for trace_ref={}: {}", trace_id, str(e))


async def _resolve_agent_payload_for_experiment(
    *,
    agent_id: str | None,
    current_user: User,
) -> dict[str, Any] | None:
    """Resolve agent payload for dataset experiment task execution."""
    normalized_agent_id = _normalize_agent_id(agent_id)
    if not normalized_agent_id:
        return None
    try:
        agent_uuid = UUID(normalized_agent_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid agent_id for experiment run")

    async with session_scope() as session:
        agent_obj = await session.get(agent, agent_uuid)
        if not agent_obj:
            raise HTTPException(status_code=404, detail=f"Agent {normalized_agent_id} not found")
        if str(agent_obj.user_id) != str(current_user.id) and agent_obj.access_type != AccessTypeEnum.PUBLIC:
            raise HTTPException(status_code=403, detail="You do not have access to this agent")
        if agent_obj.data is None:
            raise HTTPException(status_code=400, detail="Selected agent has no data payload")

        return {
            "id": str(agent_obj.id),
            "name": agent_obj.name or str(agent_obj.id),
            "data": agent_obj.data,
        }


async def _resolve_experiment_judge_config(
    *,
    current_user: User,
    evaluator_config_id: str | None,
    preset_id: str | None,
    evaluator_name: str | None,
    criteria: str | None,
    judge_model: str | None,
    judge_model_api_key: str | None,
) -> dict[str, Any]:
    """Resolve dataset experiment judge settings from optional saved evaluator."""
    judge_name = (evaluator_name or "").strip() or "Dataset LLM Judge"
    resolved_criteria = (criteria or "").strip() or None
    resolved_model = (judge_model or "").strip() or None
    resolved_api_key = (judge_model_api_key or "").strip() or None
    resolved_preset_id = (preset_id or "").strip() or None

    if evaluator_config_id:
        try:
            config_uuid = UUID(evaluator_config_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid evaluator_config_id")

        async with session_scope() as session:
            evaluator = await session.get(Evaluator, config_uuid)
            if not evaluator or str(evaluator.user_id) != str(current_user.id):
                raise HTTPException(status_code=404, detail="Evaluator config not found")

        judge_name = evaluator.name or judge_name
        if not resolved_criteria:
            resolved_criteria = (evaluator.criteria or "").strip() or None
        if not resolved_model:
            resolved_model = (evaluator.model or "").strip() or None
        if not resolved_api_key:
            resolved_api_key = (evaluator.model_api_key or "").strip() or None
        if not resolved_preset_id:
            resolved_preset_id = str(evaluator.preset_id) if evaluator.preset_id else None

    preset = get_preset_by_id(resolved_preset_id)
    if resolved_preset_id and preset is None:
        raise HTTPException(status_code=400, detail=f"Unknown preset_id '{resolved_preset_id}'")

    # Optional convenience: allow evaluator_name to match a preset id/name.
    if not preset and judge_name:
        normalized_name = judge_name.strip().lower()
        for candidate in EVALUATION_PRESETS:
            candidate_id = str(candidate.get("id") or "").strip().lower()
            candidate_name = str(candidate.get("name") or "").strip().lower()
            if normalized_name and normalized_name in {candidate_id, candidate_name}:
                preset = candidate
                resolved_preset_id = str(candidate.get("id"))
                break

    if preset:
        if not resolved_criteria:
            resolved_criteria = str(preset.get("criteria") or "").strip() or None
        if not (evaluator_name or "").strip():
            judge_name = str(preset.get("name") or judge_name)

    if resolved_criteria:
        resolved_criteria = _ensure_dataset_prompt_template(resolved_criteria)

    return {
        "judge_name": judge_name,
        "criteria": resolved_criteria,
        "model": resolved_model,
        "model_api_key": resolved_api_key,
        "preset_id": resolved_preset_id,
        "requires_ground_truth": bool(preset and preset.get("requires_ground_truth")),
    }


def _run_dataset_experiment_sync(
    *,
    client: Any,
    dataset_name: str,
    experiment_name: str,
    description: str | None,
    user_id: str,
    agent_payload: dict[str, Any] | None,
    generation_model: str | None,
    generation_model_api_key: str | None,
    judge_name: str | None,
    judge_preset_id: str | None,
    judge_criteria: str | None,
    judge_model: str | None,
    judge_model_api_key: str | None,
) -> dict[str, Any]:
    """Run dataset experiment synchronously (executed in a worker thread)."""
    dataset = client.get_dataset(dataset_name)
    data_items = list(getattr(dataset, "items", []) or [])
    if not data_items:
        raise RuntimeError(f"Dataset '{dataset_name}' has no items")

    has_expected_outputs = any(get_attr(item, "expected_output", "expectedOutput", default=None) is not None for item in data_items)

    def task(*, item, **kwargs):  # noqa: ARG001
        item_input = get_attr(item, "input", default=None)
        item_id = str(get_attr(item, "id", default="") or "")
        if agent_payload:
            session_id = f"dataset:{dataset_name}:{item_id or int(time.time() * 1000)}"
            return _run_async(
                _run_dataset_item_with_agent(
                    agent_payload=agent_payload,
                    user_id=str(user_id),
                    item_input=item_input,
                    session_id=session_id,
                )
            )
        if not generation_model:
            raise RuntimeError("No generation model configured for dataset experiment.")
        try:
            generated_output, _ = _run_async(
                _dataset_generate_with_model(
                    model=generation_model,
                    model_api_key=generation_model_api_key,
                    item_input=item_input,
                )
            )
            return generated_output
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Generation failed for dataset={} item_id={}: {}",
                dataset_name,
                item_id,
                str(exc),
            )
            return f"[GENERATION_ERROR] {exc}"

    evaluators: list[Any] = []
    if has_expected_outputs:
        def exact_match_evaluator(*, input, output, expected_output=None, **kwargs):  # noqa: ARG001
            if expected_output is None:
                return _build_experiment_evaluation(
                    name="exact_match",
                    value=0.0,
                    comment="No expected output configured for this dataset item.",
                )
            expected_norm = _normalize_for_exact_match(expected_output)
            output_norm = _normalize_for_exact_match(output)
            is_match = expected_norm == output_norm
            return _build_experiment_evaluation(
                name="exact_match",
                value=1.0 if is_match else 0.0,
                comment="Exact match" if is_match else "Output differs from expected output",
            )

        evaluators.append(exact_match_evaluator)

    if judge_criteria and judge_model and (LITELLM_AVAILABLE or OPENAI_AVAILABLE):
        llm_metric_name = f"llm_judge:{judge_name or 'judge'}"

        def llm_judge_evaluator(*, input, output, expected_output=None, **kwargs):  # noqa: ARG001
            try:
                value, reason, used_model = _run_async(
                    _dataset_llm_evaluate(
                        criteria=judge_criteria,
                        model=judge_model,
                        model_api_key=judge_model_api_key,
                        item_input=input,
                        output=output,
                        expected_output=expected_output,
                    )
                )
                return _build_experiment_evaluation(
                    name=llm_metric_name,
                    value=float(value),
                    comment=json.dumps(
                        {
                            "reason": reason,
                            "model": used_model,
                            "criteria": judge_criteria,
                        }
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Dataset LLM evaluator failed for experiment={}: {}", experiment_name, str(exc))
                return _build_experiment_evaluation(
                    name=llm_metric_name,
                    value=0.0,
                    comment=f"LLM evaluator error: {exc}",
                )

        evaluators.append(llm_judge_evaluator)

    # Keep metadata compact to avoid propagated-attribute truncation warnings.
    experiment_metadata = {
        "source": "agentcore-evaluation-datasets",
        "user_id": str(user_id),
    }

    result = client.run_experiment(
        name=experiment_name,
        description=description,
        data=data_items,
        task=task,
        evaluators=evaluators,
        max_concurrency=_get_dataset_experiment_concurrency(),
        metadata=experiment_metadata,
        _dataset_version=getattr(dataset, "version", None),
    )

    metric_buckets: dict[str, list[float]] = defaultdict(list)
    for item_result in list(get_attr(result, "item_results", default=[]) or []):
        evaluations = list(get_attr(item_result, "evaluations", default=[]) or [])
        for ev in evaluations:
            score_name = str(get_attr(ev, "name", default="") or "")
            score_value = get_attr(ev, "value", default=None)
            if not score_name:
                continue
            if isinstance(score_value, (int, float)):
                metric_buckets[score_name].append(float(score_value))

    metrics_summary: dict[str, dict[str, Any]] = {}
    for metric_name, values in metric_buckets.items():
        if not values:
            continue
        metrics_summary[metric_name] = {
            "count": len(values),
            "avg": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
        }

    return {
        "dataset_run_id": get_attr(result, "dataset_run_id", "datasetRunId", default=None),
        "dataset_run_url": get_attr(result, "dataset_run_url", "datasetRunUrl", default=None),
        "run_name": get_attr(result, "run_name", "runName", default=None),
        "item_count": len(list(get_attr(result, "item_results", default=[]) or [])),
        "metrics": metrics_summary,
    }


async def _run_dataset_experiment_job(
    *,
    job_id: str,
    client: Any,
    dataset_name: str,
    experiment_name: str,
    description: str | None,
    user_id: str,
    agent_payload: dict[str, Any] | None,
    generation_model: str | None,
    generation_model_api_key: str | None,
    judge_name: str | None,
    judge_preset_id: str | None,
    judge_criteria: str | None,
    judge_model: str | None,
    judge_model_api_key: str | None,
) -> None:
    """Background task runner for dataset experiments."""
    _set_dataset_experiment_job(
        job_id,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    try:
        result_payload = await asyncio.to_thread(
            _run_dataset_experiment_sync,
            client=client,
            dataset_name=dataset_name,
            experiment_name=experiment_name,
            description=description,
            user_id=user_id,
            agent_payload=agent_payload,
            generation_model=generation_model,
            generation_model_api_key=generation_model_api_key,
            judge_name=judge_name,
            judge_preset_id=judge_preset_id,
            judge_criteria=judge_criteria,
            judge_model=judge_model,
            judge_model_api_key=judge_model_api_key,
        )
        _set_dataset_experiment_job(
            job_id,
            status="completed",
            finished_at=datetime.now(timezone.utc),
            result=result_payload,
            error=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.opt(exception=True).error(
            "Dataset experiment job failed: job_id={}, dataset={}, error={}",
            job_id,
            dataset_name,
            str(exc),
        )
        _set_dataset_experiment_job(
            job_id,
            status="failed",
            finished_at=datetime.now(timezone.utc),
            error=str(exc),
        )


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("/status")
async def get_status(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Dict[str, Any]:
    """Check if evaluation features are available."""
    client = get_langfuse_client()
    
    return {
        "langfuse_available": client is not None,
        "llm_judge_available": LITELLM_AVAILABLE or OPENAI_AVAILABLE,
        "user_id": str(current_user.id)
    }


@router.get("/scores")
async def get_scores(
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    page: Annotated[int, Query(ge=1)] = 1,
    trace_id: Annotated[str | None, Query()] = None,
    name: Annotated[str | None, Query()] = None,
) -> Dict[str, Any]:
    """
    List evaluation scores for the current user.
    Uses user_id when available, with trace-based fallback for providers that do not
    persist score-level user_id.
    """
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        user_id = str(current_user.id)
        trace_id = str(trace_id).strip() if trace_id and str(trace_id).strip() else None
        name = str(name).strip() if name and str(name).strip() else None
        score_cache_key = f"{user_id}|{page}|{limit}|{trace_id or ''}|{(name or '').lower()}"
        now_mono = time.monotonic()
        cached_score_payload: dict[str, Any] | None = None
        cached_score_entry = _SCORE_LIST_CACHE.get(score_cache_key)
        if cached_score_entry:
            cached_age = now_mono - float(cached_score_entry.get("ts", 0))
            cached_payload = cached_score_entry.get("payload")
            if isinstance(cached_payload, dict):
                # Fast path: serve any cached result (including empty) within TTL.
                # Empty results use a shorter TTL (30s) so we re-check Langfuse quickly.
                is_empty_result = not cached_payload.get("items") and cached_payload.get("total", 0) == 0
                ttl = 30.0 if is_empty_result else _SCORE_LIST_CACHE_STALE_SECONDS
                if cached_age <= ttl:
                    return cached_payload
                # Stale but non-empty: keep as fallback in case fresh fetch returns empty.
                if not is_empty_result:
                    cached_score_payload = cached_payload

        trace_lookup: Dict[str, Dict[str, Any]] = {}
        user_trace_ids: set[str] = set()
        trace_owner_cache: Dict[str, bool] = {}
        user_traces_prefetched = False

        def _ensure_user_traces_prefetched() -> None:
            nonlocal user_traces_prefetched
            if user_traces_prefetched:
                return
            user_traces_prefetched = True
            try:
                prefetch_limit = 2000 if not trace_id else 200
                user_traces = fetch_traces_from_langfuse(
                    client,
                    user_id=user_id,
                    limit=prefetch_limit,
                )
                for raw_trace in user_traces or []:
                    trace_dict = parse_trace_data(raw_trace)
                    trace_key = str(trace_dict.get("id") or "")
                    if not trace_key:
                        continue
                    trace_lookup[trace_key] = trace_dict
                    user_trace_ids.add(trace_key)
            except Exception as trace_error:
                logger.debug(
                    "Failed to prefetch user traces for score listing: {}",
                    str(trace_error),
                )

        def _extract_scores_payload(response: Any) -> tuple[list[Any], int | None]:
            if response is None:
                return [], None

            rows: list[Any] = []
            total_items: int | None = None
            if hasattr(response, "data"):
                rows = list(response.data or [])
                meta = getattr(response, "meta", None)
                if isinstance(meta, dict):
                    total_items = meta.get("total_items") or meta.get("total")
                elif meta is not None:
                    total_items = (
                        getattr(meta, "total_items", None)
                        or getattr(meta, "total", None)
                    )
            elif isinstance(response, dict):
                rows = list(response.get("data") or [])
                meta = response.get("meta")
                if isinstance(meta, dict):
                    total_items = meta.get("total_items") or meta.get("total")
            elif isinstance(response, list):
                rows = response
                total_items = len(rows)
            return rows, total_items

        def _list_scores_page(page_num: int, page_limit: int, *, include_user_filter: bool) -> tuple[list[Any], int | None]:
            if not (hasattr(client, "client") and hasattr(client.client, "scores")):
                return [], None

            kwargs: Dict[str, Any] = {
                "page": page_num,
                "limit": page_limit,
            }
            if trace_id:
                kwargs["trace_id"] = trace_id
            if name:
                kwargs["name"] = name
            if include_user_filter:
                kwargs["user_id"] = user_id

            try:
                response = client.client.scores.list(**kwargs)
            except TypeError:
                kwargs.pop("user_id", None)
                response = client.client.scores.list(**kwargs)
            return _extract_scores_payload(response)

        def _list_global_scores(max_rows: int = 2000) -> list[Any]:
            """Best-effort global score scan across SDK variants."""
            rows_out: list[Any] = []
            seen_keys: set[str] = set()
            page_size = min(100, max_rows)
            max_pages = max(1, (max_rows + page_size - 1) // page_size)

            def _append(rows: list[Any]) -> None:
                for row in rows or []:
                    row_id = str(get_attr(row, "id", default="") or "")
                    row_trace_id = str(get_attr(row, "trace_id", "traceId", default="") or "")
                    row_name = str(get_attr(row, "name", default="score") or "score")
                    row_ts = str(get_attr(row, "timestamp", "created_at", "createdAt", default="") or "")
                    dedupe_key = row_id or f"{row_trace_id}::{row_name}::{row_ts}"
                    if dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)
                    rows_out.append(row)

            # Method 1: v3 score_v_2.get
            if hasattr(client, "api") and hasattr(client.api, "score_v_2"):
                for page_num in range(1, max_pages + 1):
                    kwargs: Dict[str, Any] = {"limit": page_size, "page": page_num}
                    try:
                        payload = client.api.score_v_2.get(**kwargs)
                    except Exception:
                        break
                    page_rows, _ = _extract_scores_payload(payload)
                    if not page_rows:
                        break
                    _append(page_rows)
                    if len(rows_out) >= max_rows or len(page_rows) < page_size:
                        break

            # Method 2: v3 api.scores.list/api.score.list
            if len(rows_out) < max_rows and hasattr(client, "api"):
                for attr in ("scores", "score"):
                    score_api = getattr(client.api, attr, None)
                    if not score_api or not hasattr(score_api, "list"):
                        continue
                    for page_num in range(1, max_pages + 1):
                        kwargs = {"limit": page_size, "page": page_num}
                        try:
                            payload = score_api.list(**kwargs)
                        except Exception:
                            break
                        page_rows, _ = _extract_scores_payload(payload)
                        if not page_rows:
                            break
                        _append(page_rows)
                        if len(rows_out) >= max_rows or len(page_rows) < page_size:
                            break
                    if len(rows_out) >= max_rows:
                        break

            # Method 3: direct scores client without user filter
            if len(rows_out) < max_rows and hasattr(client, "client") and hasattr(client.client, "scores"):
                for page_num in range(1, max_pages + 1):
                    kwargs = {"limit": page_size, "page": page_num}
                    try:
                        payload = client.client.scores.list(**kwargs)
                    except Exception:
                        break
                    page_rows, _ = _extract_scores_payload(payload)
                    if not page_rows:
                        break
                    _append(page_rows)
                    if len(rows_out) >= max_rows or len(page_rows) < page_size:
                        break

            return rows_out[:max_rows]

        def _score_belongs_to_user(score_row: Any) -> bool:
            score_user_id = get_attr(score_row, "user_id", "userId")
            if score_user_id is not None:
                return str(score_user_id) == user_id

            score_trace_id = str(get_attr(score_row, "trace_id", "traceId", default="") or "")
            if not score_trace_id:
                return False
            if score_trace_id in trace_owner_cache:
                return trace_owner_cache[score_trace_id]

            _ensure_user_traces_prefetched()
            if score_trace_id in user_trace_ids:
                trace_owner_cache[score_trace_id] = True
                return True

            # Last-resort ownership check: resolve trace and compare trace user_id.
            try:
                trace_raw = _fetch_trace_by_id(client, score_trace_id)
                if trace_raw:
                    trace_dict = parse_trace_data(trace_raw)
                    trace_lookup[score_trace_id] = trace_dict
                    trace_user_id = str(_extract_trace_user_id(trace_dict) or "")
                    if trace_user_id:
                        is_owner = trace_user_id == user_id
                    else:
                        # Some deployments don't populate user_id on traces/scores.
                        # If we cannot establish ownership via user metadata at all,
                        # allow the score as a best-effort fallback.
                        is_owner = not user_trace_ids
                    trace_owner_cache[score_trace_id] = is_owner
                    if is_owner:
                        user_trace_ids.add(score_trace_id)
                    return is_owner
            except Exception as owner_error:
                logger.debug(
                    "Could not verify trace ownership for score trace_id={}: {}",
                    score_trace_id,
                    str(owner_error),
                )

            if not user_trace_ids:
                logger.debug(
                    "Score ownership fallback: accepting trace_id={} without user metadata",
                    score_trace_id,
                )
                trace_owner_cache[score_trace_id] = True
                return True

            trace_owner_cache[score_trace_id] = False
            return False

        def _score_matches_name(score_row: Any) -> bool:
            if not name:
                return True
            score_name = str(get_attr(score_row, "name", default="") or "")
            return name.lower() in score_name.lower()

        raw_scores: list[Any] = []
        total = 0
        unscoped_collected: list[Any] = []

        # Primary fetch with user filter.
        primary_rows, primary_total = _list_scores_page(page, limit, include_user_filter=True)
        primary_rows = [
            row for row in primary_rows
            if _score_belongs_to_user(row) and _score_matches_name(row)
        ]
        if primary_rows:
            raw_scores = primary_rows
            total = (
                int(primary_total)
                if primary_total is not None and len(primary_rows) > 0
                else len(primary_rows)
            )
        else:
            # Fallback: some score records do not carry user_id; scan without user filter,
            # then enforce user isolation with trace ownership checks.
            collected: list[Any] = []
            seen_keys: set[str] = set()
            unscoped_seen_keys: set[str] = set()
            target_count = page * limit
            scan_limit = min(200, max(50, limit))
            max_scan_pages = 10

            for scan_page in range(1, max_scan_pages + 1):
                scan_rows, _ = _list_scores_page(scan_page, scan_limit, include_user_filter=False)
                if not scan_rows:
                    break

                for row in scan_rows:
                    row_trace_id = str(get_attr(row, "trace_id", "traceId", default="") or "")
                    if trace_id and row_trace_id != str(trace_id):
                        continue
                    if not _score_matches_name(row):
                        continue

                    # Keep an unscoped copy in case ownership metadata is completely absent.
                    row_id_for_unscoped = str(get_attr(row, "id", default="") or "")
                    unscoped_dedupe_key = row_id_for_unscoped or (
                        f"{row_trace_id}::{get_attr(row, 'name', default='score')}::"
                        f"{get_attr(row, 'timestamp', 'created_at', 'createdAt', default='')}"
                    )
                    if unscoped_dedupe_key not in unscoped_seen_keys:
                        unscoped_seen_keys.add(unscoped_dedupe_key)
                        unscoped_collected.append(row)

                    if not _score_belongs_to_user(row):
                        continue

                    row_id = str(get_attr(row, "id", default="") or "")
                    dedupe_key = row_id or (
                        f"{row_trace_id}::{get_attr(row, 'name', default='score')}::"
                        f"{get_attr(row, 'timestamp', 'created_at', 'createdAt', default='')}"
                    )
                    if dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)
                    collected.append(row)

                if len(collected) >= target_count:
                    break
                if len(scan_rows) < scan_limit:
                    break

            # If the direct list endpoint is empty, try broader SDK-specific score APIs.
            if not collected and not unscoped_collected:
                global_scan_rows = _list_global_scores(max_rows=max(1000, page * limit * 10))
                logger.info(
                    "Global score scan fallback collected {} row(s) for user_id={}",
                    len(global_scan_rows),
                    user_id,
                )
                for row in global_scan_rows:
                    row_trace_id = str(get_attr(row, "trace_id", "traceId", default="") or "")
                    if trace_id and row_trace_id != str(trace_id):
                        continue
                    if not _score_matches_name(row):
                        continue

                    row_id_for_unscoped = str(get_attr(row, "id", default="") or "")
                    unscoped_dedupe_key = row_id_for_unscoped or (
                        f"{row_trace_id}::{get_attr(row, 'name', default='score')}::"
                        f"{get_attr(row, 'timestamp', 'created_at', 'createdAt', default='')}"
                    )
                    if unscoped_dedupe_key not in unscoped_seen_keys:
                        unscoped_seen_keys.add(unscoped_dedupe_key)
                        unscoped_collected.append(row)

                    if not _score_belongs_to_user(row):
                        continue

                    row_id = str(get_attr(row, "id", default="") or "")
                    dedupe_key = row_id or (
                        f"{row_trace_id}::{get_attr(row, 'name', default='score')}::"
                        f"{get_attr(row, 'timestamp', 'created_at', 'createdAt', default='')}"
                    )
                    if dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)
                    collected.append(row)

            total = len(collected)
            start = (page - 1) * limit
            raw_scores = collected[start:start + limit]

            # If ownership metadata is unavailable, fall back to unscoped rows so the
            # UI remains usable in single-tenant/local deployments.
            if not raw_scores and not user_trace_ids and unscoped_collected:
                logger.warning(
                    "Score ownership metadata unavailable for user_id={}; using unscoped score fallback",
                    user_id,
                )
                total = len(unscoped_collected)
                raw_scores = unscoped_collected[start:start + limit]

        # Final fallback: collect scores per user-owned trace using observability's
        # robust score fetcher when list-based score APIs are empty/incompatible.
        if not raw_scores and not user_trace_ids and not trace_id and not unscoped_collected:
            _ensure_user_traces_prefetched()

        if not raw_scores and (user_trace_ids or trace_id or unscoped_collected):
            logger.info(
                "Score list API returned no rows for user_id={}; using per-trace score fallback",
                user_id,
            )
            trace_candidates: list[str] = []
            if trace_id:
                trace_candidates = [str(trace_id)]
            elif user_trace_ids:
                trace_candidates = list(user_trace_ids)
            else:
                trace_candidates = list(
                    dict.fromkeys(
                        str(get_attr(row, "trace_id", "traceId", default="") or "")
                        for row in unscoped_collected
                        if str(get_attr(row, "trace_id", "traceId", default="") or "")
                    )
                )

            # Expand trace candidates with canonical ids and run_ids, as score writes may
            # target a different id than the one returned by list endpoints.
            expanded_trace_candidates: list[str] = []
            for candidate_id in trace_candidates:
                candidate_id = str(candidate_id or "").strip()
                if not candidate_id:
                    continue
                if candidate_id not in expanded_trace_candidates:
                    expanded_trace_candidates.append(candidate_id)

                trace_dict = trace_lookup.get(candidate_id)
                if not trace_dict:
                    try:
                        trace_raw = _fetch_trace_by_id(client, candidate_id)
                        if trace_raw:
                            trace_dict = parse_trace_data(trace_raw)
                            resolved_id = str(trace_dict.get("id") or "")
                            if resolved_id:
                                trace_lookup[resolved_id] = trace_dict
                            trace_lookup[candidate_id] = trace_dict
                    except Exception as resolve_error:
                        logger.debug(
                            "Failed resolving canonical trace id for candidate {}: {}",
                            candidate_id,
                            str(resolve_error),
                        )

                if trace_dict:
                    resolved_id = str(trace_dict.get("id") or "")
                    if resolved_id and resolved_id not in expanded_trace_candidates:
                        expanded_trace_candidates.append(resolved_id)
                    run_id = _extract_trace_run_id(trace_dict)
                    if run_id and run_id not in expanded_trace_candidates:
                        expanded_trace_candidates.append(str(run_id))

            if expanded_trace_candidates:
                trace_candidates = expanded_trace_candidates
                logger.info(
                    "Expanded per-trace score fallback candidates to {} ids",
                    len(trace_candidates),
                )

            collected_rows: list[dict[str, Any]] = []
            seen_keys: set[str] = set()
            max_traces_to_scan = 500

            for trace_key in trace_candidates[:max_traces_to_scan]:
                if not trace_key:
                    continue
                try:
                    trace_scores = fetch_scores_for_trace(
                        client,
                        trace_id=trace_key,
                        user_id=user_id,
                        limit=200,
                    )
                except Exception as trace_score_error:
                    logger.debug(
                        "Per-trace score fetch failed for trace_id={}: {}",
                        trace_key,
                        str(trace_score_error),
                    )
                    continue

                for trace_score in trace_scores:
                    score_name = str(get_attr(trace_score, "name", default="") or "")
                    if name and name.lower() not in score_name.lower():
                        continue

                    score_id = str(get_attr(trace_score, "id", default="") or "")
                    created_at = get_attr(trace_score, "created_at", "timestamp", default=None)
                    dedupe_key = score_id or f"{trace_key}::{score_name}::{created_at}"
                    if dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)

                    source_value = get_attr(trace_score, "source", default=None)
                    if hasattr(source_value, "value"):
                        source_value = source_value.value

                    collected_rows.append(
                        {
                            "id": score_id,
                            "trace_id": trace_key,
                            "name": score_name or "Score",
                            "value": float(get_attr(trace_score, "value", default=0.0) or 0.0),
                            "source": str(source_value) if source_value is not None else "API",
                            "comment": get_attr(trace_score, "comment", default=None),
                            "created_at": created_at,
                            "observation_id": get_attr(trace_score, "observation_id", "observationId", default=None),
                            "config_id": get_attr(trace_score, "config_id", "configId", default=None),
                            "user_id": user_id,
                        }
                    )

            def _score_sort_key(row: dict[str, Any]) -> datetime:
                parsed = _parse_trace_timestamp(row.get("created_at"))
                return parsed or datetime.min.replace(tzinfo=timezone.utc)

            collected_rows.sort(key=_score_sort_key, reverse=True)
            total = len(collected_rows)
            start = (page - 1) * limit
            raw_scores = collected_rows[start:start + limit]
            logger.info(
                "Per-trace score fallback produced {} row(s); returning {} row(s) for page={} limit={}",
                total,
                len(raw_scores),
                page,
                limit,
            )

        # Last-mile retry for intermittent first-load empties.
        if not raw_scores and page == 1 and not trace_id and not name:
            retry_rows, retry_total = _list_scores_page(page, limit, include_user_filter=True)
            retry_rows = [
                row for row in retry_rows
                if _score_belongs_to_user(row) and _score_matches_name(row)
            ]
            if retry_rows:
                logger.info(
                    "Recovered transient empty score list on retry for user_id={} with {} row(s)",
                    user_id,
                    len(retry_rows),
                )
                raw_scores = retry_rows
                total = (
                    int(retry_total)
                    if retry_total is not None and len(retry_rows) > 0
                    else len(retry_rows)
                )

        # Parse to response model (including agent/agent name).
        items: list[ScoreResponse] = []
        for s in raw_scores:
            score_trace_id = str(get_attr(s, "trace_id", "traceId", default="") or "")
            trace_dict = trace_lookup.get(score_trace_id)
            if score_trace_id and not trace_dict:
                try:
                    trace_raw = _fetch_trace_by_id(client, score_trace_id)
                    if trace_raw:
                        trace_dict = parse_trace_data(trace_raw)
                        trace_lookup[score_trace_id] = trace_dict
                except Exception as trace_error:
                    logger.debug("Failed to fetch trace {} for score enrichment: {}", score_trace_id, str(trace_error))

            agent_name = _extract_trace_agent_name(trace_dict or {}) if trace_dict else None
            if not agent_name and trace_dict:
                trace_name = trace_dict.get("name")
                agent_name = str(trace_name) if trace_name else None

            source = get_attr(s, "source")
            if hasattr(source, "value"):
                source = source.value

            score_id = str(get_attr(s, "id", default="") or "")
            items.append(ScoreResponse(
                id=score_id or f"{score_trace_id}:{get_attr(s, 'name', default='score')}",
                trace_id=score_trace_id,
                agent_name=agent_name,
                name=str(get_attr(s, "name", default="Score") or "Score"),
                value=float(get_attr(s, "value", default=0.0) or 0.0),
                source=str(source) if source is not None else "API",
                comment=get_attr(s, "comment"),
                user_id=str(get_attr(s, "user_id", "userId")) if get_attr(s, "user_id", "userId") else None,
                created_at=get_attr(s, "timestamp", "createdAt", "created_at"),
                observation_id=get_attr(s, "observation_id", "observationId"),
                config_id=get_attr(s, "config_id", "configId"),
            ))

        response_payload = {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit
        }
        # Always write to cache, including empty results.
        # Empty results use a short TTL (30s) so they are re-validated quickly.
        cache_payload = {
            "items": [item.model_dump() for item in items],
            "total": total,
            "page": page,
            "limit": limit,
        }
        _SCORE_LIST_CACHE[score_cache_key] = {
            "ts": now_mono,
            "payload": cache_payload,
        }
        if len(_SCORE_LIST_CACHE) > 512:
            oldest_key = min(
                _SCORE_LIST_CACHE.items(),
                key=lambda kv: float(kv[1].get("ts", 0)),
            )[0]
            _SCORE_LIST_CACHE.pop(oldest_key, None)

        # If fresh fetch returned empty but we have stale non-empty data, prefer stale.
        if not items and total == 0 and cached_score_payload and page == 1 and not trace_id and not name:
            logger.warning(
                "Using stale cached score payload for user_id={} after transient empty response",
                user_id,
            )
            return cached_score_payload

        return response_payload

    except Exception as e:
        logger.opt(exception=True).error("Error fetching scores: {}", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create")
async def create_score(
    payload: CreateScoreRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Dict[str, str]:
    """
    Create a manual score (Annotation).
    """
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        user_id = str(current_user.id)
        
        # Verify trace belongs to user (optional but recommended)
        # For now we trust the frontend only shows user's traces
        
        _submit_score_to_langfuse(
            client,
            trace_id=payload.trace_id,
            observation_id=payload.observation_id,
            name=payload.name,
            value=payload.value,
            comment=payload.comment,
            source="ANNOTATION",
        )
        
        # Flush to ensure it sends
        if hasattr(client, "flush"):
            client.flush()

        # Invalidate score list and pending-reviews caches so the next fetch is fresh.
        for _k in [k for k in list(_SCORE_LIST_CACHE) if k.startswith(user_id + "|")]:
            _SCORE_LIST_CACHE.pop(_k, None)
        for _k in [k for k in list(_PENDING_REVIEWS_CACHE) if k.startswith(user_id + "|")]:
            _PENDING_REVIEWS_CACHE.pop(_k, None)

        logger.info(f"User {user_id} created score for trace {payload.trace_id}")
        
        return {"status": "success", "message": "Score created successfully"}

    except Exception as e:
        logger.opt(exception=True).error("Error creating score: {}", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traces/pending")
async def get_pending_reviews(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: DbSession,
    trace_id: Annotated[Optional[str], Query()] = None,
    agent_name: Annotated[Optional[str], Query()] = None,
    session_id: Annotated[Optional[str], Query()] = None,
    user_id_filter: Annotated[Optional[str], Query()] = None,
    ts_from: Annotated[Optional[str], Query()] = None,
    ts_to: Annotated[Optional[str], Query()] = None,
    limit: int = 20,
) -> List[TraceForReview]:
    """
    Get recent traces that might need review (Annotation Queue).
    Returns traces belonging to user with score status.
    """
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        user_id = str(current_user.id)

        # Fast-path: serve cached pending reviews within TTL.
        # Filters bust the cache so only unfiltered requests are cached.
        _use_pending_cache = not any([trace_id, agent_name, session_id, user_id_filter, ts_from, ts_to])
        _pending_cache_key = f"{user_id}|{limit}"
        _now_mono = time.monotonic()
        if _use_pending_cache:
            _pending_entry = _PENDING_REVIEWS_CACHE.get(_pending_cache_key)
            if _pending_entry:
                _age = _now_mono - float(_pending_entry.get("ts", 0))
                if _age <= _PENDING_REVIEWS_CACHE_TTL_SECONDS:
                    return _pending_entry["payload"]

        # Fetch recent traces for this user via shared helper (observability)
        fetch_limit = max(limit * 5, 100)
        try:
            traces_data = fetch_traces_from_langfuse(client, user_id=user_id, limit=fetch_limit)
            logger.info(f"Fetched {len(traces_data or [])} traces for user_id={user_id} (limit={fetch_limit})")
            sample_ids = [str(get_attr(t, 'id') or get_attr(t, 'trace_id') or '') for t in (traces_data or [])[:5]]
            logger.debug(f"Sample trace ids: {sample_ids}")
        except Exception as e:
            logger.warning("fetch_traces_from_langfuse failed: {}", str(e))
            traces_data = []

        # Fetch all scores for these traces
        score_counts = defaultdict(int)
        if hasattr(client, 'client') and hasattr(client.client, 'scores'):
            scores_response = client.client.scores.list(user_id=user_id, limit=1000)
            scores_data = []
            if hasattr(scores_response, 'data'):
                scores_data = scores_response.data
            elif isinstance(scores_response, list):
                scores_data = scores_response
            
            for score in scores_data:
                trace_id = get_attr(score, 'trace_id', 'traceId')
                if trace_id:
                    score_counts[trace_id] += 1

        # Get agent names from database for better context
        agent_query = select(agent).where(agent.user_id == current_user.id)
        db_agents = (await session.execute(agent_query)).scalars().all()
        agent_names = {str(agent.id): agent.name for agent in db_agents}

        # Apply filtering and build response
        result = []
        for t in traces_data:
            trace_dict = parse_trace_data(t)
            tid = trace_dict.get('id')
            if not tid:
                continue

            # filter by trace id exact match
            if trace_id and str(tid) != str(trace_id):
                continue

            # filter by agent name substring match (uses metadata or agent_id)
            metadata = trace_dict.get('metadata') or {}
            inferred_agent_name = None
            if isinstance(metadata, dict):
                inferred_agent_name = metadata.get('agent_name') or metadata.get('agentId') or metadata.get('agent_id')
            if not inferred_agent_name:
                # fallback to DB lookup using agent id stored in metadata
                agent_id = metadata.get('agent_id') if isinstance(metadata, dict) else None
                if agent_id:
                    inferred_agent_name = agent_names.get(str(agent_id))

            if agent_name:
                if not inferred_agent_name or agent_name.lower() not in str(inferred_agent_name).lower():
                    continue

            # filter by session id
            if session_id and str(trace_dict.get('session_id') or '').lower().find(session_id.lower()) < 0:
                continue

            # filter by user id
            if user_id_filter and str(trace_dict.get('user_id') or '').lower().find(user_id_filter.lower()) < 0:
                continue

            # filter by timestamp range if provided (ISO format)
            if ts_from or ts_to:
                try:
                    ts_val = None
                    ts = trace_dict.get('timestamp')
                    if isinstance(ts, (int, float)):
                        ts_val = datetime.fromtimestamp(float(ts) / 1000.0, timezone.utc)
                    else:
                        try:
                            ts_val = datetime.fromisoformat(str(ts))
                        except Exception:
                            ts_val = None

                    if ts_val:
                        if ts_from:
                            try:
                                tfrom = datetime.fromisoformat(ts_from)
                                if ts_val < tfrom:
                                    continue
                            except Exception:
                                pass
                        if ts_to:
                            try:
                                tto = datetime.fromisoformat(ts_to)
                                if ts_val > tto:
                                    continue
                            except Exception:
                                pass
                except Exception:
                    pass

            score_count = score_counts.get(str(tid), 0)

            result.append(TraceForReview(
                id=str(tid),
                name=trace_dict.get('name'),
                timestamp=trace_dict.get('timestamp'),
                input=trace_dict.get('input'),
                output=trace_dict.get('output'),
                session_id=trace_dict.get('session_id'),
                agent_name=inferred_agent_name,
                has_scores=score_count > 0,
                score_count=score_count
            ))

            if len(result) >= limit:
                break

        # Cache unfiltered results so subsequent calls are served instantly.
        if _use_pending_cache:
            _PENDING_REVIEWS_CACHE[_pending_cache_key] = {"ts": _now_mono, "payload": result}
            # Evict oldest entry if cache exceeds 128 entries.
            if len(_PENDING_REVIEWS_CACHE) > 128:
                _oldest = min(_PENDING_REVIEWS_CACHE.items(), key=lambda kv: float(kv[1].get("ts", 0)))[0]
                _PENDING_REVIEWS_CACHE.pop(_oldest, None)

        return result

    except Exception as e:
        logger.opt(exception=True).error("Error fetching pending queue: {}", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/datasets")
async def list_datasets(
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    page: Annotated[int, Query(ge=1)] = 1,
    search: Annotated[str | None, Query()] = None,
) -> Dict[str, Any]:
    """List Langfuse datasets visible to the current user."""
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        user_id = str(current_user.id)

        # Fast-path: serve from cache for unfiltered requests.
        _datasets_cache_key = f"{user_id}|{page}|{limit}|{(search or '').lower()}"
        _now_mono = time.monotonic()
        _datasets_entry = _DATASETS_LIST_CACHE.get(_datasets_cache_key)
        if _datasets_entry:
            _age = _now_mono - float(_datasets_entry.get("ts", 0))
            if _age <= _DATASETS_LIST_CACHE_TTL_SECONDS:
                return _datasets_entry["payload"]

        max_rows = max(page * limit, 200)
        rows = _list_all_datasets_for_user(client, user_id=user_id, max_rows=max_rows)

        if search:
            normalized_search = search.lower().strip()
            rows = [
                dataset
                for dataset in rows
                if normalized_search in str(get_attr(dataset, "name", default="") or "").lower()
            ]

        total = len(rows)
        start = (page - 1) * limit
        page_rows = rows[start:start + limit]

        # Build responses without per-dataset item count API calls (N+1 eliminated).
        # Item counts are loaded when a specific dataset is opened.
        items: list[DatasetResponse] = [
            _dataset_to_response(dataset, item_count=None) for dataset in page_rows
        ]

        payload_out = {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
        }
        _DATASETS_LIST_CACHE[_datasets_cache_key] = {"ts": _now_mono, "payload": payload_out}
        if len(_DATASETS_LIST_CACHE) > 256:
            _oldest = min(_DATASETS_LIST_CACHE.items(), key=lambda kv: float(kv[1].get("ts", 0)))[0]
            _DATASETS_LIST_CACHE.pop(_oldest, None)
        return payload_out
    except HTTPException:
        raise
    except Exception as exc:
        logger.opt(exception=True).error("Error listing datasets: {}", str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/datasets")
async def create_dataset(
    payload: CreateDatasetRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DatasetResponse:
    """Create a Langfuse dataset."""
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    dataset_name = payload.name.strip()
    if not dataset_name:
        raise HTTPException(status_code=400, detail="Dataset name is required")

    try:
        dataset = client.create_dataset(
            name=dataset_name,
            description=payload.description,
            metadata=_merge_dataset_metadata(payload.metadata, user_id=str(current_user.id)),
        )
        if hasattr(client, "flush"):
            client.flush()
        # Invalidate dataset list cache for this user so the new entry appears immediately.
        _user_id = str(current_user.id)
        keys_to_drop = [k for k in list(_DATASETS_LIST_CACHE) if k.startswith(_user_id + "|")]
        for _k in keys_to_drop:
            _DATASETS_LIST_CACHE.pop(_k, None)
        return _dataset_to_response(dataset, item_count=0)
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        if "already exists" in message or "duplicate" in message or "unique" in message:
            raise HTTPException(status_code=409, detail=f"Dataset '{dataset_name}' already exists")
        logger.opt(exception=True).error("Error creating dataset '{}': {}", dataset_name, str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/datasets/{dataset_name}")
async def delete_dataset(
    dataset_name: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Dict[str, Any]:
    """Delete/purge a dataset for the current user."""
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        dataset = client.get_dataset(dataset_name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    if not _dataset_owned_by_user(dataset, str(current_user.id)):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    runs_deleted = 0
    items_deleted = 0
    errors: list[str] = []

    for run_obj in _fetch_all_dataset_runs(client, dataset_name=dataset_name, max_rows=2000):
        run_name = str(get_attr(run_obj, "name", default="") or "").strip()
        if not run_name:
            continue
        try:
            _delete_dataset_run(client, dataset_name=dataset_name, run_name=run_name)
            runs_deleted += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed deleting dataset run '{}' for '{}': {}", run_name, dataset_name, str(exc))
            errors.append(f"run:{run_name}:{exc}")

    for item_obj in _fetch_all_dataset_items(client, dataset_name=dataset_name, max_rows=5000):
        item_id = str(get_attr(item_obj, "id", default="") or "").strip()
        if not item_id:
            continue
        try:
            _delete_dataset_item(client, item_id)
            items_deleted += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed deleting dataset item '{}' for '{}': {}", item_id, dataset_name, str(exc))
            errors.append(f"item:{item_id}:{exc}")

    # Langfuse SDK currently exposes run/item deletion, but may not support deleting
    # the dataset container itself in every version.
    dataset_deleted = False
    if hasattr(client, "api") and hasattr(client.api, "datasets") and hasattr(client.api.datasets, "delete"):
        try:
            client.api.datasets.delete(dataset_name=dataset_name)
            dataset_deleted = True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Dataset container delete not available for '{}': {}", dataset_name, str(exc))

    if hasattr(client, "flush"):
        try:
            client.flush()
        except Exception:
            pass

    # Invalidate dataset list cache for this user.
    _del_user_id = str(current_user.id)
    for _k in [k for k in list(_DATASETS_LIST_CACHE) if k.startswith(_del_user_id + "|")]:
        _DATASETS_LIST_CACHE.pop(_k, None)
    return {
        "status": "deleted" if dataset_deleted else "purged",
        "dataset_name": dataset_name,
        "dataset_deleted": dataset_deleted,
        "runs_deleted": runs_deleted,
        "items_deleted": items_deleted,
        "errors": errors[:20],
    }


@router.get("/datasets/{dataset_name}/items")
async def list_dataset_items(
    dataset_name: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    page: Annotated[int, Query(ge=1)] = 1,
    source_trace_id: Annotated[str | None, Query()] = None,
) -> Dict[str, Any]:
    """List items in a dataset."""
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        dataset = client.get_dataset(dataset_name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    if not _dataset_owned_by_user(dataset, str(current_user.id)):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    try:
        rows, total = _fetch_dataset_items_page(client, dataset_name, page, limit)
        if source_trace_id:
            rows = [
                row
                for row in rows
                if str(get_attr(row, "source_trace_id", "sourceTraceId", default="") or "") == str(source_trace_id)
            ]
        return {
            "items": [_dataset_item_to_response(row) for row in rows],
            "total": total,
            "page": page,
            "limit": limit,
        }
    except Exception as exc:
        logger.opt(exception=True).error("Error listing dataset items for '{}': {}", dataset_name, str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/datasets/{dataset_name}/items")
async def create_dataset_item(
    dataset_name: str,
    payload: CreateDatasetItemRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DatasetItemResponse:
    """Create one dataset item from manual input or a trace."""
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        dataset = client.get_dataset(dataset_name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    if not _dataset_owned_by_user(dataset, str(current_user.id)):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    try:
        return _create_dataset_item_for_user(
            client=client,
            dataset_name=dataset_name,
            payload=payload,
            current_user_id=str(current_user.id),
            flush=True,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.opt(exception=True).error("Error creating dataset item for '{}': {}", dataset_name, str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/datasets/{dataset_name}/items/upload-csv")
async def upload_dataset_items_csv(
    dataset_name: str,
    csv_file: Annotated[UploadFile, File(...)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DatasetCsvImportResponse:
    """Bulk-create dataset items from CSV rows."""
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        dataset = client.get_dataset(dataset_name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    if not _dataset_owned_by_user(dataset, str(current_user.id)):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    filename = (csv_file.filename or "").strip()
    if filename and not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file")

    max_bytes = 10 * 1024 * 1024  # 10 MB
    max_rows = 5000
    max_error_rows = 100

    raw = await csv_file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded CSV is empty")
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"CSV file too large. Maximum supported size is {max_bytes // (1024 * 1024)} MB.",
        )

    try:
        text = raw.decode("utf-8-sig")
    except Exception:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV header row is required")

    total_rows = 0
    created_count = 0
    failed_count = 0
    skipped_count = 0
    errors: list[DatasetCsvImportError] = []

    try:
        for row_number, row in enumerate(reader, start=2):
            row_values = list((row or {}).values())
            if not any(str(value).strip() for value in row_values if value is not None):
                skipped_count += 1
                continue

            total_rows += 1
            if total_rows > max_rows:
                failed_count += 1
                errors.append(
                    DatasetCsvImportError(
                        row=row_number,
                        message=f"Row limit exceeded. Maximum import rows per file: {max_rows}",
                    )
                )
                break

            try:
                request_payload = _csv_row_to_dataset_item_request(row or {})
                _create_dataset_item_for_user(
                    client=client,
                    dataset_name=dataset_name,
                    payload=request_payload,
                    current_user_id=str(current_user.id),
                    flush=False,
                )
                created_count += 1
            except HTTPException as http_exc:
                failed_count += 1
                if len(errors) < max_error_rows:
                    detail = http_exc.detail
                    if isinstance(detail, (dict, list)):
                        message = json.dumps(detail, ensure_ascii=False)
                    else:
                        message = str(detail)
                    errors.append(DatasetCsvImportError(row=row_number, message=message))
            except Exception as exc:
                failed_count += 1
                if len(errors) < max_error_rows:
                    errors.append(DatasetCsvImportError(row=row_number, message=str(exc)))

        if total_rows == 0:
            raise HTTPException(status_code=400, detail="CSV has no importable rows")

        if created_count > 0 and hasattr(client, "flush"):
            client.flush()
    except HTTPException:
        raise
    except Exception as exc:
        logger.opt(exception=True).error(
            "Error importing CSV dataset items for '{}': {}",
            dataset_name,
            str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))

    return DatasetCsvImportResponse(
        dataset_name=dataset_name,
        total_rows=total_rows,
        created_count=created_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        errors=errors,
    )


@router.delete("/datasets/{dataset_name}/items/{item_id}")
async def delete_dataset_item(
    dataset_name: str,
    item_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Dict[str, Any]:
    """Delete one dataset item."""
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        dataset = client.get_dataset(dataset_name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    if not _dataset_owned_by_user(dataset, str(current_user.id)):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    item_obj = _fetch_dataset_item_by_id(client, item_id)
    if item_obj is None:
        # SDK fallback: scan current dataset items to find the item id.
        for candidate in _fetch_all_dataset_items(client, dataset_name=dataset_name, max_rows=5000):
            if str(get_attr(candidate, "id", default="") or "") == str(item_id):
                item_obj = candidate
                break

    if item_obj is None:
        raise HTTPException(status_code=404, detail=f"Dataset item '{item_id}' not found")

    item_dataset_name = str(get_attr(item_obj, "dataset_name", "datasetName", default="") or "")
    if item_dataset_name and item_dataset_name != dataset_name:
        raise HTTPException(status_code=404, detail=f"Dataset item '{item_id}' not found in dataset '{dataset_name}'")

    if not _dataset_item_owned_by_user(item_obj, str(current_user.id)):
        raise HTTPException(status_code=404, detail=f"Dataset item '{item_id}' not found")

    try:
        _delete_dataset_item(client, item_id)
        if hasattr(client, "flush"):
            client.flush()
        return {
            "status": "deleted",
            "dataset_name": dataset_name,
            "item_id": item_id,
        }
    except Exception as exc:  # noqa: BLE001
        logger.opt(exception=True).error("Error deleting dataset item '{}': {}", item_id, str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/datasets/{dataset_name}/runs")
async def list_dataset_runs(
    dataset_name: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    page: Annotated[int, Query(ge=1)] = 1,
) -> Dict[str, Any]:
    """List experiment runs for a dataset."""
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        dataset = client.get_dataset(dataset_name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    if not _dataset_owned_by_user(dataset, str(current_user.id)):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    try:
        rows, total = _fetch_dataset_runs_page(client, dataset_name, page, limit)
        return {
            "items": [_dataset_run_to_response(row) for row in rows],
            "total": total,
            "page": page,
            "limit": limit,
        }
    except Exception as exc:
        logger.opt(exception=True).error("Error listing dataset runs for '{}': {}", dataset_name, str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/datasets/{dataset_name}/runs/{run_id}")
async def get_dataset_run_detail(
    dataset_name: str,
    run_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    item_limit: Annotated[int, Query(ge=1, le=200)] = 50,
    score_limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DatasetRunDetailResponse:
    """Return a dataset run with item-level trace and score details."""
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        dataset = client.get_dataset(dataset_name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    if not _dataset_owned_by_user(dataset, str(current_user.id)):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    run_obj = _find_dataset_run_by_id(client, dataset_name=dataset_name, run_id=run_id, max_scan=1000)
    if not run_obj:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found in dataset '{dataset_name}'")

    run_name = str(get_attr(run_obj, "name", default="") or "")
    if not run_name:
        raise HTTPException(status_code=500, detail="Run name is missing for selected run")

    dataset_id = str(get_attr(dataset, "id", default="") or "") or str(get_attr(run_obj, "dataset_id", "datasetId", default="") or "")
    run_items = _fetch_dataset_run_items(
        client,
        dataset_name=dataset_name,
        dataset_id=dataset_id or None,
        run_name=run_name,
        item_limit=item_limit,
    )

    detailed_items: list[DatasetRunItemDetailResponse] = []
    user_id = str(current_user.id)
    for run_item in run_items:
        trace_id = str(get_attr(run_item, "trace_id", "traceId", default="") or "")
        trace_dict: dict[str, Any] | None = None
        score_rows: list[DatasetRunItemScoreResponse] = []

        if trace_id:
            try:
                trace_raw = _fetch_trace_by_id(client, trace_id)
                if trace_raw:
                    trace_dict = parse_trace_data(trace_raw)
            except Exception as trace_exc:
                logger.debug("Failed loading trace {} for dataset run detail: {}", trace_id, str(trace_exc))

            try:
                score_payloads = fetch_scores_for_trace(
                    client,
                    trace_id=trace_id,
                    user_id=user_id,
                    limit=score_limit,
                )
                for score in score_payloads or []:
                    source_value = get_attr(score, "source", default=None)
                    if hasattr(source_value, "value"):
                        source_value = source_value.value
                    score_rows.append(
                        DatasetRunItemScoreResponse(
                            id=str(get_attr(score, "id", default="") or ""),
                            name=str(get_attr(score, "name", default="") or "Score"),
                            value=float(get_attr(score, "value", default=0.0) or 0.0),
                            source=str(source_value) if source_value is not None else "API",
                            comment=get_attr(score, "comment", default=None),
                            created_at=get_attr(score, "created_at", "timestamp", "createdAt", default=None),
                        )
                    )
            except Exception as score_exc:
                logger.debug("Failed loading scores for trace {} in run detail: {}", trace_id, str(score_exc))

        if not score_rows:
            score_rows = _extract_run_item_evaluation_scores(run_item)

        detailed_items.append(
            _dataset_run_item_to_detail_response(
                run_item,
                trace_dict=trace_dict,
                scores=score_rows,
            )
        )

    return DatasetRunDetailResponse(
        run=_dataset_run_to_response(run_obj),
        item_count=len(run_items),
        items=detailed_items,
    )


@router.delete("/datasets/{dataset_name}/runs/{run_id}")
async def delete_dataset_run(
    dataset_name: str,
    run_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Dict[str, Any]:
    """Delete one dataset run by id."""
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        dataset = client.get_dataset(dataset_name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    if not _dataset_owned_by_user(dataset, str(current_user.id)):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    run_obj = _find_dataset_run_by_id(client, dataset_name=dataset_name, run_id=run_id, max_scan=1000)
    if not run_obj:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found in dataset '{dataset_name}'")

    run_name = str(get_attr(run_obj, "name", default="") or "").strip()
    if not run_name:
        raise HTTPException(status_code=500, detail="Run name is missing for selected run")

    try:
        _delete_dataset_run(client, dataset_name=dataset_name, run_name=run_name)
        if hasattr(client, "flush"):
            client.flush()
        return {
            "status": "deleted",
            "dataset_name": dataset_name,
            "run_id": run_id,
            "run_name": run_name,
        }
    except Exception as exc:  # noqa: BLE001
        logger.opt(exception=True).error("Error deleting dataset run '{}': {}", run_id, str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/datasets/{dataset_name}/experiments")
async def run_dataset_experiment(
    dataset_name: str,
    payload: RunDatasetExperimentRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DatasetExperimentEnqueueResponse:
    """Queue an experiment run against a dataset."""
    client = get_langfuse_client()
    if not client:
        raise HTTPException(status_code=503, detail="Langfuse not configured.")

    try:
        dataset = client.get_dataset(dataset_name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    if not _dataset_owned_by_user(dataset, str(current_user.id)):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    agent_payload = await _resolve_agent_payload_for_experiment(
        agent_id=payload.agent_id,
        current_user=current_user,
    )
    generation_model = (payload.generation_model or "").strip() or None
    generation_model_api_key = (payload.generation_model_api_key or "").strip() or None

    if not agent_payload and not generation_model:
        raise HTTPException(
            status_code=400,
            detail="Select an agent or provide a generation model.",
        )
    if not agent_payload and not generation_model_api_key:
        raise HTTPException(
            status_code=400,
            detail="Generation model API key is required when no agent is selected.",
        )

    judge_cfg = await _resolve_experiment_judge_config(
        current_user=current_user,
        evaluator_config_id=payload.evaluator_config_id,
        preset_id=payload.preset_id,
        evaluator_name=payload.evaluator_name,
        criteria=payload.criteria,
        judge_model=payload.judge_model or payload.model,
        judge_model_api_key=payload.judge_model_api_key or payload.model_api_key,
    )
    if judge_cfg["criteria"] and not judge_cfg["model"]:
        judge_cfg["model"] = "gpt-4o"
    if judge_cfg.get("requires_ground_truth"):
        dataset_items = list(getattr(dataset, "items", []) or [])
        has_ground_truth = any(
            get_attr(item, "expected_output", "expectedOutput", default=None) not in (None, "", [])
            for item in dataset_items
        )
        if not has_ground_truth:
            raise HTTPException(
                status_code=400,
                detail="Selected evaluator preset requires ground truth, but dataset items do not have expected_output.",
            )

    job_id = str(uuid4())
    _set_dataset_experiment_job(
        job_id,
        status="queued",
        dataset_name=dataset_name,
        experiment_name=payload.experiment_name,
        started_at=None,
        finished_at=None,
        result=None,
        error=None,
        user_id=str(current_user.id),
    )

    background_tasks.add_task(
        _run_dataset_experiment_job,
        job_id=job_id,
        client=client,
        dataset_name=dataset_name,
        experiment_name=payload.experiment_name,
        description=payload.description,
        user_id=str(current_user.id),
        agent_payload=agent_payload,
        generation_model=generation_model,
        generation_model_api_key=generation_model_api_key,
        judge_name=judge_cfg["judge_name"],
        judge_preset_id=judge_cfg.get("preset_id"),
        judge_criteria=judge_cfg["criteria"],
        judge_model=judge_cfg["model"],
        judge_model_api_key=judge_cfg["model_api_key"],
    )

    return DatasetExperimentEnqueueResponse(
        job_id=job_id,
        dataset_name=dataset_name,
        experiment_name=payload.experiment_name,
        status="queued",
    )


@router.get("/datasets/experiments/{job_id}")
async def get_dataset_experiment_job(
    job_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DatasetExperimentJobResponse:
    """Fetch status for a background dataset experiment job."""
    payload = _get_dataset_experiment_job(job_id)
    if not payload or str(payload.get("user_id")) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Dataset experiment job not found")
    return _dataset_job_response(job_id, payload)


# =============================================================================
# Presets Configuration
# =============================================================================

EVALUATION_PRESETS = [
    {
        "id": "correctness",
        "name": "Correctness",
        "description": "Evaluate if the output is factually correct compared to the ground truth.",
        "criteria": "Evaluate the correctness of the generation against the ground truth on a scale 0-1. Consider:\n- Factual accuracy: Does the output match the ground truth?\n- Completeness: Are all key points from the ground truth covered?\n- Precision: Is the information accurate without hallucinations?",
        "requires_ground_truth": True,
    },
    {
        "id": "helpfulness",
        "name": "Helpfulness",
        "description": "Evaluate how helpful the response is to the user's query.",
        "criteria": "Evaluate how helpful the output is in addressing the user's input on a scale 0-1. Consider:\n- Relevance: Does it directly address what was asked?\n- Clarity: Is the response easy to understand?\n- Actionability: Can the user act on this information?",
        "requires_ground_truth": False,
    },
    {
        "id": "conciseness",
        "name": "Conciseness",
        "description": "Evaluate if the response is appropriately concise without unnecessary verbosity.",
        "criteria": "Evaluate the conciseness of the output on a scale 0-1. Consider:\n- Brevity: Is it as short as possible while being complete?\n- Focus: Does it avoid tangential information?\n- Efficiency: Does it convey the message without redundancy?",
        "requires_ground_truth": False,
    },
    {
        "id": "coherence",
        "name": "Coherence",
        "description": "Evaluate if the response agents logically and makes sense.",
        "criteria": "Evaluate the coherence and logical agent of the output on a scale 0-1. Consider:\n- Logical structure: Do ideas connect naturally?\n- Internal consistency: Are there contradictions?\n- Clarity of thought: Is the reasoning easy to follow?",
        "requires_ground_truth": False,
    },
    {
        "id": "relevance",
        "name": "Relevance",
        "description": "Evaluate how relevant the response is to the input query.",
        "criteria": "Evaluate the relevance of the output to the input query on a scale 0-1. Consider:\n- Topic alignment: Does it stay on topic?\n- Query understanding: Does it address the user's intent?\n- Information pertinence: Is all information provided relevant?",
        "requires_ground_truth": False,
    },
]


def get_preset_by_id(preset_id: str | None) -> Dict[str, Any] | None:
    """Return preset configuration by id."""
    if not preset_id:
        return None
    for preset in EVALUATION_PRESETS:
        if str(preset.get("id")) == str(preset_id):
            return preset
    return None


def validate_ground_truth_requirement(preset_id: str | None, ground_truth: str | None) -> None:
    """Validate whether ground truth is provided for presets that require it."""
    preset = get_preset_by_id(preset_id)
    if preset and preset.get("requires_ground_truth") and not (ground_truth or "").strip():
        raise HTTPException(
            status_code=400,
            detail=f"Ground truth is required for preset '{preset.get('name', preset_id)}'.",
        )


async def run_saved_evaluators_for_new_trace(
    *,
    trace_id: str,
    user_id: str,
    agent_id: str | None = None,
    agent_name: str | None = None,
    session_id: str | None = None,
    project_name: str | None = None,
    timestamp: datetime | None = None,
) -> int:
    """Run all saved evaluators targeting new traces for a just-finished trace."""
    logger.info(
        f"🔍 EVALUATOR FUNCTION CALLED: trace={trace_id}, user={user_id}, "
        f"agent_id={agent_id}, agent_id={agent_id}, agent_name={agent_name}"
    )
    
    if not (LITELLM_AVAILABLE or OPENAI_AVAILABLE):
        logger.warning("⚠️ LiteLLM/OpenAI not available, skipping evaluators")
        return 0

    try:
        user_uuid = UUID(str(user_id))
    except Exception:
        logger.warning(f"Invalid user_id for new-trace evaluation: {user_id}")
        return 0

    client = get_langfuse_client()
    if not client:
        logger.warning("⚠️ Langfuse client not available, skipping evaluators")
        return 0

    requested_timestamp = _parse_trace_timestamp(timestamp) or datetime.now(timezone.utc)
    trace_ref_id = str(trace_id)
    
    # Use agent_id or agent_id (they're aliases)
    agent_id = agent_id or agent_id

    trace_dict: Dict[str, Any] = {
        "id": trace_ref_id,
        "session_id": session_id,
        "timestamp": requested_timestamp,
        "metadata": {
            "agent_id": _normalize_agent_id(agent_id),
            "agent_name": agent_name,
            "project_name": project_name,
            "run_id": trace_ref_id,
        },
    }

    resolved_trace_id, resolved_trace_dict = await _resolve_trace_for_judge(
        client,
        trace_id=trace_ref_id,
        user_id=str(user_id),
        session_id=session_id,
        agent_id=agent_id,
        agent_name=agent_name,
        project_name=project_name,
        timestamp=requested_timestamp,
        max_attempts=4,
    )
    if resolved_trace_dict:
        trace_dict = resolved_trace_dict

    try:
        async with session_scope() as session:
            stmt = select(Evaluator).where(Evaluator.user_id == user_uuid)
            rows = await session.exec(stmt)
            evaluators = rows.all()
    except Exception as e:
        logger.warning("Failed loading evaluators for new trace {}: {}", trace_id, str(e))
        return 0

    logger.info(f" Found {len(evaluators)} evaluator(s) for user {user_id}")
    
    scheduled = 0
    for idx, evaluator in enumerate(evaluators, 1):
        logger.info(
            f" Evaluator {idx}/{len(evaluators)}: name='{evaluator.name}', "
            f"target={evaluator.target}, agent_id={evaluator.agent_id}, "
            f"agent_ids={evaluator.agent_ids}, agent_name={evaluator.agent_name}"
        )
        
        targets = _normalize_targets(evaluator.target)
        if "new" not in targets:
            logger.info(f"  Skipping: target={targets} (not 'new')")
            continue

        logger.info(
            f"   Checking filters: trace_dict_agent_id={trace_dict.get('metadata', {}).get('agent_id')}, "
            f"trace_dict_agent_name={trace_dict.get('metadata', {}).get('agent_name')}"
        )
        
        matches = _trace_matches_evaluator_filters(
            trace_dict,
            trace_id=evaluator.trace_id,
            session_id=evaluator.session_id,
            agent_id=evaluator.agent_id,
            agent_ids=evaluator.agent_ids,
            agent_name=evaluator.agent_name,
            project_name=evaluator.project_name,
            ts_from=evaluator.ts_from,
            ts_to=evaluator.ts_to,
        )
        
        if not matches:
            logger.info(f"   Skipping: trace does not match filters")
            continue
        
        logger.info(f"  MATCH! Scheduling evaluation for '{evaluator.name}'")

        # Skip invalid evaluator definitions instead of failing all.
        try:
            validate_ground_truth_requirement(evaluator.preset_id, evaluator.ground_truth)
        except HTTPException as e:
            logger.warning(
                f"Skipping evaluator {evaluator.id} for trace {trace_id}: {e.detail}"
            )
            continue

        asyncio.create_task(
            run_llm_judge_task(
                client=client,
                trace_id=str(resolved_trace_id or trace_ref_id),
                criteria=evaluator.criteria,
                score_name=f"Evaluator: {evaluator.name}",
                model=evaluator.model or "gpt-4o",
                user_id=str(user_id),
                model_api_key=evaluator.model_api_key,
                preset_id=evaluator.preset_id,
                ground_truth=evaluator.ground_truth,
                session_id=session_id,
                agent_id=agent_id,
                agent_name=agent_name,
                project_name=project_name,
                timestamp=requested_timestamp,
            )
        )
        scheduled += 1

    if scheduled:
        logger.info(
            f" Scheduled {scheduled} new-trace evaluator(s) for trace_ref={trace_ref_id}, "
            f"resolved_trace_id={resolved_trace_id}, user_id={user_id}"
        )
    else:
        logger.info(
            f"No evaluators scheduled for trace {trace_ref_id}. "
            f"Total evaluators checked: {len(evaluators)}"
        )
    return scheduled


@router.get("/presets")
async def list_evaluation_presets(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[Dict[str, Any]]:
    """List available evaluation presets with their requirements."""
    return EVALUATION_PRESETS


@router.get("/models")
async def list_evaluation_models(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Dict[str, Any]:
    """Return agents accessible to the current user as a normalized model list.

    This endpoint intentionally uses the application's standard auth (JWT/cookie)
    so the frontend can fetch the Model Catalogue without requiring an API key.
    """
    try:
        async with session_scope() as session:
            stmt = select(agent).where(
                or_(
                    agent.user_id == current_user.id,
                    agent.access_type == AccessTypeEnum.PUBLIC,
                )
            )
            is_component_col = getattr(agent, "is_component", None)
            if is_component_col is not None:
                stmt = stmt.where(
                    or_(
                        is_component_col == False,  # noqa: E712
                        is_component_col.is_(None),
                    )
                )
            _res = await session.exec(stmt)
            agents = _res.all()

        def to_payload(agent_obj: agent) -> dict:
            updated = agent_obj.updated_at
            try:
                updated_dt = datetime.fromisoformat(updated) if isinstance(updated, str) else updated
            except Exception:
                updated_dt = None
            created_ts = int(updated_dt.timestamp()) if updated_dt else int(time.time())
            endpoint_name = getattr(agent_obj, "endpoint_name", None)
            model_id = endpoint_name or agent_obj.id
            access = agent_obj.access_type.value if agent_obj.access_type else AccessTypeEnum.PRIVATE.value
            return {
                "id": f"lb:{model_id}",
                "name": agent_obj.name,
                "object": "model",
                "created": created_ts,
                "owned_by": str(agent_obj.user_id) if agent_obj.user_id else None,
                "root": f"lb:{model_id}",
                "parent": None,
                "permission": [],
                "metadata": {
                    "display_name": agent_obj.name,
                    "description": agent_obj.description,
                    "endpoint_name": endpoint_name,
                    # New canonical key used across the codebase
                    "agent_id": str(agent_obj.id),
                    # Legacy aliases expected by some frontend codepaths — keep for compatibility
                    "agent_id": str(agent_obj.id),
                    "agent_ids": [str(agent_obj.id)],
                    "access": access,
                },
            }

        return {"object": "list", "data": [to_payload(f) for f in agents]}
    except Exception as e:
        logger.opt(exception=True).error("Error listing evaluation models: {}", str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def _enqueue_existing_trace_evaluations(
    *,
    background_tasks: BackgroundTasks,
    user_id: str,
    evaluator_name: str,
    criteria: str,
    model: str | None,
    trace_id: str | None = None,
    agent_id: str | None = None,
    agent_ids: Optional[List[str]] = None,
    agent_name: str | None = None,
    session_id: str | None = None,
    project_name: str | None = None,
    ts_from: datetime | None = None,
    ts_to: datetime | None = None,
    model_api_key: str | None = None,
    preset_id: str | None = None,
    ground_truth: str | None = None,
) -> int:
    """Queue evaluator runs for all matching existing traces."""
    validate_ground_truth_requirement(preset_id, ground_truth)

    client = get_langfuse_client()
    if not client:
        return 0

    normalized_agent_id = _normalize_agent_id(agent_id)
    normalized_agent_ids = _normalize_agent_ids(agent_ids)

    try:
        traces = fetch_traces_from_langfuse(
            client,
            user_id=user_id,
            limit=1000,
            from_timestamp=ts_from,
            to_timestamp=ts_to,
        )
    except Exception as exc:
        logger.warning("Failed to fetch traces for evaluator run: {}", str(exc))
        return 0

    enqueued = 0
    seen_trace_ids: set[str] = set()
    for trace in traces or []:
        trace_dict = parse_trace_data(trace)
        if not _trace_matches_evaluator_filters(
            trace_dict,
            trace_id=trace_id,
            session_id=session_id,
            agent_id=normalized_agent_id,
            agent_ids=normalized_agent_ids,
            agent_name=agent_name,
            project_name=project_name,
            ts_from=ts_from,
            ts_to=ts_to,
        ):
            continue

        matched_trace_id = str(trace_dict.get("id") or "")
        if not matched_trace_id:
            continue
        if matched_trace_id in seen_trace_ids:
            continue
        seen_trace_ids.add(matched_trace_id)

        background_tasks.add_task(
            run_llm_judge_task,
            client=client,
            trace_id=matched_trace_id,
            criteria=criteria,
            score_name=f"Evaluator: {evaluator_name}",
            model=model or "gpt-4o",
            user_id=user_id,
            model_api_key=model_api_key,
            preset_id=preset_id,
            ground_truth=ground_truth,
            session_id=str(trace_dict.get("session_id") or "") or None,
            agent_id=_extract_trace_agent_id(trace_dict),
            agent_name=_extract_trace_agent_name(trace_dict),
            project_name=_extract_trace_project_name(trace_dict),
            timestamp=_parse_trace_timestamp(trace_dict.get("timestamp")),
        )
        enqueued += 1

    return enqueued


@router.post("/configs")
async def create_evaluator_config(
    payload: EvaluatorCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> EvaluatorResponse:
    """Create a reusable evaluator configuration and optionally run on existing traces."""
    try:
        normalized_target = _normalize_targets(payload.target)
        invalid_targets = [target for target in normalized_target if target not in {"existing", "new"}]
        if invalid_targets:
            raise HTTPException(status_code=400, detail=f"Invalid target value(s): {', '.join(invalid_targets)}")
        normalized_agent_id = _normalize_agent_id(payload.agent_id)
        normalized_agent_ids = _normalize_agent_ids(payload.agent_ids)
        validate_ground_truth_requirement(payload.preset_id, payload.ground_truth)

        from_ts = _parse_iso_datetime_or_400(payload.ts_from, "ts_from")
        to_ts = _parse_iso_datetime_or_400(payload.ts_to, "ts_to")

        async with session_scope() as session:
            evaluator = Evaluator(
                name=payload.name,
                criteria=payload.criteria,
                model=payload.model,
                preset_id=payload.preset_id,
                ground_truth=payload.ground_truth,
                target=normalized_target,
                trace_id=payload.trace_id,
                agent_id=normalized_agent_id,
                agent_ids=normalized_agent_ids or None,
                agent_name=payload.agent_name,
                session_id=payload.session_id,
                project_name=payload.project_name,
                ts_from=from_ts,
                ts_to=to_ts,
                model_api_key=payload.model_api_key,
                user_id=current_user.id,
            )
            session.add(evaluator)
            await session.commit()
            await session.refresh(evaluator)

        eid = str(evaluator.id)
        logger.info(
            f"evaluation - Created evaluator config in DB: id={eid}, user={current_user.id}, target={normalized_target}"
        )

        # If target includes 'existing', fetch matching traces and enqueue judge tasks.
        if "existing" in normalized_target:
            enqueued = await _enqueue_existing_trace_evaluations(
                background_tasks=background_tasks,
                user_id=str(current_user.id),
                evaluator_name=payload.name,
                criteria=payload.criteria,
                model=payload.model,
                trace_id=payload.trace_id,
                agent_id=normalized_agent_id,
                agent_ids=normalized_agent_ids,
                agent_name=payload.agent_name,
                session_id=payload.session_id,
                project_name=payload.project_name,
                ts_from=from_ts,
                ts_to=to_ts,
                model_api_key=payload.model_api_key,
                preset_id=payload.preset_id,
                ground_truth=payload.ground_truth,
            )
            logger.info(f"evaluation - Enqueued {enqueued} judge tasks for evaluator id={eid}")

        return EvaluatorResponse(**evaluator.to_response())
    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error("Error creating evaluator config: {}", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/configs/{config_id}/run")
async def run_evaluator_config(
    config_id: str,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Dict[str, Any]:
    """Run an existing saved evaluator against matching existing traces."""
    try:
        async with session_scope() as session:
            try:
                eval_obj = await session.get(Evaluator, UUID(config_id))
            except Exception:
                raise HTTPException(status_code=404, detail="Evaluator not found")
            if not eval_obj or str(current_user.id) != str(eval_obj.user_id):
                raise HTTPException(status_code=404, detail="Evaluator not found")

        normalized_target = _normalize_targets(eval_obj.target)
        if "existing" not in normalized_target:
            logger.info(
                "evaluation - Skipping manual run for evaluator id={} user={} target={}",
                config_id,
                current_user.id,
                normalized_target,
            )
            return {
                "status": "noop",
                "config_id": config_id,
                "enqueued": 0,
                "target": normalized_target,
                "message": "Evaluator is configured for new traces only. It will run automatically on new traces.",
            }

        enqueued = await _enqueue_existing_trace_evaluations(
            background_tasks=background_tasks,
            user_id=str(current_user.id),
            evaluator_name=eval_obj.name,
            criteria=eval_obj.criteria,
            model=eval_obj.model,
            trace_id=eval_obj.trace_id,
            agent_id=eval_obj.agent_id,
            agent_ids=eval_obj.agent_ids,
            agent_name=eval_obj.agent_name,
            session_id=eval_obj.session_id,
            project_name=eval_obj.project_name,
            ts_from=eval_obj.ts_from,
            ts_to=eval_obj.ts_to,
            model_api_key=eval_obj.model_api_key,
            preset_id=eval_obj.preset_id,
            ground_truth=eval_obj.ground_truth,
        )
        logger.info(
            "evaluation - Enqueued {} judge tasks for existing evaluator id={} user={}",
            enqueued,
            config_id,
            current_user.id,
        )
        return {
            "status": "queued",
            "config_id": config_id,
            "enqueued": enqueued,
            "target": normalized_target,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error("Error running evaluator config: {}", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/configs")
async def list_evaluator_configs(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[EvaluatorResponse]:
    """List evaluator configs for the current user."""
    try:
        async with session_scope() as session:
            stmt = select(Evaluator).where(Evaluator.user_id == current_user.id)
            res = await session.exec(stmt)
            evaluators = res.all()
        return [EvaluatorResponse(**e.to_response()) for e in evaluators]
    except Exception as e:
        logger.opt(exception=True).error("Error listing evaluator configs: {}", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/configs/{config_id}")
async def update_evaluator_config(
    config_id: str,
    payload: EvaluatorCreateRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> EvaluatorResponse:
    """Update an existing evaluator config."""
    try:
        validate_ground_truth_requirement(payload.preset_id, payload.ground_truth)
        normalized_target = _normalize_targets(payload.target)
        invalid_targets = [target for target in normalized_target if target not in {"existing", "new"}]
        if invalid_targets:
            raise HTTPException(status_code=400, detail=f"Invalid target value(s): {', '.join(invalid_targets)}")
        normalized_agent_id = _normalize_agent_id(payload.agent_id)
        normalized_agent_ids = _normalize_agent_ids(payload.agent_ids)
        from_ts = _parse_iso_datetime_or_400(payload.ts_from, "ts_from")
        to_ts = _parse_iso_datetime_or_400(payload.ts_to, "ts_to")

        # Fetch evaluator from DB
        async with session_scope() as session:
            try:
                eval_obj = await session.get(Evaluator, UUID(config_id))
            except Exception:
                raise HTTPException(status_code=404, detail="Evaluator not found")
            if not eval_obj or str(current_user.id) != str(eval_obj.user_id):
                raise HTTPException(status_code=404, detail="Evaluator not found")

            eval_obj.name = payload.name
            eval_obj.criteria = payload.criteria
            eval_obj.model = payload.model
            eval_obj.preset_id = payload.preset_id
            eval_obj.ground_truth = payload.ground_truth
            eval_obj.target = normalized_target
            eval_obj.trace_id = payload.trace_id
            eval_obj.agent_id = normalized_agent_id
            eval_obj.agent_ids = normalized_agent_ids or None
            eval_obj.agent_name = payload.agent_name
            eval_obj.session_id = payload.session_id
            eval_obj.project_name = payload.project_name
            eval_obj.ts_from = from_ts
            eval_obj.ts_to = to_ts
            eval_obj.model_api_key = payload.model_api_key

            session.add(eval_obj)
            await session.commit()
            await session.refresh(eval_obj)

        return EvaluatorResponse(**eval_obj.to_response())
    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error("Error updating evaluator config: {}", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/configs/{config_id}")
async def delete_evaluator_config(
    config_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Dict[str, str]:
    """Delete an evaluator config."""
    try:
        async with session_scope() as session:
            try:
                eval_obj = await session.get(Evaluator, UUID(config_id))
            except Exception:
                raise HTTPException(status_code=404, detail="Evaluator not found")
            if not eval_obj or str(current_user.id) != str(eval_obj.user_id):
                raise HTTPException(status_code=404, detail="Evaluator not found")
            await session.delete(eval_obj)
            await session.commit()
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error("Error deleting evaluator config: {}", str(e))
        raise HTTPException(status_code=500, detail=str(e))
