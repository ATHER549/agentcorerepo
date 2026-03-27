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
    from agentcore.graph_langgraph import LangGraphVertex
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
# Write-path Langfuse client factory
# ==========================================================

_BLOCKED_INSTRUMENTATION_SCOPES = [
    "fastapi", "starlette", "asgi",
    "opentelemetry.instrumentation.fastapi",
    "opentelemetry.instrumentation.starlette",
    "opentelemetry.instrumentation.asgi",
    "httpx", "aiohttp", "requests", "urllib3",
    "opentelemetry.instrumentation.httpx",
    "opentelemetry.instrumentation.aiohttp",
    "opentelemetry.instrumentation.requests",
    "opentelemetry.instrumentation.urllib3",
]

_WRITE_CLIENT_CACHE: dict[str, Any] = {}


def _get_or_create_write_client(
    host: str | None,
    public_key: str | None,
    secret_key: str | None,
    environment: str | None,
) -> Any:
    """Return a cached Langfuse client for trace writing, creating one if needed.

    Reusing the client keeps the same OTEL TracerProvider/SpanExporter across
    traces so buffered spans are not lost between traces.
    """
    cache_key = f"{host or ''}:{public_key or ''}:{environment or ''}"
    cached = _WRITE_CLIENT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    from langfuse import Langfuse

    kwargs: dict[str, Any] = {}
    if host:
        kwargs["host"] = host
    if public_key:
        kwargs["public_key"] = public_key
    if secret_key:
        kwargs["secret_key"] = secret_key
    if environment:
        kwargs["environment"] = environment

    try:
        client = Langfuse(
            blocked_instrumentation_scopes=_BLOCKED_INSTRUMENTATION_SCOPES,
            **kwargs,
        )
    except TypeError:
        try:
            client = Langfuse(**kwargs)
        except TypeError:
            from langfuse import get_client
            if kwargs:
                raise
            client = get_client()

    if hasattr(client, "auth_check"):
        try:
            if not client.auth_check():
                logger.warning("Langfuse auth_check failed — check credentials")
            else:
                logger.debug("Langfuse write-client auth_check passed")
        except Exception as e:
            logger.warning(f"Langfuse auth_check error (continuing): {e}")

    _WRITE_CLIENT_CACHE[cache_key] = client
    logger.info(f"Created and cached Langfuse write-client for {cache_key}")
    return client


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
        langfuse_host: str | None = None,
        langfuse_public_key: str | None = None,
        langfuse_secret_key: str | None = None,
        environment: str | None = None,
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
        self.langfuse_host = langfuse_host
        self.langfuse_public_key = langfuse_public_key
        self.langfuse_secret_key = langfuse_secret_key
        self.environment = environment

        # Span tracking
        self.spans: dict[str, Any] = {}
        self._span_contexts: dict[str, Any] = {}
        self._span_stack: list[Any] = []

        self._ready = False
        self._client = None
        self._root_span = None
        self._root_context = None
        self._propagate_context = None
        self._otel_reset_token = None  # Token for detaching the clean OTEL context

        # Accumulate token usage from child spans so the root span carries
        # trace-level totals — prevents needing per-trace observation API calls
        # in Langfuse list views (v3 OTEL does not auto-roll-up span tokens).
        self._accumulated_tokens: dict[str, int] = {"input": 0, "output": 0, "total": 0}
        self._accumulated_model: str | None = None

        self._setup_langfuse()

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def langfuse_trace_id(self) -> str | None:
        """Return the actual Langfuse/OTEL trace ID (hex format)."""
        return getattr(self, "_langfuse_trace_id", None)

    def _setup_langfuse(self) -> None:
        """Initialize Langfuse v3 client using official OTEL-based API."""
        try:
            from langfuse import propagate_attributes

            host = self.langfuse_host or os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")

            # Fallback to env propagation only when explicit runtime host is not provided.
            if not self.langfuse_host and host and not os.getenv("LANGFUSE_BASE_URL"):
                os.environ["LANGFUSE_BASE_URL"] = str(host)

            # Reuse a cached client to keep the same OTEL TracerProvider/SpanExporter
            # across traces so buffered spans are not lost between traces.
            self._client = _get_or_create_write_client(
                host=host,
                public_key=self.langfuse_public_key,
                secret_key=self.langfuse_secret_key,
                environment=self.environment,
            )

            # Build trace metadata.  Include an explicit UTC timestamp so the
            # observability layer can use it instead of Langfuse's potentially
            # timezone-inconsistent trace timestamp.
            from datetime import datetime as _dt, timezone as _tz
            trace_metadata = {
                "agent_id": self.agent_id,
                "agent_name": self.agent_name,
                "run_id": str(self.trace_id),
                "user_id": self.user_id,
                "session_id": self.session_id,
                "trace_created_at_utc": _dt.now(_tz.utc).isoformat(),
            }
            if self.observability_project_id:
                trace_metadata["project_id"] = self.observability_project_id
            if self.observability_project_name:
                trace_metadata["project_name"] = self.observability_project_name
            if self.environment:
                trace_metadata["environment"] = self.environment

            # Clear any existing OTEL context so our root span always creates
            # a NEW top-level trace.  Without this, auto-instrumented spans
            # (FastAPI, HTTP clients, or prior Langfuse clients) can become the
            # parent, resulting in an "Unnamed trace" wrapper in the Langfuse UI.
            try:
                from opentelemetry import context as otel_context
                self._otel_reset_token = otel_context.attach(otel_context.Context())
            except ImportError:
                pass

            # v3: Create root span as the trace container.  Child component
            # spans (Worker Node, etc.) are created as "generation" and carry
            # their own token/cost data.  Langfuse aggregates child generation
            # metrics to the trace level automatically.
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

            # Extract the actual Langfuse/OTEL trace ID (hex format)
            self._langfuse_trace_id = None
            try:
                from opentelemetry import trace as otel_trace
                current_span = otel_trace.get_current_span()
                if current_span and current_span.get_span_context().is_valid:
                    self._langfuse_trace_id = format(current_span.get_span_context().trace_id, '032x')
                    logger.info(f"Langfuse OTEL trace_id={self._langfuse_trace_id}")
            except Exception:
                pass

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
        vertex: LangGraphVertex | None = None,
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
            # Use "generation" for components that produce LLM token usage so
            # Langfuse displays token counts, model info, and cost in its UI.
            # Agent-type nodes (Worker Node, etc.) also carry token usage from
            # their internal LLM calls, so they need "generation" too.
            # "span" observations do not show token metrics in the Langfuse UI.
            observation_type = "generation" if str(trace_type).lower() in ("llm", "guardrail", "agent") else "span"
            # v3: Create span with input passed directly to start_as_current_observation
            span_context = self._client.start_as_current_observation(
                as_type=observation_type,
                name=name,
                input=serialize(inputs),
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
                    # Roll up to tracer-level accumulator so the root span can
                    # carry trace-level token totals for Langfuse list views.
                    self._accumulated_tokens["input"] += usage_payload.get("input", 0)
                    self._accumulated_tokens["output"] += usage_payload.get("output", 0)
                    self._accumulated_tokens["total"] += usage_payload.get("total", 0)
                if model_name:
                    update_payload["model"] = str(model_name)
                    # Capture the first model used for root span attribution.
                    if not self._accumulated_model:
                        self._accumulated_model = model_name
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
            # v3: Use update on root span (which is now a trace) to set trace-level input/output.
            # Also propagate accumulated token totals and model so Langfuse stores them at
            # the trace level — this way list-API responses include token counts and observation
            # fallback fetches are unnecessary for aggregated views.
            if self._root_span and hasattr(self._root_span, 'update'):
                root_update: dict[str, Any] = {
                    "input": serialize(inputs),
                    "output": serialize(outputs),
                    "metadata": metadata,
                }
                if error is not None:
                    root_update["level"] = "ERROR"
                    root_update["status_message"] = str(error)
                # Do NOT write accumulated tokens to the root span — child
                # generation spans already carry token/cost data.  Writing
                # them here too causes Langfuse to double-count at the trace
                # level (root usage + child usage).
                if self._accumulated_model:
                    root_update["model"] = self._accumulated_model
                self._root_span.update(**root_update)

            # Exit propagate_attributes context
            if self._propagate_context:
                self._propagate_context.__exit__(None, None, None)

            # Exit root span context
            if self._root_context:
                self._root_context.__exit__(None, None, None)

        except Exception as e:
            logger.warning(f"Error ending trace: {e}")

        # Detach the clean OTEL context we attached during setup
        if self._otel_reset_token is not None:
            try:
                from opentelemetry import context as otel_context
                otel_context.detach(self._otel_reset_token)
                self._otel_reset_token = None
            except Exception:
                pass

        # Flush both the Langfuse client buffer AND the OTEL span processor.
        # The Langfuse client.flush() may only flush its own REST queue, while
        # OTEL spans sit in the BatchSpanProcessor's separate buffer.  Without
        # flushing both, earlier traces' spans can be lost before the next trace
        # starts.
        try:
            if hasattr(self._client, 'flush'):
                self._client.flush()
        except Exception:
            pass
        try:
            from opentelemetry import trace as otel_trace
            provider = otel_trace.get_tracer_provider()
            if hasattr(provider, 'force_flush'):
                provider.force_flush(timeout_millis=5000)
        except Exception:
            pass

    # ======================================================
    # LangChain callback
    # ======================================================

    def get_langchain_callback(self) -> BaseCallbackHandler | None:
        """Get LangChain callback using v3 metadata fields approach."""
        if not self._ready:
            return None

        callback_kwargs: dict[str, Any] = {}
        if self.langfuse_host:
            callback_kwargs["host"] = self.langfuse_host
        if self.langfuse_public_key:
            callback_kwargs["public_key"] = self.langfuse_public_key
        if self.langfuse_secret_key:
            callback_kwargs["secret_key"] = self.langfuse_secret_key

        try:
            # v3: Use langfuse.langchain.CallbackHandler
            from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

            try:
                callback = LangfuseCallbackHandler(**callback_kwargs)
            except TypeError:
                if callback_kwargs:
                    logger.warning(
                        "Langfuse callback handler does not accept explicit credentials; "
                        "skipping callback to avoid cross-tenant leakage."
                    )
                    return None
                callback = LangfuseCallbackHandler()
            return LangfuseCallbackWrapper(callback)
        except ImportError:
            try:
                # Fallback import path
                from langfuse.callback import CallbackHandler as LangfuseCallbackHandler
                try:
                    callback = LangfuseCallbackHandler(**callback_kwargs)
                except TypeError:
                    if callback_kwargs:
                        logger.warning(
                            "Langfuse callback handler does not accept explicit credentials; "
                            "skipping callback to avoid cross-tenant leakage."
                        )
                        return None
                    callback = LangfuseCallbackHandler()
                return LangfuseCallbackWrapper(callback)
            except ImportError:
                logger.debug("langfuse.langchain not available")
                return None
        except Exception:
            return None
