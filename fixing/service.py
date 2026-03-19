from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from loguru import logger

from agentcore.services.base import Service
from agentcore.services.auth.permissions import normalize_role
from agentcore.services.deps import session_scope
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.user.model import User
from agentcore.services.observability import (
    get_langfuse_provisioning_service,
    resolve_write_langfuse_binding,
)

if TYPE_CHECKING:
    from uuid import UUID

    from langchain_core.callbacks import BaseCallbackHandler

    from agentcore.custom.custom_node.node import Node
    from agentcore.graph_langgraph import LangGraphVertex
    from agentcore.services.settings.service import SettingsService
    from agentcore.services.tracing.base import BaseTracer
    from agentcore.services.tracing.schema import Log


def _get_langfuse_tracer():
    from agentcore.services.tracing.langfuse import LangFuseTracer

    return LangFuseTracer


trace_context_var: ContextVar[TraceContext | None] = ContextVar("trace_context", default=None)
component_context_var: ContextVar[ComponentTraceContext | None] = ContextVar("component_trace_context", default=None)

# Keep strong references to background tasks to prevent "Task was destroyed but pending" warnings
_background_tasks: set[asyncio.Task] = set()


class TraceContext:
    def __init__(
        self,
        run_id: UUID | None,
        run_name: str | None,
        project_name: str | None,
        user_id: str | None,
        session_id: str | None,
        agent_id: str | None = None,
        agent_name: str | None = None,
        observability_project_id: str | None = None,
        observability_project_name: str | None = None,
        environment: str | None = None,
    ):
        self.run_id: UUID | None = run_id
        self.run_name: str | None = run_name
        self.project_name: str | None = project_name
        self.user_id: str | None = user_id
        self.session_id: str | None = session_id
        # Observability tracking fields
        self.agent_id: str | None = agent_id
        self.agent_name: str | None = agent_name
        self.observability_project_id: str | None = observability_project_id
        self.observability_project_name: str | None = observability_project_name
        # Langfuse environment for logical separation (e.g. "uat", "production")
        self.environment: str | None = environment
        self.langfuse_host: str | None = None
        self.langfuse_public_key: str | None = None
        self.langfuse_secret_key: str | None = None
        self.langfuse_credentials_resolved: bool = False
        self.tracers: dict[str, BaseTracer] = {}
        self.all_inputs: dict[str, dict] = defaultdict(dict)
        self.all_outputs: dict[str, dict] = defaultdict(dict)

        self.traces_queue: asyncio.Queue = asyncio.Queue()
        self.running = False
        self.worker_task: asyncio.Task | None = None


class ComponentTraceContext:
    def __init__(
        self,
        trace_id: str,
        trace_name: str,
        trace_type: str,
        vertex: LangGraphVertex | None,
        inputs: dict[str, dict],
        metadata: dict[str, dict] | None = None,
    ):
        self.trace_id: str = trace_id
        self.trace_name: str = trace_name
        self.trace_type: str = trace_type
        self.vertex: LangGraphVertex | None = vertex
        self.inputs: dict[str, dict] = inputs
        self.inputs_metadata: dict[str, dict] = metadata or {}
        self.outputs: dict[str, dict] = defaultdict(dict)
        self.outputs_metadata: dict[str, dict] = defaultdict(dict)
        self.logs: dict[str, list[Log | dict[Any, Any]]] = defaultdict(list)


