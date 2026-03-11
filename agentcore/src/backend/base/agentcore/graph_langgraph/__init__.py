"""LangGraph-based implementation for AgentCore graph execution."""

from agentcore.graph_langgraph.adapter import LangGraphAdapter
from agentcore.graph_langgraph.edge import LangGraphEdge
from agentcore.graph_langgraph.executor import LangGraphExecutor
from agentcore.graph_langgraph.logging import log_transaction, log_vertex_build
from agentcore.graph_langgraph.param_handler import ParameterHandler
from agentcore.graph_langgraph.runnable_vertices_manager import RunnableVerticesManager
from agentcore.graph_langgraph.schema import (
    CHAT_COMPONENTS,
    INPUT_COMPONENTS,
    OUTPUT_COMPONENTS,
    RECORDS_COMPONENTS,
    EdgeData,
    EdgeDataDetails,
    GraphData,
    GraphDump,
    InterfaceComponentTypes,
    LoopTargetHandleDict,
    NodeData,
    NodeTypeEnum,
    OutputConfigDict,
    Payload,
    Position,
    ResultData,
    ResultPair,
    RunOutputs,
    SourceHandle,
    SourceHandleDict,
    StartConfigDict,
    TargetHandle,
    TargetHandleDict,
    VertexBuildResult,
    VertexStates,
    ViewPort,
)
from agentcore.graph_langgraph.state import AgentCoreState
from agentcore.graph_langgraph.state_model import create_state_model
from agentcore.graph_langgraph.utils import (
    build_adjacency_maps,
    find_start_component_id,
    has_chat_output,
    has_output_vertex,
    layered_topological_sort,
)
from agentcore.graph_langgraph.vertex_wrapper import LangGraphVertex

__all__ = [
    # Main classes
    "LangGraphAdapter",
    "LangGraphExecutor",
    "LangGraphVertex",
    "LangGraphEdge",
    "AgentCoreState",
    "RunnableVerticesManager",
    "InterfaceComponentTypes",
    "VertexStates",
    "ResultData",
    "RunOutputs",
    "VertexBuildResult",
    "GraphDump",
    "GraphData",
    "ViewPort",
    "NodeData",
    "NodeTypeEnum",
    "Position",
    "EdgeData",
    "EdgeDataDetails",
    "SourceHandleDict",
    "TargetHandleDict",
    "LoopTargetHandleDict",
    "SourceHandle",
    "TargetHandle",
    "ResultPair",
    "Payload",
    "OutputConfigDict",
    "StartConfigDict",
    # Component type groupings
    "CHAT_COMPONENTS",
    "RECORDS_COMPONENTS",
    "INPUT_COMPONENTS",
    "OUTPUT_COMPONENTS",
    # Utility functions
    "log_vertex_build",
    "log_transaction",
    "build_adjacency_maps",
    "layered_topological_sort",
    "find_start_component_id",
    "has_chat_output",
    "has_output_vertex",
    "create_state_model",
    "ParameterHandler",
]
