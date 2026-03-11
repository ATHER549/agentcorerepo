# TARGET PATH: src/backend/base/agentcore/base/child_agent/guards.py
"""Guards for preventing circular and deeply nested child agent calls.

This module provides mechanisms to detect and prevent:
- Circular agent calls (Agent A -> Agent B -> Agent A)
- Excessively deep call chains
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Generator


class CircularAgentCallError(Exception):
    """Raised when a circular agent call is detected."""

    def __init__(self, message: str, call_chain: list[str] | None = None):
        super().__init__(message)
        self.call_chain = call_chain or []


class MaxCallDepthError(Exception):
    """Raised when the maximum call depth is exceeded."""

    def __init__(self, message: str, depth: int = 0):
        super().__init__(message)
        self.depth = depth


# Context variable to track the call stack across async boundaries
_call_stack: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
    "child_agent_call_stack", default=[]
)


class ChildAgentCallGuard:
    """Prevents circular and deeply nested child agent calls.

    This guard maintains a call stack using context variables, which properly
    propagate across async task boundaries. It detects:
    - Circular calls: When an agent that's already in the call stack is called again
    - Deep nesting: When the call depth exceeds the maximum allowed
    """

    DEFAULT_MAX_DEPTH = 10

    def __init__(self, max_depth: int | None = None):
        self.max_depth = max_depth or self.DEFAULT_MAX_DEPTH

    def get_call_stack(self) -> list[str]:
        """Get the current call stack."""
        return list(_call_stack.get())

    def get_call_depth(self) -> int:
        """Get the current call depth."""
        return len(_call_stack.get())

    def is_in_call_stack(self, agent_id: str) -> bool:
        """Check if an agent is already in the call stack."""
        return agent_id in _call_stack.get()

    def enter_child_agent(self, agent_id: str) -> None:
        """Called when entering a child agent."""
        current_stack = _call_stack.get()

        # Check for circular call
        if agent_id in current_stack:
            circular_index = current_stack.index(agent_id)
            circular_path = current_stack[circular_index:] + [agent_id]
            chain_str = " -> ".join(circular_path)

            raise CircularAgentCallError(
                f"Circular agent call detected: {chain_str}",
                call_chain=current_stack + [agent_id],
            )

        # Check for max depth
        if len(current_stack) >= self.max_depth:
            raise MaxCallDepthError(
                f"Maximum call depth ({self.max_depth}) exceeded. "
                f"Current call chain: {' -> '.join(current_stack)}",
                depth=len(current_stack),
            )

        # Add to call stack
        new_stack = current_stack + [agent_id]
        _call_stack.set(new_stack)

    def exit_child_agent(self) -> None:
        """Called when exiting a child agent."""
        current_stack = _call_stack.get()
        if current_stack:
            new_stack = current_stack[:-1]
            _call_stack.set(new_stack)

    @contextmanager
    def guard(self, agent_id: str) -> Generator[None, None, None]:
        """Context manager for safe child agent execution."""
        self.enter_child_agent(agent_id)
        try:
            yield
        finally:
            self.exit_child_agent()

    def reset(self) -> None:
        """Reset the call stack."""
        _call_stack.set([])


# Global instance for convenience
_default_guard = ChildAgentCallGuard()


def get_default_guard() -> ChildAgentCallGuard:
    """Get the default global guard instance."""
    return _default_guard
