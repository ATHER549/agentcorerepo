import json
from typing import Any, cast

from loguru import logger

from agentcore.custom.custom_node.node import Node
from agentcore.helpers.data import data_to_text
from agentcore.inputs.inputs import DropdownInput, HandleInput, IntInput, MessageTextInput, MultilineInput, TabInput
from agentcore.memory import aget_messages, astore_message
from agentcore.schema.data import Data
from agentcore.schema.dataframe import DataFrame
from agentcore.schema.dotdict import dotdict
from agentcore.schema.message import Message
from agentcore.template.field.base import Output
from agentcore.utils.component_utils import set_current_fields, set_field_display
from agentcore.utils.constants import MESSAGE_SENDER_AI, MESSAGE_SENDER_NAME_AI, MESSAGE_SENDER_USER

# STM Redis cache settings
STM_CACHE_PREFIX = "stm:history:"


class MemoryNode(Node):
    display_name = "Message History"
    description = "Stores or retrieves stored chat messages from agentCore tables or an external memory."
    icon = "message-square-more"
    name = "Memory"
    default_keys = ["mode", "memory"]
    mode_config = {
        "Store": ["message", "sender", "sender_name", "session_id"],
        "Retrieve": ["order", "template", "n_messages"],
        "Short Term Memory": ["input_value", "n_messages", "session_id", "template"],
    }

    inputs = [
        TabInput(
            name="mode",
            display_name="Mode",
            options=["Retrieve", "Store", "Short Term Memory"],
            value="Retrieve",
            info="Operation mode: Store messages, Retrieve messages, or Short Term Memory (fetch recent conversation and concat with current input).",
            real_time_refresh=True,
        ),
        HandleInput(
            name="input_value",
            display_name="Chat Input",
            input_types=["Message"],
            info="The current chat input message. In Short Term Memory mode, recent conversation history will be prepended to this message.",
            required=True,
            show=False,
        ),
        MessageTextInput(
            name="message",
            display_name="Message",
            info="The chat message to be stored.",
            tool_mode=True,
            dynamic=True,
            show=False,
        ),
        HandleInput(
            name="memory",
            display_name="External Memory",
            input_types=["Memory"],
            info="Retrieve messages from an external memory. If empty, it will use the Agentcore tables.",
            advanced=True,
            show=True,
        ),
        DropdownInput(
            name="sender_type",
            display_name="Sender Type",
            options=[MESSAGE_SENDER_AI, MESSAGE_SENDER_USER, "Machine and User"],
            value="Machine and User",
            info="Filter by sender type.",
            advanced=True,
            show=True,
        ),
        MessageTextInput(
            name="sender",
            display_name="Sender",
            info="The sender of the message. Might be Machine or User. "
            "If empty, the current sender parameter will be used.",
            advanced=True,
            show=True,
        ),
        MessageTextInput(
            name="sender_name",
            display_name="Sender Name",
            info="Filter by sender name.",
            advanced=True,
            show=False,
        ),
        IntInput(
            name="n_messages",
            display_name="Top K (Number of Messages)",
            value=10,
            info="Number of recent messages to retrieve. In Short Term Memory mode, these are the top K latest conversations prepended to the input.",
            show=True,
            advanced=False,
            real_time_refresh=True,
        ),
        MessageTextInput(
            name="session_id",
            display_name="Session ID",
            info="The session ID of the chat. If empty, the current session ID parameter will be used.",
            value="",
            advanced=True,
            show=True,
        ),
        DropdownInput(
            name="order",
            display_name="Order",
            options=["Ascending", "Descending"],
            value="Ascending",
            info="Order of the messages.",
            advanced=True,
            tool_mode=True,
            required=True,
            show=True,
        ),
        MultilineInput(
            name="template",
            display_name="Template",
            info="The template to use for formatting the data. "
            "It can contain the keys {text}, {sender} or any other key in the message data.",
            value="{sender_name}: {text}",
            advanced=True,
            show=False,
        ),
    ]

    outputs = [
        Output(display_name="Message", name="messages_text", method="retrieve_messages_as_text", dynamic=True),
        Output(display_name="Dataframe", name="dataframe", method="retrieve_messages_dataframe", dynamic=True),
        Output(display_name="Enriched Message", name="enriched_message", method="short_term_memory", dynamic=True),
    ]

    def update_outputs(self, frontend_node: dict, field_name: str, field_value: Any) -> dict:
        """Dynamically show only the relevant output based on the selected output type."""
        if field_name == "mode":
            # Start with empty outputs
            frontend_node["outputs"] = []
            if field_value == "Store":
                frontend_node["outputs"] = [
                    Output(
                        display_name="Stored Messages",
                        name="stored_messages",
                        method="store_message",
                        hidden=True,
                        dynamic=True,
                    )
                ]
            if field_value == "Retrieve":
                frontend_node["outputs"] = [
                    Output(
                        display_name="Messages", name="messages_text", method="retrieve_messages_as_text", dynamic=True
                    ),
                    Output(
                        display_name="Dataframe", name="dataframe", method="retrieve_messages_dataframe", dynamic=True
                    ),
                ]
            if field_value == "Short Term Memory":
                frontend_node["outputs"] = [
                    Output(
                        display_name="Enriched Message",
                        name="enriched_message",
                        method="short_term_memory",
                        dynamic=True,
                    ),
                ]
        return frontend_node

    def _get_redis_client_and_ttl(self):
        """Get the Redis client and STM TTL from settings. Returns (None, 300) if Redis is unavailable."""
        try:
            from agentcore.services.deps import get_settings_service
            from agentcore.services.cache.redis_client import get_redis_client

            settings_service = get_settings_service()
            ttl = getattr(settings_service.settings, "stm_cache_ttl", 300)
            if settings_service.settings.cache_type == "redis":
                return get_redis_client(settings_service), ttl
        except Exception:
            logger.debug("[STM] Redis not available, skipping cache layer")
        return None, 300

    async def _get_stm_cache(self, session_id: str, n_messages: int) -> list[dict] | None:
        """Try to get cached STM history from Redis."""
        redis, _ = self._get_redis_client_and_ttl()
        if not redis:
            return None
        try:
            cache_key = f"{STM_CACHE_PREFIX}{session_id}:{n_messages}"
            data = await redis.get(cache_key)
            if data:
                logger.info(f"[STM] Cache HIT for session={session_id}, n={n_messages}")
                return json.loads(data)
            logger.debug(f"[STM] Cache MISS for session={session_id}, n={n_messages}")
        except Exception as e:
            logger.warning(f"[STM] Redis cache read failed: {e}")
        return None

    async def _set_stm_cache(self, session_id: str, n_messages: int, messages: list[Message]) -> None:
        """Cache STM history in Redis with TTL from settings (STM_CACHE_TTL env var)."""
        redis, ttl = self._get_redis_client_and_ttl()
        if not redis:
            return
        try:
            cache_key = f"{STM_CACHE_PREFIX}{session_id}:{n_messages}"
            # Serialize messages to dicts for JSON storage
            data = [{"text": m.text or "", "sender": m.sender or "", "sender_name": m.sender_name or ""} for m in messages]
            await redis.setex(cache_key, ttl, json.dumps(data))
            logger.debug(f"[STM] Cached {len(messages)} messages for session={session_id}, ttl={ttl}s")
        except Exception as e:
            logger.warning(f"[STM] Redis cache write failed: {e}")

    async def _invalidate_stm_cache(self, session_id: str) -> None:
        """Invalidate all STM cache entries for a session (any n_messages value)."""
        redis, _ = self._get_redis_client_and_ttl()
        if not redis:
            return
        try:
            # Delete all keys matching stm:history:{session_id}:*
            pattern = f"{STM_CACHE_PREFIX}{session_id}:*"
            keys = []
            async for key in redis.scan_iter(match=pattern, count=100):
                keys.append(key)
            if keys:
                await redis.delete(*keys)
                logger.debug(f"[STM] Invalidated {len(keys)} cache entries for session={session_id}")
        except Exception as e:
            logger.warning(f"[STM] Redis cache invalidation failed: {e}")

    def _effective_session_id(self) -> str | None:
        """Return the session_id to use: explicit input field → graph session → None."""
        sid = self.session_id
        if sid:
            return sid
        if hasattr(self, "_session_id") and self._session_id:
            return self._session_id
        if hasattr(self, "graph") and getattr(self.graph, "session_id", None):
            return self.graph.session_id
        return None

    async def store_message(self) -> Message:
        message = Message(text=self.message) if isinstance(self.message, str) else self.message

        message.session_id = self._effective_session_id() or message.session_id
        message.sender = self.sender or message.sender or MESSAGE_SENDER_AI
        message.sender_name = self.sender_name or message.sender_name or MESSAGE_SENDER_NAME_AI

        stored_messages: list[Message] = []

        if self.memory:
            self.memory.session_id = message.session_id
            lc_message = message.to_lc_message()
            await self.memory.aadd_messages([lc_message])

            stored_messages = await self.memory.aget_messages() or []

            stored_messages = [Message.from_lc_message(m) for m in stored_messages] if stored_messages else []

            if message.sender:
                stored_messages = [m for m in stored_messages if m.sender == message.sender]
        else:
            await astore_message(message, agent_id=self.graph.agent_id)
            stored_messages = (
                await aget_messages(
                    session_id=message.session_id, sender_name=message.sender_name, sender=message.sender
                )
                or []
            )

        if not stored_messages:
            msg = "No messages were stored. Please ensure that the session ID and sender are properly set."
            raise ValueError(msg)

        stored_message = stored_messages[0]
        self.status = stored_message
        return stored_message

    async def retrieve_messages(self) -> Data:
        sender_type = self.sender_type
        sender_name = self.sender_name
        session_id = self._effective_session_id()
        n_messages = self.n_messages
        order = "DESC" if self.order == "Descending" else "ASC"

        if sender_type == "Machine and User":
            sender_type = None

        if self.memory and not hasattr(self.memory, "aget_messages"):
            memory_name = type(self.memory).__name__
            err_msg = f"External Memory object ({memory_name}) must have 'aget_messages' method."
            raise AttributeError(err_msg)
        # Check if n_messages is None or 0
        if n_messages == 0:
            stored = []
        elif self.memory:
            # override session_id
            self.memory.session_id = session_id

            stored = await self.memory.aget_messages()
            # langchain memories are supposed to return messages in ascending order

            if order == "DESC":
                stored = stored[::-1]
            if n_messages:
                stored = stored[-n_messages:] if order == "ASC" else stored[:n_messages]
            stored = [Message.from_lc_message(m) for m in stored]
            if sender_type:
                expected_type = MESSAGE_SENDER_AI if sender_type == MESSAGE_SENDER_AI else MESSAGE_SENDER_USER
                stored = [m for m in stored if m.type == expected_type]
        else:
            # For internal memory, we always fetch the last N messages by ordering by DESC
            stored = await aget_messages(
                sender=sender_type,
                sender_name=sender_name,
                session_id=session_id,
                limit=10000,
                order=order,
            )
            if n_messages:
                stored = stored[-n_messages:] if order == "ASC" else stored[:n_messages]

        # self.status = stored
        return cast(Data, stored)

    async def retrieve_messages_as_text(self) -> Message:
        stored_text = data_to_text(self.template, await self.retrieve_messages())
        # self.status = stored_text
        return Message(text=stored_text)

    async def retrieve_messages_dataframe(self) -> DataFrame:
        """Convert the retrieved messages into a DataFrame.

        Returns:
            DataFrame: A DataFrame containing the message data.
        """
        messages = await self.retrieve_messages()
        return DataFrame(messages)

    async def short_term_memory(self) -> Message:
        """Fetch the top K latest messages from the session and concat with the current chat input.

        The conversation history is prepended to the current user message so the downstream
        LLM receives recent context along with the new input. The current user message is also
        stored in the conversation history so future STM retrievals include it.

        Returns:
            Message: A new Message with conversation history prepended to the input text.
        """
        session_id = self._effective_session_id()
        n_messages = self.n_messages or 10

        # NOTE: Cache invalidation is handled by ChatOutput (after storing AI response).
        # We do NOT invalidate here — otherwise the cache would never get a HIT
        # since ChatInput → Memory(STM) runs sequentially in the same request.

        # Get the current input text from ChatInput
        current_input = self.input_value
        if current_input is None:
            logger.warning("[STM] input_value is None — ChatInput output is not connected to Memory's 'Chat Input' handle.")
        if isinstance(current_input, Message):
            current_text = current_input.text or ""
            logger.info(f"[STM] Received input from ChatInput: {current_text[:100]}")
        elif isinstance(current_input, str):
            current_text = current_input
        else:
            current_text = str(current_input) if current_input else ""

        # Check if ChatInput already stored this message (has an id from DB)
        already_stored = (
            isinstance(current_input, Message)
            and hasattr(current_input, "id")
            and current_input.id is not None
        )

        # Only store if not already saved by ChatInput (avoid duplicates)
        if not already_stored:
            user_message = Message(text=current_text)
            if isinstance(current_input, Message):
                user_message.sender = current_input.sender or MESSAGE_SENDER_USER
                user_message.sender_name = current_input.sender_name or "User"
                user_message.session_id = current_input.session_id or session_id
                user_message.files = current_input.files
            else:
                user_message.sender = MESSAGE_SENDER_USER
                user_message.sender_name = "User"
                user_message.session_id = session_id

            if session_id and user_message.sender and user_message.sender_name:
                if self.memory:
                    self.memory.session_id = session_id
                    lc_message = user_message.to_lc_message()
                    await self.memory.aadd_messages([lc_message])
                else:
                    await astore_message(user_message, agent_id=self.graph.agent_id if hasattr(self, "graph") else None)

        # Fetch the top K latest messages — try Redis cache first, fall back to DB
        history_messages: list[Message] = []
        history_source = "none"
        if session_id:
            if self.memory:
                # External memory — always fetch directly, no Redis caching
                self.memory.session_id = session_id
                lc_messages = await self.memory.aget_messages()
                history_messages = [Message.from_lc_message(m) for m in lc_messages] if lc_messages else []
                history_messages = history_messages[-n_messages:]
                history_source = "external_memory"
            else:
                # Try Redis cache first
                cached = await self._get_stm_cache(session_id, n_messages)
                if cached is not None:
                    history_messages = [
                        Message(text=m["text"], sender=m.get("sender", ""), sender_name=m.get("sender_name", ""))
                        for m in cached
                    ]
                    # Check if the current user message is already in the cached history
                    # (ChatInput stored it in DB but cache may not have it yet)
                    if current_text and already_stored:
                        last_cached_text = cached[-1]["text"] if cached else ""
                        if last_cached_text != current_text:
                            # Append current user message to cached history
                            user_msg = Message(
                                text=current_text,
                                sender=current_input.sender if isinstance(current_input, Message) else MESSAGE_SENDER_USER,
                                sender_name=current_input.sender_name if isinstance(current_input, Message) else "User",
                            )
                            history_messages.append(user_msg)
                            # Trim to n_messages limit
                            if len(history_messages) > n_messages:
                                history_messages = history_messages[-n_messages:]
                            # Update cache with appended user message
                            await self._set_stm_cache(session_id, n_messages, history_messages)
                            logger.info(f"[STM] Appended current user message to cache for session={session_id}")
                    history_source = "redis_cache"
                else:
                    # Cache miss — fetch from DB
                    history_messages = await aget_messages(
                        session_id=session_id,
                        order="DESC",
                        limit=n_messages,
                    )
                    # Reverse to chronological order (oldest first)
                    history_messages = list(reversed(history_messages))
                    history_source = "database"

                    # Cache the fresh DB result in Redis for rapid re-fetches
                    if history_messages:
                        await self._set_stm_cache(session_id, n_messages, history_messages)

        logger.info(
            f"[STM] Fetched {len(history_messages)} history messages | "
            f"source={history_source} | session_id={session_id} | n_messages={n_messages}"
        )

        # Format conversation history using the template
        template = self.template if hasattr(self, "template") and self.template else "{sender_name}: {text}"
        if history_messages:
            conversation_history = data_to_text(template, history_messages)
        else:
            conversation_history = ""

        # Build the enriched text: history + current input
        if conversation_history:
            enriched_text = (
                f"Conversation History:\n{conversation_history}\n\n"
                f"Current Message:\n{current_text}"
            )
        else:
            enriched_text = current_text

        # Create a new message with the enriched text, preserving original message properties
        enriched_message = Message(text=enriched_text)
        if isinstance(current_input, Message):
            enriched_message.sender = current_input.sender
            enriched_message.sender_name = current_input.sender_name
            enriched_message.session_id = current_input.session_id or session_id
            enriched_message.files = current_input.files
        else:
            enriched_message.session_id = session_id

        logger.info(
            f"[STM] session_id={session_id} | "
            f"n_messages={n_messages} | "
            f"history_source={history_source} | "
            f"history_count={len(history_messages)} | "
            f"already_stored={already_stored}"
        )
        logger.debug(f"[STM] Final enriched payload to LLM:\n{enriched_text}")

        self.status = enriched_message
        return enriched_message

    def update_build_config(
        self,
        build_config: dotdict,
        field_value: Any,  # noqa: ARG002
        field_name: str | None = None,  # noqa: ARG002
    ) -> dotdict:
        selected_mode = build_config["mode"]["value"]

        build_config = set_current_fields(
            build_config=build_config,
            action_fields=self.mode_config,
            selected_action=selected_mode,
            default_fields=self.default_keys,
            func=set_field_display,
        )

        # Re-apply selected mode's fields to fix overlap issue
        # (set_current_fields hides shared fields when processing other modes)
        if selected_mode in self.mode_config:
            for field in self.mode_config[selected_mode]:
                build_config = set_field_display(build_config, field, True)

        return build_config
