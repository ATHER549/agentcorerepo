import importlib
import json
import time as _time_mod
import warnings
from abc import abstractmethod

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.llms import LLM
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import BaseOutputParser

from agentcore.base.constants import STREAM_INFO_TEXT
from agentcore.custom.custom_node.node import Node
from agentcore.field_typing import LanguageModel
from agentcore.inputs.inputs import BoolInput, InputTypes, MessageInput, MultilineInput
from agentcore.schema.message import Message
from agentcore.template.field.base import Output
from agentcore.utils.constants import MESSAGE_SENDER_AI

# Enabled detailed thinking for NVIDIA reasoning models.
#
# Models are trained with this exact string. Do not update.
DETAILED_THINKING_PREFIX = "detailed thinking on\n\n"


class LCModelNode(Node):
    display_name: str = "Model Name"
    description: str = "Model Description"
    trace_type = "llm"
    metadata = {
        "keywords": [
            "model",
            "llm",
            "language model",
            "large language model",
        ],
    }

    # Optional output parser to pass to the runnable. Subclasses may allow the user to input an `output_parser`
    output_parser: BaseOutputParser | None = None

    _base_inputs: list[InputTypes] = [
        MessageInput(name="input_value", display_name="Input"),
        MultilineInput(
            name="system_message",
            display_name="System Message",
            info="System message to pass to the model.",
            advanced=False,
        ),
        BoolInput(name="stream", display_name="Stream", info=STREAM_INFO_TEXT, advanced=True),
    ]

    outputs = [
        Output(display_name="Model Response", name="text_output", method="text_response"),
        Output(display_name="Language Model", name="model_output", method="build_model"),
    ]

    def _get_exception_message(self, e: Exception):
        return str(e)

    def supports_tool_calling(self, model: LanguageModel) -> bool:
        """Check if a model supports tool calling by testing bind_tools method."""
        try:
            # Check if the bind_tools method is the same as the base class's method
            if model.bind_tools is BaseChatModel.bind_tools:
                return False

            def test_tool(x: int) -> int:
                """A test tool that returns the input."""
                return x

            model_with_tool = model.bind_tools([test_tool])
            
            # RunnableBinding stores tools in kwargs['tools'], not as direct attribute
            # Check both locations for compatibility
            tools_from_kwargs = model_with_tool.kwargs.get('tools', []) if hasattr(model_with_tool, 'kwargs') else []
            tools_from_attr = getattr(model_with_tool, 'tools', []) or []
            
            tools = tools_from_kwargs or tools_from_attr
            return len(tools) > 0 if tools else False
        except (AttributeError, TypeError, ValueError):
            return False

    def _validate_outputs(self) -> None:
        # At least these two outputs must be defined
        required_output_methods = ["text_response", "build_model"]
        output_names = [output.name for output in self.outputs]
        for method_name in required_output_methods:
            if method_name not in output_names:
                msg = f"Output with name '{method_name}' must be defined."
                raise ValueError(msg)
            if not hasattr(self, method_name):
                msg = f"Method '{method_name}' must be defined."
                raise ValueError(msg)

    async def text_response(self) -> Message:
        output = self.build_model()
        result = await self.get_chat_result(
            runnable=output, stream=self.stream, input_value=self.input_value, system_message=self.system_message
        )
        self.status = result
        return result

    def get_result(self, *, runnable: LLM, stream: bool, input_value: str):
        """Retrieves the result from the output of a Runnable object.

        Args:
            runnable (Runnable): The runnable to retrieve the result from.
            stream (bool): Indicates whether to use streaming or invocation mode.
            input_value (str): The input value to pass to the output object.

        Returns:
            The result obtained from the output object.
        """
        try:
            if stream:
                result = runnable.stream(input_value)
            else:
                message = runnable.invoke(input_value)
                result = message.content if hasattr(message, "content") else message
                self.status = result
        except Exception as e:
            if message := self._get_exception_message(e):
                raise ValueError(message) from e
            raise

        return result

    def build_status_message(self, message: AIMessage):
        """Builds a status message from an AIMessage object.

        Args:
            message (AIMessage): The AIMessage object to build the status message from.

        Returns:
            The status message.
        """
        if message.response_metadata:
            # Build a well formatted status message
            content = message.content
            response_metadata = message.response_metadata
            openai_keys = ["token_usage", "model_name", "finish_reason"]
            inner_openai_keys = ["completion_tokens", "prompt_tokens", "total_tokens"]
            anthropic_keys = ["model", "usage", "stop_reason"]
            inner_anthropic_keys = ["input_tokens", "output_tokens"]
            if all(key in response_metadata for key in openai_keys) and all(
                key in response_metadata["token_usage"] for key in inner_openai_keys
            ):
                token_usage = response_metadata["token_usage"]
                status_message = {
                    "tokens": {
                        "input": token_usage["prompt_tokens"],
                        "output": token_usage["completion_tokens"],
                        "total": token_usage["total_tokens"],
                        "stop_reason": response_metadata["finish_reason"],
                        "response": content,
                    }
                }

            elif all(key in response_metadata for key in anthropic_keys) and all(
                key in response_metadata["usage"] for key in inner_anthropic_keys
            ):
                usage = response_metadata["usage"]
                status_message = {
                    "tokens": {
                        "input": usage["input_tokens"],
                        "output": usage["output_tokens"],
                        "stop_reason": response_metadata["stop_reason"],
                        "response": content,
                    }
                }
            else:
                status_message = f"Response: {content}"  # type: ignore[assignment]
        else:
            status_message = f"Response: {message.content}"  # type: ignore[assignment]
        return status_message

    async def get_chat_result(
        self,
        *,
        runnable: LanguageModel,
        stream: bool,
        input_value: str | Message,
        system_message: str | None = None,
    ) -> Message:
        # NVIDIA reasoning models use detailed thinking
        if getattr(self, "detailed_thinking", False):
            system_message = DETAILED_THINKING_PREFIX + (system_message or "")

        return await self._get_chat_result(
            runnable=runnable,
            stream=stream,
            input_value=input_value,
            system_message=system_message,
        )

    async def _get_chat_result(
        self,
        *,
        runnable: LanguageModel,
        stream: bool,
        input_value: str | Message,
        system_message: str | None = None,
    ) -> Message:
        """Get chat result from a language model.

        This method handles the core logic of getting a response from a language model,
        including handling different input types, streaming, and error handling.

        Args:
            runnable (LanguageModel): The language model to use for generating responses
            stream (bool): Whether to stream the response
            input_value (str | Message): The input to send to the model
            system_message (str | None, optional): System message to prepend. Defaults to None.

        Returns:
            The model response, either as a Message object or raw content

        Raises:
            ValueError: If the input message is empty or if there's an error during model invocation
        """
        messages: list[BaseMessage] = []
        if not input_value and not system_message:
            msg = "The message you want to send to the model is empty."
            raise ValueError(msg)
        system_message_added = False
        message = None
        if input_value:
            if isinstance(input_value, Message):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    if "prompt" in input_value:
                        prompt = input_value.load_lc_prompt()
                        if system_message:
                            prompt.messages = [
                                SystemMessage(content=system_message),
                                *prompt.messages,  # type: ignore[has-type]
                            ]
                            system_message_added = True
                        runnable = prompt | runnable
                    else:
                        messages.append(input_value.to_lc_message())
            else:
                messages.append(HumanMessage(content=input_value))

        if system_message and not system_message_added:
            messages.insert(0, SystemMessage(content=system_message))
        inputs: list | dict = messages or {}
        lf_message = None
        _llm_start = _time_mod.perf_counter()
        try:
            if hasattr(self, "output_parser") and self.output_parser is not None:
                runnable |= self.output_parser

            runnable = runnable.with_config(
                {
                    "run_name": self.display_name,
                    "project_name": self.get_project_name(),
                    "callbacks": self.get_langchain_callbacks(),
                }
            )
            if stream:
                lf_message, result, stream_ai_message = await self._handle_stream(runnable, inputs)
                if stream_ai_message is not None:
                    message = stream_ai_message
            else:
                message = runnable.invoke(inputs)
                result = message.content if hasattr(message, "content") else message
            if isinstance(message, AIMessage):
                status_message = self.build_status_message(message)
                self.status = status_message
                # Propagate token usage to Langfuse via trace_output_metadata.
                # When LLM calls go through the model-service microservice,
                # LangChain callbacks never see the real provider response,
                # so we must extract tokens from the AIMessage metadata.
                self._set_trace_usage_from_message(
                    message, duration_ms=(_time_mod.perf_counter() - _llm_start) * 1000
                )
            elif isinstance(result, dict):
                result = json.dumps(message, indent=4)
                self.status = result
            else:
                self.status = result
        except Exception as e:
            if message := self._get_exception_message(e):
                raise ValueError(message) from e
            raise
        return lf_message or Message(text=result)

    def _set_trace_usage_from_message(self, message: AIMessage, duration_ms: float = 0.0) -> None:
        """Extract token usage from AIMessage and set trace_output_metadata.

        Checks three sources in order:
        1. response_metadata.token_usage (OpenAI-style, non-streaming)
        2. response_metadata.usage (Anthropic-style, non-streaming)
        3. usage_metadata (LangChain standard, works with streaming chunks)
        """
        meta = message.response_metadata or {}

        input_tokens = 0
        output_tokens = 0
        model_name = meta.get("model_name") or meta.get("model") or ""

        # OpenAI-style (token_usage dict in response_metadata)
        token_usage = meta.get("token_usage")
        if isinstance(token_usage, dict):
            input_tokens = int(token_usage.get("prompt_tokens") or 0)
            output_tokens = int(token_usage.get("completion_tokens") or 0)

        # Anthropic-style (usage dict in response_metadata)
        if not (input_tokens or output_tokens):
            usage = meta.get("usage")
            if isinstance(usage, dict):
                input_tokens = int(usage.get("input_tokens") or 0)
                output_tokens = int(usage.get("output_tokens") or 0)

        # LangChain usage_metadata (standard for streaming chunks and newer providers)
        if not (input_tokens or output_tokens):
            usage_meta = getattr(message, "usage_metadata", None)
            if isinstance(usage_meta, dict):
                input_tokens = int(usage_meta.get("input_tokens") or 0)
                output_tokens = int(usage_meta.get("output_tokens") or 0)
                if not model_name:
                    model_name = usage_meta.get("model_name") or ""

        if input_tokens or output_tokens:
            self.trace_output_metadata = {
                "agentcore_usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                    "model": model_name,
                }
            }

        # Emit Prometheus metric for Grafana LLM dashboards
        from agentcore.observability.metrics_registry import record_llm_call
        record_llm_call(
            model_name=model_name or self.display_name,
            provider=getattr(self, "model_provider", "unknown"),
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def _handle_stream(self, runnable, inputs):
        """Handle streaming responses from the language model.

        Args:
            runnable: The language model configured for streaming
            inputs: The inputs to send to the model

        Returns:
            tuple: (Message object if connected to chat output, model result, AIMessage or None)
                   The third element carries the accumulated AIMessage with response_metadata
                   so the caller can extract token usage for Langfuse tracing.
        """
        from uuid import uuid4

        lf_message = None
        ai_message = None  # Will hold the full AIMessage if available
        if self.is_connected_to_chat_output():
            # Add a Message — use async streaming to avoid blocking the event loop
            if hasattr(self, "graph"):
                session_id = self.graph.session_id
            elif hasattr(self, "_session_id"):
                session_id = self._session_id
            else:
                session_id = None

            # Wrap the async generator to accumulate chunks for token usage
            # extraction while still passing them through to send_message.
            chunk_collector: list = []

            async def _accumulate_and_yield(astream):
                accumulated = None
                async for chunk in astream:
                    try:
                        accumulated = chunk if accumulated is None else accumulated + chunk
                    except TypeError:
                        pass
                    yield chunk
                if accumulated is not None:
                    chunk_collector.append(accumulated)

            model_message = Message(
                text=_accumulate_and_yield(runnable.astream(inputs)),
                sender=MESSAGE_SENDER_AI,
                sender_name="AI",
                properties={"icon": self.icon, "state": "partial"},
                session_id=session_id,
            )
            model_message.properties.source = self._build_source(self._id, self.display_name, self)
            lf_message = await self.send_message(model_message)
            result = lf_message.text
            # Extract the accumulated AIMessage with response_metadata / usage_metadata
            if chunk_collector and isinstance(chunk_collector[0], AIMessage):
                ai_message = chunk_collector[0]
        elif hasattr(self, "_event_manager") and self._event_manager:
            # Stream tokens directly via event_manager even when not
            # connected to ChatOutput (e.g. LLM → Agent → ChatOutput).
            # ChatOutput will still emit its own add_message with the
            # final text; the token events let the UI render progressively.
            import asyncio

            message_id = str(uuid4())
            complete = ""
            accumulated = None
            async for chunk in runnable.astream(inputs):
                # Accumulate chunks to build the full AIMessage with
                # response_metadata (token usage arrives in the last chunk).
                try:
                    accumulated = chunk if accumulated is None else accumulated + chunk
                except TypeError:
                    pass
                content = chunk.content if hasattr(chunk, "content") else str(chunk)
                complete += content
                self._event_manager.on_token(
                    data={"chunk": content, "id": message_id},
                )
                # Yield to the event loop so the queue consumer can
                # deliver the token to the client immediately.
                await asyncio.sleep(0)
            result = complete
            if isinstance(accumulated, AIMessage):
                ai_message = accumulated
        else:
            message = await runnable.ainvoke(inputs)
            result = message.content if hasattr(message, "content") else message
            if isinstance(message, AIMessage):
                ai_message = message
        return lf_message, result, ai_message

    @abstractmethod
    def build_model(self) -> LanguageModel:  # type: ignore[type-var]
        """Implement this method to build the model."""

    def get_llm(self, provider_name: str, model_info: dict[str, dict[str, str | list[InputTypes]]]) -> LanguageModel:
        """Get LLM model based on provider name and inputs.

        Args:
            provider_name: Name of the model provider (e.g."Azure OpenAI")
            inputs: Dictionary of input parameters for the model
            model_info: Dictionary of model information

        Returns:
            Built LLM model instance
        """
        try:
            if provider_name not in [model.get("display_name") for model in model_info.values()]:
                msg = f"Unknown model provider: {provider_name}"
                raise ValueError(msg)

            # Find the component class name from MODEL_INFO in a single iteration
            component_info, module_name = next(
                ((info, key) for key, info in model_info.items() if info.get("display_name") == provider_name),
                (None, None),
            )
            if not component_info:
                msg = f"Component information not found for {provider_name}"
                raise ValueError(msg)
            component_inputs = component_info.get("inputs", [])
            # Get the component class from the models module
            # Ensure component_inputs is a list of the expected types
            if not isinstance(component_inputs, list):
                component_inputs = []

            import warnings

            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore", message="Support for class-based `config`", category=DeprecationWarning
                )
                warnings.filterwarnings("ignore", message="Valid config keys have changed in V2", category=UserWarning)
                models_module = importlib.import_module("agentcore.components.models")
                component_class = getattr(models_module, str(module_name))
                component = component_class()

            return self.build_llm_model_from_inputs(component, component_inputs)
        except Exception as e:
            msg = f"Error building {provider_name} language model"
            raise ValueError(msg) from e

    def build_llm_model_from_inputs(
        self, component: Node, inputs: list[InputTypes], prefix: str = ""
    ) -> LanguageModel:
        """Build LLM model from component and inputs.

        Args:
            component: LLM component instance
            inputs: Dictionary of input parameters for the model
            prefix: Prefix for the input names
        Returns:
            Built LLM model instance
        """
        # Ensure prefix is a string
        prefix = prefix or ""
        # Filter inputs to only include valid component input names
        input_data = {
            str(component_input.name): getattr(self, f"{prefix}{component_input.name}", None)
            for component_input in inputs
        }

        return component.set(**input_data).build_model()
