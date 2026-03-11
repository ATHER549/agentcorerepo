
from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from loguru import logger

from agentcore.graph_langgraph.state import AgentCoreState

if TYPE_CHECKING:
    from agentcore.events.event_manager import EventManager
    from agentcore.graph_langgraph.adapter import LangGraphAdapter


class LangGraphExecutor:
    """Handles execution of LangGraph workflows.
    
    """
    
    def __init__(self, adapter: LangGraphAdapter) -> None:
        """Initialize the executor.
        
        Args:
            adapter: The LangGraphAdapter containing the compiled workflow
        """
        self.adapter = adapter
        
        if not adapter.compiled_app:
            msg = "LangGraph workflow not compiled. Call adapter._build_langgraph_workflow() first."
            raise ValueError(msg)
        
        self.compiled_app = adapter.compiled_app
    
    async def execute(
        self,
        inputs: dict[str, Any] | None = None,
        files: list[str] | None = None,
        user_id: str | None = None,
        event_manager: EventManager | None = None,
        fallback_to_env_vars: bool = False,
        stop_component_id: str | None = None,
        start_component_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute the LangGraph workflow.
        
        Args:
            inputs: Input data for the agent
            files: List of file paths
            user_id: User ID for execution
            event_manager: Event manager for streaming
            fallback_to_env_vars: Whether to use environment variables as fallback
            stop_component_id: ID of component to stop at
            start_component_id: ID of component to start from
            
        Returns:
            Final state after execution
        """
        logger.info(f"Starting LangGraph execution for agent {self.adapter.agent_id}")
        
        # Update input vertices with the input data (like ChatInput's input_value).
        # Only overwrite when the new input_value is non-empty so that
        # TextInput's configured value is preserved when the Playground
        # sends an empty chat message.
        if inputs:
            from agentcore.schema.schema import INPUT_FIELD_NAME

            for vertex_id in self.adapter._is_input_vertices:
                vertex = self.adapter.get_vertex(vertex_id)
                if vertex:
                    filtered = {
                        k: v for k, v in inputs.items()
                        if k != INPUT_FIELD_NAME or v
                    }
                    if filtered:
                        logger.debug(f"Updating vertex {vertex_id} with inputs: {filtered}")
                        vertex.update_raw_params(filtered, overwrite=True)

        # Prepare initial state
        initial_state = self._create_initial_state(
            inputs=inputs or {},
            files=files,
            user_id=user_id or self.adapter.user_id,
            event_manager=event_manager,
            fallback_to_env_vars=fallback_to_env_vars,
            stop_component_id=stop_component_id,
            start_component_id=start_component_id,
        )

        try:
            # Execute the workflow
            logger.debug("Invoking LangGraph workflow")
            _thread_id = (
                getattr(self.adapter, "_session_id", None)
                or getattr(self.adapter, "session_id", None)
                or str(uuid4())
            )
            _lg_config = {"configurable": {"thread_id": _thread_id}}
            final_state = await self.compiled_app.ainvoke(initial_state, config=_lg_config)
            
            logger.info(
                f"LangGraph execution completed. "
                f"Processed {len(final_state.get('completed_vertices', []))} vertices"
            )
            
            return final_state
            
        except Exception as e:
            logger.exception(f"Error during LangGraph execution: {e}")
            raise
    
    async def stream_execute(
        self,
        inputs: dict[str, Any] | None = None,
        files: list[str] | None = None,
        user_id: str | None = None,
        event_manager: EventManager | None = None,
        fallback_to_env_vars: bool = False,
        stop_component_id: str | None = None,
        start_component_id: str | None = None,
    ):
        """Execute with streaming (yields state updates).
        
        Args:
            inputs: Input data for the agent
            files: List of file paths
            user_id: User ID for execution
            event_manager: Event manager for streaming
            fallback_to_env_vars: Whether to use environment variables as fallback
            stop_component_id: ID of component to stop at
            start_component_id: ID of component to start from
            
        Yields:
            State updates as execution progresses
        """
        logger.info(f"Starting streaming LangGraph execution for agent {self.adapter.agent_id}")
        
        # Update input vertices with the input data (like ChatInput's input_value).
        # Only overwrite when the new input_value is non-empty so that
        # TextInput's configured value is preserved.
        if inputs:
            from agentcore.schema.schema import INPUT_FIELD_NAME

            logger.debug(f"Updating input vertices with data: {inputs}")
            for vertex_id in self.adapter._is_input_vertices:
                vertex = self.adapter.get_vertex(vertex_id)
                if vertex:
                    filtered = {
                        k: v for k, v in inputs.items()
                        if k != INPUT_FIELD_NAME or v
                    }
                    if filtered:
                        logger.debug(f"Updating vertex {vertex_id} with inputs: {filtered}")
                        vertex.update_raw_params(filtered, overwrite=True)
        
        # Prepare initial state
        initial_state = self._create_initial_state(
            inputs=inputs or {},
            files=files,
            user_id=user_id or self.adapter.user_id,
            event_manager=event_manager,
            fallback_to_env_vars=fallback_to_env_vars,
            stop_component_id=stop_component_id,
            start_component_id=start_component_id,
        )
        
        try:
            # Stream execution
            _thread_id = (
                getattr(self.adapter, "_session_id", None)
                or getattr(self.adapter, "session_id", None)
                or str(uuid4())
            )
            _lg_config = {"configurable": {"thread_id": _thread_id}}
            async for state_update in self.compiled_app.astream(initial_state, config=_lg_config):
                logger.debug(f"State update: {state_update.keys() if isinstance(state_update, dict) else type(state_update)}")
                yield state_update
                
        except Exception as e:
            logger.exception(f"Error during streaming execution: {e}")
            raise
    
    def _create_initial_state(
        self,
        inputs: dict[str, Any],
        files: list[str] | None,
        user_id: str | None,
        event_manager: EventManager | None,
        fallback_to_env_vars: bool,
        stop_component_id: str | None,
        start_component_id: str | None,
    ) -> AgentCoreState:
        """Create the initial state for execution.
        
        Args:
            inputs: Input data
            files: File paths
            user_id: User ID
            event_manager: Event manager
            fallback_to_env_vars: Fallback flag
            stop_component_id: Stop component ID
            start_component_id: Start component ID
            
        Returns:
            Initial AgentCoreState
        """
        # Store event_manager on adapter so node_function can access it
        # via vertex.graph._event_manager (must NOT be in state — not serializable)
        self.adapter._event_manager = event_manager

        return AgentCoreState(
            # Results storage
            vertices_results={},
            artifacts={},
            outputs_logs={},

            # Execution tracking
            current_vertex="",
            completed_vertices=[],
            events=[],

            # Agent metadata
            agent_id=self.adapter.agent_id or "",
            agent_name=self.adapter.agent_name,
            session_id=inputs.get("session_id") or self.adapter.session_id or self.adapter.agent_id or "",
            user_id=user_id,

            # Context
            input_data=inputs,
            files=files,

            # Configuration
            fallback_to_env_vars=fallback_to_env_vars,
            stop_component_id=stop_component_id,
            start_component_id=start_component_id,

            # Maps
            predecessor_map=self.adapter.predecessor_map,
            successor_map=self.adapter.successor_map,
            in_degree_map=self.adapter.in_degree_map,

            # Cycles
            cycle_vertices=list(self.adapter.cycle_vertices),
            is_cyclic=self.adapter.is_cyclic,

            # Layers
            current_layer=0,
            vertices_layers=self.adapter.vertices_layers,

            # Input vertex tracking
            input_vertex_ids=list(self.adapter._is_input_vertices),
        )
    
    def get_results(self, state: dict[str, Any]) -> list[Any]:
        """Extract results from final state.
        
        Args:
            state: Final execution state
            
        Returns:
            List of vertex results
        """
        results = []
        
        for vertex in self.adapter.vertices:
            if vertex.is_output and vertex.id in state.get("vertices_results", {}):
                results.append({
                    "vertex_id": vertex.id,
                    "result": state["vertices_results"][vertex.id],
                    "artifacts": state.get("artifacts", {}).get(vertex.id),
                })
        
        return results
