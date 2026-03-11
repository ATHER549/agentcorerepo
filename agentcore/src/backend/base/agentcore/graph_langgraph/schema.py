
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator
from typing_extensions import NotRequired, TypedDict

from agentcore.schema.schema import OutputValue, StreamURL
from agentcore.serialization.serialization import serialize
from agentcore.utils.schemas import ChatOutputResponse, ContainsEnumMeta

if TYPE_CHECKING:
    from agentcore.graph_langgraph.vertex_wrapper import LangGraphVertex
    from agentcore.schema.log import LoggableType


class NodeTypeEnum(str, Enum):
    NoteNode = "noteNode"
    GenericNode = "genericNode"


class Position(TypedDict):
    x: float
    y: float


class NodeData(TypedDict):
    id: str
    data: dict
    dragging: NotRequired[bool]
    height: NotRequired[int]
    width: NotRequired[int]
    position: NotRequired[Position]
    positionAbsolute: NotRequired[Position]
    selected: NotRequired[bool]
    parent_node_id: NotRequired[str]
    type: NotRequired[NodeTypeEnum]

class SourceHandleDict(TypedDict, total=False):
    baseClasses: list[str]
    dataType: str
    id: str
    name: str | None
    output_types: list[str]


class TargetHandleDict(TypedDict):
    fieldName: str
    id: str
    inputTypes: list[str] | None
    type: str


class LoopTargetHandleDict(TypedDict):
    dataType: str
    id: str
    name: str
    output_types: list[str]


class EdgeDataDetails(TypedDict):
    sourceHandle: SourceHandleDict
    targetHandle: TargetHandleDict | LoopTargetHandleDict


class EdgeData(TypedDict, total=False):
    source: str
    target: str
    data: EdgeDataDetails


class ResultPair(BaseModel):
    result: Any
    extra: Any


class Payload(BaseModel):
    result_pairs: list[ResultPair] = []

    def __iter__(self):
        return iter(self.result_pairs)

    def add_result_pair(self, result: Any, extra: Any | None = None) -> None:
        self.result_pairs.append(ResultPair(result=result, extra=extra))

    def get_last_result_pair(self) -> ResultPair:
        return self.result_pairs[-1]

    def format(self, sep: str = "\n") -> str:
        return sep.join(
            [
                f"Result: {result_pair.result}\nExtra: {result_pair.extra}"
                if result_pair.extra is not None
                else f"Result: {result_pair.result}"
                for result_pair in self.result_pairs[:-1]
            ]
        )


class TargetHandle(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    field_name: str = Field(..., alias="fieldName", description="Field name for the target handle.")
    id: str = Field(..., description="Unique identifier for the target handle.")
    input_types: list[str] = Field(
        default_factory=list, alias="inputTypes", description="List of input types for the target handle."
    )
    type: str = Field(None, description="Type of the target handle.")

    @classmethod
    def from_loop_target_handle(cls, target_handle: LoopTargetHandleDict) -> "TargetHandle":
        return cls(
            field_name=target_handle.get("name"),
            id=target_handle.get("id"),
            input_types=target_handle.get("output_types"),
        )


class SourceHandle(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    base_classes: list[str] = Field(
        default_factory=list, alias="baseClasses", description="List of base classes for the source handle."
    )
    data_type: str = Field(..., alias="dataType", description="Data type for the source handle.")
    id: str = Field(..., description="Unique identifier for the source handle.")
    name: str | None = Field(None, description="Name of the source handle.")
    output_types: list[str] = Field(default_factory=list, description="List of output types for the source handle.")

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v, info):
        if info.data.get("data_type") == "GroupNode":
            splits = v.split("_", 1) if v else []
            if len(splits) != 2:
                msg = f"Invalid source handle name {v}"
                raise ValueError(msg)
            v = splits[1]
        return v



class ViewPort(TypedDict):
    x: float
    y: float
    zoom: float


class GraphData(TypedDict):
    nodes: list[NodeData]
    edges: list[EdgeData]
    viewport: NotRequired[ViewPort]


class GraphDump(TypedDict, total=False):
    data: GraphData
    name: str
    description: str


class OutputConfigDict(TypedDict):
    cache: bool


class StartConfigDict(TypedDict):
    output: OutputConfigDict


class LogCallbackFunction(Protocol):
    def __call__(self, event_name: str, log: LoggableType) -> None: ...



class VertexStates(str, Enum):
    """Vertex states for conditional routing - ACTIVE, INACTIVE, or ERROR."""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"


class InterfaceComponentTypes(str, Enum, metaclass=ContainsEnumMeta):
    """Types of interface components."""
    ChatInput = "ChatInput"
    ChatOutput = "ChatOutput"
    TextInput = "TextInput"
    TextOutput = "TextOutput"
    DataOutput = "DataOutput"
    WebhookInput = "Webhook"


# Component type groupings
CHAT_COMPONENTS = [InterfaceComponentTypes.ChatInput, InterfaceComponentTypes.ChatOutput]
RECORDS_COMPONENTS = [InterfaceComponentTypes.DataOutput]
INPUT_COMPONENTS = [
    InterfaceComponentTypes.ChatInput,
    InterfaceComponentTypes.WebhookInput,
    InterfaceComponentTypes.TextInput,
]
OUTPUT_COMPONENTS = [
    InterfaceComponentTypes.ChatOutput,
    InterfaceComponentTypes.DataOutput,
    InterfaceComponentTypes.TextOutput,
]


class ResultData(BaseModel):
    """Result data from a single vertex/component execution."""
    results: Any | None = Field(default_factory=dict)
    artifacts: Any | None = Field(default_factory=dict)
    outputs: dict | None = Field(default_factory=dict)
    logs: dict | None = Field(default_factory=dict)
    messages: list[ChatOutputResponse] | None = Field(default_factory=list)
    timedelta: float | None = None
    duration: str | None = None
    component_display_name: str | None = None
    component_id: str | None = None
    used_frozen_result: bool | None = False

    @field_serializer("results")
    def serialize_results(self, value):
        if isinstance(value, dict):
            return {key: serialize(val) for key, val in value.items()}
        return serialize(value)

    @model_validator(mode="before")
    @classmethod
    def validate_model(cls, values):
        if not values.get("outputs") and values.get("artifacts"):
            # Build the log from the artifacts
            for key in values["artifacts"]:
                message = values["artifacts"][key]
                if message is None:
                    continue
                if "stream_url" in message and "type" in message:
                    stream_url = StreamURL(location=message["stream_url"])
                    values["outputs"].update({key: OutputValue(message=stream_url, type=message["type"])})
                elif "type" in message:
                    values["outputs"].update({key: OutputValue(message=message, type=message["type"])})
        return values


class RunOutputs(BaseModel):
    """Output structure for a graph run - contains inputs and results.

    This is the return type of LangGraphAdapter.arun() method.
    Each run can have multiple outputs (one per output vertex).
    """
    inputs: dict = Field(default_factory=dict)
    outputs: list[ResultData | None] = Field(default_factory=list)
    # Populated when graph is paused by interrupt() (HITL).
    # Contains: {"status": "interrupted", "thread_id": ..., "interrupt_data": {...}}
    metadata: dict = Field(default_factory=dict)


class VertexBuildResult(NamedTuple):
    """Result of building a single vertex."""
    result_dict: dict[str, Any]
    params: str
    valid: bool
    artifacts: dict[str, Any]
    vertex: LangGraphVertex

