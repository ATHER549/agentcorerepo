
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from agentcore.events.event_manager import EventManager
    from agentcore.graph_langgraph.executor import LangGraphExecutor


async def stream_langgraph_events(
    executor: LangGraphExecutor,
    inputs: dict[str, Any] | None = None,
    files: list[str] | None = None,
    user_id: str | None = None,
    event_manager: EventManager | None = None,
    fallback_to_env_vars: bool = False,
    stop_component_id: str | None = None,
    start_component_id: str | None = None,
):
    """Stream events from LangGraph execution.
    
    This function adapts LangGraph's streaming to AgentCore's event format.
    
    Args:
        executor: The LangGraph executor
        inputs: Input data
        files: File paths
        user_id: User ID
        event_manager: Event manager for emitting events
        fallback_to_env_vars: Fallback flag
        stop_component_id: Stop component ID
        start_component_id: Start component ID
        
    Yields:
        Event dictionaries in AgentCore format
    """
    logger.info("Starting event streaming from LangGraph execution")
    
    try:
        async for state_update in executor.stream_execute(
            inputs=inputs,
            files=files,
            user_id=user_id,
            event_manager=event_manager,
            fallback_to_env_vars=fallback_to_env_vars,
            stop_component_id=stop_component_id,
            start_component_id=start_component_id,
        ):
            # Extract events from state update
            if isinstance(state_update, dict) and "events" in state_update:
                events = state_update["events"]
                
                # Emit each event
                for event in events:
                    if not event:
                        continue
                    
                    # Convert to AgentCore event format
                    agentcore_event = _convert_to_agentcore_event(event, state_update)
                    
                    # Emit via event manager if available
                    if event_manager:
                        await _emit_event(event_manager, agentcore_event)
                    
                    # Yield the event
                    yield agentcore_event
    
    except Exception as e:
        logger.exception(f"Error during event streaming: {e}")
        
        # Emit error event
        error_event = {
            "type": "error",
            "error": str(e),
            "timestamp": None,
        }
        
        if event_manager:
            await event_manager.on_error(error=str(e))
        
        yield error_event
        raise


def _convert_to_agentcore_event(event: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Convert LangGraph event to AgentCore format.
    
    Args:
        event: Event from LangGraph state
        state: Full state update
        
    Returns:
        Event in AgentCore format
    """
    vertex_id = event.get("vertex_id", "")
    status = event.get("status", "success")
    
    # Base event structure
    agentcore_event = {
        "type": "vertex_build",
        "vertex_id": vertex_id,
        "status": status,
        "timestamp": event.get("timestamp"),
    }
    
    # Add display name if available
    if "display_name" in event:
        agentcore_event["display_name"] = event["display_name"]
    
    # Add result data if success
    if status == "success" and "result" in event:
        agentcore_event["result"] = event["result"]
        agentcore_event["elapsed_time"] = event.get("elapsed_time", 0)
    
    # Add error if failed
    if status == "error" and "error" in event:
        agentcore_event["error"] = event["error"]
    
    # Add metadata
    if "current_vertex" in state:
        agentcore_event["current_vertex"] = state["current_vertex"]
    
    if "completed_vertices" in state:
        agentcore_event["completed_vertices"] = state["completed_vertices"]
    
    return agentcore_event


async def _emit_event(event_manager: EventManager, event: dict[str, Any]) -> None:
    """Emit event via event manager.
    
    Args:
        event_manager: The event manager
        event: The event to emit
    """
    try:
        vertex_id = event.get("vertex_id", "")
        status = event.get("status", "")
        
        if status == "success":
            # Emit vertex built event
            await event_manager.on_vertex_built(
                vertex_id=vertex_id,
                result=event.get("result"),
            )
        elif status == "error":
            # Emit error event
            await event_manager.on_error(
                error=event.get("error", "Unknown error"),
            )
    
    except Exception as e:
        logger.warning(f"Failed to emit event via event manager: {e}")


def format_event_as_ndjson(event: dict[str, Any]) -> str:
    """Format event as NDJSON (newline-delimited JSON).
    
    Args:
        event: The event dictionary
        
    Returns:
        JSON string
    """
    try:
        return json.dumps(event, default=str)
    except Exception as e:
        logger.error(f"Failed to serialize event: {e}")
        return json.dumps({"type": "error", "error": "Failed to serialize event"})
