from collections.abc import Generator
from typing import Any

import orjson
from fastapi.encoders import jsonable_encoder
from loguru import logger

from agentcore.base.io.chat import ChatNode
from agentcore.helpers.data import safe_convert
from agentcore.inputs.inputs import BoolInput, DropdownInput, HandleInput, MessageTextInput
from agentcore.schema.data import Data
from agentcore.schema.dataframe import DataFrame
from agentcore.schema.message import Message
from agentcore.schema.properties import Source
from agentcore.template.field.base import Output
from agentcore.utils.constants import (
    MESSAGE_SENDER_AI,
    MESSAGE_SENDER_NAME_AI,
    MESSAGE_SENDER_USER,
)


class ChatOutput(ChatNode):
    display_name = "Chat Output"
    description = "Display a chat message in the Playground."
    icon = "MessagesSquare"
    name = "ChatOutput"
    minimized = True

    inputs = [
        HandleInput(
            name="input_value",
            display_name="Inputs",
            info="Message to be passed as output.",
            input_types=["Data", "DataFrame", "Message"],
            required=True,
        ),
        BoolInput(
            name="should_store_message",
            display_name="Store Messages",
            info="Store the message in the history.",
            value=True,
            advanced=True,
        ),
        DropdownInput(
            name="sender",
            display_name="Sender Type",
            options=[MESSAGE_SENDER_AI, MESSAGE_SENDER_USER],
            value=MESSAGE_SENDER_AI,
            advanced=True,
            info="Type of sender.",
        ),
        MessageTextInput(
            name="sender_name",
            display_name="Sender Name",
            info="Name of the sender.",
            value=MESSAGE_SENDER_NAME_AI,
            advanced=True,
        ),
        MessageTextInput(
            name="session_id",
            display_name="Session ID",
            info="The session ID of the chat. If empty, the current session ID parameter will be used.",
            advanced=True,
        ),
        MessageTextInput(
            name="data_template",
            display_name="Data Template",
            value="{text}",
            advanced=True,
            info="Template to convert Data to Text. If left empty, it will be dynamically set to the Data's text key.",
        ),
        MessageTextInput(
            name="background_color",
            display_name="Background Color",
            info="The background color of the icon.",
            advanced=True,
        ),
        MessageTextInput(
            name="chat_icon",
            display_name="Icon",
            info="The icon of the message.",
            advanced=True,
        ),
        MessageTextInput(
            name="text_color",
            display_name="Text Color",
            info="The text color of the name",
            advanced=True,
        ),
        BoolInput(
            name="clean_data",
            display_name="Basic Clean Data",
            value=True,
            info="Whether to clean the data",
            advanced=True,
        ),
    ]
    outputs = [
        Output(
            display_name="Output Message",
            name="message",
            method="message_response",
        ),
    ]

    def _build_source(self, id_: str | None, display_name: str | None, source: str | None) -> Source:
        source_dict = {}
        if id_:
            source_dict["id"] = id_
        if display_name:
            source_dict["display_name"] = display_name
        if source:
            # Handle case where source is a ChatOpenAI object
            if hasattr(source, "model_name"):
                source_dict["source"] = source.model_name
            elif hasattr(source, "model"):
                source_dict["source"] = str(source.model)
            else:
                source_dict["source"] = str(source)
        return Source(**source_dict)

    async def message_response(self) -> Message:
        # Check if input is already a stored Message (has an ID)
        # This happens when input comes from Agent component which already stores its response
        input_already_stored = (
            isinstance(self.input_value, Message) 
            and hasattr(self.input_value, "id") 
            and self.input_value.id is not None
        )
        
        # First convert the input to string if needed
        text = self.convert_to_string()

        # Get source properties
        source, icon, display_name, source_id = self.get_properties_from_source_component()
        background_color = self.background_color
        text_color = self.text_color
        if self.chat_icon:
            icon = self.chat_icon

        # If input is already a stored Message, just return it with updated properties
        # Don't create a new message to avoid duplicate storage
        if input_already_stored:
            message = self.input_value
            # Update properties if user has customized them
            if background_color:
                message.properties.background_color = background_color
            if text_color:
                message.properties.text_color = text_color
            if self.chat_icon:
                message.properties.icon = icon
            self.status = message
            if message.sender == MESSAGE_SENDER_AI:
                preview = (message.text or "")[:150]
                logger.info(f"[AI_MESSAGE] AI: {preview}")
            return message

        # IMPORTANT: Create a NEW Message object for non-stored inputs
        # If we reuse the input message (which may have an ID from a previous store),
        # astore_message will UPDATE that existing record instead of creating a new one.
        message = Message(text=text)
        # Preserve content_blocks from the input message (e.g. SupervisorAgent trace steps)
        if isinstance(self.input_value, Message) and self.input_value.content_blocks:
            message.content_blocks = self.input_value.content_blocks

        # Set message properties
        message.sender = self.sender
        message.sender_name = self.sender_name
        message.session_id = self.session_id
        message.agent_id = self.graph.agent_id if hasattr(self, "graph") else None
        message.properties.source = self._build_source(source_id, display_name, source)
        message.properties.icon = icon
        message.properties.background_color = background_color
        message.properties.text_color = text_color

        # Store message if needed
        if self.session_id and self.should_store_message:
            stored_message = await self.send_message(message)
            self.message.value = stored_message
            message = stored_message

            # Update STM cache: append this AI response so next STM read gets a cache HIT
            # with the complete conversation including this response.
            try:
                import json
                from agentcore.services.deps import get_settings_service
                from agentcore.services.cache.redis_client import get_redis_client

                settings_service = get_settings_service()
                if settings_service.settings.cache_type == "redis":
                    redis_client = get_redis_client(settings_service)
                    stm_prefix = "stm:history:"
                    ttl = getattr(settings_service.settings, "stm_cache_ttl", 300)
                    pattern = f"{stm_prefix}{self.session_id}:*"
                    async for key in redis_client.scan_iter(match=pattern, count=100):
                        existing = await redis_client.get(key)
                        if existing:
                            cached_msgs = json.loads(existing)
                            # Append the AI response
                            ai_entry = {
                                "text": message.text or "",
                                "sender": message.sender or "",
                                "sender_name": message.sender_name or "",
                            }
                            cached_msgs.append(ai_entry)
                            # Trim to the n_messages limit (extract from key: stm:history:{sid}:{n})
                            try:
                                n_limit = int(str(key).rsplit(":", 1)[-1])
                                if n_limit and len(cached_msgs) > n_limit:
                                    cached_msgs = cached_msgs[-n_limit:]
                            except (ValueError, IndexError):
                                pass
                            await redis_client.setex(key, ttl, json.dumps(cached_msgs))
                            logger.info(f"[ChatOutput] Updated STM cache with AI response for session={self.session_id}, total={len(cached_msgs)} msgs")
            except Exception as e:
                logger.debug(f"[ChatOutput] STM cache update skipped: {e}")

        self.status = message
        if message.sender == MESSAGE_SENDER_AI:
            preview = (message.text or "")[:150]
            logger.info(f"[AI_MESSAGE] AI: {preview}")
        return message

    def _serialize_data(self, data: Data) -> str:
        """Serialize Data object to JSON string."""
        # Convert data.data to JSON-serializable format
        serializable_data = jsonable_encoder(data.data)
        # Serialize with orjson, enabling pretty printing with indentation
        json_bytes = orjson.dumps(serializable_data, option=orjson.OPT_INDENT_2)
        # Convert bytes to string and wrap in Markdown code blocks
        return "```json\n" + json_bytes.decode("utf-8") + "\n```"

    def _validate_input(self) -> None:
        """Validate the input data and raise ValueError if invalid."""
        if self.input_value is None:
            msg = "Input data cannot be None"
            raise ValueError(msg)
        if isinstance(self.input_value, list) and not all(
            isinstance(item, Message | Data | DataFrame | str) for item in self.input_value
        ):
            invalid_types = [
                type(item).__name__
                for item in self.input_value
                if not isinstance(item, Message | Data | DataFrame | str)
            ]
            msg = f"Expected Data or DataFrame or Message or str, got {invalid_types}"
            raise TypeError(msg)
        if not isinstance(
            self.input_value,
            Message | Data | DataFrame | str | list | Generator | type(None),
        ):
            type_name = type(self.input_value).__name__
            msg = f"Expected Data or DataFrame or Message or str, Generator or None, got {type_name}"
            raise TypeError(msg)

    def convert_to_string(self) -> str | Generator[Any, None, None]:
        """Convert input data to string with proper error handling."""
        self._validate_input()
        if isinstance(self.input_value, list):
            return "\n".join([safe_convert(item, clean_data=self.clean_data) for item in self.input_value])
        if isinstance(self.input_value, Generator):
            return self.input_value
        return safe_convert(self.input_value)
