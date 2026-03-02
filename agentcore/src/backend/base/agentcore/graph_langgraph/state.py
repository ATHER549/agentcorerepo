
from __future__ import annotations

from operator import add
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

# EventManager is optional and only used at runtime, use string annotation
class AgentCoreState(TypedDict):
    """State that agents through the LangGraph execution.
    
    This state is passed between nodes and maintains the execution context,
    results, and events for the entire agent.
    """
    
    # Core execution results
    vertices_results: dict[str, Any]  # Maps vertex_id to its built result
    artifacts: dict[str, Any]  # Maps vertex_id to its artifacts
    outputs_logs: dict[str, dict[str, Any]]  # Maps vertex_id to output logs
    
    # Current execution context
    current_vertex: str  # ID of currently executing vertex
    completed_vertices: Annotated[list[str], add]  # List of completed vertex IDs
    
    # Event streaming (accumulate events as list)
    events: Annotated[list[dict[str, Any]], add]
    
    # Agent metadata
    agent_id: str
    agent_name: str | None
    session_id: str
    user_id: str | None
    
    # Execution context (use Any to avoid import issues)
    event_manager: Any  # EventManager | None - using Any to avoid circular imports
    input_data: dict[str, Any]
    files: list[str] | None
    
    # Configuration
    fallback_to_env_vars: bool
    stop_component_id: str | None
    start_component_id: str | None
    
    # Vertex maps for traversal
    vertex_objects: dict[str, Any]  # Store actual vertex objects
    predecessor_map: dict[str, list[str]]
    successor_map: dict[str, list[str]]
    in_degree_map: dict[str, int]
    
    # Cycle handling
    cycle_vertices: set[str]
    is_cyclic: bool
    
    # Layer execution tracking
    current_layer: int
    vertices_layers: list[list[str]]
