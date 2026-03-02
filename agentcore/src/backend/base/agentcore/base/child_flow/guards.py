# TARGET PATH: src/backend/base/agentcore/base/child_flow/guards.py
"""Guards for preventing circular and deeply nested child flow calls.

This module provides mechanisms to detect and prevent:
- Circular flow calls (Flow A -> Flow B -> Flow A)
- Excessively deep call chains
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Generator


class CircularFlowCallError(Exception):
    """Raised when a circular flow call is detected."""

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
    "child_flow_call_stack", default=[]
)


class ChildFlowCallGuard:
    """Prevents circular and deeply nested child flow calls.

    This guard maintains a call stack using context variables, which properly
    propagate across async task boundaries. It detects:
    - Circular calls: When a flow that's already in the call stack is called again
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

    def is_in_call_stack(self, flow_id: str) -> bool:
        """Check if a flow is already in the call stack."""
        return flow_id in _call_stack.get()

    def enter_child_flow(self, flow_id: str) -> None:
        """Called when entering a child flow."""
        current_stack = _call_stack.get()

        # Check for circular call
        if flow_id in current_stack:
            circular_index = current_stack.index(flow_id)
            circular_path = current_stack[circular_index:] + [flow_id]
            chain_str = " -> ".join(circular_path)

            raise CircularFlowCallError(
                f"Circular flow call detected: {chain_str}",
                call_chain=current_stack + [flow_id],
            )

        # Check for max depth
        if len(current_stack) >= self.max_depth:
            raise MaxCallDepthError(
                f"Maximum call depth ({self.max_depth}) exceeded. "
                f"Current call chain: {' -> '.join(current_stack)}",
                depth=len(current_stack),
            )

        # Add to call stack
        new_stack = current_stack + [flow_id]
        _call_stack.set(new_stack)

    def exit_child_flow(self) -> None:
        """Called when exiting a child flow."""
        current_stack = _call_stack.get()
        if current_stack:
            new_stack = current_stack[:-1]
            _call_stack.set(new_stack)

    @contextmanager
    def guard(self, flow_id: str) -> Generator[None, None, None]:
        """Context manager for safe child flow execution."""
        self.enter_child_flow(flow_id)
        try:
            yield
        finally:
            self.exit_child_flow()

    def reset(self) -> None:
        """Reset the call stack."""
        _call_stack.set([])


# Global instance for convenience
_default_guard = ChildFlowCallGuard()


def get_default_guard() -> ChildFlowCallGuard:
    """Get the default global guard instance."""
    return _default_guard
