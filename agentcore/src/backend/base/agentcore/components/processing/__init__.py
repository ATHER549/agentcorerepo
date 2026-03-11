"""Processing components for AgentCore."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcore.components._importing import import_mod

if TYPE_CHECKING:
    from agentcore.components.processing.batch_run import BatchRun
    from agentcore.components.processing.parser import Parser
    from agentcore.components.processing.prompt import Prompt
    from agentcore.components.processing.split_text import SplitText
    from agentcore.components.processing.structured_output import StructuredOutput

_dynamic_imports = {
    "BatchRun": "batch_run",
    "Parser": "parser",
    "Prompt": "prompt",
    "SplitText": "split_text",
    "StructuredOutput": "structured_output",
}

__all__ = [
    "BatchRun",
    "Parser",
    "Prompt",
    "SplitText",
    "StructuredOutput",
]


def __getattr__(attr_name: str) -> Any:
    """Lazily import processing components on attribute access."""
    if attr_name not in _dynamic_imports:
        msg = f"module '{__name__}' has no attribute '{attr_name}'"
        raise AttributeError(msg)
    try:
        result = import_mod(attr_name, _dynamic_imports[attr_name], __spec__.parent)
    except (ModuleNotFoundError, ImportError, AttributeError) as e:
        msg = f"Could not import '{attr_name}' from '{__name__}': {e}"
        raise AttributeError(msg) from e
    globals()[attr_name] = result
    return result


def __dir__() -> list[str]:
    return list(__all__)
