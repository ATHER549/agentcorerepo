from agentcore.custom.custom_node.node import Node
from agentcore.inputs.inputs import MessageTextInput, BoolInput
from agentcore.io import Output
from agentcore.schema.message import Message


class HumanApprovalComponent(Node):
    display_name = "Human Approval"
    description = "Pause workagent execution and wait for human approval before proceeding."
    icon = "UserCheck"
    name = "HumanApproval"

    inputs = [
        MessageTextInput(
            name="input_text",
            display_name="Input Text",
            info="The content to be reviewed by a human.",
        ),
        MessageTextInput(
            name="approval_message",
            display_name="Approval Message",
            info="Message to display to the human reviewer.",
            value="Please review and approve the following content:",
        ),
        BoolInput(
            name="auto_approve",
            display_name="Auto Approve",
            info="If enabled, automatically approve without waiting for human input.",
            value=False,
            advanced=True,
        ),
    ]

    outputs = [
        Output(display_name="Approved Output", name="approved_output", type_=Message, method="request_approval"),
    ]

    def request_approval(self) -> Message:
        """Request human approval for the input content."""
        # Placeholder implementation - can be extended with actual human-in-the-loop logic
        if self.auto_approve:
            self.status = "Auto-approved"
            return Message(text=self.input_text)
        
        # In a real implementation, this would pause and wait for human input
        self.status = "Awaiting human approval"
        return Message(text=self.input_text)
