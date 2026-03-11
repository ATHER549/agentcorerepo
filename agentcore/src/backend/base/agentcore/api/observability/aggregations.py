"""Pure aggregation functions that consume EnrichedTrace lists.

All functions are stateless: they take enriched traces (+ optional DB lookups)
and return response-model-ready data.  No Langfuse calls, no caching.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlmodel import select

from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.folder.model import Folder

from .models import (
    AgentListItem,
    DailyUsageItem,
    ModelUsageItem,
    ProjectListItem,
    SessionListItem,
    TraceListItem,
)
from .parsing import get_attr, normalize_metadata
from .trace_store import EnrichedTrace


# ---------------------------------------------------------------------------
# Agent matching
# ---------------------------------------------------------------------------

def _is_vertex_trace(trace_name: str | None) -> bool:
    """Check if a trace name looks like a vertex-level trace (not an agent trace)."""
    if not trace_name:
        return False
    vertex_prefixes = ("vertex_", "vertex_build_")
    if trace_name.startswith(vertex_prefixes):
        return True
    if "-" in trace_name:
        parts = trace_name.rsplit("-", 1)
        if len(parts) == 2 and len(parts[1]) == 5 and parts[1].isalnum():
            return True
    return False


def match_trace_to_agent(
    trace: EnrichedTrace,
    agents_by_id: dict[str, Agent],
    agents_by_name: dict[str, Agent],
) -> tuple[str | None, str | None]:
    """Match a trace to a DB agent.  Returns (agent_id, agent_name) or (None, None)."""
    trace_name = trace.name
    metadata = trace.metadata
    tags = trace.tags

    agents_by_name_lower = {
        str(name).strip().lower(): agent
        for name, agent in agents_by_name.items()
        if name
    }

    # Method 1: metadata agent_id
    agent_id_from_meta = metadata.get("agent_id") or metadata.get("agentId")
    agent_id_str = str(agent_id_from_meta).strip() if agent_id_from_meta else None
    if agent_id_str and agent_id_str in agents_by_id:
        agent = agents_by_id[agent_id_str]
        return str(agent.id), agent.name

    # Method 2: tags
    for tag in tags:
        if isinstance(tag, str) and tag.startswith("agent_id:"):
            fid = str(tag.split(":", 1)[1]).strip()
            if fid in agents_by_id:
                agent = agents_by_id[fid]
                return str(agent.id), agent.name

    # Method 3: metadata agent_name
    agent_name_from_meta = metadata.get("agent_name") or metadata.get("agentName")
    if agent_name_from_meta:
        agent = agents_by_name.get(agent_name_from_meta)
        if agent:
            return str(agent.id), agent.name
        agent = agents_by_name_lower.get(str(agent_name_from_meta).strip().lower())
        if agent:
            return str(agent.id), agent.name

    # Skip vertex traces for name-based fallback
    if _is_vertex_trace(trace_name):
        return None, None

    # Method 4: trace name match
    if trace_name:
        if trace_name in agents_by_name:
            agent = agents_by_name[trace_name]
            return str(agent.id), agent.name
        trace_name_lower = str(trace_name).strip().lower()
        if trace_name_lower in agents_by_name_lower:
            agent = agents_by_name_lower[trace_name_lower]
            return str(agent.id), agent.name
        if " - " in trace_name:
            name_part = trace_name.rsplit(" - ", 1)[0]
            if name_part in agents_by_name:
                agent = agents_by_name[name_part]
                return str(agent.id), agent.name
            name_part_lower = str(name_part).strip().lower()
            if name_part_lower in agents_by_name_lower:
                agent = agents_by_name_lower[name_part_lower]
                return str(agent.id), agent.name

    return None, None


def _match_raw_trace_to_agent(
    trace: Any,
    agents_by_id: dict[str, Agent],
    agents_by_name: dict[str, Agent],
) -> tuple[str | None, str | None]:
    """Match a RAW trace (not enriched) to a DB agent."""
    trace_name = get_attr(trace, "name")
    metadata = normalize_metadata(get_attr(trace, "metadata", default={}) or {})
    tags = get_attr(trace, "tags", default=[]) or []

    agents_by_name_lower = {str(n).strip().lower(): a for n, a in agents_by_name.items() if n}

    agent_id_from_meta = metadata.get("agent_id") or metadata.get("agentId")
    agent_id_str = str(agent_id_from_meta).strip() if agent_id_from_meta else None
    if agent_id_str and agent_id_str in agents_by_id:
        agent = agents_by_id[agent_id_str]
        return str(agent.id), agent.name

    for tag in tags:
        if isinstance(tag, str) and tag.startswith("agent_id:"):
            fid = str(tag.split(":", 1)[1]).strip()
            if fid in agents_by_id:
                agent = agents_by_id[fid]
                return str(agent.id), agent.name

    agent_name_from_meta = metadata.get("agent_name") or metadata.get("agentName")
    if agent_name_from_meta:
        agent = agents_by_name.get(agent_name_from_meta)
        if agent:
            return str(agent.id), agent.name
        agent = agents_by_name_lower.get(str(agent_name_from_meta).strip().lower())
        if agent:
            return str(agent.id), agent.name

    if _is_vertex_trace(trace_name):
        return None, None

    if trace_name:
        if trace_name in agents_by_name:
            agent = agents_by_name[trace_name]
            return str(agent.id), agent.name
        trace_name_lower = str(trace_name).strip().lower()
        if trace_name_lower in agents_by_name_lower:
            agent = agents_by_name_lower[trace_name_lower]
            return str(agent.id), agent.name
        if " - " in trace_name:
            name_part = trace_name.rsplit(" - ", 1)[0]
            if name_part in agents_by_name:
                agent = agents_by_name[name_part]
                return str(agent.id), agent.name
            if str(name_part).strip().lower() in agents_by_name_lower:
                agent = agents_by_name_lower[str(name_part).strip().lower()]
                return str(agent.id), agent.name

    return None, None


def user_agents_stmt(user_ids: UUID | list[UUID] | set[UUID]):
    """Build a user-agent query compatible with schemas that may not expose `is_component`."""
    if isinstance(user_ids, set):
        user_ids = list(user_ids)
    if isinstance(user_ids, list):
        if not user_ids:
            stmt = select(Agent).where(Agent.user_id.is_(None))
        else:
            stmt = select(Agent).where(Agent.user_id.in_(user_ids))
    else:
        stmt = select(Agent).where(Agent.user_id == user_ids)
    is_component_col = getattr(Agent, "is_component", None)
    if is_component_col is not None:
        stmt = stmt.where((is_component_col == False) | (is_component_col.is_(None)))  # noqa: E712
    return stmt


# ---------------------------------------------------------------------------
# Metrics aggregation
# ---------------------------------------------------------------------------

def aggregate_metrics(
    traces: list[EnrichedTrace],
    tz_offset: int | None = None,
) -> dict[str, Any]:
    """Aggregate metrics from enriched traces.

    Returns a dict matching MetricsResponse fields.
    """
    total_traces = len(traces)
    total_observations = 0
    total_tokens = 0
    input_tokens = 0
    output_tokens = 0
    total_cost = 0.0
    latencies: list[float] = []
    sessions: set[str] = set()

    model_data: dict[str, dict] = defaultdict(lambda: {
        "call_count": 0, "total_tokens": 0, "input_tokens": 0,
        "output_tokens": 0, "total_cost": 0.0, "latencies": [],
    })
    daily_data: dict[str, dict] = defaultdict(lambda: {
        "trace_count": 0, "observation_count": 0, "total_tokens": 0, "total_cost": 0.0,
    })
    agent_data: dict[str, dict] = defaultdict(lambda: {"count": 0, "tokens": 0, "cost": 0.0})

    for t in traces:
        total_observations += t.observation_count
        total_tokens += t.total_tokens
        input_tokens += t.input_tokens
        output_tokens += t.output_tokens
        total_cost += t.total_cost
        if t.latency_ms is not None:
            latencies.append(t.latency_ms)
        if t.session_id:
            sessions.add(t.session_id)

        # Date bucketing
        if t.timestamp:
            if tz_offset is not None:
                local_ts = t.timestamp + timedelta(minutes=tz_offset)
                date_str = local_ts.strftime("%Y-%m-%d")
            else:
                date_str = t.timestamp.strftime("%Y-%m-%d")
        else:
            date_str = "Unknown"

        daily_data[date_str]["trace_count"] += 1
        daily_data[date_str]["observation_count"] += t.observation_count
        daily_data[date_str]["total_tokens"] += t.total_tokens
        daily_data[date_str]["total_cost"] += t.total_cost

        trace_name = t.name or "Unknown"
        agent_data[trace_name]["count"] += 1
        agent_data[trace_name]["tokens"] += t.total_tokens
        agent_data[trace_name]["cost"] += t.total_cost

        for model_name in t.models:
            model_data[model_name]["call_count"] += 1
            model_data[model_name]["total_tokens"] += t.total_tokens
            model_data[model_name]["input_tokens"] += t.input_tokens
            model_data[model_name]["output_tokens"] += t.output_tokens
            model_data[model_name]["total_cost"] += t.total_cost
            if t.latency_ms is not None:
                model_data[model_name]["latencies"].append(t.latency_ms)

    avg_latency = sum(latencies) / len(latencies) if latencies else None
    p95_latency = None
    if latencies:
        sorted_lats = sorted(latencies)
        p95_idx = int(len(sorted_lats) * 0.95)
        p95_latency = sorted_lats[min(p95_idx, len(sorted_lats) - 1)]

    by_model = sorted(
        [
            ModelUsageItem(
                model=model,
                call_count=data["call_count"],
                total_tokens=data["total_tokens"],
                input_tokens=data["input_tokens"],
                output_tokens=data["output_tokens"],
                total_cost=data["total_cost"],
                avg_latency_ms=sum(data["latencies"]) / len(data["latencies"]) if data["latencies"] else None,
            )
            for model, data in model_data.items()
        ],
        key=lambda m: m.total_tokens,
        reverse=True,
    )

    by_date = [
        DailyUsageItem(
            date=date,
            trace_count=data["trace_count"],
            observation_count=data["observation_count"],
            total_tokens=data["total_tokens"],
            total_cost=data["total_cost"],
        )
        for date, data in sorted(daily_data.items())
        if date != "Unknown"
    ][-30:]

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


# ---------------------------------------------------------------------------
# Sessions aggregation
# ---------------------------------------------------------------------------

def aggregate_sessions(
    traces: list[EnrichedTrace],
    search: str | None = None,
) -> list[SessionListItem]:
    """Aggregate traces into session list items."""
    sessions_data: dict[str, dict] = {}

    for t in traces:
        if not t.session_id:
            continue
        if t.session_id not in sessions_data:
            sessions_data[t.session_id] = {
                "trace_count": 0,
                "total_tokens": 0,
                "total_cost": 0.0,
                "timestamps": [],
                "models": set(),
                "latencies": [],
                "error_count": 0,
            }
        sd = sessions_data[t.session_id]
        sd["trace_count"] += 1
        sd["total_tokens"] += t.total_tokens
        sd["total_cost"] += t.total_cost
        sd["models"].update(t.models)
        sd["error_count"] += t.error_count
        if t.latency_ms is not None:
            sd["latencies"].append(t.latency_ms)
        if t.timestamp:
            sd["timestamps"].append(t.timestamp)

    sessions: list[SessionListItem] = []
    for sid, data in sessions_data.items():
        ts = data["timestamps"]
        lats = data["latencies"]
        err = int(data["error_count"])
        sessions.append(SessionListItem(
            session_id=sid,
            trace_count=data["trace_count"],
            total_tokens=data["total_tokens"],
            total_cost=data["total_cost"],
            avg_latency_ms=sum(lats) / len(lats) if lats else None,
            first_trace_at=min(ts) if ts else None,
            last_trace_at=max(ts) if ts else None,
            models_used=list(data["models"]),
            error_count=err,
            has_errors=err > 0,
        ))

    if search:
        search_lower = search.lower()
        sessions = [s for s in sessions if search_lower in s.session_id.lower()]

    sessions.sort(key=lambda s: s.last_trace_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return sessions


# ---------------------------------------------------------------------------
# Agents aggregation
# ---------------------------------------------------------------------------

def aggregate_agents(
    traces: list[EnrichedTrace],
    agents_by_id: dict[str, Agent],
    agents_by_name: dict[str, Agent],
    agent_to_folder: dict[str, tuple[str | None, str | None]],
) -> list[AgentListItem]:
    """Two-pass aggregation: session mapping then full token aggregation."""

    # Pass 1: identify which sessions belong to which agent
    session_to_agent: dict[str, tuple[str, str]] = {}
    for t in traces:
        agent_id, agent_name = match_trace_to_agent(t, agents_by_id, agents_by_name)
        if agent_id and t.session_id:
            session_to_agent[t.session_id] = (agent_id, agent_name)

    # Pass 2: aggregate all traces
    agents_data: dict[str, dict] = {}
    processed: set[str] = set()

    for t in traces:
        if t.id in processed:
            continue
        processed.add(t.id)

        agent_id = agent_name = None
        matched_id, matched_name = match_trace_to_agent(t, agents_by_id, agents_by_name)
        is_agent_trace = bool(matched_id)
        if matched_id:
            agent_id, agent_name = matched_id, matched_name
        elif t.session_id and t.session_id in session_to_agent:
            agent_id, agent_name = session_to_agent[t.session_id]
        else:
            continue

        if agent_id not in agents_data:
            agents_data[agent_id] = {
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

        ad = agents_data[agent_id]
        if is_agent_trace:
            ad["trace_count"] += 1
        ad["total_tokens"] += t.total_tokens
        ad["total_cost"] += t.total_cost
        ad["models"].update(t.models)
        ad["error_count"] += t.error_count
        if t.latency_ms is not None:
            ad["latencies"].append(t.latency_ms)
        if t.session_id:
            ad["sessions"].add(t.session_id)
        if t.timestamp:
            ad["timestamps"].append(t.timestamp)

    agents: list[AgentListItem] = []
    for fid, data in agents_data.items():
        ts = data["timestamps"]
        lats = data["latencies"]
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
            avg_latency_ms=sum(lats) / len(lats) if lats else None,
            models_used=list(data["models"]),
            last_activity=max(ts) if ts else None,
            error_count=data["error_count"],
        ))

    agents.sort(key=lambda a: a.last_activity or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return agents


# ---------------------------------------------------------------------------
# Projects aggregation
# ---------------------------------------------------------------------------

def aggregate_projects(
    traces: list[EnrichedTrace],
    agents_by_id: dict[str, Agent],
    agents_by_name: dict[str, Agent],
    agent_to_folder: dict[str, str],
    folders_by_id: dict[str, Folder],
) -> list[ProjectListItem]:
    """Two-pass aggregation: discover project sessions, then aggregate tokens."""

    # Pass 1: discover project sessions
    session_to_project: dict[str, str] = {}
    projects_data: dict[str, dict] = {}

    for t in traces:
        matched_fid, _ = match_trace_to_agent(t, agents_by_id, agents_by_name)
        if not matched_fid:
            continue
        folder_id = agent_to_folder.get(matched_fid)
        if not folder_id:
            continue
        if t.session_id:
            session_to_project[t.session_id] = folder_id
        if folder_id not in projects_data:
            folder = folders_by_id.get(folder_id)
            projects_data[folder_id] = {
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

    # Pass 2: aggregate tokens from all traces belonging to project sessions
    processed: set[str] = set()
    for t in traces:
        if t.id in processed:
            continue
        processed.add(t.id)
        folder_id = session_to_project.get(t.session_id) if t.session_id else None
        if not folder_id:
            continue
        projects_data[folder_id]["total_tokens"] += t.total_tokens
        projects_data[folder_id]["total_cost"] += t.total_cost
        if t.session_id:
            projects_data[folder_id]["sessions"].add(t.session_id)
        if t.timestamp:
            projects_data[folder_id]["timestamps"].append(t.timestamp)

    projects: list[ProjectListItem] = []
    for pid, data in projects_data.items():
        ts = data["timestamps"]
        projects.append(ProjectListItem(
            project_id=pid,
            project_name=data["project_name"],
            agent_count=len(data["agents"]),
            trace_count=data["trace_count"],
            session_count=len(data["sessions"]),
            total_tokens=data["total_tokens"],
            total_cost=data["total_cost"],
            last_activity=max(ts) if ts else None,
        ))

    projects.sort(key=lambda p: p.last_activity or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return projects


# ---------------------------------------------------------------------------
# Trace list items (for traces endpoint)
# ---------------------------------------------------------------------------

def traces_to_list_items(traces: list[EnrichedTrace]) -> list[TraceListItem]:
    """Convert enriched traces to TraceListItem list (sorted by timestamp desc)."""
    items = [
        TraceListItem(
            id=t.id,
            name=t.name,
            session_id=t.session_id,
            timestamp=t.timestamp,
            total_tokens=t.total_tokens,
            total_cost=t.total_cost,
            latency_ms=t.latency_ms,
            models_used=t.models,
            observation_count=t.observation_count,
            level=t.level,
        )
        for t in traces
    ]
    items.sort(key=lambda t: t.timestamp or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items