class TracingService(Service):
    """Tracing service.

    To trace a graph run:
        1. start_tracers: start a trace for a graph run
        2. with trace_component: start a sub-trace for a component build, three methods are available:
            - add_log
            - set_outputs
            - get_langchain_callbacks
        3. end_tracers: end the trace for a graph run

    check context var in public methods.
    """

    name = "tracing_service"

    def __init__(self, settings_service: SettingsService):
        self.settings_service = settings_service
        self.deactivated = self.settings_service.settings.deactivate_tracing
        logger.info(f"TracingService initialized: deactivated={self.deactivated}")

    async def _trace_worker(self, trace_context: TraceContext) -> None:
        try:
            while trace_context.running or not trace_context.traces_queue.empty():
                trace_func, args = await trace_context.traces_queue.get()
                try:
                    trace_func(*args)
                except Exception:  # noqa: BLE001
                    logger.exception("Error processing trace_func")
                finally:
                    trace_context.traces_queue.task_done()
        except asyncio.CancelledError:
            # Graceful shutdown — drain remaining items before exiting
            while not trace_context.traces_queue.empty():
                try:
                    trace_func, args = trace_context.traces_queue.get_nowait()
                    trace_func(*args)
                    trace_context.traces_queue.task_done()
                except Exception:  # noqa: BLE001
                    break

    async def _start(self, trace_context: TraceContext) -> None:
        if trace_context.running or self.deactivated:
            return
        try:
            trace_context.running = True
            trace_context.worker_task = asyncio.create_task(self._trace_worker(trace_context))
            _background_tasks.add(trace_context.worker_task)
            trace_context.worker_task.add_done_callback(_background_tasks.discard)
        except Exception:  # noqa: BLE001
            logger.exception("Error starting tracing service")

    def _initialize_langfuse_tracer(self, trace_context: TraceContext) -> None:
        if self.deactivated:
            logger.warning("🚫 Langfuse tracer init skipped - tracing deactivated")
            return
        if not trace_context.langfuse_credentials_resolved:
            logger.warning(
                "Langfuse tracer init skipped - no scoped binding credentials resolved for user={} agent={}",
                trace_context.user_id,
                trace_context.agent_id,
            )
            return
        logger.info(f"Creating LangFuseTracer instance for agent={trace_context.agent_name}")
        langfuse_tracer = _get_langfuse_tracer()
        tracer_instance = langfuse_tracer(
            trace_name=trace_context.run_name,
            trace_type="chain",
            project_name=trace_context.project_name,
            trace_id=trace_context.run_id,
            user_id=trace_context.user_id,
            session_id=trace_context.session_id,
            agent_id=trace_context.agent_id,
            agent_name=trace_context.agent_name,
            observability_project_id=trace_context.observability_project_id,
            observability_project_name=trace_context.observability_project_name,
            langfuse_host=trace_context.langfuse_host,
            langfuse_public_key=trace_context.langfuse_public_key,
            langfuse_secret_key=trace_context.langfuse_secret_key,
            environment=trace_context.environment,
        )
        trace_context.tracers["langfuse"] = tracer_instance
        logger.info(f"LangFuseTracer created: ready={tracer_instance.ready}, agent={trace_context.agent_name}")

    async def _resolve_langfuse_credentials(self, trace_context: TraceContext) -> None:
        if not trace_context.user_id:
            return
        try:
            user_uuid = UUID(str(trace_context.user_id))
        except (ValueError, TypeError):
            logger.warning("Skipping Langfuse binding resolution: invalid user_id={}", trace_context.user_id)
            return

        agent_uuid: UUID | None = None
        if trace_context.agent_id:
            try:
                agent_uuid = UUID(str(trace_context.agent_id))
            except (ValueError, TypeError):
                agent_uuid = None

        try:
            async with session_scope() as session:
                provisioning_service = get_langfuse_provisioning_service()
                binding = await resolve_write_langfuse_binding(
                    session,
                    user_id=user_uuid,
                    agent_id=agent_uuid,
                    selected_dept_id=None,
                )

                if not binding:
                    actor = await session.get(User, user_uuid)
                    actor_role = normalize_role(actor.role) if actor else ""
                    if actor and actor_role == "root":
                        is_unscoped_root_agent = True
                        if agent_uuid is not None:
                            agent = await session.get(Agent, agent_uuid)
                            if agent and (agent.org_id is not None or agent.dept_id is not None):
                                is_unscoped_root_agent = False
                        if is_unscoped_root_agent:
                            try:
                                binding = await provisioning_service.ensure_root_private_binding(
                                    session,
                                    actor=actor,
                                )
                                await session.commit()
                                logger.info(
                                    "Resolved root-private Langfuse binding for root trace write user_id={} agent_id={}",
                                    user_uuid,
                                    agent_uuid,
                                )
                            except Exception:
                                await session.rollback()
                                logger.exception(
                                    "Failed ensuring root-private Langfuse binding for user_id={} agent_id={}",
                                    user_uuid,
                                    agent_uuid,
                                )

                if not binding:
                    logger.warning(
                        "No active Langfuse binding resolved for trace write user_id={} agent_id={}",
                        user_uuid,
                        agent_uuid,
                    )
                    return
                trace_context.langfuse_host = binding.langfuse_host
                trace_context.langfuse_public_key = provisioning_service.decrypt_secret(
                    binding.public_key_encrypted
                )
                trace_context.langfuse_secret_key = provisioning_service.decrypt_secret(
                    binding.secret_key_encrypted
                )
                trace_context.langfuse_credentials_resolved = bool(
                    trace_context.langfuse_host
                    and trace_context.langfuse_public_key
                    and trace_context.langfuse_secret_key
                )
        except Exception:
            logger.exception(
                "Failed resolving Langfuse binding for trace write user_id={} agent_id={}",
                user_uuid,
                agent_uuid,
            )

    async def start_tracers(
        self,
        run_id: UUID,
        run_name: str,
        user_id: str | None,
        session_id: str | None,
        project_name: str | None = None,
        agent_id: str | None = None,
        agent_name: str | None = None,
        observability_project_id: str | None = None,
        observability_project_name: str | None = None,
        environment: str | None = None,
    ) -> None:
        """Start a trace for a graph run.

        - create a trace context
        - start a worker for this trace context
        - initialize the tracers

        Args:
            run_id: Unique identifier for this run
            run_name: Name of this run (typically agent_name - agent_id)
            user_id: User ID for observability isolation
            session_id: Session ID for grouping related traces
            project_name: Langchain project name
            agent_id: Agent UUID for observability tracking
            agent_name: Agent name for observability display
            observability_project_id: Folder ID for project-level grouping
            observability_project_name: Folder name for project display
            environment: Langfuse environment tag ("uat" or "production")
        """
        if self.deactivated:
            logger.warning(f"TRACING DEACTIVATED - skipping tracer start for agent={agent_name}")
            return
        try:
            project_name = project_name or os.getenv("LANGCHAIN_PROJECT", "Agentcore")
            # Session-centric observability views require a session_id.
            # If upstream did not provide one, fall back to run_id so the trace is still discoverable.
            effective_session_id = session_id or str(run_id)
            logger.info(f"Creating trace context: agent={agent_name}, user={user_id}, session={session_id}")
            trace_context = TraceContext(
                run_id=run_id,
                run_name=run_name,
                project_name=project_name,
                user_id=user_id,
                session_id=effective_session_id,
                agent_id=agent_id,
                agent_name=agent_name,
                observability_project_id=observability_project_id,
                observability_project_name=observability_project_name,
                environment=environment,
            )
            trace_context_var.set(trace_context)
            await self._resolve_langfuse_credentials(trace_context)
            
            logger.info(f"Initializing Langfuse tracer for agent={agent_name}")
            self._initialize_langfuse_tracer(trace_context)
            logger.info(f"Starting trace worker for agent={agent_name}")
            await self._start(trace_context)
            logger.info(f"Trace context ready for agent={agent_name}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error initializing tracers for agent={agent_name}: {e}", exc_info=True)

    async def _stop(self, trace_context: TraceContext) -> None:
        try:
            trace_context.running = False
            # Drain any remaining items in the queue
            if not trace_context.traces_queue.empty():
                await trace_context.traces_queue.join()
            if trace_context.worker_task:
                trace_context.worker_task.cancel()
                try:
                    await trace_context.worker_task
                except (asyncio.CancelledError, Exception):
                    pass
                trace_context.worker_task = None

        except Exception:  # noqa: BLE001
            logger.exception("Error stopping tracing service")

    def _end_all_tracers(self, trace_context: TraceContext, outputs: dict, error: Exception | None = None) -> None:
        for name, tracer in trace_context.tracers.items():
            if tracer.ready:
                try:
                    # why all_inputs and all_outputs? why metadata=outputs?
                    tracer.end(
                        trace_context.all_inputs,
                        outputs=trace_context.all_outputs,
                        error=error,
                        metadata=outputs,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Error ending tracer '{name}': {e}")

    def _schedule_new_trace_evaluations(self, trace_context: TraceContext) -> None:
        """Trigger evaluators configured for 'new' traces (fire-and-forget)."""
        if not trace_context.user_id or not trace_context.run_id:
            logger.info("⏭️ Skipping evaluator scheduling: missing user_id or run_id")
            return

        # Extract the real Langfuse/OTEL trace ID from the tracer
        effective_trace_id = str(trace_context.run_id)
        lf_tracer = (trace_context.tracers or {}).get("langfuse")
        if lf_tracer and hasattr(lf_tracer, "langfuse_trace_id") and lf_tracer.langfuse_trace_id:
            effective_trace_id = lf_tracer.langfuse_trace_id
            logger.info(f"Using Langfuse OTEL trace_id={effective_trace_id} for evaluator scheduling (run_id={trace_context.run_id})")

        logger.info(
            f"SCHEDULING EVALUATORS: trace={effective_trace_id}, "
            f"agent={trace_context.agent_name}, agent_id={trace_context.agent_id}, "
            f"user={trace_context.user_id}, session={trace_context.session_id}"
        )

        try:
            from agentcore.api.evaluation import run_saved_evaluators_for_new_trace

            # Pass trace input/output directly so the evaluator doesn't need
            # to re-fetch from Langfuse (which may not have ingested yet).
            # Also pass the tracer's Langfuse client so scores go to the same project.
            trace_input = trace_context.all_inputs
            trace_output = trace_context.all_outputs
            tracer_lf_client = getattr(lf_tracer, "_client", None) if lf_tracer else None
            logger.info(f"Evaluator scheduling: lf_tracer={'present' if lf_tracer else 'None'}, tracer_client={'present' if tracer_lf_client else 'None'}")
            asyncio.create_task(
                run_saved_evaluators_for_new_trace(
                    trace_id=effective_trace_id,
                    user_id=str(trace_context.user_id),
                    agent_id=trace_context.agent_id,
                    agent_name=trace_context.agent_name,
                    session_id=trace_context.session_id,
                    project_name=trace_context.observability_project_name or trace_context.project_name,
                    timestamp=datetime.now(timezone.utc),
                    trace_input=trace_input,
                    trace_output=trace_output,
                    langfuse_client=tracer_lf_client,
                )
            )
            logger.info("Evaluator task scheduled successfully")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to schedule new-trace evaluators: {e}")

    async def end_tracers(self, outputs: dict, error: Exception | None = None) -> None:
        """End the trace for a graph run.

        - stop worker for current trace_context
        - call end for all the tracers
        """
        if self.deactivated:
            return
        trace_context = trace_context_var.get()
        if trace_context is None:
            msg = "called end_tracers but no trace context found"
            raise RuntimeError(msg)
        await self._stop(trace_context)
        self._end_all_tracers(trace_context, outputs, error)
        self._schedule_new_trace_evaluations(trace_context)

    @staticmethod
    def _cleanup_inputs(inputs: dict[str, Any]):
        inputs = inputs.copy()
        for key in inputs:
            if "api_key" in key:
                inputs[key] = "*****"  # avoid logging api_keys for security reasons
        return inputs

    def _start_component_traces(
        self,
        component_trace_context: ComponentTraceContext,
        trace_context: TraceContext,
    ) -> None:
        inputs = self._cleanup_inputs(component_trace_context.inputs)
        component_trace_context.inputs = inputs
        component_trace_context.inputs_metadata = component_trace_context.inputs_metadata or {}
        for tracer in trace_context.tracers.values():
            if not tracer.ready:
                continue
            try:
                tracer.add_trace(
                    component_trace_context.trace_id,
                    component_trace_context.trace_name,
                    component_trace_context.trace_type,
                    inputs,
                    component_trace_context.inputs_metadata,
                    component_trace_context.vertex,
                )
            except Exception:  # noqa: BLE001
                logger.exception(f"Error starting trace {component_trace_context.trace_name}")

    def _end_component_traces(
        self,
        component_trace_context: ComponentTraceContext,
        trace_context: TraceContext,
        error: Exception | None = None,
    ) -> None:
        for name, tracer in trace_context.tracers.items():
            if tracer.ready:
                try:
                    tracer.end_trace(
                        trace_id=component_trace_context.trace_id,
                        trace_name=component_trace_context.trace_name,
                        outputs=trace_context.all_outputs[component_trace_context.trace_name],
                        output_metadata=component_trace_context.outputs_metadata[component_trace_context.trace_name],
                        error=error,
                        logs=component_trace_context.logs[component_trace_context.trace_name],
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(f"Error ending trace {component_trace_context.trace_name}")

    @asynccontextmanager
    async def trace_component(
        self,
        component: Node,
        trace_name: str,
        inputs: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ):
        """Trace a component.

        @param component: the component to trace
        @param trace_name: component name + component id
        @param inputs: the inputs to the component
        @param metadata: the metadata to the component
        """
        if self.deactivated:
            yield self
            return
        trace_id = trace_name
        if component._vertex:
            trace_id = component._vertex.id
        trace_type = component.trace_type
        component_trace_context = ComponentTraceContext(
            trace_id, trace_name, trace_type, component._vertex, inputs, metadata
        )
        component_context_var.set(component_trace_context)
        trace_context = trace_context_var.get()
        if trace_context is None:
            msg = "called trace_component but no trace context found"
            raise RuntimeError(msg)
        trace_context.all_inputs[trace_name] |= inputs or {}
        await trace_context.traces_queue.put((self._start_component_traces, (component_trace_context, trace_context)))
        try:
            yield self
        except Exception as e:
            await trace_context.traces_queue.put(
                (self._end_component_traces, (component_trace_context, trace_context, e))
            )
            raise
        else:
            await trace_context.traces_queue.put(
                (self._end_component_traces, (component_trace_context, trace_context, None))
            )

    @property
    def project_name(self):
        if self.deactivated:
            return os.getenv("LANGCHAIN_PROJECT", "Agentcore")
        trace_context = trace_context_var.get()
        if trace_context is None:
            msg = "called project_name but no trace context found"
            raise RuntimeError(msg)
        return trace_context.project_name

    def add_log(self, trace_name: str, log: Log) -> None:
        """Add a log to the current component trace context."""
        if self.deactivated:
            return
        component_context = component_context_var.get()
        if component_context is None:
            msg = "called add_log but no component context found"
            raise RuntimeError(msg)
        component_context.logs[trace_name].append(log)

    def set_outputs(
        self,
        trace_name: str,
        outputs: dict[str, Any],
        output_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set the outputs for the current component trace context."""
        if self.deactivated:
            return
        component_context = component_context_var.get()
        if component_context is None:
            msg = "called set_outputs but no component context found"
            raise RuntimeError(msg)
        component_context.outputs[trace_name] |= outputs or {}
        component_context.outputs_metadata[trace_name] |= output_metadata or {}
        trace_context = trace_context_var.get()
        if trace_context is None:
            msg = "called set_outputs but no trace context found"
            raise RuntimeError(msg)
        trace_context.all_outputs[trace_name] |= outputs or {}

    def get_tracer(self, tracer_name: str) -> BaseTracer | None:
        trace_context = trace_context_var.get()
        if trace_context is None:
            msg = "called get_tracer but no trace context found"
            raise RuntimeError(msg)
        return trace_context.tracers.get(tracer_name)

    def get_langchain_callbacks(self) -> list[BaseCallbackHandler]:
        if self.deactivated:
            return []
        callbacks = []
        trace_context = trace_context_var.get()
        if trace_context is None:
            msg = "called get_langchain_callbacks but no trace context found"
            raise RuntimeError(msg)
        for tracer in trace_context.tracers.values():
            if not tracer.ready:  # type: ignore[truthy-function]
                continue
            langchain_callback = tracer.get_langchain_callback()
            if langchain_callback:
                callbacks.append(langchain_callback)
        return callbacks
