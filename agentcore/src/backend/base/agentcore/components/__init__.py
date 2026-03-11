"""AgentCore Components module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcore.components._importing import import_mod

if TYPE_CHECKING:
    from agentcore.components import (
        agents,
        Guardrails,
        HumanInTheLoop,
        azure,
        custom_component,
        data,
        google,
        graph_rag,
        groq,
        helpers,
        input_output,
        logic,
        models,
        processing,
        tools,
        triggers,
        vectorstores,
    )

_dynamic_imports = {
    "agents": "agentcore.components.agents",
    "data": "agentcore.components.data",
    "processing": "agentcore.components.processing",
    "vectorstores": "agentcore.components.vectorstores",
    "tools": "agentcore.components.tools",
    "models": "agentcore.components.models",
    "helpers": "agentcore.components.helpers",
    "input_output": "agentcore.components.input_output",
    "logic": "agentcore.components.logic",
    "custom_component": "agentcore.components.custom_component",
    "google": "agentcore.components.google",
    "azure": "agentcore.components.azure",
    "groq": "agentcore.components.groq",
    "Guardrails": "agentcore.components.Guardrails",
    "HumanInTheLoop": "agentcore.components.HumanInTheLoop",
    "graph_rag": "agentcore.components.graph_rag",
    "triggers": "agentcore.components.triggers",
}

__all__: list[str] = [
    "agents",
    "azure",
    "custom_component",
    "data",
    "google",
    "groq",
    "Guardrails",
    "HumanInTheLoop",
    "helpers",
    "input_output",
    "logic",
    "models",
    "processing",
    "tools",
    "triggers",
    "vectorstores",
    "graph_rag",
]


def __getattr__(attr_name: str) -> Any:
    """Lazily import component modules on attribute access.

    Args:
        attr_name (str): The attribute/module name to import.

    Returns:
        Any: The imported module or attribute.

    Raises:
        AttributeError: If the attribute is not a known component or cannot be imported.
    """
    if attr_name not in _dynamic_imports:
        msg = f"module '{__name__}' has no attribute '{attr_name}'"
        raise AttributeError(msg)
    try:
        # Use import_mod as in LangChain, passing the module name and package
        result = import_mod(attr_name, "__module__", __spec__.parent)
    except (ModuleNotFoundError, ImportError, AttributeError) as e:
        msg = f"Could not import '{attr_name}' from '{__name__}': {e}"
        raise AttributeError(msg) from e
    globals()[attr_name] = result  # Cache for future access
    return result


def __dir__() -> list[str]:
    """Return list of available attributes for tab-completion and dir()."""
    return list(__all__)


# Optional: Consistency check (can be removed in production)
_missing = set(__all__) - set(_dynamic_imports)
if _missing:
    msg = f"Missing dynamic import mapping for: {', '.join(_missing)}"
    raise ImportError(msg)
