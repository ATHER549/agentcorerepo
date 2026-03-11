from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

PROVIDER_REGISTRY: dict[str, type["BaseProvider"]] = {}


def register_provider(name: str):
    """Decorator to register a provider class in the registry."""

    def decorator(cls: type["BaseProvider"]):
        PROVIDER_REGISTRY[name] = cls
        return cls

    return decorator


def get_provider(name: str) -> "BaseProvider":
    """Get an instantiated provider by name."""
    if name not in PROVIDER_REGISTRY:
        available = ", ".join(PROVIDER_REGISTRY.keys())
        msg = f"Unknown provider '{name}'. Available: {available}"
        raise ValueError(msg)
    return PROVIDER_REGISTRY[name]()


class BaseProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def build_model(
        self,
        model: str,
        provider_config: dict[str, Any],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        n: int | None = None,
        streaming: bool = False,
        seed: int | None = None,
        json_mode: bool = False,
        model_kwargs: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        """Build a LangChain chat model from the given configuration."""

    def build_embeddings(
        self,
        model: str,
        provider_config: dict[str, Any],
        *,
        dimensions: int | None = None,
    ):
        """Build a LangChain embeddings model.  Override in providers that support embeddings."""
        msg = f"Provider {type(self).__name__} does not support embeddings"
        raise NotImplementedError(msg)

    def build_messages(self, messages: list[dict[str, str]]) -> list[BaseMessage]:
        """Convert OpenAI-format message dicts to LangChain BaseMessage objects."""
        lc_messages: list[BaseMessage] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content") or ""
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "tool":
                lc_messages.append(ToolMessage(
                    content=content,
                    tool_call_id=msg.get("tool_call_id", ""),
                ))
            elif role == "assistant":
                tool_calls_raw = msg.get("tool_calls")
                if tool_calls_raw:
                    lc_tool_calls = []
                    for tc in tool_calls_raw:
                        func = tc.get("function", {})
                        args_str = func.get("arguments", "{}")
                        try:
                            args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        except (json.JSONDecodeError, TypeError):
                            args = {"raw": args_str}
                        lc_tool_calls.append({
                            "name": func.get("name", ""),
                            "args": args,
                            "id": tc.get("id", ""),
                        })
                    lc_messages.append(AIMessage(content=content, tool_calls=lc_tool_calls))
                else:
                    lc_messages.append(AIMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=content))
        return lc_messages

    async def list_models(self, provider_config: dict[str, Any]) -> list[str]:
        """List available models for this provider. Override in subclasses."""
        return []

    async def invoke(self, model: BaseChatModel, messages: list[BaseMessage]) -> AIMessage:
        """Invoke the model and return the response."""
        return await model.ainvoke(messages)

    async def stream(self, model: BaseChatModel, messages: list[BaseMessage]) -> AsyncIterator:
        """Stream the model response."""
        async for chunk in model.astream(messages):
            yield chunk
