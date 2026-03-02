# TARGET PATH: src/backend/base/agentcore/services/a2a/task_store.py
"""In-memory task store for A2A task management.

This module provides an in-memory storage solution for tracking
A2A task execution status, results, and errors.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from agentcore.base.a2a.protocol import TaskStatus


@dataclass
class A2ATaskRecord:
    """Record of an A2A task execution."""

    id: str = field(default_factory=lambda: str(uuid4()))
    agent_id: str = ""
    user_id: str = ""
    status: TaskStatus = TaskStatus.PENDING
    input_data: str = ""
    result: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # For cancellation support
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Convert task record to dictionary."""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "input_data": self.input_data,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "session_id": self.session_id,
            "metadata": self.metadata,
        }

    def is_cancelled(self) -> bool:
        """Check if the task has been cancelled."""
        return self._cancel_event.is_set()


class A2ATaskStore:
    """In-memory store for A2A tasks with TTL-based cleanup.

    This is a singleton class that stores task records in memory.
    Tasks are automatically cleaned up after the TTL expires.
    """

    _instance: A2ATaskStore | None = None
    _lock: asyncio.Lock | None = None

    def __init__(self, max_tasks: int = 10000, ttl_seconds: int = 3600):
        self._tasks: dict[str, A2ATaskRecord] = {}
        self._max_tasks = max_tasks
        self._ttl_seconds = ttl_seconds

    @classmethod
    def get_instance(cls) -> A2ATaskStore:
        """Get the singleton instance of the task store."""
        if cls._instance is None:
            cls._instance = cls()
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None
        cls._lock = None

    async def create_task(
        self,
        agent_id: str,
        user_id: str,
        input_data: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> A2ATaskRecord:
        """Create a new task record."""
        async with self._get_lock():
            await self._cleanup_if_needed()

            task = A2ATaskRecord(
                agent_id=agent_id,
                user_id=user_id,
                input_data=input_data,
                session_id=session_id,
                metadata=metadata or {},
            )
            self._tasks[task.id] = task
            return task

    async def get_task(self, task_id: str) -> A2ATaskRecord | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    async def update_task(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        result: str | None = None,
        error: str | None = None,
    ) -> A2ATaskRecord | None:
        """Update a task's status and/or result."""
        task = self._tasks.get(task_id)
        if task:
            if status is not None:
                task.status = status
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                task.completed_at = datetime.now()
        return task

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running or pending task."""
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task._cancel_event.set()
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now()
            return True
        return False

    async def list_tasks(
        self,
        agent_id: str | None = None,
        user_id: str | None = None,
        status: TaskStatus | None = None,
        limit: int = 100,
    ) -> list[A2ATaskRecord]:
        """List tasks with optional filtering."""
        results = []
        for task in self._tasks.values():
            if agent_id and task.agent_id != agent_id:
                continue
            if user_id and task.user_id != user_id:
                continue
            if status and task.status != status:
                continue
            results.append(task)
            if len(results) >= limit:
                break
        return results

    def _get_lock(self) -> asyncio.Lock:
        """Get the asyncio lock, creating if necessary."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _cleanup_if_needed(self) -> None:
        """Clean up old tasks if the store is at capacity."""
        if len(self._tasks) >= self._max_tasks:
            now = datetime.now()
            expired = [
                tid
                for tid, t in self._tasks.items()
                if (now - t.created_at).total_seconds() > self._ttl_seconds
            ]
            removal_count = min(len(expired), self._max_tasks // 4)
            for tid in expired[:removal_count]:
                del self._tasks[tid]
