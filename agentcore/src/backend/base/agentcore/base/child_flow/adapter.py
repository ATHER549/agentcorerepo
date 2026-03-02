# TARGET PATH: src/backend/base/agentcore/base/child_flow/adapter.py
"""Child Flow Adapter for executing flows as child flows with A2A protocol.

This module provides an adapter that wraps an agent/flow to be executed as a child flow,
using the A2A protocol for communication and logging.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from loguru import logger

from agentcore.base.a2a.protocol import (
    A2AAgentCard,
    A2AMessage,
    A2AProtocol,
    A2ATask,
    MessageType,
    TaskStatus,
)
from agentcore.base.child_flow.guards import ChildFlowCallGuard, get_default_guard
from agentcore.base.child_flow.registry import ChildFlowRegistry, FlowInfo
from agentcore.helpers.agent import load_agent, run_agent

if TYPE_CHECKING:
    from agentcore.graph_langgraph import RunOutputs


@dataclass
class ParentFlowContext:
    """Context passed from parent to child flow."""

    parent_flow_id: str
    parent_flow_name: str
    session_id: str | None = None
    call_depth: int = 0
    a2a_task_id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChildFlowResult:
    """Result returned from child flow to parent."""

    output: str
    status: str  # "success" or "error"
    a2a_messages: list[A2AMessage] = field(default_factory=list)
    execution_time_ms: float = 0.0
    error: str | None = None
    raw_outputs: list[Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "output": self.output,
            "status": self.status,
            "a2a_messages": [msg.to_dict() for msg in self.a2a_messages],
            "execution_time_ms": self.execution_time_ms,
            "error": self.error,
        }


class ChildFlowAdapter:
    """Adapts an agent/flow to be called as a child flow with A2A protocol."""

    def __init__(
        self,
        flow_info: FlowInfo,
        user_id: str,
        guard: ChildFlowCallGuard | None = None,
    ):
        self.flow_info = flow_info
        self.flow_id = flow_info.id
        self.flow_name = flow_info.name
        self.user_id = user_id
        self.guard = guard or get_default_guard()
        self._a2a_protocol = A2AProtocol()
        self._agent_card = self._build_agent_card()

    @classmethod
    async def from_flow_name(
        cls,
        flow_name: str,
        user_id: str,
        guard: ChildFlowCallGuard | None = None,
    ) -> ChildFlowAdapter:
        """Create an adapter from a flow name."""
        flow_info = await ChildFlowRegistry.get_flow_by_name(flow_name, user_id)
        if not flow_info:
            msg = f"Agent/Flow '{flow_name}' not found"
            raise ValueError(msg)
        return cls(flow_info, user_id, guard)

    @classmethod
    async def from_flow_id(
        cls,
        flow_id: str,
        user_id: str,
        guard: ChildFlowCallGuard | None = None,
    ) -> ChildFlowAdapter:
        """Create an adapter from a flow ID."""
        flow_info = await ChildFlowRegistry.get_flow_by_id(flow_id, user_id)
        if not flow_info:
            msg = f"Agent/Flow with ID '{flow_id}' not found"
            raise ValueError(msg)
        return cls(flow_info, user_id, guard)

    def _build_agent_card(self) -> A2AAgentCard:
        """Build an A2A Agent Card for this flow."""
        return A2AAgentCard(
            name=self.flow_name,
            description=self.flow_info.description or f"Child flow: {self.flow_name}",
            capabilities=["flow-execution", "child-flow"],
            metadata={
                "agent_id": self.flow_id,
            },
        )

    @property
    def agent_card(self) -> A2AAgentCard:
        """Get the A2A Agent Card for this flow."""
        return self._agent_card

    async def execute(
        self,
        input_value: str,
        parent_context: ParentFlowContext,
        session_id: str | None = None,
        tweaks: dict | None = None,
    ) -> ChildFlowResult:
        """Execute this flow as a child flow."""
        start_time = datetime.now()
        a2a_messages: list[A2AMessage] = []

        effective_session_id = session_id or parent_context.session_id or str(uuid4())

        # Create A2A task
        task = A2ATask(
            id=parent_context.a2a_task_id,
            name=f"Child flow execution: {self.flow_name}",
            input_data=input_value,
            metadata={
                "parent_flow_id": parent_context.parent_flow_id,
                "parent_flow_name": parent_context.parent_flow_name,
                "call_depth": parent_context.call_depth,
            },
        )

        # Log child flow invoke message
        request_message = A2AMessage(
            task_id=task.id,
            sender_id=parent_context.parent_flow_id,
            receiver_id=self.flow_id,
            content=input_value,
            message_type=MessageType.CHILD_FLOW_INVOKE,
            artifacts={
                "parent_flow_name": parent_context.parent_flow_name,
                "child_flow_name": self.flow_name,
                "call_depth": parent_context.call_depth,
            },
        )
        a2a_messages.append(request_message)

        try:
            with self.guard.guard(self.flow_id):
                task.status = TaskStatus.RUNNING

                # Load the child flow graph and pre-build predecessor vertices
                # so that output vertices can resolve their dependencies.
                # Without this, arun() only builds output vertices while
                # _resolve_params() skips unbuilt predecessors, causing
                # AttributeError in ChatOutput.get_properties_from_source_component().
                graph = await load_agent(
                    self.user_id, agent_name=self.flow_name, tweaks=tweaks,
                )
                await self._prebuild_dependencies(graph, input_value)

                run_outputs = await run_agent(
                    inputs={"input_value": input_value},
                    graph=graph,
                    user_id=self.user_id,
                    session_id=effective_session_id,
                )

                output_text = self._extract_output(run_outputs)

                # Detect when graph execution failed (all outputs were None)
                if not output_text:
                    error_msg = (
                        f"Child flow '{self.flow_name}' executed but produced no output. "
                        f"The child flow's graph may have encountered an error during execution."
                    )
                    logger.error(error_msg)

                    task.status = TaskStatus.FAILED
                    task.error = error_msg
                    task.completed_at = datetime.now()

                    error_response = A2AMessage(
                        task_id=task.id,
                        sender_id=self.flow_id,
                        receiver_id=parent_context.parent_flow_id,
                        content=error_msg,
                        message_type=MessageType.ERROR,
                    )
                    a2a_messages.append(error_response)

                    end_time = datetime.now()
                    execution_time_ms = (end_time - start_time).total_seconds() * 1000

                    return ChildFlowResult(
                        output="",
                        status="error",
                        a2a_messages=a2a_messages,
                        execution_time_ms=execution_time_ms,
                        error=error_msg,
                        raw_outputs=run_outputs,
                    )

                task.status = TaskStatus.COMPLETED
                task.result = output_text
                task.completed_at = datetime.now()

                response_message = A2AMessage(
                    task_id=task.id,
                    sender_id=self.flow_id,
                    receiver_id=parent_context.parent_flow_id,
                    content=output_text,
                    message_type=MessageType.CHILD_FLOW_RESULT,
                    artifacts={
                        "parent_flow_name": parent_context.parent_flow_name,
                        "child_flow_name": self.flow_name,
                        "execution_status": "success",
                    },
                )
                a2a_messages.append(response_message)

                end_time = datetime.now()
                execution_time_ms = (end_time - start_time).total_seconds() * 1000

                return ChildFlowResult(
                    output=output_text,
                    status="success",
                    a2a_messages=a2a_messages,
                    execution_time_ms=execution_time_ms,
                    raw_outputs=run_outputs,
                )

        except Exception as e:
            logger.exception(f"Error executing child flow '{self.flow_name}': {e}")

            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()

            error_message = A2AMessage(
                task_id=task.id,
                sender_id=self.flow_id,
                receiver_id=parent_context.parent_flow_id,
                content=str(e),
                message_type=MessageType.ERROR,
            )
            a2a_messages.append(error_message)

            end_time = datetime.now()
            execution_time_ms = (end_time - start_time).total_seconds() * 1000

            return ChildFlowResult(
                output="",
                status="error",
                a2a_messages=a2a_messages,
                execution_time_ms=execution_time_ms,
                error=str(e),
            )

    async def execute_with_a2a(
        self,
        task: A2ATask,
        parent_context: ParentFlowContext,
        session_id: str | None = None,
        tweaks: dict | None = None,
    ) -> ChildFlowResult:
        """Execute with an existing A2A task."""
        return await self.execute(
            input_value=task.input_data,
            parent_context=parent_context,
            session_id=session_id,
            tweaks=tweaks,
        )

    async def _prebuild_dependencies(self, graph, input_value: str) -> None:
        """Pre-build non-output vertices in topological order.

        When a child flow graph is executed via run_agent() -> arun(), only
        output vertices are built directly.  _resolve_params() skips
        predecessors that have not been built yet, so components like
        ChatOutput crash when they access source-component properties
        (e.g. display_name) on an unbuilt predecessor.

        This method builds all non-output vertices first so that when
        arun() builds the output vertices, all dependencies are resolved.
        """
        from agentcore.schema.schema import INPUT_FIELD_NAME
        from agentcore.services.deps import get_chat_service, get_settings_service

        chat_service = get_chat_service()
        fallback_to_env_vars = get_settings_service().settings.fallback_to_env_var
        inputs_dict = {INPUT_FIELD_NAME: input_value}

        sorted_ids = self._topological_sort(graph)

        for vertex_id in sorted_ids:
            vertex = graph.get_vertex(vertex_id)
            if not vertex or vertex.is_output:
                continue
            try:
                await graph.build_vertex(
                    vertex_id=vertex_id,
                    user_id=self.user_id,
                    inputs_dict=inputs_dict,
                    get_cache=chat_service.get_cache,
                    set_cache=chat_service.set_cache,
                    fallback_to_env_vars=fallback_to_env_vars,
                )
            except Exception as e:
                logger.warning(f"Error pre-building vertex {vertex_id}: {e}")

    @staticmethod
    def _topological_sort(graph) -> list[str]:
        """Sort graph vertices in topological order (Kahn's algorithm)."""
        in_degree: dict[str, int] = {}
        successors: dict[str, list[str]] = {}
        for vertex in graph.vertices:
            in_degree[vertex.id] = 0
            successors[vertex.id] = []

        for edge in graph.edges:
            source = edge.get("source")
            target = edge.get("target")
            if source in in_degree and target in in_degree:
                in_degree[target] += 1
                successors[source].append(target)

        queue = [vid for vid, deg in in_degree.items() if deg == 0]
        result: list[str] = []
        while queue:
            vid = queue.pop(0)
            result.append(vid)
            for succ in successors.get(vid, []):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        # Append any remaining vertices (cycles)
        for vid in in_degree:
            if vid not in result:
                result.append(vid)

        return result

    def _extract_output(self, run_outputs: list[RunOutputs]) -> str:
        """Extract text output from run_outputs."""
        if not run_outputs:
            return ""

        try:
            first_output = run_outputs[0]

            if hasattr(first_output, "outputs") and first_output.outputs:
                # All outputs None means graph vertex builds failed
                if all(output is None for output in first_output.outputs):
                    logger.warning(
                        f"Child flow graph execution produced all-null outputs "
                        f"({len(first_output.outputs)} output(s) failed). "
                        f"Inputs were: {first_output.inputs}"
                    )
                    return ""

                for output in first_output.outputs:
                    if output and hasattr(output, "results"):
                        for result_key, result_value in output.results.items():
                            if hasattr(result_value, "data"):
                                data = result_value.data
                                if isinstance(data, dict) and "text" in data:
                                    return data["text"]
                                if isinstance(data, str):
                                    return data
                            if hasattr(result_value, "text"):
                                return result_value.text
                            if isinstance(result_value, str):
                                return result_value

            return str(first_output)

        except Exception as e:
            logger.warning(f"Error extracting output: {e}")
            return str(run_outputs)
