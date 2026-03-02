
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

from loguru import logger

from agentcore.graph_langgraph.state import AgentCoreState
from agentcore.graph_langgraph.logging import log_vertex_build

if TYPE_CHECKING:
    from agentcore.graph_langgraph.vertex_wrapper import LangGraphVertex


def create_node_function(vertex: LangGraphVertex):
    """Convert an AgentCore Vertex to a LangGraph node function.
    
    Args:
        vertex: The Vertex object to convert to a node function
        
    Returns:
        An async function that can be used as a LangGraph node
    """
    
    async def node_function(state: AgentCoreState) -> AgentCoreState:
        """Execute this vertex and update state."""
        logger.debug(f"Executing node for vertex: {vertex.id} ({vertex.display_name})")
        
        start_time = time.time()
        agent_id = state.get("agent_id")
        skip_dev = getattr(getattr(vertex, 'graph', None), 'skip_dev_logging', False)

        try:
            # 1. Resolve dependencies from state
            resolved_params = _resolve_vertex_dependencies(vertex, state)
            
            # 2. Update vertex params with resolved values
            if resolved_params:
                vertex.update_raw_params(resolved_params, overwrite=True)
            
            # 3. Build the vertex (this executes the component)
            await vertex.build(
                user_id=state.get("user_id"),
                inputs=state.get("input_data", {}),
                files=state.get("files"),
                event_manager=state.get("event_manager"),
                fallback_to_env_vars=state.get("fallback_to_env_vars", False),
            )
            
            # 4. Store results in state
            state["vertices_results"][vertex.id] = vertex.built_result
            state["artifacts"][vertex.id] = vertex.artifacts
            
            if vertex.outputs_logs:
                state["outputs_logs"][vertex.id] = vertex.outputs_logs
            
            # 5. Track completion
            state["current_vertex"] = vertex.id
            state["completed_vertices"].append(vertex.id)
            
            # 6. Add event for streaming
            elapsed_time = time.time() - start_time
            vertex_event = {
                "vertex_id": vertex.id,
                "display_name": vertex.display_name,
                "result": vertex.result,
                "timestamp": time.time(),
                "elapsed_time": elapsed_time,
                "status": "success",
            }
            state["events"].append(vertex_event)
            
            logger.debug(f"Vertex {vertex.id} completed in {elapsed_time:.2f}s")
            
            # 7. Log vertex build to database
            if agent_id and not skip_dev:
                try:
                    # Prepare data for logging
                    data_dict = {}
                    if vertex.built_result is not None:
                        data_dict = {"result": str(vertex.built_result)}
                    
                    await log_vertex_build(
                        agent_id=agent_id if isinstance(agent_id, UUID) else UUID(agent_id),
                        vertex_id=vertex.id,
                        valid=True,
                        params=vertex.raw_params,
                        data=data_dict,
                        artifacts=vertex.artifacts,
                    )
                except Exception as log_error:
                    logger.warning(f"Failed to log vertex build for {vertex.id}: {log_error}")
            
        except Exception as e:
            # Handle vertex build error
            logger.exception(f"Error building vertex {vertex.id}: {e}")
            
            elapsed_time = time.time() - start_time
            error_event = {
                "vertex_id": vertex.id,
                "display_name": vertex.display_name,
                "timestamp": time.time(),
                "elapsed_time": elapsed_time,
                "status": "error",
                "error": str(e),
            }
            state["events"].append(error_event)
            
            # Log failed vertex build to database
            if agent_id and not skip_dev:
                try:
                    await log_vertex_build(
                        agent_id=agent_id if isinstance(agent_id, UUID) else UUID(agent_id),
                        vertex_id=vertex.id,
                        valid=False,
                        params=vertex.raw_params,
                        data={"error": str(e)},
                        artifacts=None,
                    )
                except Exception as log_error:
                    logger.warning(f"Failed to log vertex build error for {vertex.id}: {log_error}")
            
            # Re-raise to stop execution
            raise
        
        return state
    
    # Set function name for debugging
    node_function.__name__ = f"node_{vertex.id}"
    
    return node_function


def _resolve_vertex_dependencies(vertex: LangGraphVertex, state: AgentCoreState) -> dict[str, Any]:
    """Resolve vertex parameter dependencies from state.
    
    Vertices can have parameters that reference other vertices by ID. This function
    resolves those references by looking up the results in the state.
    
    Args:
        vertex: The vertex whose dependencies to resolve
        state: The current execution state
        
    Returns:
        Dictionary of resolved parameters
    """
    resolved_params = {}
    
    for key, value in vertex.raw_params.items():
        # Case 1: Value is a vertex ID (string matching pattern)
        if isinstance(value, str) and value in state["vertices_results"]:
            resolved_params[key] = state["vertices_results"][value]
        
        # Case 2: Value is a list that might contain vertex IDs
        elif isinstance(value, list):
            resolved_list = []
            for item in value:
                if isinstance(item, str) and item in state["vertices_results"]:
                    resolved_list.append(state["vertices_results"][item])
                else:
                    resolved_list.append(item)
            if resolved_list != value:  # Only add if we resolved something
                resolved_params[key] = resolved_list
        
        # Case 3: Value is a dict with vertex ID values
        elif isinstance(value, dict):
            resolved_dict = {}
            has_vertices = False
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, str) and sub_value in state["vertices_results"]:
                    has_vertices = True
                    resolved_dict[sub_key] = state["vertices_results"][sub_value]
                else:
                    resolved_dict[sub_key] = sub_value
            
            if has_vertices:
                resolved_params[key] = resolved_dict
    
    return resolved_params
