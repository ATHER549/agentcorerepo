"""Pydantic response models for observability API endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Langfuse connection
# ---------------------------------------------------------------------------

class LangfuseStatusResponse(BaseModel):
    connected: bool
    host: str | None = None
    message: str


# ---------------------------------------------------------------------------
# Observations & Scores
# ---------------------------------------------------------------------------

class ObservationResponse(BaseModel):
    id: str
    trace_id: str
    name: str | None = None
    type: str | None = None  # "GENERATION", "SPAN", "EVENT"
    model: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    completion_start_time: datetime | None = None
    latency_ms: float | None = None
    time_to_first_token_ms: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    input: Any | None = None
    output: Any | None = None
    metadata: dict | None = None
    level: str | None = None  # "DEBUG", "DEFAULT", "WARNING", "ERROR"
    status_message: str | None = None
    parent_observation_id: str | None = None


class ScoreItem(BaseModel):
    id: str
    name: str
    value: float
    source: str | None = None
    comment: str | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------

class TraceListItem(BaseModel):
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
    traces: list[TraceListItem]
    total: int
    page: int
    limit: int
    scope_warning: bool = False
    scope_warning_message: str | None = None


class TraceDetailResponse(BaseModel):
    id: str
    name: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    timestamp: datetime | None = None
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    latency_ms: float | None = None
    models_used: list[str] = []
    observations: list[ObservationResponse] = []
    scores: list[ScoreItem] = []
    input: Any | None = None
    output: Any | None = None
    metadata: dict | None = None
    tags: list[str] = []
    level: str | None = None
    status: str | None = None
    scope_warning: bool = False
    scope_warning_message: str | None = None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class SessionListItem(BaseModel):
    session_id: str
    trace_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float | None = None
    first_trace_at: datetime | None = None
    last_trace_at: datetime | None = None
    models_used: list[str] = []
    error_count: int = 0
    has_errors: bool = False


class SessionsListResponse(BaseModel):
    sessions: list[SessionListItem]
    total: int
    truncated: bool = False
    fetched_trace_count: int = 0
    scope_warning: bool = False
    scope_warning_message: str | None = None


class SessionDetailResponse(BaseModel):
    session_id: str
    trace_count: int = 0
    observation_count: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float | None = None
    first_trace_at: datetime | None = None
    last_trace_at: datetime | None = None
    duration_seconds: float | None = None
    models_used: dict[str, dict] = {}
    traces: list[TraceListItem] = []
    scope_warning: bool = False
    scope_warning_message: str | None = None


# ---------------------------------------------------------------------------
# Metrics / Overview
# ---------------------------------------------------------------------------

class ModelUsageItem(BaseModel):
    model: str
    call_count: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float | None = None


class DailyUsageItem(BaseModel):
    date: str
    trace_count: int = 0
    observation_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0


class MetricsResponse(BaseModel):
    total_traces: int = 0
    total_observations: int = 0
    total_sessions: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    by_model: list[ModelUsageItem] = []
    by_date: list[DailyUsageItem] = []
    top_agents: list[dict] = []
    truncated: bool = False
    fetched_trace_count: int = 0
    cache_age_seconds: int | None = None
    cache_is_fresh: bool | None = None
    scope_warning: bool = False
    scope_warning_message: str | None = None


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class AgentListItem(BaseModel):
    agent_id: str
    agent_name: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    trace_count: int = 0
    session_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float | None = None
    models_used: list[str] = []
    last_activity: datetime | None = None
    error_count: int = 0


class AgentListResponse(BaseModel):
    agents: list[AgentListItem]
    total: int
    truncated: bool = False
    fetched_trace_count: int = 0
    scope_warning: bool = False
    scope_warning_message: str | None = None


class AgentDetailResponse(BaseModel):
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
    models_used: dict[str, dict] = {}
    sessions: list[SessionListItem] = []
    by_date: list[DailyUsageItem] = []
    scope_warning: bool = False
    scope_warning_message: str | None = None


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class ProjectListItem(BaseModel):
    project_id: str
    project_name: str | None = None
    agent_count: int = 0
    trace_count: int = 0
    session_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    last_activity: datetime | None = None


class ProjectListResponse(BaseModel):
    projects: list[ProjectListItem]
    total: int
    truncated: bool = False
    fetched_trace_count: int = 0
    scope_warning: bool = False
    scope_warning_message: str | None = None


class ProjectDetailResponse(BaseModel):
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
    models_used: dict[str, dict] = {}
    agents: list[AgentListItem] = []
    by_date: list[DailyUsageItem] = []
    scope_warning: bool = False
    scope_warning_message: str | None = None
