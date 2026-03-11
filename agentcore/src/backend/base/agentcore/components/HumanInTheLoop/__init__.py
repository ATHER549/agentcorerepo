from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcore.components._importing import import_mod

if TYPE_CHECKING:
    from agentcore.components.HumanInTheLoop.human_approval import HumanApprovalComponent

_dynamic_imports = {
    "HumanApprovalComponent": "human_approval",
}

__all__ = [
    "HumanApprovalComponent",
]


def __getattr__(attr_name: str) -> Any:
    if attr_name not in _dynamic_imports:
        msg = f"module '{__name__}' has no attribute '{attr_name}'"
        raise AttributeError(msg)
    result = import_mod(attr_name, _dynamic_imports[attr_name], __spec__.parent)
    globals()[attr_name] = result
    return result


def __dir__() -> list[str]:
    return list(__all__)
