from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, Sequence
from uuid import UUID

from loguru import logger
from typing_extensions import override
try:
    from langchain_core.callbacks.base import BaseCallbackHandler
except ImportError:
    from langchain.callbacks.base import BaseCallbackHandler

from agentcore.serialization.serialization import serialize
from agentcore.services.tracing.base import BaseTracer

if TYPE_CHECKING:
    from agentcore.graph_langgraph import LangGraphVertex as Vertex
    from agentcore.services.tracing.schema import Log


# ==========================================================
# LangChain callback wrapper (suppresses known errors)
# ==========================================================

class LangfuseCallbackWrapper(BaseCallbackHandler):
    """Wrapper for Langfuse callback that suppresses known errors."""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def _safe_call(self, method_name: str, *args, **kwargs):
        try:
            method = getattr(self._callback, method_name, None)
            if method:
                return method(*args, **kwargs)
        except KeyError as e:
            logger.debug(f"Suppressed Langfuse KeyError in {method_name}: {e}")
        except Exception as e:
            error_msg = str(e).lower()
            if 'parent run not found' in error_msg or 'run not found' in error_msg:
                logger.debug(f"Suppressed Langfuse tracing error in {method_name}: {e}")
            else:
                raise
        return None

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        return self._safe_call('on_llm_start', serialized, prompts, run_id=run_id, parent_run_id=parent_run_id, tags=tags, metadata=metadata, **kwargs)

    def on_llm_new_token(self, token, *, chunk=None, run_id, parent_run_id=None, tags=None, **kwargs):
        return self._safe_call('on_llm_new_token', token, chunk=chunk, run_id=run_id, parent_run_id=parent_run_id, tags=tags, **kwargs)

    def on_llm_end(self, response, *, run_id, parent_run_id=None, tags=None, **kwargs):
        return self._safe_call('on_llm_end', response, run_id=run_id, parent_run_id=parent_run_id, tags=tags, **kwargs)

    def on_llm_error(self, error, *, run_id, parent_run_id=None, tags=None, **kwargs):
        return self._safe_call('on_llm_error', error, run_id=run_id, parent_run_id=parent_run_id, tags=tags, **kwargs)

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        return self._safe_call('on_chat_model_start', serialized, messages, run_id=run_id, parent_run_id=parent_run_id, tags=tags, metadata=metadata, **kwargs)

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        return self._safe_call('on_chain_start', serialized, inputs, run_id=run_id, parent_run_id=parent_run_id, tags=tags, metadata=metadata, **kwargs)

    def on_chain_end(self, outputs, *, run_id, parent_run_id=None, tags=None, **kwargs):
        return self._safe_call('on_chain_end', outputs, run_id=run_id, parent_run_id=parent_run_id, tags=tags, **kwargs)

    def on_chain_error(self, error, *, run_id, parent_run_id=None, tags=None, **kwargs):
        return self._safe_call('on_chain_error', error, run_id=run_id, parent_run_id=parent_run_id, tags=tags, **kwargs)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        return self._safe_call('on_tool_start', serialized, input_str, run_id=run_id, parent_run_id=parent_run_id, tags=tags, metadata=metadata, **kwargs)

    def on_tool_end(self, output, *, run_id, parent_run_id=None, tags=None, **kwargs):
        return self._safe_call('on_tool_end', output, run_id=run_id, parent_run_id=parent_run_id, tags=tags, **kwargs)

    def on_tool_error(self, error, *, run_id, parent_run_id=None, tags=None, **kwargs):
        return self._safe_call('on_tool_error', error, run_id=run_id, parent_run_id=parent_run_id, tags=tags, **kwargs)

    def on_retriever_start(self, serialized, query, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        return self._safe_call('on_retriever_start', serialized, query, run_id=run_id, parent_run_id=parent_run_id, tags=tags, metadata=metadata, **kwargs)

    def on_retriever_end(self, documents, *, run_id, parent_run_id=None, tags=None, **kwargs):
        return self._safe_call('on_retriever_end', documents, run_id=run_id, parent_run_id=parent_run_id, tags=tags, **kwargs)

    def on_retriever_error(self, error, *, run_id, parent_run_id=None, tags=None, **kwargs):
        return self._safe_call('on_retriever_error', error, run_id=run_id, parent_run_id=parent_run_id, tags=tags, **kwargs)

    def __getattr__(self, name):
        return getattr(self._callback, name)


# ==========================================================
# Langfuse v3 Tracer (OTEL-based with proper nested spans)
# ==========================================================

class LangFuseTracer(BaseTracer):
    """
    Langfuse v3 tracer using official OTEL-based API.

    Uses start_as_current_observation() with input passed directly,
    propagate_attributes() for user_id/session_id, and proper context management.
    """

    def __init__(
        self,
        trace_name: str,
        trace_type: str,
        project_name: str,
        trace_id: UUID,
        user_id: str | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
        agent_name: str | None = None,
        observability_project_id: str | None = None,
        observability_project_name: str | None = None,
    ) -> None:
        self.trace_name = trace_name
        self.trace_type = trace_type
        self.project_name = project_name
        self.trace_id = trace_id
        self.user_id = user_id
        self.session_id = session_id
        self.agent_id = agent_id or trace_name
        self.agent_name = agent_name
        self.observability_project_id = observability_project_id
        self.observability_project_name = observability_project_name

        # Span tracking
        self.spans: dict[str, Any] = {}
        self._span_contexts: dict[str, Any] = {}
        self._span_stack: list[Any] = []

        self._ready = False
        self._client = None
        self._root_span = None
        self._root_context = None
        self._propagate_context = None

        self._setup_langfuse()

    @property
    def ready(self) -> bool:
        return self._ready

    def _setup_langfuse(self) -> None:
        """Initialize Langfuse v3 client using official OTEL-based API."""
        try:
            from langfuse import Langfuse, propagate_attributes

            # Ensure env vars are set (v3 reads from env)
            if not os.getenv("LANGFUSE_BASE_URL"):
                host = os.getenv("LANGFUSE_HOST", "")
                if host:
                    os.environ["LANGFUSE_BASE_URL"] = host

            # Block POST/HTTP spans from OTEL auto-instrumentation
            # These come from FastAPI, HTTP clients, etc.
            blocked_scopes = [
                # FastAPI/ASGI instrumentation (causes POST /api/build/... spans)
                "fastapi",
                "starlette",
                "asgi",
                "opentelemetry.instrumentation.fastapi",
                "opentelemetry.instrumentation.starlette",
                "opentelemetry.instrumentation.asgi",
                # HTTP client instrumentation
                "httpx",
                "aiohttp",
                "requests",
                "urllib3",
                "opentelemetry.instrumentation.httpx",
                "opentelemetry.instrumentation.aiohttp",
                "opentelemetry.instrumentation.requests",
                "opentelemetry.instrumentation.urllib3",
            ]

            # Try to create Langfuse client with blocked_instrumentation_scopes
            # If not supported, fall back to regular client
            try:
                self._client = Langfuse(blocked_instrumentation_scopes=blocked_scopes)
            except TypeError:
                # blocked_instrumentation_scopes not supported in this version
                from langfuse import get_client
                self._client = get_client()

            # Health check - log but continue if it fails
            # The auth_check can fail for various reasons (network, wrong credentials, etc.)
            # but we want to attempt tracing anyway since the client might still work
            if hasattr(self._client, 'auth_check'):
                try:
                    if not self._client.auth_check():
                        logger.warning(
                            f"Langfuse auth_check failed for agent={self.agent_name}. "
                            f"Check LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_BASE_URL. "
                            f"Will attempt to continue anyway."
                        )
                    else:
                        logger.debug(f"Langfuse auth_check passed for agent={self.agent_name}")
                except Exception as e:
                    logger.warning(f"Langfuse auth_check error (continuing anyway): {e}")

            # Build trace metadata
            trace_metadata = {
                "agent_id": self.agent_id,
                "agent_name": self.agent_name,
                "run_id": str(self.trace_id),
                "user_id": self.user_id,
                "session_id": self.session_id,
            }
            if self.observability_project_id:
                trace_metadata["project_id"] = self.observability_project_id
            if self.observability_project_name:
                trace_metadata["project_name"] = self.observability_project_name

            # v3: Create root span using start_as_current_observation
            # The root span becomes the trace, input/output derive from it
            self._root_context = self._client.start_as_current_observation(
                as_type="span",
                name=self.agent_name or self.agent_id,
                metadata=trace_metadata,
            )
            self._root_span = self._root_context.__enter__()

            # v3: Use propagate_attributes for user_id, session_id
            self._propagate_context = propagate_attributes(
                user_id=self.user_id,
                session_id=self.session_id,
            )
            self._propagate_context.__enter__()

            self._ready = True
            logger.info(f"Langfuse v3 tracer ready: agent={self.agent_name}, user={self.user_id}, session={self.session_id}")

        except ImportError:
            logger.warning("langfuse not installed - tracing disabled")
        except Exception as e:
            logger.error(f"Error setting up Langfuse tracer for agent={self.agent_name}: {e}", exc_info=True)

    # ======================================================
    # Span lifecycle
    # ======================================================

    @override
    def add_trace(
        self,
        trace_id: str,
        trace_name: str,
        trace_type: str,
        inputs: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        vertex: Vertex | None = None,
    ) -> None:
        """Add a new span using v3 start_as_current_observation with input passed directly."""
        if not self._ready:
            return

        name = trace_name.removesuffix(f" ({trace_id})")

        # Prevent duplicate root span if the component name matches the agent name
        root_name = self.agent_name or self.agent_id
        if root_name and name == root_name:
            return

        span_metadata = {
            "from_agentcore_component": True,
            "component_id": trace_id,
            "trace_type": trace_type,
        }
        span_metadata |= metadata or {}

        try:
            observation_type = "generation" if str(trace_type).lower() == "guardrail" else "span"
            # v3: Create span with input passed directly to start_as_current_observation
            span_context = self._client.start_as_current_observation(
                as_type=observation_type,
                name=name,
                input=serialize(inputs),  # Input passed directly!
                metadata=span_metadata,
            )
            span = span_context.__enter__()

            self.spans[trace_id] = span
            self._span_contexts[trace_id] = span_context
            self._span_stack.append(span)
        except Exception as e:
            logger.debug(f"Error creating span: {e}")

    @override
    def end_trace(
        self,
        trace_id: str,
        trace_name: str,
        outputs: dict[str, Any] | None = None,
        output_metadata: dict[str, Any] | None = None,
        error: Exception | None = None,
        logs: Sequence[Log | dict] = (),
    ) -> None:
        """End a span using v3 span.update() then context exit."""
        if not self._ready:
            return

        span = self.spans.pop(trace_id, None)
        span_context = self._span_contexts.pop(trace_id, None)

        if not span:
            return

        output = outputs or {}
        if error:
            output["error"] = str(error)
        if logs:
            output["logs"] = list(logs)

        try:
            # v3: Update span with output before exiting
            if hasattr(span, 'update'):
                update_payload: dict[str, Any] = {"output": serialize(output)}

                usage_payload: dict[str, Any] | None = None
                model_name: str | None = None
                if isinstance(output_metadata, dict):
                    usage_candidate = output_metadata.get("agentcore_usage")
                    if isinstance(usage_candidate, str):
                        try:
                            usage_candidate = json.loads(usage_candidate)
                        except Exception:
                            usage_candidate = None
                    if isinstance(usage_candidate, dict):
                        input_tokens = int(usage_candidate.get("input_tokens") or usage_candidate.get("input") or 0)
                        output_tokens = int(usage_candidate.get("output_tokens") or usage_candidate.get("output") or 0)
                        total_tokens = int(usage_candidate.get("total_tokens") or usage_candidate.get("total") or 0)
                        if total_tokens == 0 and (input_tokens or output_tokens):
                            total_tokens = input_tokens + output_tokens
                        if input_tokens or output_tokens or total_tokens:
                            usage_payload = {
                                "input": input_tokens,
                                "output": output_tokens,
                                "total": total_tokens,
                            }
                        model_name = usage_candidate.get("model")

                if output_metadata:
                    update_payload["metadata"] = serialize(output_metadata)
                if usage_payload:
                    # Langfuse v3 style
                    update_payload["usage_details"] = usage_payload
                    # Backward compatibility for some SDK paths
                    update_payload["usage"] = usage_payload
                if model_name:
                    update_payload["model"] = str(model_name)
                span.update(**update_payload)

            # Exit the span context
            if span_context:
                span_context.__exit__(None, None, None)
        except Exception as e:
            logger.debug(f"Error ending span: {e}")

        # Pop from stack
        if self._span_stack and self._span_stack[-1] == span:
            self._span_stack.pop()

    # ======================================================
    # End trace
    # ======================================================

    @override
    def end(
        self,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        error: Exception | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """End the root trace using v3 update_trace() API."""
        if not self._ready:
            return

        try:
            # v3: Use update on root span (which is now a trace) to set trace-level input/output
            if self._root_span and hasattr(self._root_span, 'update'):
                self._root_span.update(
                    input=serialize(inputs),
                    output=serialize(outputs),
                    metadata=metadata,
                )

            # Exit propagate_attributes context
            if self._propagate_context:
                self._propagate_context.__exit__(None, None, None)

            # Exit root span context
            if self._root_context:
                self._root_context.__exit__(None, None, None)

        except Exception as e:
            logger.warning(f"Error ending trace: {e}")

        # Flush
        try:
            if hasattr(self._client, 'flush'):
                self._client.flush()
        except Exception:
            pass

    # ======================================================
    # LangChain callback
    # ======================================================

    def get_langchain_callback(self) -> BaseCallbackHandler | None:
        """Get LangChain callback using v3 metadata fields approach."""
        if not self._ready:
            return None

        try:
            # v3: Use langfuse.langchain.CallbackHandler
            from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

            callback = LangfuseCallbackHandler()
            return LangfuseCallbackWrapper(callback)
        except ImportError:
            try:
                # Fallback import path
                from langfuse.callback import CallbackHandler as LangfuseCallbackHandler
                callback = LangfuseCallbackHandler()
                return LangfuseCallbackWrapper(callback)
            except ImportError:
                logger.debug("langfuse.langchain not available")
                return None
        except Exception:
            return None
