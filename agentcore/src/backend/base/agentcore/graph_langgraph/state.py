
from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict


def _merge_dicts(left: dict, right: dict) -> dict:
    """Reducer that merges two dicts.

    Used for state channels that can be written by parallel nodes
    (e.g. ``vertices_results``, ``artifacts``, ``outputs_logs``).
    Without this, LangGraph raises ``InvalidUpdateError`` when two
    nodes in the same superstep both return state updates for the
    same dict key.
    """
    merged = left.copy()
    merged.update(right)
    return merged


def _last_value(left: str, right: str) -> str:
    """Reducer that simply takes the latest value (last writer wins)."""
    return right


class AgentCoreState(TypedDict):
    """State that flows through the LangGraph execution.

    This state is passed between nodes and maintains the execution context,
    results, and events for the entire agent.

    IMPORTANT — serialization constraint:
        The MemorySaver checkpointer (required for HITL interrupt/resume)
        serializes this entire dict using msgpack.  Only JSON-compatible
        Python types may appear here.  Non-serializable runtime objects
        (EventManager, LangGraphVertex, etc.) MUST NOT be placed in this
        state.  Access them via the LangGraphAdapter closure instead:
            event_manager  → vertex.graph._event_manager
            vertex objects → vertex.graph.vertex_map
    """

    # Core execution results — _merge_dicts reducer lets parallel nodes
    # each contribute their vertex's results without conflicting.
    vertices_results: Annotated[dict[str, Any], _merge_dicts]
    artifacts: Annotated[dict[str, Any], _merge_dicts]
    outputs_logs: Annotated[dict[str, Any], _merge_dicts]

    # Current execution context — last writer wins for parallel nodes
    current_vertex: Annotated[str, _last_value]
    completed_vertices: Annotated[list[str], add]

    # Event streaming (accumulate events as list)
    events: Annotated[list[dict[str, Any]], add]

    # Agent metadata (plain scalars — safe to checkpoint)
    agent_id: str
    agent_name: str | None
    session_id: str
    user_id: str | None

    # Execution context (plain scalars / dicts only)
    input_data: dict[str, Any]
    files: list[str] | None

    # Configuration
    fallback_to_env_vars: bool
    stop_component_id: str | None
    start_component_id: str | None

    # Vertex maps for traversal (serializable scalars only — no Python objects)
    predecessor_map: dict[str, list[str]]
    successor_map: dict[str, list[str]]
    in_degree_map: dict[str, int]

    # Cycle handling
    cycle_vertices: list[str]   # list, not set — msgpack doesn't support sets
    is_cyclic: bool

    # Layer execution tracking
    current_layer: int
    vertices_layers: list[list[str]]

    # Input vertex tracking (for parameter filtering in node_function)
    input_vertex_ids: list[str]
