from agentcore.template.field.base import Input
from agentcore.template.frontend_node.base import FrontendNode
from agentcore.template.template.base import Template

DEFAULT_CUSTOM_COMPONENT_CODE = """from agentcore.custom import Node

from typing import Optional, List, Dict, Union
from agentcore.field_typing import (
    AgentExecutor,
    BaseChatMemory,
    BaseLanguageModel,
    BaseLLM,
    BaseLoader,
    BaseMemory,
    BasePromptTemplate,
    BaseRetriever,
    Callable,
    Chain,
    ChatPromptTemplate,
    Data,
    Document,
    Embeddings,
    NestedDict,
    Object,
    PromptTemplate,
    TextSplitter,
    Tool,
    VectorStore,
)


class MyComponent(Node):
    display_name: str = "Custom Component"
    description: str = "Create any custom component you want!"

    def build_config(self):
        return {"param": {"display_name": "Parameter"}}

    def build(self, param: Data) -> Data:
        return param

"""


class ExecutableNodeFrontendNode(FrontendNode):
    _format_template: bool = False
    name: str = "ExecutableNode"
    display_name: str | None = "ExecutableNode"
    beta: bool = False
    minimized: bool = False
    template: Template = Template(
        type_name="ExecutableNode",
        fields=[
            Input(
                field_type="code",
                required=True,
                placeholder="",
                is_list=False,
                show=True,
                value=DEFAULT_CUSTOM_COMPONENT_CODE,
                name="code",
                advanced=False,
                dynamic=True,
            )
        ],
    )
    description: str | None = None
    base_classes: list[str] = []
    last_updated: str | None = None


class NodeFrontendNode(FrontendNode):
    _format_template: bool = False
    name: str = "Node"
    display_name: str | None = "Node"
    beta: bool = False
    minimized: bool = False
    template: Template = Template(
        type_name="Node",
        fields=[
            Input(
                field_type="code",
                required=True,
                placeholder="",
                is_list=False,
                show=True,
                value=DEFAULT_CUSTOM_COMPONENT_CODE,
                name="code",
                advanced=False,
                dynamic=True,
            )
        ],
    )
    description: str | None = None
    base_classes: list[str] = []
