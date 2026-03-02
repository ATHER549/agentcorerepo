# TARGET PATH: src/backend/base/agentcore/base/a2a/protocol.py
"""Google A2A (Agent-to-Agent) Protocol Implementation.

This module implements the Google A2A protocol for agent-to-agent communication.
The protocol enables agents to discover, communicate, and delegate tasks to each other.

Reference: https://google.github.io/a2a-protocol/
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable
from uuid import uuid4


class MessageType(Enum):
    """Types of messages in A2A communication."""

    TASK_REQUEST = "task_request"
    TASK_RESPONSE = "task_response"
    TASK_UPDATE = "task_update"
    ERROR = "error"
    ACKNOWLEDGMENT = "acknowledgment"
    # Child flow message types for cross-flow communication
    CHILD_FLOW_INVOKE = "child_flow_invoke"
    CHILD_FLOW_RESULT = "child_flow_result"


class TaskStatus(Enum):
    """Status of an A2A task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RoutingError(Exception):
    """Raised when routing fails in dynamic mode."""

    pass


@dataclass
class RoutingDecision:
    """Parsed routing decision from agent response.

    In dynamic routing mode, agents include routing directives in their responses
    to indicate which agent should handle the task next, or that the task is complete.
    """

    next_agent: str | None  # Agent name to route to, None means final response
    content: str  # The actual response content (without routing directive)
    is_final: bool  # True if this is the final response


