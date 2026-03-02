from typing import TYPE_CHECKING

from agentcore.utils import validate

if TYPE_CHECKING:
    from agentcore.custom.custom_node.custom_node import ExecutableNode


def eval_custom_component_code(code: str) -> type["ExecutableNode"]:
    """Evaluate custom component code."""
    class_name = validate.extract_class_name(code)
    return validate.create_class(code, class_name)
