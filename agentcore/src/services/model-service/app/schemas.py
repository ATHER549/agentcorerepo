import time
import uuid
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProviderEnum(str, Enum):
    AZURE = "azure"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    GROQ = "groq"
    OPENAI_COMPATIBLE = "openai_compatible"


# ---------------------------------------------------------------------------
# Chat Completion schemas
# ---------------------------------------------------------------------------


class ChatMessageToolCall(BaseModel):
    id: str = ""
    type: str = "function"
    function: dict = {}


class ChatMessage(BaseModel):
    role: str
    content: str | None = ""
    tool_call_id: str | None = None
    tool_calls: list[ChatMessageToolCall] | None = None


class ChatCompletionRequest(BaseModel):
    provider: ProviderEnum
    model: str
    messages: list[ChatMessage]
    provider_config: dict = Field(default_factory=dict)
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    n: int | None = None
    stream: bool = False
    seed: int | None = None
    json_mode: bool = False
    model_kwargs: dict | None = None
    tools: list[dict] | None = None


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ToolCallFunction(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    type: str = "function"
    function: ToolCallFunction


class ChoiceMessage(BaseModel):
    role: str = "assistant"
    content: str | None = ""
    tool_calls: list[ToolCall] | None = None


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: str | None = "stop"


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: list[ChatCompletionChoice] = []
    usage: UsageInfo = Field(default_factory=UsageInfo)


class DeltaMessage(BaseModel):
    role: str | None = None
    content: str | None = None
    tool_calls: list[dict] | None = None


class ChunkChoice(BaseModel):
    index: int = 0
    delta: DeltaMessage
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: list[ChunkChoice] = []
    usage: UsageInfo | None = None


# ---------------------------------------------------------------------------
# Embedding schemas
# ---------------------------------------------------------------------------


class EmbeddingRequest(BaseModel):
    provider: ProviderEnum
    model: str
    input: list[str]
    provider_config: dict = Field(default_factory=dict)
    dimensions: int | None = None


class EmbeddingData(BaseModel):
    object: str = "embedding"
    embedding: list[float]
    index: int


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: list[EmbeddingData] = []
    model: str = ""
    usage: UsageInfo = Field(default_factory=UsageInfo)


# ---------------------------------------------------------------------------
# Model listing schemas
# ---------------------------------------------------------------------------


class ModelListRequest(BaseModel):
    provider: ProviderEnum
    provider_config: dict = Field(default_factory=dict)


class ProviderModelListResponse(BaseModel):
    models: list[str] = []


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    owned_by: str = ""
    provider: str = ""


class ModelListResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo] = []
