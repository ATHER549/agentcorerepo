from agentcore.base.io.text import TextNode
from agentcore.io import MultilineInput, Output
from agentcore.schema.message import Message


class TextOutput(TextNode):
    display_name = "Text Output"
    description = "Sends text output via API."
    icon = "type"
    name = "TextOutput"

    inputs = [
        MultilineInput(
            name="input_value",
            display_name="Inputs",
            info="Text to be passed as output.",
        ),
    ]
    outputs = [
        Output(display_name="Output Text", name="text", method="text_response"),
    ]

    def text_response(self) -> Message:
        message = Message(
            text=self.input_value,
        )
        self.status = self.input_value
        return message
