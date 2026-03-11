# from agentcore.field_typing import Data
from agentcore.custom.custom_node.node import Node
from agentcore.io import MessageTextInput, Output
from agentcore.schema.data import Data


class CodeEditorNode(Node):
    display_name = "Custom Code"
    description = "Use as a template to create your own component."
    icon = "Pythoncode"
    name = "CustomComponent"

    inputs = [
        MessageTextInput(
            name="input_value",
            display_name="Input Value",
            info="This is a custom component Input",
            value="Hello, World!",
            tool_mode=True,
        ),
    ]

    outputs = [
        Output(display_name="Output", name="output", method="build_output"),
    ]

    def build_output(self) -> Data:
        data = Data(value=self.input_value)
        self.status = data
        return data
