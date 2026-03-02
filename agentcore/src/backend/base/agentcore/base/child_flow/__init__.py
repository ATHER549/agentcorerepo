# TARGET PATH: src/backend/base/agentcore/base/child_flow/__init__.py
"""Child Flow module for cross-flow communication.

This module enables flows to call other flows as "child flows" with
A2A protocol-based communication.
"""

from agentcore.base.child_flow.adapter import ChildFlowAdapter
from agentcore.base.child_flow.guards import (
    ChildFlowCallGuard,
    CircularFlowCallError,
    MaxCallDepthError,
)
from agentcore.base.child_flow.registry import ChildFlowRegistry, FlowInfo

__all__ = [
    "ChildFlowAdapter",
    "ChildFlowCallGuard",
    "ChildFlowRegistry",
    "CircularFlowCallError",
    "FlowInfo",
    "MaxCallDepthError",
]
