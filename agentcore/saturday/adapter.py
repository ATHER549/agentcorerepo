
from __future__ import annotations

import asyncio
import copy
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any, Iterable

import pandas as pd
from langgraph.graph import StateGraph
from loguru import logger

from agentcore.graph_langgraph.constants import Finish
from agentcore.graph_langgraph.nodes import create_node_function
from agentcore.graph_langgraph.state import AgentCoreState
from agentcore.graph_langgraph.utils import (
    build_adjacency_maps,
    build_in_degree_map,
    find_cycle_vertices,
    has_cycle,
    process_agent,
)
from agentcore.graph_langgraph.vertex_wrapper import LangGraphVertex

if TYPE_CHECKING:
    from uuid import UUID
    
    from agentcore.events.event_manager import EventManager
    from agentcore.schema.schema import InputValueRequest


class LangGraphAdapter:
    """Adapter to convert AgentCore Graph to LangGraph StateGraph.
    
    This class replaces the custom Graph implementation with LangGraph,
    while maintaining all the same functionality for drag-and-drop agents.
    """
    
    def __init__(
        self,
        agent_id: str | UUID | None = None,
        agent_name: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        project_name: str | None = None,
    ) -> None:
        """Initialize the LangGraph adapter.

        Args:
            agent_id: The ID of the agent
            agent_name: The name of the agent
            user_id: The user ID
            project_id: The project/folder ID for observability grouping
            project_name: The project/folder name for observability display
        """
        self.agent_id = str(agent_id) if agent_id else None
        self.agent_name = agent_name
        self.user_id = user_id
        self.project_id = project_id
        self.project_name = project_name
        
        # Storage
        self.vertices: list[LangGraphVertex] = []
        self.vertex_map: dict[str, LangGraphVertex] = {}
        self.edges: list[dict[str, Any]] = []  # Store edge data directly
        self.raw_graph_data: dict[str, Any] = {"nodes": [], "edges": []}
        
        # Adjacency maps (for compatibility and cycle detection)
        self.predecessor_map: dict[str, list[str]] = {}
        self.successor_map: dict[str, list[str]] = {}
        self.in_degree_map: dict[str, int] = {}
        self.parent_child_map: dict[str, list[str]] = {}  # Map parent to children for branch marking
        
        # Cycle handling
        self.cycle_vertices: set[str] = set()
        self.is_cyclic: bool = False
        
        # Session and execution
        self._session_id: str | None = None
        self.has_session_id_vertices: list[str] = []
        self._is_input_vertices: list[str] = []
        self._is_output_vertices: list[str] = []
        
        # Context for shared state (used by conditional router, loops, etc.)
        self.context: dict[str, Any] = {}
        
        # When True, skip writing to dev tables (conversation, transaction,
        # vertex_build).  Set by the orchestration chat so that only the
        # orch-specific tables receive data.
        self.skip_dev_logging: bool = False

        # Orchestrator context — when set, transactions are logged to the
        # orch_transaction table instead of the dev transaction table.
        self.orch_session_id: str | None = None
        self.orch_deployment_id: str | None = None
        self.orch_org_id: str | None = None
        self.orch_dept_id: str | None = None

        # PROD deployment context — when set, transactions are also logged
        # to the transaction_prod table (for control-panel metrics).
        # Set by orch chat AND /api/run?env=prod.
        self.prod_deployment_id: str | None = None
        self.prod_org_id: str | None = None
        self.prod_dept_id: str | None = None

        # UAT deployment context — when set, transactions are also logged
        # to the transaction_uat table (for control-panel metrics).
        # Set by /api/run?env=uat.
        self.uat_deployment_id: str | None = None
        self.uat_org_id: str | None = None
        self.uat_dept_id: str | None = None

        # LangGraph components
        self.workflow: StateGraph | None = None
        self.compiled_app: Any = None
        
        # Layer execution
        self.vertices_layers: list[list[str]] = []
        self._sorted_vertices_layers: list[list[str]] = []
        self._first_layer: list[str] = []
        
        # Compatibility properties for existing code
        from agentcore.graph_langgraph.runnable_vertices_manager import RunnableVerticesManager
        self.run_manager = RunnableVerticesManager()
        self.vertices_to_run: set[str] = set()
        self.inactivated_vertices: set[str] = set()
        self.stop_vertex: str | None = None
        
        # Tracing support
        self._run_id: str | None = None
        self.tracing_service = None
        
        # Snapshot and step execution support
        self._snapshots: list[dict[str, Any]] = []
        self._call_order: list[str] = []
        self._run_queue: deque[str] = deque()
        self._prepared: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()
        self.activated_vertices: list[str] = []
        self._is_state_vertices: list[str] | None = None
    
 # ── Redis serialization support ──────────────────────────────────────
    def __getstate__(self) -> dict:
        """Return serializable state for Redis/dill/pickle.
        Non-serializable objects (asyncio.Lock, compiled LangGraph app,
        StateGraph, tracing service) are excluded and re-created on load
        via ``__setstate__``.
        """
        state = self.__dict__.copy()
        # Remove non-serializable attributes
        state.pop("_lock", None)
        state.pop("workflow", None)
        state.pop("compiled_app", None)
        state.pop("tracing_service", None)
        # Convert deque to list for clean serialization
        if "_run_queue" in state and isinstance(state["_run_queue"], deque):
            state["_run_queue"] = list(state["_run_queue"])
        return state

    def __setstate__(self, state: dict) -> None:
        """Restore state after deserialization from Redis.
        Re-creates non-serializable objects that were stripped in
        ``__getstate__``.
        """
        self.__dict__.update(state)
        # Restore non-serializable attributes
        self._lock = asyncio.Lock()
        self.workflow = None
        self.compiled_app = None
        self.tracing_service = None
        # Restore deque if it was converted to list
        if isinstance(self._run_queue, list):
            self._run_queue = deque(self._run_queue)
        # Rebuild LangGraph workflow from stored raw data if available
        if self.raw_graph_data and self.vertices:
            try:
                self._build_langgraph_workflow()
            except Exception:
                logger.warning("Could not rebuild LangGraph workflow after deserialization")


    @classmethod
    def from_payload(
        cls,
        payload: dict,
        agent_id: str | None = None,
        agent_name: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        project_name: str | None = None,
    ) -> LangGraphAdapter:
        """Create adapter from JSON payload.

        Args:
            payload: The JSON payload with nodes and edges
            agent_id: The agent ID
            agent_name: The agent name
            user_id: The user ID
            project_id: The project/folder ID for observability grouping
            project_name: The project/folder name for observability display

        Returns:
            LangGraphAdapter instance
        """
        if "data" in payload:
            payload = payload["data"]

        try:
            vertices_data = payload["nodes"]
            edges_data = payload["edges"]

            adapter = cls(
                agent_id=agent_id,
                agent_name=agent_name,
                user_id=user_id,
                project_id=project_id,
                project_name=project_name,
            )
            adapter.add_nodes_and_edges(vertices_data, edges_data)
            
        except KeyError as exc:
            logger.exception(exc)
            if "nodes" not in payload and "edges" not in payload:
                msg = f"Invalid payload. Expected keys 'nodes' and 'edges'. Found {list(payload.keys())}"
                raise ValueError(msg) from exc
            
            msg = f"Error while creating adapter from payload: {exc}"
            raise ValueError(msg) from exc
        
        return adapter
    
    def add_nodes_and_edges(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        """Add nodes and edges to the adapter.
        
        Args:
            nodes: List of node data
            edges: List of edge data
        """
        self.raw_graph_data = {"nodes": nodes, "edges": edges}
        
        # Process agent (handles group nodes, etc.)
        processed_data = process_agent(self.raw_graph_data)
        
        vertices_data = processed_data["nodes"]
        edges_data = processed_data["edges"]
        
        # Detect cycles
        vertex_ids = [node["id"] for node in vertices_data]
        edge_tuples = [(edge["source"], edge["target"]) for edge in edges_data]
        self.is_cyclic = has_cycle(vertex_ids, edge_tuples)
        
        if self.is_cyclic:
            self.cycle_vertices = set(find_cycle_vertices(edge_tuples))
            logger.info(f"Detected cycles in graph. Cycle vertices: {self.cycle_vertices}")
        
        # Build vertices
        self._build_vertices(vertices_data)
        
        # Build edges
        self._build_edges(edges_data)
        
        # Build maps
        self.predecessor_map, self.successor_map = build_adjacency_maps(edges_data)
        self.in_degree_map = build_in_degree_map(edges_data, set(self.vertex_map.keys()))
        
        # Build parent-child map for branch marking (used by conditional router)
        self._build_parent_child_map()
        
        # Set first layer (vertices with no predecessors)
        self._first_layer = [vid for vid, in_degree in self.in_degree_map.items() if in_degree == 0]
        
        # Parameters already built in _build_vertices and _build_edges
        
        # Set parent_is_top_level flags
        self._set_parent_top_level()
        
        # Categorize vertices
        self._define_vertices_lists()
        
        # Build LangGraph workflow
        self._build_langgraph_workflow()
    
    def _build_vertices(self, vertices_data: list[dict[str, Any]]) -> None:
        """Create Vertex objects from node data.
        
        Args:
            vertices_data: List of node data
        """
        for node_data in vertices_data:
            vertex = LangGraphVertex(node_data, graph_adapter=self)
            vertex.build_params_from_template()
            self.vertices.append(vertex)
            self.vertex_map[vertex.id] = vertex
    
    def _build_edges(self, edges_data: list[dict[str, Any]]) -> None:
        """Store edge data and resolve parameter dependencies.
        
        Args:
            edges_data: List of edge data
        """
        for edge_data in edges_data:
            source_id = edge_data.get("source")
            target_id = edge_data.get("target")
            
            if not source_id or not target_id:
                continue
            
            # Store edge
            self.edges.append(edge_data)
            
            # Resolve parameter dependency
            target_vertex = self.vertex_map.get(target_id)
            source_vertex = self.vertex_map.get(source_id)
            
            if target_vertex and source_vertex:
                # Get target parameter name from edge data
                target_handle = edge_data.get("data", {}).get("targetHandle", {})
                param_name = target_handle.get("fieldName") if isinstance(target_handle, dict) else None
                
                if param_name:
                    # Store source vertex ID as dependency
                    target_vertex.update_param(param_name, source_id)
    
    def _set_parent_top_level(self) -> None:
        """Set parent_is_top_level flag for vertices with parents."""
        # Get top level vertices (those with no parents)
        top_level_vertices = [v.id for v in self.vertices if not v.parent_node_id]
        
        # Set flag for vertices that have parents
        for vertex in self.vertices:
            if vertex.parent_node_id:
                vertex.parent_is_top_level = vertex.parent_node_id in top_level_vertices
    
    def _define_vertices_lists(self) -> None:
        """Categorize vertices by type."""
        for vertex in self.vertices:
            if vertex.is_input:
                self._is_input_vertices.append(vertex.id)
            if vertex.is_output:
                self._is_output_vertices.append(vertex.id)
            if vertex.has_session_id:
                self.has_session_id_vertices.append(vertex.id)
    
    def _build_langgraph_workflow(self) -> None:
        """Build the LangGraph StateGraph from vertices and edges."""
        logger.info("Building LangGraph workflow")
        
        # Create StateGraph
        self.workflow = StateGraph(AgentCoreState)
        
        # Add nodes to workflow
        for vertex in self.vertices:
            node_func = create_node_function(vertex)
            self.workflow.add_node(vertex.id, node_func)
        
        # Add edges to workflow
        for edge_data in self.edges:
            source_id = edge_data.get("source")
            target_id = edge_data.get("target")
            
            if source_id and target_id and source_id in self.vertex_map and target_id in self.vertex_map:
                try:
                    self.workflow.add_edge(source_id, target_id)
                except Exception as e:
                    logger.warning(f"Failed to add edge {source_id} -> {target_id}: {e}")
        
        # Set entry point (first layer of vertices)
        if self._is_input_vertices:
            # Use input vertices as entry points
            entry_point = self._is_input_vertices[0]
        elif self.vertices:
            # Use first vertex with no predecessors
            for vertex_id, in_degree in self.in_degree_map.items():
                if in_degree == 0:
                    entry_point = vertex_id
                    break
            else:
                entry_point = self.vertices[0].id
        else:
            logger.warning("No vertices found for entry point")
            return
        
        self.workflow.set_entry_point(entry_point)
        logger.info(f"Set entry point: {entry_point}")
        
        # Compile the workflow
        try:
            logger.info("Compiling LangGraph workflow...")
            self.compiled_app = self.workflow.compile()
            logger.info("LangGraph workflow compiled successfully")
        except Exception as e:
            logger.error(f"Failed to compile LangGraph workflow: {e}")
            raise
    
    def get_vertex(self, vertex_id: str) -> LangGraphVertex | None:
        """Get a vertex by ID.
        
        Args:
            vertex_id: The vertex ID
            
        Returns:
            Vertex object or None
        """
        return self.vertex_map.get(vertex_id)
    
    def sort_vertices(
        self,
        stop_component_id: str | None = None,
        start_component_id: str | None = None,
    ) -> list[str]:
       
        from agentcore.graph_langgraph.utils import get_sorted_vertices_for_langgraph
        
        # Get all vertex IDs
        all_vertex_ids = list(self.vertex_map.keys())
        
        # Handle the case where stop_component_id is in a cycle
        # In cycles, we convert stop to start to avoid infinite loops
        if stop_component_id and stop_component_id in self.cycle_vertices:
            start_component_id = stop_component_id
            stop_component_id = None
        
        # Store the stop vertex for later use (to limit next_runnable_vertices)
        self.stop_vertex = stop_component_id
        
        # Use the utility function to get sorted vertices
        first_layer, vertices_to_run_list, filtered_vertices = get_sorted_vertices_for_langgraph(
            vertices_ids=all_vertex_ids,
            in_degree_map=self.in_degree_map,
            predecessor_map=self.predecessor_map,
            successor_map=self.successor_map,
            cycle_vertices=self.cycle_vertices,
            stop_component_id=stop_component_id,
            start_component_id=start_component_id,
            is_cyclic=self.is_cyclic,
        )
        
        # Update vertices_to_run with the filtered set
        self.vertices_to_run = filtered_vertices
        
        # Update the first layer
        self._first_layer = first_layer
        
        # Update run manager with filtered vertices
        self.run_manager.build_run_map(
            predecessor_map={k: v for k, v in self.predecessor_map.items() if k in filtered_vertices},
            vertices_to_run=self.vertices_to_run,
        )
        
        return first_layer if first_layer else list(self.vertex_map.keys())[:1]
    
    def get_vertex_ids(self) -> list[str]:
        """Get all vertex IDs.
        
        Returns:
            List of all vertex IDs
        """
        return list(self.vertex_map.keys())
    
    @property
    def session_id(self) -> str | None:
        """Get the session ID."""
        return self._session_id
    
    @session_id.setter
    def session_id(self, value: str) -> None:
        """Set the session ID."""
        self._session_id = value
    
    @property
    def is_state_vertices(self) -> list[str]:
        """Returns a cached list of vertex IDs for vertices marked as state vertices.

        The list is computed on first access by filtering vertices with `is_state` set to True and is
        cached for future calls.
        """
        if self._is_state_vertices is None:
            self._is_state_vertices = [vertex.id for vertex in self.vertices if vertex.is_state]
        return self._is_state_vertices
    
    async def initialize_run(self) -> None:
        """Initialize run with tracing support.
        
        This method resets all state from previous runs to ensure a fresh execution.
        """
        from uuid import uuid4
        from collections import deque
        from agentcore.services.deps import get_tracing_service
        
        # IMPORTANT: Reset all state from previous runs
        # This is critical when the graph is cached and reused
        
        # 1. Reset all vertex states to ACTIVE
        self.mark_all_vertices("ACTIVE")
        
        # 2. Reset tracking sets
        self.reset_inactivated_vertices()  # Clear inactivated_vertices set
        self.reset_activated_vertices()     # Clear activated_vertices list
        
        # 3. Reset run manager state
        self.run_manager.ran_at_least_once = set()
        self.run_manager.vertices_being_run = set()
        
        # 4. Reset execution state
        self._prepared = False
        self._run_queue = deque()
        
        # 5. Set up run state with all vertices
        self.vertices_to_run = set(self.vertex_map.keys())
        
        # 6. Rebuild the run map for the run manager
        # This is critical for determining which vertices can run
        self.run_manager.build_run_map(
            predecessor_map=self.predecessor_map,
            vertices_to_run=self.vertices_to_run
        )
        
        # Always generate a new run ID for each run
        self.set_run_id()
        
        # Clean up any existing trace worker before re-initialization
        if self.tracing_service and not self.tracing_service.deactivated:
            try:
                await self.end_all_traces_in_context()
            except Exception:
                pass

        # Initialize tracing service - this creates the FLOW-LEVEL trace
        # Each vertex build will create child spans under this trace via trace_component()
        self.tracing_service = get_tracing_service()
        logger.info(f"TRACING INIT: service={self.tracing_service}, deactivated={self.tracing_service.deactivated if self.tracing_service else 'N/A'}")
        if self.tracing_service and not self.tracing_service.deactivated:
            try:
                from uuid import UUID
                run_name = f"{self.agent_name} - {self.agent_id}"
                # Use the run_id we just set (converted to UUID)
                run_id = UUID(self._run_id) if self._run_id else uuid4()
                logger.info(f" STARTING TRACERS: agent={self.agent_name}, user={self.user_id}, session={self._session_id}, run_id={run_id}")
                await self.tracing_service.start_tracers(
                    run_id=run_id,
                    run_name=run_name,
                    user_id=self.user_id,
                    session_id=self._session_id,
                    agent_id=self.agent_id,
                    agent_name=self.agent_name,
                    observability_project_id=self.project_id,
                    observability_project_name=self.project_name,
                )
                logger.info(f"TRACERS STARTED: agent={self.agent_name}")
            except Exception as e:
                logger.error(f"❌ Error initializing tracers for agent={self.agent_name}: {e}", exc_info=True)
                # Deactivate tracing so components don't try to use it and crash
                self.tracing_service.deactivated = True
        else:
            logger.warning(f"TRACING DISABLED: service_exists={self.tracing_service is not None}, deactivated={self.tracing_service.deactivated if self.tracing_service else 'N/A'}")
    
    def set_run_id(self, run_id: str | None = None) -> None:
        """Set the run ID for this graph execution.
        
        Args:
            run_id: Optional run ID to set. If None, generates a new UUID.
        """
        from uuid import uuid4
        if run_id is None:
            self._run_id = str(uuid4())
        else:
            self._run_id = str(run_id)
    
    def get_top_level_vertices(self, vertex_ids: Iterable[str]) -> list[str]:
        """Get top level vertices (compatibility method).
        
        Args:
            vertex_ids: List of vertex IDs
            
        Returns:
            List of top-level vertex IDs
        """
        # For LangGraph, return the same list (no hierarchy concept)
        return list(vertex_ids)
    
    async def end_all_traces(self, outputs: dict | None = None, error: Exception | None = None) -> None:
        """End all traces for this graph execution.
        
        This is the main method called by build.py to end tracing.
        
        Args:
            outputs: Optional output data to include in traces
            error: Optional error that occurred during execution
        """
        await self.end_all_traces_in_context(error=error)
    
    async def end_all_traces_in_context(self, error: Exception | None = None) -> None:
        """End all traces for this graph execution.
        
        Args:
            error: Optional error that occurred during execution
        """
        if self.tracing_service and not self.tracing_service.deactivated:
            try:
                from datetime import datetime, timezone
                outputs = {}
                if self.agent_id:
                    outputs["agent_id"] = self.agent_id
                if self.agent_name:
                    outputs["agent_name"] = self.agent_name
                outputs["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                await self.tracing_service.end_tracers(outputs=outputs, error=error)
            except Exception as e:
                logger.warning(f"Error ending traces for agent={self.agent_name}: {e}")
    
    async def arun(
        self,
        inputs: list[dict[str, str]],
        *,
        inputs_components: list[list[str]] | None = None,
        types: list[str | None] | None = None,
        outputs: list[str] | None = None,
        session_id: str | None = None,
        stream: bool = False,
        fallback_to_env_vars: bool = False,
        event_manager = None,
    ):
        """Run the graph with given inputs.

        Uses the same adaptive layer-by-layer execution as the Playground:
        after each vertex build, calls get_next_runnable_vertices() to
        discover which vertices to build next.  This respects routing
        decisions made by ANY component that calls self.stop() to mark
        branches as INACTIVE (e.g. SmartRouter, ConditionalRouter, or
        any future routing / orchestration component).

        Args:
            inputs: List of input dictionaries (e.g., [{"input_value": "hello"}])
            inputs_components: Optional list of component filters for each input
            types: Optional list of input types for each input
            outputs: Optional list of output vertex IDs to retrieve
            session_id: Optional session ID
            stream: Accepted for caller compatibility; streaming is handled
                at the component level via event_manager, not here.
            fallback_to_env_vars: Whether to fallback to environment variables
            event_manager: Event manager for real-time token streaming

        Returns:
            List of RunOutputs objects with inputs and outputs
        """
        import asyncio as _asyncio
        from agentcore.graph_langgraph.schema import RunOutputs
        from agentcore.services.deps import get_chat_service

        if session_id:
            self._session_id = session_id
            self.session_id = session_id

        # Initialize run (resets all vertex states, run_manager, etc.)
        await self.initialize_run()

        # Get chat service for caching
        chat_service = get_chat_service()

        # Sort vertices to get the first layer — same as Playground.
        # sort_vertices() sets up vertices_to_run and run_manager state.
        #
        # In orchestration mode (skip_dev_logging), filter execution to only the
        # query path (starting from the input vertex).  This mirrors how the
        # Playground's chat phase uses start_component_id to avoid re-running
        # ingestion / build-only branches.  The filtering is fully generic — it
        # uses the same DAG-reachability logic that sort_vertices already supports.
        start_component_id = None
        if getattr(self, "skip_dev_logging", False):
            from agentcore.graph_langgraph.utils import find_start_component_id

            start_component_id = find_start_component_id(
                [v.id for v in self.vertices]
            )
        first_layer = self.sort_vertices(start_component_id=start_component_id)

        vertex_outputs = []

        # Process each input
        for idx, run_inputs in enumerate(inputs):
            input_components = inputs_components[idx] if inputs_components and idx < len(inputs_components) else []

            # Determine which outputs to collect
            if outputs:
                output_ids = set(outputs)
            else:
                output_ids = {v.id for v in self.vertices if v.is_output}

            build_kwargs = dict(
                user_id=self.user_id,
                inputs_dict=run_inputs,
                get_cache=chat_service.get_cache,
                set_cache=chat_service.set_cache,
                fallback_to_env_vars=fallback_to_env_vars,
                event_manager=event_manager,
            )

            built_results: dict[str, object] = {}
            completed_vertices: set[str] = set()

            # ── Adaptive layer-by-layer execution (same as Playground) ──
            #
            # After each vertex build we call get_next_runnable_vertices()
            # which checks vertex active/inactive state.  Any component
            # (router, conditional, A2A, etc.) that calls self.stop() to
            # deactivate a branch will cause those downstream vertices to
            # be skipped here — automatically and generically.

            # Separate input vertices from non-input in first layer
            input_ids = [vid for vid in first_layer
                         if self.get_vertex(vid) and self.get_vertex(vid).is_input]
            non_input_ids = [vid for vid in first_layer if vid not in input_ids]

            is_orch = getattr(self, "skip_dev_logging", False)

            async def _build_and_follow(vertex_id: str) -> None:
                """Build one vertex, then recursively build its runnable successors."""
                vertex = self.get_vertex(vertex_id)
                if not vertex:
                    return

                if is_orch:
                    display = getattr(vertex, "display_name", vertex_id)
                    logger.info(f"[ORCH] ▶️  Building component: {display} ({vertex_id})")

                try:
                    result = await self.build_vertex(vertex_id=vertex_id, **build_kwargs)
                    built_results[vertex_id] = (
                        result.result_dict if hasattr(result, 'result_dict') else result
                    )
                    if is_orch:
                        logger.info(f"[ORCH] ✅ Built component: {display} ({vertex_id})")
                except Exception:
                    logger.exception(f"Error building vertex {vertex_id}")
                    built_results[vertex_id] = None
                    if is_orch:
                        logger.error(f"[ORCH] ❌ Failed component: {display} ({vertex_id})")

                completed_vertices.add(vertex_id)

                # Reset per-vertex tracking (same as Playground's _build_vertex)
                self.reset_inactivated_vertices()
                self.reset_activated_vertices()

                # Discover which successors are now runnable.
                # get_next_runnable_vertices respects INACTIVE state set by
                # any component's self.stop() → graph.mark_branch().
                next_runnable = await self.get_next_runnable_vertices(
                    self._lock, vertex=vertex, cache=False,
                )

                if self.stop_vertex and self.stop_vertex in next_runnable:
                    next_runnable = [self.stop_vertex]

                if not next_runnable:
                    return

                # Only schedule successors whose predecessors are ALL done
                tasks = []
                for next_vid in next_runnable:
                    predecessors = self.predecessor_map.get(next_vid, [])
                    if all(p in completed_vertices for p in predecessors):
                        tasks.append(_asyncio.create_task(_build_and_follow(next_vid)))

                if tasks:
                    await _asyncio.gather(*tasks)

            # 1) Build input vertices sequentially (user message stored first)
            for vid in input_ids:
                await _build_and_follow(vid)

            # 2) Build remaining first-layer vertices concurrently
            if non_input_ids:
                tasks = [_asyncio.create_task(_build_and_follow(vid))
                         for vid in non_input_ids]
                await _asyncio.gather(*tasks)

            # Collect results only for the requested output vertices
            run_outputs = [built_results.get(oid) for oid in (outputs or list(output_ids))]

            vertex_outputs.append(RunOutputs(inputs=run_inputs, outputs=run_outputs))

        # End traces
        await self.end_all_traces_in_context()

        return vertex_outputs
    
    async def build_vertex(self, vertex_id: str, **kwargs):
        """Build a single vertex (compatibility method).
        
        This is called by the existing build system. For LangGraph, we need
        to execute the full workflow instead.
        
        Args:
            vertex_id: ID of the vertex to build
            **kwargs: Additional arguments
            
        Returns:
            VertexBuildResult with vertex build result
        """
        from agentcore.graph_langgraph.schema import VertexBuildResult
        
        # Get the vertex
        vertex = self.get_vertex(vertex_id)
        if not vertex:
            msg = f"Vertex {vertex_id} not found"
            raise ValueError(msg)
        
        # Note: We do NOT start a new trace here. The agent-level trace is started 
        # in initialize_run(). Each vertex build creates child spans via the 
        # component's trace_component() call in build_results().
        # This ensures all vertex builds appear as spans under a single agent trace.
        
        user_id = kwargs.get("user_id")
        inputs_dict = kwargs.get("inputs_dict", {})
        
        # If this is an input vertex AND we have inputs_dict, update the vertex parameters first
        # This mimics the old Graph's _set_inputs() behavior with component and type filtering
        if vertex_id in self._is_input_vertices and inputs_dict:
            # Get input filtering parameters
            from agentcore.schema.schema import INPUT_FIELD_NAME
            
            # Extract components filter (if provided)
            input_components = inputs_dict.get('components', [])
            # Note: input_type is not in inputs_dict, would need to be passed separately
            # For now, we skip input_type filtering as it's rarely used
            
            # Filter by component (only update if vertex matches component filter)
            should_update = True
            if input_components:
                # Check if vertex_id or display_name is in the components list
                if vertex_id not in input_components and vertex.display_name not in input_components:
                    should_update = False
                    logger.debug(f"Skipping input vertex {vertex_id} - not in components filter: {input_components}")
            
            if should_update:
                logger.debug(f"Updating input vertex {vertex_id} with inputs: {inputs_dict}")
                
                if INPUT_FIELD_NAME in inputs_dict:
                    vertex.update_raw_params({INPUT_FIELD_NAME: inputs_dict[INPUT_FIELD_NAME]}, overwrite=True)
                    logger.debug(f"Input vertex {vertex_id} updated with input_value: {inputs_dict[INPUT_FIELD_NAME]}")
        
        # Check if we should build or use cached result (frozen vertex optimization)
        should_build = False
        if not vertex.frozen:
            should_build = True
        else:
            # Vertex is frozen - check cache
            from agentcore.services.cache.utils import CacheMiss
            get_cache = kwargs.get("get_cache")
            if get_cache is not None:
                cached_result = await get_cache(key=vertex.id)
            else:
                cached_result = CacheMiss()
            
            if isinstance(cached_result, CacheMiss):
                should_build = True
            else:
                # Try to restore from cache
                try:
                    cached_vertex_dict = cached_result["result"]
                    vertex.built = cached_vertex_dict["built"]
                    vertex.artifacts = cached_vertex_dict["artifacts"]
                    vertex.built_object = cached_vertex_dict["built_object"]
                    vertex.built_result = cached_vertex_dict["built_result"]
                    vertex.results = cached_vertex_dict.get("results", {})
                    
                    # Try to finalize build with cached data
                    try:
                        vertex.finalize_build()
                        if vertex.result is not None:
                            vertex.result.used_frozen_result = True
                    except Exception:
                        logger.opt(exception=True).debug("Error finalizing cached build")
                        should_build = True
                except KeyError:
                    should_build = True
        
        if should_build:
            try:
                # Build the vertex directly (not via LangGraph for individual builds)
                await vertex.build(
                    user_id=user_id,
                    inputs=inputs_dict,
                    files=kwargs.get("files"),
                    event_manager=kwargs.get("event_manager"),
                    fallback_to_env_vars=kwargs.get("fallback_to_env_vars", False),
                )
                
                # Log transaction to database (for Logs UI)
                if self.agent_id and not self.skip_dev_logging:
                    try:
                        from agentcore.graph_langgraph.logging import log_transaction, _vertex_to_primitive_dict

                        # Prepare inputs
                        inputs_for_log = _vertex_to_primitive_dict(vertex.raw_params)

                        # Prepare outputs - use built_result which contains the actual output
                        outputs_for_log = None
                        if vertex.built_result is not None:
                            try:
                                # built_result contains the actual component output
                                if isinstance(vertex.built_result, dict):
                                    result_dict = vertex.built_result.copy()
                                elif hasattr(vertex.built_result, 'model_dump'):
                                    result_dict = vertex.built_result.model_dump()
                                elif hasattr(vertex.built_result, '__dict__'):
                                    result_dict = vertex.built_result.__dict__
                                else:
                                    result_dict = {"result": str(vertex.built_result)}

                                # Handle pandas DataFrames
                                for key, value in list(result_dict.items()):
                                    if isinstance(value, pd.DataFrame):
                                        result_dict[key] = value.to_dict()
                                outputs_for_log = result_dict
                            except Exception as e:
                                logger.debug(f"Error preparing outputs for {vertex.id}: {e}")
                                outputs_for_log = {"result": str(vertex.built_result)}

                        # Get target vertices from outgoing edges
                        target_ids = []
                        if hasattr(vertex, 'outgoing_edges'):
                            for edge in vertex.outgoing_edges:
                                if hasattr(edge, 'target') and hasattr(edge.target, 'id'):
                                    target_ids.append(edge.target.id)

                        # Log transaction for each target (or None if no targets)
                        if target_ids:
                            for target_id in target_ids:
                                await log_transaction(
                                    agent_id=self.agent_id,
                                    vertex_id=vertex.id,
                                    status="success",
                                    inputs=inputs_for_log,
                                    outputs=outputs_for_log,
                                    target_id=target_id,
                                    error=None,
                                )
                        else:
                            # No targets, log single transaction
                            await log_transaction(
                                agent_id=self.agent_id,
                                vertex_id=vertex.id,
                                status="success",
                                inputs=inputs_for_log,
                                outputs=outputs_for_log,
                                target_id=None,
                                error=None,
                            )
                    except Exception as log_error:
                        logger.warning(f"Failed to log transaction for {vertex.id}: {log_error}")

                # Log to orch_transaction when running under orchestrator
                if self.agent_id and self.skip_dev_logging and self.orch_session_id:
                    try:
                        from uuid import UUID as _UUID
                        from agentcore.graph_langgraph.logging import _vertex_to_primitive_dict
                        from agentcore.serialization.serialization import serialize, get_max_text_length, get_max_items_length
                        from agentcore.services.database.models.orch_transaction.model import OrchTransactionTable
                        from agentcore.services.database.models.orch_transaction.crud import orch_log_transaction
                        from agentcore.services.database.utils import session_getter
                        from agentcore.services.deps import get_db_service

                        _ml = get_max_text_length()
                        _mi = get_max_items_length()
                        orch_inputs = serialize(
                            _vertex_to_primitive_dict(vertex.raw_params),
                            max_length=_ml, max_items=_mi,
                        ) if vertex.raw_params else None
                        orch_outputs = serialize(
                            vertex.built_result, max_length=_ml, max_items=_mi,
                        ) if vertex.built_result is not None else None

                        target_ids = []
                        if hasattr(vertex, 'outgoing_edges'):
                            for edge in vertex.outgoing_edges:
                                if hasattr(edge, 'target') and hasattr(edge.target, 'id'):
                                    target_ids.append(edge.target.id)

                        agent_uuid = self.agent_id if isinstance(self.agent_id, _UUID) else _UUID(self.agent_id)
                        dep_uuid = _UUID(self.orch_deployment_id) if self.orch_deployment_id else None
                        org_uuid = _UUID(self.orch_org_id) if self.orch_org_id else None
                        dept_uuid = _UUID(self.orch_dept_id) if self.orch_dept_id else None

                        targets = target_ids if target_ids else [None]
                        async with session_getter(get_db_service()) as db:
                            for tid in targets:
                                txn = OrchTransactionTable(
                                    vertex_id=vertex.id,
                                    target_id=tid,
                                    inputs=orch_inputs,
                                    outputs=orch_outputs,
                                    status="success",
                                    error=None,
                                    agent_id=agent_uuid,
                                    session_id=self.orch_session_id,
                                    deployment_id=dep_uuid,
                                    org_id=org_uuid,
                                    dept_id=dept_uuid,
                                )
                                await orch_log_transaction(txn, db)
                    except Exception as log_error:
                        logger.warning(f"Failed to log orch transaction for {vertex.id}: {log_error}")

                # Log to transaction_prod when running from a PROD deployment
                if self.agent_id and self.prod_deployment_id:
                    try:
                        from uuid import UUID as _UUID
                        from agentcore.graph_langgraph.logging import _vertex_to_primitive_dict
                        from agentcore.serialization.serialization import serialize, get_max_text_length, get_max_items_length
                        from agentcore.services.database.models.transaction_prod.model import TransactionProdTable
                        from agentcore.services.database.models.transaction_prod.crud import log_transaction_prod
                        from agentcore.services.database.utils import session_getter
                        from agentcore.services.deps import get_db_service

                        _ml = get_max_text_length()
                        _mi = get_max_items_length()
                        prod_inputs = serialize(
                            _vertex_to_primitive_dict(vertex.raw_params),
                            max_length=_ml, max_items=_mi,
                        ) if vertex.raw_params else None
                        prod_outputs = serialize(
                            vertex.built_result, max_length=_ml, max_items=_mi,
                        ) if vertex.built_result is not None else None

                        agent_uuid = self.agent_id if isinstance(self.agent_id, _UUID) else _UUID(self.agent_id)
                        dep_uuid = _UUID(self.prod_deployment_id)
                        org_uuid = _UUID(self.prod_org_id) if self.prod_org_id else None
                        dept_uuid = _UUID(self.prod_dept_id) if self.prod_dept_id else None

                        target_ids = []
                        if hasattr(vertex, 'outgoing_edges'):
                            for edge in vertex.outgoing_edges:
                                if hasattr(edge, 'target') and hasattr(edge.target, 'id'):
                                    target_ids.append(edge.target.id)

                        targets = target_ids if target_ids else [None]
                        async with session_getter(get_db_service()) as db:
                            for tid in targets:
                                prod_txn = TransactionProdTable(
                                    vertex_id=vertex.id,
                                    target_id=tid,
                                    inputs=prod_inputs,
                                    outputs=prod_outputs,
                                    status="success",
                                    error=None,
                                    agent_id=agent_uuid,
                                    deployment_id=dep_uuid,
                                    org_id=org_uuid,
                                    dept_id=dept_uuid,
                                )
                                await log_transaction_prod(prod_txn, db)
                    except Exception as log_error:
                        logger.warning(f"Failed to log transaction_prod for {vertex.id}: {log_error}")

                # Log to transaction_uat when running from a UAT deployment
                if self.agent_id and self.uat_deployment_id:
                    try:
                        from uuid import UUID as _UUID
                        from agentcore.graph_langgraph.logging import _vertex_to_primitive_dict
                        from agentcore.serialization.serialization import serialize, get_max_text_length, get_max_items_length
                        from agentcore.services.database.models.transaction_uat.model import TransactionUATTable
                        from agentcore.services.database.models.transaction_uat.crud import log_transaction_uat
                        from agentcore.services.database.utils import session_getter
                        from agentcore.services.deps import get_db_service

                        _ml = get_max_text_length()
                        _mi = get_max_items_length()
                        uat_inputs = serialize(
                            _vertex_to_primitive_dict(vertex.raw_params),
                            max_length=_ml, max_items=_mi,
                        ) if vertex.raw_params else None
                        uat_outputs = serialize(
                            vertex.built_result, max_length=_ml, max_items=_mi,
                        ) if vertex.built_result is not None else None

                        agent_uuid = self.agent_id if isinstance(self.agent_id, _UUID) else _UUID(self.agent_id)
                        dep_uuid = _UUID(self.uat_deployment_id)
                        org_uuid = _UUID(self.uat_org_id) if self.uat_org_id else None
                        dept_uuid = _UUID(self.uat_dept_id) if self.uat_dept_id else None

                        target_ids = []
                        if hasattr(vertex, 'outgoing_edges'):
                            for edge in vertex.outgoing_edges:
                                if hasattr(edge, 'target') and hasattr(edge.target, 'id'):
                                    target_ids.append(edge.target.id)

                        targets = target_ids if target_ids else [None]
                        async with session_getter(get_db_service()) as db:
                            for tid in targets:
                                uat_txn = TransactionUATTable(
                                    vertex_id=vertex.id,
                                    target_id=tid,
                                    inputs=uat_inputs,
                                    outputs=uat_outputs,
                                    status="success",
                                    error=None,
                                    agent_id=agent_uuid,
                                    deployment_id=dep_uuid,
                                    org_id=org_uuid,
                                    dept_id=dept_uuid,
                                )
                                await log_transaction_uat(uat_txn, db)
                    except Exception as log_error:
                        logger.warning(f"Failed to log transaction_uat for {vertex.id}: {log_error}")

                # Log successful vertex build to database
                if self.agent_id and not self.skip_dev_logging:
                    try:
                        from uuid import UUID
                        from agentcore.graph_langgraph.logging import log_vertex_build
                        
                        # Prepare data for logging
                        data_dict = {}
                        if vertex.built_result is not None:
                            data_dict = {"result": str(vertex.built_result)}
                        
                        await log_vertex_build(
                            agent_id=self.agent_id if isinstance(self.agent_id, UUID) else UUID(self.agent_id),
                            vertex_id=vertex.id,
                            valid=vertex.built,
                            params=vertex.raw_params,
                            data=data_dict,
                            artifacts=vertex.artifacts,
                        )
                    except Exception as log_error:
                        logger.warning(f"Failed to log vertex build for {vertex.id}: {log_error}")
                
                # Save to cache if vertex is frozen and set_cache is available
                if vertex.frozen:
                    set_cache = kwargs.get("set_cache")
                    if set_cache is not None:
                        vertex_dict = {
                            "built": vertex.built,
                            "results": vertex.results,
                            "artifacts": vertex.artifacts,
                            "built_object": vertex.built_object,
                            "built_result": vertex.built_result,
                        }
                        await set_cache(key=vertex.id, value={"result": vertex_dict})
            
            except Exception as build_error:
                # Log failed transaction to database
                if self.agent_id and not self.skip_dev_logging:
                    try:
                        from agentcore.graph_langgraph.logging import log_transaction, _vertex_to_primitive_dict

                        inputs_for_log = _vertex_to_primitive_dict(vertex.raw_params)

                        await log_transaction(
                            agent_id=self.agent_id,
                            vertex_id=vertex.id,
                            status="error",
                            inputs=inputs_for_log,
                            outputs=None,
                            target_id=None,
                            error=str(build_error),
                        )
                    except Exception as log_error:
                        logger.warning(f"Failed to log transaction error for {vertex.id}: {log_error}")

                # Log failed transaction to orch_transaction
                if self.agent_id and self.skip_dev_logging and self.orch_session_id:
                    try:
                        from uuid import UUID as _UUID
                        from agentcore.graph_langgraph.logging import _vertex_to_primitive_dict
                        from agentcore.serialization.serialization import serialize, get_max_text_length, get_max_items_length
                        from agentcore.services.database.models.orch_transaction.model import OrchTransactionTable
                        from agentcore.services.database.models.orch_transaction.crud import orch_log_transaction
                        from agentcore.services.database.utils import session_getter
                        from agentcore.services.deps import get_db_service

                        orch_inputs = serialize(
                            _vertex_to_primitive_dict(vertex.raw_params),
                            max_length=get_max_text_length(),
                            max_items=get_max_items_length(),
                        ) if vertex.raw_params else None
                        agent_uuid = self.agent_id if isinstance(self.agent_id, _UUID) else _UUID(self.agent_id)

                        async with session_getter(get_db_service()) as db:
                            txn = OrchTransactionTable(
                                vertex_id=vertex.id,
                                target_id=None,
                                inputs=orch_inputs,
                                outputs=None,
                                status="error",
                                error=str(build_error),
                                agent_id=agent_uuid,
                                session_id=self.orch_session_id,
                                deployment_id=_UUID(self.orch_deployment_id) if self.orch_deployment_id else None,
                                org_id=_UUID(self.orch_org_id) if self.orch_org_id else None,
                                dept_id=_UUID(self.orch_dept_id) if self.orch_dept_id else None,
                            )
                            await orch_log_transaction(txn, db)
                    except Exception as log_error:
                        logger.warning(f"Failed to log orch transaction error for {vertex.id}: {log_error}")

                # Log failed transaction to transaction_prod
                if self.agent_id and self.prod_deployment_id:
                    try:
                        from uuid import UUID as _UUID
                        from agentcore.graph_langgraph.logging import _vertex_to_primitive_dict
                        from agentcore.serialization.serialization import serialize, get_max_text_length, get_max_items_length
                        from agentcore.services.database.models.transaction_prod.model import TransactionProdTable
                        from agentcore.services.database.models.transaction_prod.crud import log_transaction_prod
                        from agentcore.services.database.utils import session_getter
                        from agentcore.services.deps import get_db_service

                        prod_inputs = serialize(
                            _vertex_to_primitive_dict(vertex.raw_params),
                            max_length=get_max_text_length(),
                            max_items=get_max_items_length(),
                        ) if vertex.raw_params else None
                        agent_uuid = self.agent_id if isinstance(self.agent_id, _UUID) else _UUID(self.agent_id)

                        async with session_getter(get_db_service()) as db:
                            prod_txn = TransactionProdTable(
                                vertex_id=vertex.id,
                                target_id=None,
                                inputs=prod_inputs,
                                outputs=None,
                                status="error",
                                error=str(build_error),
                                agent_id=agent_uuid,
                                deployment_id=_UUID(self.prod_deployment_id),
                                org_id=_UUID(self.prod_org_id) if self.prod_org_id else None,
                                dept_id=_UUID(self.prod_dept_id) if self.prod_dept_id else None,
                            )
                            await log_transaction_prod(prod_txn, db)
                    except Exception as log_error:
                        logger.warning(f"Failed to log transaction_prod error for {vertex.id}: {log_error}")

                # Log failed transaction to transaction_uat
                if self.agent_id and self.uat_deployment_id:
                    try:
                        from uuid import UUID as _UUID
                        from agentcore.graph_langgraph.logging import _vertex_to_primitive_dict
                        from agentcore.serialization.serialization import serialize, get_max_text_length, get_max_items_length
                        from agentcore.services.database.models.transaction_uat.model import TransactionUATTable
                        from agentcore.services.database.models.transaction_uat.crud import log_transaction_uat
                        from agentcore.services.database.utils import session_getter
                        from agentcore.services.deps import get_db_service

                        uat_inputs = serialize(
                            _vertex_to_primitive_dict(vertex.raw_params),
                            max_length=get_max_text_length(),
                            max_items=get_max_items_length(),
                        ) if vertex.raw_params else None
                        agent_uuid = self.agent_id if isinstance(self.agent_id, _UUID) else _UUID(self.agent_id)

                        async with session_getter(get_db_service()) as db:
                            uat_txn = TransactionUATTable(
                                vertex_id=vertex.id,
                                target_id=None,
                                inputs=uat_inputs,
                                outputs=None,
                                status="error",
                                error=str(build_error),
                                agent_id=agent_uuid,
                                deployment_id=_UUID(self.uat_deployment_id),
                                org_id=_UUID(self.uat_org_id) if self.uat_org_id else None,
                                dept_id=_UUID(self.uat_dept_id) if self.uat_dept_id else None,
                            )
                            await log_transaction_uat(uat_txn, db)
                    except Exception as log_error:
                        logger.warning(f"Failed to log transaction_uat error for {vertex.id}: {log_error}")

                # Log failed vertex build to database
                if self.agent_id and not self.skip_dev_logging:
                    try:
                        from uuid import UUID
                        from agentcore.graph_langgraph.logging import log_vertex_build
                        
                        await log_vertex_build(
                            agent_id=self.agent_id if isinstance(self.agent_id, UUID) else UUID(self.agent_id),
                            vertex_id=vertex.id,
                            valid=False,
                            params=vertex.raw_params,
                            data={"error": str(build_error)},
                            artifacts=None,
                        )
                    except Exception as log_error:
                        logger.warning(f"Failed to log vertex build error for {vertex.id}: {log_error}")
                
                # Re-raise the build error
                raise
        
        # Return result as VertexBuildResult NamedTuple
        return VertexBuildResult(
            result_dict=vertex.result,
            params=str(vertex.built_object_repr()),
            valid=vertex.built,
            artifacts=vertex.artifacts,
            vertex=vertex,
        )
    
    async def get_next_runnable_vertices(self, lock, vertex: LangGraphVertex, cache: bool = False) -> list[str]:
        """Get next runnable vertices (compatibility method).
        
        This method respects the vertices_to_run filter set by sort_vertices,
        which enables "Run Till Specific Component" functionality.
        
        Args:
            lock: Async lock
            vertex: The vertex that just finished
            cache: Whether to use cache
            
        Returns:
            List of next runnable vertex IDs (filtered by vertices_to_run)
        """
        v_id = vertex.id
        v_successors_ids = self.successor_map.get(vertex.id, [])
        
        # Filter successors to only include those in vertices_to_run
        # This ensures "Run Till Specific Component" works correctly
        if self.vertices_to_run:
            v_successors_ids = [s_id for s_id in v_successors_ids if s_id in self.vertices_to_run]
        
        # Track that this vertex has run
        self.run_manager.ran_at_least_once.add(v_id)
        
        async with lock:
            self.run_manager.remove_vertex_from_runnables(v_id)
            
            # Use find_next_runnable_vertices to filter out inactive vertices
            next_runnable_vertices = self.find_next_runnable_vertices(v_successors_ids)
            
            for next_v_id in set(next_runnable_vertices):  # Use set to avoid duplicates
                if next_v_id == v_id:
                    next_runnable_vertices.remove(v_id)
                else:
                    self.run_manager.add_to_vertices_being_run(next_v_id)
        
        return next_runnable_vertices
    
    def get_vertex_neighbors(self, vertex: LangGraphVertex) -> dict[LangGraphVertex, int]:
        """Returns a dictionary mapping each direct neighbor of a vertex to the count of connecting edges.
        
        A neighbor is any vertex directly connected to the input vertex, either as a source or target.
        The count reflects the number of edges between the input vertex and each neighbor.
        
        Args:
            vertex: The vertex to get neighbors for
            
        Returns:
            Dictionary mapping neighbor vertices to edge counts
        """
        neighbors: dict[LangGraphVertex, int] = {}
        
        # Get neighbors from edges (stored as dicts)
        for edge_data in self.edges:
            if edge_data.get("source") == vertex.id:
                neighbor = self.get_vertex(edge_data.get("target"))
                if neighbor:
                    neighbors[neighbor] = neighbors.get(neighbor, 0) + 1
            elif edge_data.get("target") == vertex.id:
                neighbor = self.get_vertex(edge_data.get("source"))
                if neighbor:
                    neighbors[neighbor] = neighbors.get(neighbor, 0) + 1
        
        return neighbors
    
    def get_snapshot(self) -> dict[str, Any]:
        """Capture current execution state snapshot.
        
        Returns:
            Dictionary containing execution state including run_manager state,
            run queue, vertices layers, and active/inactive vertices.
        """
        return copy.deepcopy(
            {
                "run_manager": self.run_manager.to_dict(),
                "run_queue": list(self._run_queue),
                "vertices_layers": self.vertices_layers,
                "first_layer": self._first_layer,
                "inactivated_vertices": list(self.inactivated_vertices),
                "activated_vertices": self.activated_vertices,
            }
        )
    
    def _record_snapshot(self, vertex_id: str | None = None) -> None:
        """Record a snapshot of the current execution state.
        
        Args:
            vertex_id: Optional vertex ID that was just executed
        """
        self._snapshots.append(self.get_snapshot())
        if vertex_id:
            self._call_order.append(vertex_id)
    
    def prepare(self, stop_component_id: str | None = None, start_component_id: str | None = None):
        """Prepare graph for step-by-step execution.
        
        Args:
            stop_component_id: Optional component to stop at
            start_component_id: Optional component to start from
            
        Returns:
            Self for chaining
        """
        # Initialize run queue with first layer vertices
        first_layer = self._first_layer if self._first_layer else []
        
        for vertex_id in first_layer:
            self.run_manager.add_to_vertices_being_run(vertex_id)
            if vertex_id in self.cycle_vertices:
                self.run_manager.add_to_cycle_vertices(vertex_id)
        
        self._run_queue = deque(sorted(first_layer))
        self._prepared = True
        self._record_snapshot()
        return self
    
    def get_next_in_queue(self) -> str | None:
        """Get next vertex ID from run queue.
        
        Returns:
            Next vertex ID or None if queue is empty
        """
        if self._run_queue:
            return self._run_queue.popleft()
        return None
    
    def extend_run_queue(self, vertices: list[str]) -> None:
        """Add vertices to the run queue (avoiding duplicates).
        
        Args:
            vertices: List of vertex IDs to add
        """
        for v in vertices:
            if v not in self._run_queue:
                self._run_queue.append(v)
    
    async def astep(
        self,
        inputs: InputValueRequest | None = None,
        files: list[str] | None = None,
        user_id: str | None = None,
        event_manager: EventManager | None = None,
    ):
        """Execute one step (one vertex) of the graph.
        
        Args:
            inputs: Input values for the step
            files: Optional list of file paths
            user_id: Optional user ID
            event_manager: Optional event manager for callbacks
            
        Returns:
            Vertex build result or Finish() if complete
        """
        if not self._prepared:
            msg = "Graph not prepared. Call prepare() first."
            raise ValueError(msg)
        
        if not self._run_queue:
            # No more vertices to run - end traces and return Finish
            await self.end_all_traces_in_context()
            return Finish()
        
        vertex_id = self.get_next_in_queue()
        if not vertex_id:
            await self.end_all_traces_in_context()
            return Finish()
        
        # Import here to avoid circular dependency
        from agentcore.services.deps import get_chat_service
        chat_service = get_chat_service()
        
        # Build the vertex
        vertex_build_result = await self.build_vertex(
            vertex_id=vertex_id,
            user_id=user_id,
            inputs_dict=inputs.model_dump() if inputs else {},
            files=files,
            get_cache=chat_service.get_cache,
            set_cache=chat_service.set_cache,
            event_manager=event_manager,
        )
        
        # Get next runnable vertices
        next_runnable_vertices = await self.get_next_runnable_vertices(
            self._lock, vertex=vertex_build_result.vertex, cache=False
        )
        
        if self.stop_vertex and self.stop_vertex in next_runnable_vertices:
            next_runnable_vertices = [self.stop_vertex]
        
        self.extend_run_queue(next_runnable_vertices)
        self.reset_inactivated_vertices()
        self.reset_activated_vertices()
        
        # Cache the graph state
        await chat_service.set_cache(str(self.agent_id or self._run_id), self)
        self._record_snapshot(vertex_id)
        
        return vertex_build_result
    
    async def async_start(
        self,
        inputs: list[dict] | None = None,
        max_iterations: int | None = None,
        config: dict | None = None,
        event_manager: EventManager | None = None,
    ):
        """Streaming generator for step-by-step execution with event support.
        
        This generator yields the result of each vertex execution and provides
        real-time progress updates. It supports max iterations to prevent infinite loops.
        
        Args:
            inputs: List of input dictionaries for initial vertices
            max_iterations: Maximum iterations per vertex (prevents infinite loops)
            config: Optional configuration dictionary
            event_manager: Optional event manager for callbacks
            
        Yields:
            Vertex build results for each step
            
        Returns:
            None when graph execution completes
            
        Raises:
            ValueError: If max_iterations is exceeded
        """
        if not self._prepared:
            msg = "Graph not prepared. Call prepare() first."
            raise ValueError(msg)
        
        # Set initial inputs on vertices if provided
        if inputs:
            for input_dict in inputs:
                for key, value in input_dict.items():
                    vertex = self.get_vertex(key)
                    if vertex:
                        # Set the input value on the vertex
                        vertex.set_input_value(key, value)
        
        # Track how many times each vertex has been yielded
        yielded_counts: dict[str, int] = defaultdict(int)
        
        def should_continue(counts: dict[str, int], max_iter: int | None) -> bool:
            """Check if execution should continue."""
            if max_iter is None:
                return True
            return max(counts.values(), default=0) <= max_iter
        
        while should_continue(yielded_counts, max_iterations):
            result = await self.astep(event_manager=event_manager)
            yield result
            
            if hasattr(result, "vertex"):
                yielded_counts[result.vertex.id] += 1
            
            if isinstance(result, Finish):
                return
        
        msg = "Max iterations reached"
        raise ValueError(msg)
    
    def update(self, other: LangGraphAdapter) -> LangGraphAdapter:
        """Update this graph with changes from another graph.
        
        This method syncs the current graph with another graph by:
        - Adding new vertices that exist in `other` but not in `self`
        - Removing vertices that exist in `self` but not in `other`
        - Updating existing vertices that have changed
        - Preserving frozen vertex states and results
        
        Args:
            other: The graph to update from
            
        Returns:
            Self for chaining
        """
        # Existing vertices in self graph
        existing_vertex_ids = set(self.vertex_map.keys())
        # Vertex IDs in the other graph
        other_vertex_ids = set(other.vertex_map.keys())

        # Find vertices that are in other but not in self (new vertices)
        new_vertex_ids = other_vertex_ids - existing_vertex_ids

        # Find vertices that are in self but not in other (removed vertices)
        removed_vertex_ids = existing_vertex_ids - other_vertex_ids

        # Remove vertices that are not in the other graph
        for vertex_id in removed_vertex_ids:
            self.remove_vertex(vertex_id)

        # Add new vertices (order matters - add vertices before edges)
        for vertex_id in new_vertex_ids:
            new_vertex = other.get_vertex(vertex_id)
            if new_vertex:
                self._add_vertex(new_vertex)

        # Update edges for new vertices
        for vertex_id in new_vertex_ids:
            new_vertex = other.get_vertex(vertex_id)
            if new_vertex:
                self._update_edges_from_vertex(new_vertex)
                # Set graph reference
                new_vertex.graph_adapter = self

        # Update existing vertices that have changed
        for vertex_id in existing_vertex_ids.intersection(other_vertex_ids):
            self_vertex = self.get_vertex(vertex_id)
            other_vertex = other.get_vertex(vertex_id)
            
            if self_vertex and other_vertex:
                # Check if data is identical
                if not self._vertex_data_is_identical(self_vertex, other_vertex):
                    self._update_vertex_from_another(self_vertex, other_vertex)

        # Rebuild graph structure
        self.raw_graph_data = copy.deepcopy(other.raw_graph_data)
        self.edges = copy.deepcopy(other.edges)
        self.predecessor_map = copy.deepcopy(other.predecessor_map)
        self.successor_map = copy.deepcopy(other.successor_map)
        self.in_degree_map = copy.deepcopy(other.in_degree_map)
        self.cycle_vertices = copy.deepcopy(other.cycle_vertices)
        self.is_cyclic = other.is_cyclic
        
        # Rebuild vertex lists
        self._define_vertices_lists()
        
        # Rebuild LangGraph workflow
        self._build_langgraph_workflow()
        
        return self
    
    def _vertex_data_is_identical(self, vertex: LangGraphVertex, other_vertex: LangGraphVertex) -> bool:
        """Check if two vertices have identical data.
        
        Args:
            vertex: First vertex
            other_vertex: Second vertex
            
        Returns:
            True if data is identical
        """
        return vertex.data == other_vertex.data
    
    def _update_vertex_from_another(self, vertex: LangGraphVertex, other_vertex: LangGraphVertex) -> None:
        """Update a vertex from another vertex.
        
        Args:
            vertex: The vertex to update
            other_vertex: The vertex to copy data from
        """
        # Update vertex data
        vertex.data = copy.deepcopy(other_vertex.data)
        vertex.display_name = other_vertex.display_name
        vertex.is_input = other_vertex.is_input
        vertex.is_output = other_vertex.is_output
        
        # Rebuild parameters from template
        vertex.build_params_from_template()
        
        # If the vertex is frozen, preserve results
        # Otherwise, reset built state
        if not vertex.frozen:
            vertex.built = False
            vertex.result = None
            vertex.artifacts = {}
    
    def _add_vertex(self, vertex: LangGraphVertex) -> None:
        """Add a vertex to the graph.
        
        Args:
            vertex: Vertex to add
        """
        self.vertices.append(vertex)
        self.vertex_map[vertex.id] = vertex
    
    # ==========================================================================
    # Branch marking methods (for conditional routing, If-Else, etc.)
    # ==========================================================================
    
    def get_edge(self, source_id: str, target_id: str) -> dict[str, Any] | None:
        """Returns the edge data between two vertices.
        
        Args:
            source_id: Source vertex ID
            target_id: Target vertex ID
            
        Returns:
            Edge data dict if found, None otherwise
        """
        for edge in self.edges:
            if edge.get("source") == source_id and edge.get("target") == target_id:
                return edge
        return None
    
    def _mark_branch(
        self, vertex_id: str, state: str, visited: set | None = None, output_name: str | None = None
    ) -> set:
        """Marks a branch of the graph as ACTIVE or INACTIVE.
        
        Used by conditional routers to deactivate branches that shouldn't run.
        
        Args:
            vertex_id: Starting vertex ID
            state: "ACTIVE" or "INACTIVE"
            visited: Set of already visited vertex IDs
            output_name: Optional output name to filter edges
            
        Returns:
            Set of visited vertex IDs
        """
        from agentcore.graph_langgraph.schema import VertexStates
        
        is_first_call = visited is None
        if visited is None:
            visited = set()
        
        if vertex_id in visited:
            return visited
        visited.add(vertex_id)
        
        # Don't mark the starting vertex itself, only its children
        if not is_first_call:
            self.mark_vertex(vertex_id, state)

        # Get children from parent_child_map or successor_map
        children = self.parent_child_map.get(vertex_id, []) or self.successor_map.get(vertex_id, [])
        
        for child_id in children:
            # Only mark children that have an edge through the specified output_name
            if output_name:
                edge = self.get_edge(vertex_id, child_id)
                if edge:
                    # Check if edge's source handle matches output_name
                    source_handle = edge.get("data", {}).get("sourceHandle", {})
                    if isinstance(source_handle, dict):
                        handle_name = source_handle.get("name", "")
                    else:
                        handle_name = str(source_handle) if source_handle else ""
                    if handle_name != output_name:
                        continue
                else:
                    continue
            self._mark_branch(child_id, state, visited)
        return visited
    
    def mark_branch(self, vertex_id: str, state: str, output_name: str | None = None) -> None:
        """Marks a branch starting from vertex_id as ACTIVE or INACTIVE.
        
        This is called by components like ConditionalRouter to deactivate
        branches that shouldn't execute.
        
        Args:
            vertex_id: Starting vertex ID
            state: "ACTIVE" or "INACTIVE"
            output_name: Optional output name to filter which branch to mark
        """
        from agentcore.graph_langgraph.utils import build_adjacency_maps
        
        visited = self._mark_branch(vertex_id=vertex_id, state=state, output_name=output_name)
        
        # Update predecessor map for visited vertices
        new_predecessor_map = {k: list(v) for k, v in self.predecessor_map.items() if k in visited}
        
        if vertex_id in self.cycle_vertices:
            # For cycle vertices, remove dependencies that are not in the cycle
            # and have already run at least once
            new_predecessor_map = {
                k: [dep for dep in v if dep in self.cycle_vertices and dep in self.run_manager.ran_at_least_once]
                for k, v in new_predecessor_map.items()
            }
        
        self.run_manager.update_run_state(
            run_predecessors=new_predecessor_map,
            vertices_to_run=self.vertices_to_run,
        )
    
    def mark_vertex(self, vertex_id: str, state: str) -> None:
        """Marks a single vertex as ACTIVE or INACTIVE.
        
        Args:
            vertex_id: Vertex ID to mark
            state: "ACTIVE" or "INACTIVE"
        """
        from agentcore.graph_langgraph.schema import VertexStates
        
        vertex = self.get_vertex(vertex_id)
        if vertex:
            vertex.set_state(state)
            if state == "INACTIVE":
                self.run_manager.remove_from_predecessors(vertex_id)
                self.inactivated_vertices.add(vertex_id)
            elif state == "ACTIVE":
                self.inactivated_vertices.discard(vertex_id)
    
    def mark_all_vertices(self, state: str) -> None:
        """Marks all vertices in the graph with the given state.
        
        Args:
            state: "ACTIVE" or "INACTIVE"
        """
        for vertex in self.vertices:
            vertex.set_state(state)
    
    def reset_inactivated_vertices(self) -> None:
        """Reset the inactivated vertices set."""
        self.inactivated_vertices = set()
    
    def reset_activated_vertices(self) -> None:
        """Reset the activated vertices list."""
        self.activated_vertices = []
    
    def get_all_successors(self, vertex: LangGraphVertex, *, recursive=True, flat=True, visited=None):
        """Returns all successors of a given vertex, optionally recursively and as a flat or nested list.

        Args:
            vertex: The vertex whose successors are to be retrieved.
            recursive: If True, retrieves successors recursively; otherwise, only immediate successors.
            flat: If True, returns a flat list of successors; if False, returns a nested list structure.
            visited: Internal set used to track visited vertices and prevent cycles.

        Returns:
            A list of successor vertices, either flat or nested depending on the `flat` parameter.
        """
        if visited is None:
            visited = set()

        # Prevent revisiting vertices to avoid infinite loops in cyclic graphs
        if vertex in visited:
            return []

        visited.add(vertex)

        successors = vertex.successors
        if not successors:
            return []

        successors_result = []

        for successor in successors:
            if recursive:
                next_successors = self.get_all_successors(successor, recursive=recursive, flat=flat, visited=visited)
                if flat:
                    successors_result.extend(next_successors)
                else:
                    successors_result.append(next_successors)
            if flat:
                successors_result.append(successor)
            else:
                successors_result.append([successor])

        if not flat and successors_result:
            return [successors, *successors_result]

        return successors_result

    def get_all_predecessors(self, vertex: LangGraphVertex, *, recursive: bool = True) -> list[LangGraphVertex]:
        """Retrieves all predecessor vertices of a given vertex.

        If `recursive` is True, returns both direct and indirect predecessors by
        traversing the graph recursively. If False, returns only the immediate predecessors.
        """
        _predecessors = self.predecessor_map.get(vertex.id, [])
        predecessors = [self.get_vertex(v_id) for v_id in _predecessors]
        if recursive:
            for predecessor in _predecessors:
                predecessors.extend(self.get_all_predecessors(self.get_vertex(predecessor), recursive=recursive))
        else:
            predecessors.extend([self.get_vertex(predecessor) for predecessor in _predecessors])
        return predecessors
    
    def is_vertex_runnable(self, vertex_id: str) -> bool:
        """Returns whether a vertex is runnable.
        
        A vertex is runnable if it is active, not currently being run,
        in the vertices_to_run set, and all its predecessors have been fulfilled.
        
        Args:
            vertex_id: Vertex ID to check
            
        Returns:
            True if vertex is runnable
        """
        vertex = self.get_vertex(vertex_id)
        if not vertex:
            return False
        is_active = vertex.is_active()
        is_loop = getattr(vertex, 'is_loop', False)
        return self.run_manager.is_vertex_runnable(vertex_id, is_active=is_active, is_loop=is_loop)
    
    def find_next_runnable_vertices(self, vertex_successors_ids: list[str]) -> list[str]:
        """Determines the next set of runnable vertices from a list of successor vertex IDs.
        
        For each successor, if it is not runnable, recursively finds its runnable
        predecessors; otherwise, includes the successor itself.
        
        Args:
            vertex_successors_ids: List of successor vertex IDs
            
        Returns:
            Sorted list of runnable vertex IDs
        """
        next_runnable_vertices = set()
        for v_id in sorted(vertex_successors_ids):
            if not self.is_vertex_runnable(v_id):
                next_runnable_vertices.update(self.find_runnable_predecessors_for_successor(v_id))
            else:
                next_runnable_vertices.add(v_id)
        return sorted(next_runnable_vertices)
    
    def find_runnable_predecessors_for_successor(self, vertex_id: str) -> list[str]:
        """Find runnable predecessors for a successor vertex.
        
        Args:
            vertex_id: Vertex ID to find predecessors for
            
        Returns:
            List of runnable predecessor IDs
        """
        runnable_vertices = []
        visited = set()

        def find_runnable_predecessors(predecessor_id: str) -> None:
            if predecessor_id in visited:
                return
            visited.add(predecessor_id)
            predecessor_vertex = self.get_vertex(predecessor_id)
            if predecessor_vertex:
                is_active = predecessor_vertex.is_active()
                is_loop = getattr(predecessor_vertex, 'is_loop', False)
                if self.run_manager.is_vertex_runnable(predecessor_id, is_active=is_active, is_loop=is_loop):
                    runnable_vertices.append(predecessor_id)
                else:
                    for pred_pred_id in self.run_manager.run_predecessors.get(predecessor_id, []):
                        find_runnable_predecessors(pred_pred_id)

        for predecessor_id in self.run_manager.run_predecessors.get(vertex_id, []):
            find_runnable_predecessors(predecessor_id)
        return runnable_vertices
    
    def _build_parent_child_map(self) -> None:
        """Build the parent-child map from edges for branch marking."""
        self.parent_child_map = {}
        for vertex in self.vertices:
            self.parent_child_map[vertex.id] = list(self.successor_map.get(vertex.id, []))
    
    # ==========================================================================
    # End of branch marking methods
    # ==========================================================================

    def remove_vertex(self, vertex_id: str) -> None:
        """Remove a vertex from the graph.
        
        Args:
            vertex_id: ID of vertex to remove
        """
        # Remove from vertex list
        self.vertices = [v for v in self.vertices if v.id != vertex_id]
        
        # Remove from vertex map
        if vertex_id in self.vertex_map:
            del self.vertex_map[vertex_id]
        
        # Remove associated edges
        self.edges = [e for e in self.edges if e.get("source") != vertex_id and e.get("target") != vertex_id]
    
    def _update_edges_from_vertex(self, vertex: LangGraphVertex) -> None:
        """Update edges associated with a vertex.
        
        Args:
            vertex: Vertex whose edges to update
        """
        # Remove old edges for this vertex
        self.edges = [e for e in self.edges if e.get("source") != vertex.id and e.get("target") != vertex.id]
        
        # Add new edges from vertex's edge data
        # (This would need vertex to track its edges, which it doesn't currently)
        # For now, edges are managed at the graph level via raw_graph_data
    
    def __deepcopy__(self, memo):
        """Deep copy the adapter."""
        if id(self) in memo:
            return memo[id(self)]
        
        new_adapter = type(self)(
            agent_id=copy.deepcopy(self.agent_id, memo),
            agent_name=copy.deepcopy(self.agent_name, memo),
            user_id=copy.deepcopy(self.user_id, memo),
        )
        
        new_adapter.add_nodes_and_edges(
            copy.deepcopy(self.raw_graph_data["nodes"], memo),
            copy.deepcopy(self.raw_graph_data["edges"], memo),
        )
        
        memo[id(self)] = new_adapter
        return new_adapter
