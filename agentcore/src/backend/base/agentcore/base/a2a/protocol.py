# TARGET PATH: src/backend/base/agentcore/base/a2a/protocol.py
"""Google A2A (Agent-to-Agent) Protocol Implementation.

This module implements the Google A2A protocol for agent-to-agent communication.
The protocol enables agents to discover, communicate, and delegate tasks to each other.

Reference: https://google.github.io/a2a-protocol/
"""

from __future__ import annotations

import asyncio
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
    # Child agent message types for cross-agent communication
    CHILD_AGENT_INVOKE = "child_agent_invoke"
    CHILD_AGENT_RESULT = "child_agent_result"


class TaskStatus(Enum):
    """Status of an A2A task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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

