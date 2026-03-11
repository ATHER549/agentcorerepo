"""Self-contained business metrics registry for AgentCore.

Drop-in file: all 11 metric instruments + helper functions.
Call ``init_instruments(meter)`` once (from otel_metrics.py) to create
every instrument.  All ``record_*`` helpers are no-op safe — they silently
skip if the instrument has not been initialised (metrics disabled).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ── Instrument references (populated by init_instruments) ──────────────

_agent_runs_counter = None
_agent_run_duration = None
_component_builds_counter = None
_component_build_duration = None
_llm_calls_counter = None
_llm_tokens_counter = None
_llm_call_duration = None
_errors_counter = None
_active_sessions = None
_login_attempts_counter = None
_api_errors_counter = None


def init_instruments(meter) -> None:
    """Create all 11 business-level metric instruments on *meter*.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _agent_runs_counter, _agent_run_duration, _component_builds_counter, \
        _component_build_duration, _llm_calls_counter, _llm_tokens_counter, \
        _llm_call_duration, _errors_counter, _active_sessions, \
        _login_attempts_counter, _api_errors_counter

    if _agent_runs_counter is not None:
        return  # already initialised

    _agent_runs_counter = meter.create_counter(
        name="agentcore_agent_runs_total",
        unit="1",
        description="Total agent executions",
    )
    _agent_run_duration = meter.create_histogram(
        name="agentcore_agent_run_duration_ms",
        unit="ms",
        description="Agent run latency in milliseconds",
    )
    _component_builds_counter = meter.create_counter(
        name="agentcore_component_builds_total",
        unit="1",
        description="Total component builds",
    )
    _component_build_duration = meter.create_histogram(
        name="agentcore_component_build_duration_ms",
        unit="ms",
        description="Component build time in milliseconds",
    )
    _llm_calls_counter = meter.create_counter(
        name="agentcore_llm_calls_total",
        unit="1",
        description="Total LLM API calls",
    )
    _llm_tokens_counter = meter.create_counter(
        name="agentcore_llm_tokens_total",
        unit="1",
        description="Total LLM tokens (input + output)",
    )
    _llm_call_duration = meter.create_histogram(
        name="agentcore_llm_call_duration_ms",
        unit="ms",
        description="LLM call latency in milliseconds",
    )
    _errors_counter = meter.create_counter(
        name="agentcore_errors_total",
        unit="1",
        description="Application errors by type and component",
    )
    _active_sessions = meter.create_up_down_counter(
        name="agentcore_active_sessions",
        unit="1",
        description="Currently active chat sessions",
    )
    _login_attempts_counter = meter.create_counter(
        name="agentcore_login_attempts_total",
        unit="1",
        description="Authentication attempts",
    )
    _api_errors_counter = meter.create_counter(
        name="agentcore_api_errors_total",
        unit="1",
        description="HTTP 4xx/5xx errors by status code and route",
    )


# ── Helper functions (no-op safe) ─────────────────────────────────────


def record_agent_run(agent_name: str, status: str, duration_ms: float) -> None:
    """Record an agent run (success or error) with its duration."""
    try:
        if _agent_runs_counter is not None:
            labels = {"agent_name": agent_name, "status": status}
            _agent_runs_counter.add(1, labels)
        if _agent_run_duration is not None:
            _agent_run_duration.record(duration_ms, {"agent_name": agent_name, "status": status})
    except Exception:
        pass


def record_component_build(component_type: str, status: str, duration_ms: float) -> None:
    """Record a component build with its duration."""
    try:
        if _component_builds_counter is not None:
            labels = {"component_type": component_type, "status": status}
            _component_builds_counter.add(1, labels)
        if _component_build_duration is not None:
            _component_build_duration.record(duration_ms, {"component_type": component_type, "status": status})
    except Exception:
        pass


def record_llm_call(
    model_name: str,
    provider: str,
    duration_ms: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Record an LLM API call with token counts and latency."""
    try:
        if _llm_calls_counter is not None:
            _llm_calls_counter.add(1, {"model_name": model_name, "provider": provider})
        if _llm_call_duration is not None:
            _llm_call_duration.record(duration_ms, {"model_name": model_name, "provider": provider})
        if _llm_tokens_counter is not None:
            if input_tokens > 0:
                _llm_tokens_counter.add(input_tokens, {"model_name": model_name, "direction": "input"})
            if output_tokens > 0:
                _llm_tokens_counter.add(output_tokens, {"model_name": model_name, "direction": "output"})
    except Exception:
        pass


def record_error(error_type: str, component: str) -> None:
    """Record an application error."""
    try:
        if _errors_counter is not None:
            _errors_counter.add(1, {"error_type": error_type, "component": component})
    except Exception:
        pass


def adjust_active_sessions(delta: int) -> None:
    """Adjust the active sessions gauge (+1 or -1)."""
    try:
        if _active_sessions is not None:
            _active_sessions.add(delta)
    except Exception:
        pass


def record_login_attempt(status: str) -> None:
    """Record a login attempt (success or failure)."""
    try:
        if _login_attempts_counter is not None:
            _login_attempts_counter.add(1, {"status": status})
    except Exception:
        pass


def record_api_error(status_code: str, route: str) -> None:
    """Record an HTTP 4xx/5xx error."""
    try:
        if _api_errors_counter is not None:
            _api_errors_counter.add(1, {"status_code": status_code, "route": route})
    except Exception:
        pass