@dataclass
class A2AAgentCard:
    """Agent Card following Google A2A specification.

    An Agent Card describes an agent's capabilities, identity, and how to communicate with it.
    This is the primary mechanism for agent discovery and capability advertisement.
    """

    name: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    supported_content_types: list[str] = field(
        default_factory=lambda: ["text/plain", "application/json"]
    )
    version: str = "1.0"
    endpoint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert agent card to dictionary format."""
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "supported_content_types": self.supported_content_types,
            "version": self.version,
            "endpoint": self.endpoint,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> A2AAgentCard:
        """Create agent card from dictionary."""
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            capabilities=data.get("capabilities", []),
            supported_content_types=data.get(
                "supported_content_types", ["text/plain", "application/json"]
            ),
            version=data.get("version", "1.0"),
            endpoint=data.get("endpoint"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class A2ATask:
    """Task definition for A2A communication.

    A task represents a unit of work that can be delegated between agents.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    input_data: str = ""
    expected_output: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary format."""
        return {
            "id": self.id,
            "name": self.name,
            "input_data": self.input_data,
            "expected_output": self.expected_output,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": self.metadata,
        }


@dataclass
class A2AMessage:
    """Message format for A2A communication.

    Messages are the primary unit of communication between agents.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    task_id: str = ""
    sender_id: str = ""
    receiver_id: str = ""
    content: str = ""
    message_type: MessageType = MessageType.TASK_REQUEST
    timestamp: datetime = field(default_factory=datetime.now)
    parent_message_id: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert message to dictionary format."""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "content": self.content,
            "message_type": self.message_type.value,
            "timestamp": self.timestamp.isoformat(),
            "parent_message_id": self.parent_message_id,
            "artifacts": self.artifacts,
        }


class A2AProtocol:
    """Protocol handler for Agent-to-Agent communication.

    This class manages the communication between agents following the Google A2A protocol.
    It handles agent registration, message routing, and task execution.
    """

    def __init__(self):
        self._agents: dict[str, A2AAgentCard] = {}
        self._message_handlers: dict[str, Callable] = {}
        self._tasks: dict[str, A2ATask] = {}
        self._message_history: list[A2AMessage] = []
        self._message_queue: asyncio.Queue = asyncio.Queue()

    def register_agent(
        self,
        agent_id: str,
        name: str,
        description: str,
        capabilities: list[str] | None = None,
        handler: Callable | None = None,
    ) -> A2AAgentCard:
        """Register an agent with the protocol."""
        card = A2AAgentCard(
            name=name,
            description=description,
            capabilities=capabilities or [],
        )
        self._agents[agent_id] = card

        if handler:
            self._message_handlers[agent_id] = handler

        return card

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the protocol."""
        self._agents.pop(agent_id, None)
        self._message_handlers.pop(agent_id, None)

    def get_agent_card(self, agent_id: str) -> A2AAgentCard | None:
        """Get the agent card for a registered agent."""
        return self._agents.get(agent_id)

    def list_agents(self) -> list[tuple[str, A2AAgentCard]]:
        """List all registered agents."""
        return list(self._agents.items())

    async def send_task(
        self,
        sender_id: str,
        receiver_id: str,
        task_input: str,
        task_name: str = "task",
        metadata: dict[str, Any] | None = None,
    ) -> A2ATask:
        """Send a task from one agent to another."""
        task = A2ATask(
            name=task_name,
            input_data=task_input,
            metadata=metadata or {},
        )
        self._tasks[task.id] = task

        message = A2AMessage(
            task_id=task.id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            content=task_input,
            message_type=MessageType.TASK_REQUEST,
        )
        self._message_history.append(message)

        await self._message_queue.put(message)

        return task

    async def process_task(
        self,
        task_id: str,
        handler: Callable[[str], str] | Callable[[str], Any],
    ) -> str:
        """Process a task using the provided handler."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        task.status = TaskStatus.RUNNING

        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(task.input_data)
            else:
                result = handler(task.input_data)

            task.result = str(result)
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()

            return task.result

        except Exception as e:
            task.error = str(e)
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now()
            raise

    async def send_response(
        self,
        task_id: str,
        sender_id: str,
        receiver_id: str,
        response_content: str,
        artifacts: dict[str, Any] | None = None,
    ) -> A2AMessage:
        """Send a response message for a task."""
        message = A2AMessage(
            task_id=task_id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            content=response_content,
            message_type=MessageType.TASK_RESPONSE,
            artifacts=artifacts or {},
        )
        self._message_history.append(message)

        task = self._tasks.get(task_id)
        if task:
            task.result = response_content
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()

        return message

    def get_task_status(self, task_id: str) -> TaskStatus | None:
        """Get the current status of a task."""
        task = self._tasks.get(task_id)
        return task.status if task else None

    def get_task(self, task_id: str) -> A2ATask | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def get_message_history(
        self,
        task_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[A2AMessage]:
        """Get message history, optionally filtered by task or agent."""
        messages = self._message_history

        if task_id:
            messages = [m for m in messages if m.task_id == task_id]

        if agent_id:
            messages = [
                m for m in messages if m.sender_id == agent_id or m.receiver_id == agent_id
            ]

        return sorted(messages, key=lambda m: m.timestamp)

    def _match_agent(self, target: str, available_agents: list[str]) -> str | None:
        """Match target text to an available agent name (exact → startswith → contains)."""
        target_lower = target.lower()

        # Exact match
        for agent in available_agents:
            if agent.lower() == target_lower:
                return agent

        # Startswith: agent name is a prefix of captured text (longest first)
        for agent in sorted(available_agents, key=len, reverse=True):
            if target_lower.startswith(agent.lower()):
                return agent

        # Substring: agent name appears anywhere in captured text (longest first)
        for agent in sorted(available_agents, key=len, reverse=True):
            if agent.lower() in target_lower:
                return agent

        return None

    def parse_routing_response(
        self,
        response: str,
        available_agents: list[str],
    ) -> RoutingDecision:
        """Parse agent response to extract routing decision.

        Strategy: strip <think> TAGS (not blocks) so all content is preserved
        for both directive search and content passing to next agent.
        """
        response = response.strip()

        # Remove <think>/<\/think> tags but KEEP content inside them.
        # This ensures: (a) directives inside think blocks are found,
        # (b) actual work content is never lost between agents.
        clean = re.sub(r"</?think>", "", response).strip()

        # --- FINAL_RESPONSE check (first priority) ---
        final_match = re.search(r"FINAL_RESPONSE:?\s*(.*)", clean, re.DOTALL | re.IGNORECASE)
        if final_match:
            # Content = everything before the directive, or everything after it
            content_before = re.sub(
                r"\s*FINAL_RESPONSE:?.*$", "", clean, flags=re.DOTALL | re.IGNORECASE
            ).strip()
            content_after = final_match.group(1).strip()
            content = content_before or content_after or "Task completed."
            return RoutingDecision(next_agent=None, content=content, is_final=True)

        # --- ROUTE_TO check ---
        route_match = re.search(r"ROUTE_TO:\s*([^\n]+)", clean, re.IGNORECASE)
        if route_match:
            target_agent = route_match.group(1).strip()
            content = re.sub(
                r"\s*ROUTE_TO:\s*[^\n]+\n?", "", clean, flags=re.IGNORECASE
            ).strip()

            # Handle LLM confusion: "ROUTE_TO: FINAL_RESPONSE" → treat as final
            if target_agent.upper().startswith("FINAL_RESPONSE"):
                return RoutingDecision(next_agent=None, content=content, is_final=True)

            matched_agent = self._match_agent(target_agent, available_agents)

            if matched_agent:
                return RoutingDecision(next_agent=matched_agent, content=content, is_final=False)
            return RoutingDecision(
                next_agent=None,
                content=f"[ROUTING_ERROR: Unknown agent '{target_agent}'. "
                        f"Available: {', '.join(available_agents)}]\n\n{content}",
                is_final=True,
            )

        # No directive found — default to final response
        return RoutingDecision(next_agent=None, content=clean, is_final=True)

    async def run_dynamic(
        self,
        agent_configs: list[dict[str, Any]],
        initial_input: str,
        agent_handlers: dict[str, Callable],
        max_iterations: int = 10,
        starting_agent: str | None = None,
    ) -> tuple[str, list[A2AMessage]]:
        """Run agents with dynamic routing based on LLM decisions."""
        # Build lookup maps
        agent_id_to_name: dict[str, str] = {}
        agent_name_to_id: dict[str, str] = {}
        available_agent_names: list[str] = []

        for config in agent_configs:
            agent_id = config.get("id", "")
            agent_name = config.get("name", "")
            agent_prompt = config.get("prompt", "")

            agent_id_to_name[agent_id] = agent_name
            agent_name_to_id[agent_name.lower()] = agent_id
            available_agent_names.append(agent_name)

            self.register_agent(
                agent_id=agent_id,
                name=agent_name,
                description=agent_prompt,
                capabilities=["text-processing", "task-completion", "dynamic-routing"],
            )

        # Determine starting agent
        if starting_agent:
            current_agent_id = starting_agent
        else:
            current_agent_id = agent_configs[0].get("id", "agent-1")

        current_input = initial_input
        original_task = initial_input
        iteration_count = 0
        agent_visit_counts: dict[str, int] = {}
        final_result = ""

        task = await self.send_task(
            sender_id="coordinator",
            receiver_id=current_agent_id,
            task_input=current_input,
            task_name=f"Dynamic task for {agent_id_to_name.get(current_agent_id, current_agent_id)}",
        )

        while iteration_count < max_iterations:
            iteration_count += 1
            agent_visit_counts[current_agent_id] = agent_visit_counts.get(current_agent_id, 0) + 1

            handler = agent_handlers.get(current_agent_id)
            if not handler:
                final_result = f"[ERROR: No handler for agent {current_agent_id}]\n{current_input}"
                break

            result = await self.process_task(task.id, handler)
            routing = self.parse_routing_response(result, available_agent_names)

            if routing.is_final:
                final_result = routing.content
                await self.send_response(
                    task_id=task.id,
                    sender_id=current_agent_id,
                    receiver_id="output",
                    response_content=routing.content,
                )
                break

            next_agent_name = routing.next_agent
            next_agent_id = agent_name_to_id.get(next_agent_name.lower()) if next_agent_name else None

            if not next_agent_id:
                final_result = f"[ROUTING_ERROR: Could not find agent '{next_agent_name}']\n{routing.content}"
                await self.send_response(
                    task_id=task.id,
                    sender_id=current_agent_id,
                    receiver_id="output",
                    response_content=final_result,
                )
                break

            if routing.content.strip():
                next_input = (
                    f"Original Task: {original_task}\n\n"
                    f"Content from previous agent:\n{routing.content}"
                )
            else:
                next_input = original_task

            await self.send_response(
                task_id=task.id,
                sender_id=current_agent_id,
                receiver_id=next_agent_id,
                response_content=routing.content if routing.content.strip() else current_input,
            )

            task = await self.send_task(
                sender_id=current_agent_id,
                receiver_id=next_agent_id,
                task_input=next_input,
                task_name=f"Routed task for {next_agent_name}",
                metadata={"routing_iteration": iteration_count, "original_task": original_task},
            )

            current_agent_id = next_agent_id
            current_input = next_input

        else:
            final_result = f"[MAX_ITERATIONS_REACHED: {max_iterations}]\n\nAgent visit counts: {agent_visit_counts}\n\nLast response:\n{current_input}"
            await self.send_response(
                task_id=task.id,
                sender_id=current_agent_id,
                receiver_id="output",
                response_content=final_result,
            )

        return final_result, self._message_history
