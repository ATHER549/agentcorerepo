from datetime import datetime, timezone

from agentcore.custom.custom_node.node import Node
from agentcore.io import (
    DropdownInput,
    IntInput,
    MessageTextInput,
    MultilineInput,
    Output,
)
from agentcore.schema.message import Message
from agentcore.utils.constants import MESSAGE_SENDER_USER


class ScheduleTrigger(Node):
    display_name = "Schedule Trigger"
    description = "Triggers the flow on a cron schedule or fixed interval. Acts as the entry point for autonomous scheduled flows."
    icon = "Clock"
    name = "ScheduleTrigger"
    minimized = True

    inputs = [
        DropdownInput(
            name="schedule_type",
            display_name="Schedule Type",
            options=["Interval", "Cron"],
            value="Interval",
            info="Choose between a fixed interval or a cron expression.",
            real_time_refresh=True,
        ),
        IntInput(
            name="interval_minutes",
            display_name="Run Every (minutes)",
            value=60,
            info="How often to run the flow, in minutes.",
        ),
        MessageTextInput(
            name="cron_expression",
            display_name="Cron Expression",
            value="0 * * * *",
            info="Standard cron expression (minute hour day month weekday). Example: '0 9 * * 1-5' runs at 9 AM on weekdays.",
        ),
        MultilineInput(
            name="trigger_message",
            display_name="Input Message",
            value="Scheduled trigger fired",
            info="Message passed to the flow when the schedule triggers.",
        ),
        MessageTextInput(
            name="session_id",
            display_name="Session ID",
            info="The session ID for this trigger. If empty, a new session is created per execution.",
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Trigger Output",
            name="trigger_output",
            method="trigger_response",
        ),
    ]

    def update_build_config(self, build_config, field_value, field_name=None):
        """Show/hide inputs based on schedule_type selection."""
        from agentcore.utils.component_utils import set_current_fields, set_field_display

        mode_config = {
            "Interval": ["interval_minutes"],
            "Cron": ["cron_expression"],
        }
        default_keys = [
            "code",
            "_type",
            "schedule_type",
            "trigger_message",
            "session_id",
        ]
        return set_current_fields(
            build_config=build_config,
            action_fields=mode_config,
            selected_action=build_config["schedule_type"]["value"],
            default_fields=default_keys,
            func=set_field_display,
        )

    async def trigger_response(self) -> Message:
        now = datetime.now(timezone.utc)
        schedule_type = self.schedule_type
        trigger_text = self.trigger_message or "Scheduled trigger fired"

        metadata = {
            "trigger_type": "schedule",
            "schedule_type": schedule_type,
            "triggered_at": now.isoformat(),
        }
        if schedule_type == "Interval":
            metadata["interval_minutes"] = self.interval_minutes
        else:
            metadata["cron_expression"] = self.cron_expression

        message = await Message.create(
            text=trigger_text,
            sender=MESSAGE_SENDER_USER,
            sender_name="ScheduleTrigger",
            session_id=self.session_id or "",
            properties={"trigger_metadata": metadata},
        )

        self.status = message
        return message
