# TARGET PATH: src/backend/base/agentcore/base/child_agent/__init__.py
"""Child Agent module for cross-agent communication.

This module enables agents to call other agents as "child agents" with
A2A protocol-based communication.
"""

from agentcore.base.child_agent.adapter import ChildAgentAdapter
from agentcore.base.child_agent.guards import (
    ChildAgentCallGuard,
    CircularAgentCallError,
    MaxCallDepthError,
)
from agentcore.base.child_agent.registry import ChildAgentRegistry, AgentInfo

__all__ = [
    "AgentInfo",
    "ChildAgentAdapter",
    "ChildAgentCallGuard",
    "ChildAgentRegistry",
    "CircularAgentCallError",
    "MaxCallDepthError",
]
