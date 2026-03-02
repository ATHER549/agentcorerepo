
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentcore.graph_langgraph.vertex_wrapper import LangGraphVertex


class LangGraphEdge:
    """Lightweight edge wrapper for LangGraph execution.
    
    """
    
    def __init__(self, source: LangGraphVertex, target: LangGraphVertex, edge_data: dict[str, Any]) -> None:
        """Initialize edge from edge data.
        
        Args:
            source: Source vertex
            target: Target vertex
            edge_data: Raw edge data from JSON
        """
        self.source_id: str = source.id if source else ""
        self.target_id: str = target.id if target else ""
        self.source = source
        self.target = target
        self._data = edge_data.copy()
        
        # Extract handle information
        self.target_param: str | None = None
        self.source_handle: dict[str, Any] = {}
        self.target_handle: dict[str, Any] = {}
        
        if data := edge_data.get("data", {}):
            self.source_handle = data.get("sourceHandle", {})
            self.target_handle = data.get("targetHandle", {})
            
            # Extract target parameter name
            if isinstance(self.target_handle, dict):
                self.target_param = self.target_handle.get("fieldName")
        
        self.is_cycle = False
        self.valid_handles = True
    
    def __repr__(self) -> str:
        """String representation."""
        return f"LangGraphEdge({self.source_id} -> {self.target_id}, param={self.target_param})"
