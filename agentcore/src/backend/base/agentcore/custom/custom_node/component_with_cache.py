from agentcore.custom.custom_node.node import Node
from agentcore.services.deps import get_shared_component_cache_service


class NodeWithCache(Node):
    def __init__(self, **data) -> None:
        super().__init__(**data)
        self._shared_component_cache = get_shared_component_cache_service()
