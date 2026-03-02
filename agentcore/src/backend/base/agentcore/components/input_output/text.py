from agentcore.base.io.text import TextNode
from agentcore.io import MultilineInput, Output
from agentcore.schema.message import Message


class TextInput(TextNode):
    display_name = "Text Input"
    description = "Get user text inputs."
    icon = "type"
    name = "TextInput"

    inputs = [
        MultilineInput(
            name="input_value",
            display_name="Text",
            info="Text to be passed as input.",
            value="",
        ),
    ]
    outputs = [
        Output(display_name="Output Text", name="text", method="text_response"),
    ]

    def build_config(self):
        # Override parent's build_config to prevent input_types from
        # turning input_value into a connection handle
        return {}

    def text_response(self) -> Message:
        return Message(
            text=self.input_value or "",
        )
