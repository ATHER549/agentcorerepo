# TARGET PATH: src/backend/base/agentcore/base/child_agent/adapter.py
"""Child Agent Adapter for executing agents as child agents with A2A protocol.

This module provides an adapter that wraps an agent to be executed as a child agent,
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
from agentcore.base.child_agent.guards import ChildAgentCallGuard, get_default_guard
from agentcore.base.child_agent.registry import ChildAgentRegistry, AgentInfo
from agentcore.helpers.agent import load_agent, run_agent

if TYPE_CHECKING:
    from agentcore.graph_langgraph import RunOutputs


@dataclass
class ParentAgentContext:
    """Context passed from parent to child agent."""

    parent_agent_id: str
    parent_agent_name: str
    session_id: str | None = None
    call_depth: int = 0
    a2a_task_id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChildAgentResult:
    """Result returned from child agent to parent."""

    output: str
    status: str  # "success" or "error"
    a2a_messages: list[A2AMessage] = field(default_factory=list)
    execution_time_ms: float = 0.0
    error: str | None = None
    raw_outputs: list[Any] | None = None
    content_blocks: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "output": self.output,
            "status": self.status,
            "a2a_messages": [msg.to_dict() for msg in self.a2a_messages],
            "execution_time_ms": self.execution_time_ms,
            "error": self.error,
        }


class ChildAgentAdapter:
    """Adapts an agent to be called as a child agent with A2A protocol."""

    def __init__(
        self,
        agent_info: AgentInfo,
        user_id: str,
        guard: ChildAgentCallGuard | None = None,
    ):
        self.agent_info = agent_info
        self.agent_id = agent_info.id
        self.agent_name = agent_info.name
        self.user_id = user_id
        self.guard = guard or get_default_guard()
        self._a2a_protocol = A2AProtocol()
        self._agent_card = self._build_agent_card()

    @classmethod
    async def from_agent_name(
        cls,
        agent_name: str,
        user_id: str,
        guard: ChildAgentCallGuard | None = None,
    ) -> ChildAgentAdapter:
        """Create an adapter from an agent name."""
        agent_info = await ChildAgentRegistry.get_agent_by_name(agent_name, user_id)
        if not agent_info:
            msg = f"Agent '{agent_name}' not found"
            raise ValueError(msg)
        return cls(agent_info, user_id, guard)

    @classmethod
    async def from_agent_id(
        cls,
        agent_id: str,
        user_id: str,
        guard: ChildAgentCallGuard | None = None,
    ) -> ChildAgentAdapter:
        """Create an adapter from an agent ID."""
        agent_info = await ChildAgentRegistry.get_agent_by_id(agent_id, user_id)
        if not agent_info:
            msg = f"Agent with ID '{agent_id}' not found"
            raise ValueError(msg)
        return cls(agent_info, user_id, guard)

    def _build_agent_card(self) -> A2AAgentCard:
        """Build an A2A Agent Card for this agent."""
        return A2AAgentCard(
            name=self.agent_name,
            description=self.agent_info.description or f"Child agent: {self.agent_name}",
            capabilities=["agent-execution", "child-agent"],
            metadata={
                "agent_id": self.agent_id,
            },
        )

    @property
    def agent_card(self) -> A2AAgentCard:
        """Get the A2A Agent Card for this agent."""
        return self._agent_card

    async def execute(
        self,
        input_value: str,
        parent_context: ParentAgentContext,
        session_id: str | None = None,
        tweaks: dict | None = None,
    ) -> ChildAgentResult:
        """Execute this agent as a child agent."""
        start_time = datetime.now()
        a2a_messages: list[A2AMessage] = []

        effective_session_id = session_id or parent_context.session_id or str(uuid4())

        # Create A2A task
        task = A2ATask(
            id=parent_context.a2a_task_id,
            name=f"Child agent execution: {self.agent_name}",
            input_data=input_value,
            metadata={
                "parent_agent_id": parent_context.parent_agent_id,
                "parent_agent_name": parent_context.parent_agent_name,
                "call_depth": parent_context.call_depth,
            },
        )

        # Log child agent invoke message
        request_message = A2AMessage(
            task_id=task.id,
            sender_id=parent_context.parent_agent_id,
            receiver_id=self.agent_id,
            content=input_value,
            message_type=MessageType.CHILD_AGENT_INVOKE,
            artifacts={
                "parent_agent_name": parent_context.parent_agent_name,
                "child_agent_name": self.agent_name,
                "call_depth": parent_context.call_depth,
            },
        )
        a2a_messages.append(request_message)

        try:
            with self.guard.guard(self.agent_id):
                task.status = TaskStatus.RUNNING

                graph = await load_agent(
                    self.user_id, agent_name=self.agent_name, tweaks=tweaks,
                )
                # Set session_id on graph before pre-building so Agent
                # vertices can persist messages (tool call content blocks).
                graph.session_id = effective_session_id
                await self._prebuild_dependencies(graph, input_value)

                run_outputs = await run_agent(
                    inputs={"input_value": input_value},
                    graph=graph,
                    user_id=self.user_id,
                    session_id=effective_session_id,
                )

                output_text, content_blocks = self._extract_output(run_outputs)

                # Detect when graph execution failed (all outputs were None)
                if not output_text:
                    error_msg = (
                        f"Child agent '{self.agent_name}' executed but produced no output. "
                        f"The child agent's graph may have encountered an error during execution."
                    )
                    logger.error(error_msg)

                    task.status = TaskStatus.FAILED
                    task.error = error_msg
                    task.completed_at = datetime.now()

                    error_response = A2AMessage(
                        task_id=task.id,
                        sender_id=self.agent_id,
                        receiver_id=parent_context.parent_agent_id,
                        content=error_msg,
                        message_type=MessageType.ERROR,
                    )
                    a2a_messages.append(error_response)

                    end_time = datetime.now()
                    execution_time_ms = (end_time - start_time).total_seconds() * 1000

                    return ChildAgentResult(
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
                    sender_id=self.agent_id,
                    receiver_id=parent_context.parent_agent_id,
                    content=output_text,
                    message_type=MessageType.CHILD_AGENT_RESULT,
                    artifacts={
                        "parent_agent_name": parent_context.parent_agent_name,
                        "child_agent_name": self.agent_name,
                        "execution_status": "success",
                    },
                )
                a2a_messages.append(response_message)

                end_time = datetime.now()
                execution_time_ms = (end_time - start_time).total_seconds() * 1000

                return ChildAgentResult(
                    output=output_text,
                    status="success",
                    a2a_messages=a2a_messages,
                    execution_time_ms=execution_time_ms,
                    raw_outputs=run_outputs,
                    content_blocks=content_blocks,
                )

        except Exception as e:
            logger.exception(f"Error executing child agent '{self.agent_name}': {e}")

            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()

            error_message = A2AMessage(
                task_id=task.id,
                sender_id=self.agent_id,
                receiver_id=parent_context.parent_agent_id,
                content=str(e),
                message_type=MessageType.ERROR,
            )
            a2a_messages.append(error_message)

            end_time = datetime.now()
            execution_time_ms = (end_time - start_time).total_seconds() * 1000

            return ChildAgentResult(
                output="",
                status="error",
                a2a_messages=a2a_messages,
                execution_time_ms=execution_time_ms,
                error=str(e),
            )

    async def execute_with_a2a(
        self,
        task: A2ATask,
        parent_context: ParentAgentContext,
        session_id: str | None = None,
        tweaks: dict | None = None,
    ) -> ChildAgentResult:
        """Execute with an existing A2A task."""
        return await self.execute(
            input_value=task.input_data,
            parent_context=parent_context,
            session_id=session_id,
            tweaks=tweaks,
        )

    async def _prebuild_dependencies(self, graph, input_value: str) -> None:
        """Pre-build non-output vertices in topological order."""
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

    def _extract_output(self, run_outputs: list[RunOutputs]) -> tuple[str, list[Any]]:
        """Extract text output and content_blocks from run_outputs.

        Returns:
            Tuple of (output_text, content_blocks).
        """
        if not run_outputs:
            return "", []

        try:
            first_output = run_outputs[0]
            content_blocks: list[Any] = []

            if hasattr(first_output, "outputs") and first_output.outputs:
                if all(output is None for output in first_output.outputs):
                    logger.warning(
                        f"Child agent graph execution produced all-null outputs "
                        f"({len(first_output.outputs)} output(s) failed). "
                        f"Inputs were: {first_output.inputs}"
                    )
                    return "", []

                for output in first_output.outputs:
                    if output and hasattr(output, "results"):
                        for result_key, result_value in output.results.items():
                            # Extract content_blocks from Message objects
                            if hasattr(result_value, "content_blocks") and result_value.content_blocks:
                                content_blocks.extend(result_value.content_blocks)
                            # Also check inside .data dict for nested Messages
                            if hasattr(result_value, "data") and isinstance(result_value.data, dict):
                                nested = result_value.data.get("message")
                                if hasattr(nested, "content_blocks") and nested.content_blocks:
                                    content_blocks.extend(nested.content_blocks)

                for output in first_output.outputs:
                    if output and hasattr(output, "results"):
                        for result_key, result_value in output.results.items():
                            if hasattr(result_value, "data"):
                                data = result_value.data
                                if isinstance(data, dict) and "text" in data:
                                    return data["text"], content_blocks
                                if isinstance(data, str):
                                    return data, content_blocks
                            if hasattr(result_value, "text"):
                                return result_value.text, content_blocks
                            if isinstance(result_value, str):
                                return result_value, content_blocks

            return str(first_output), content_blocks

        except Exception as e:
            logger.warning(f"Error extracting output: {e}")
            return str(run_outputs), []
