"""Production-grade OpenTelemetry tracing setup for AgentCore.

Tracing is env-gated (off by default). When enabled via OTEL env vars:
- Sets SDK TracerProvider with Resource(service.name, deployment.environment)
- Adds BatchSpanProcessor + OTLPSpanExporter when OTEL_EXPORTER_OTLP_ENDPOINT is set
- Instruments FastAPI via FastAPIInstrumentor (runs once)
- Loguru correlation logs receive non-null trace_id/span_id from trace.get_current_span()

Never logs tokens/JWT. Sampling configurable via OTEL_TRACES_SAMPLER env.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from fastapi import FastAPI


_sqlalchemy_instrumented = False
_redis_instrumented = False
_httpx_instrumented = False
_tracer_provider = None


def is_tracing_enabled() -> bool:
    """Return True if OpenTelemetry tracing should be enabled.

    Enabled when any of these env vars are set:
    - OTEL_EXPORTER_OTLP_ENDPOINT (OTLP export)
    - OTEL_SERVICE_NAME (local tracing without export)
    """
    return bool(
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTEL_SERVICE_NAME")
    )


def _get_fastapi_excluded_urls() -> str:
    """Resolve FastAPI instrumentation excluded_urls from env vars.

    Precedence:
    1) OTEL_FASTAPI_EXCLUDED_URLS (explicit override)
    2) default: exclude only infra endpoints so API routes are traced
    """
    explicit_excluded_urls = os.getenv("OTEL_FASTAPI_EXCLUDED_URLS", "").strip()
    if explicit_excluded_urls:
        return explicit_excluded_urls

    return "/health,/health_check,/metrics"


def _setup_sqlalchemy_instrumentation() -> None:
    """Optionally enable SQLAlchemy instrumentation (env-gated, idempotent)."""
    global _sqlalchemy_instrumented

    if os.getenv("OTEL_DB_INSTRUMENTATION_ENABLED", "").lower() != "true":
        return
    if _sqlalchemy_instrumented:
        return

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    except ImportError as e:
        logger.warning("OpenTelemetry SQLAlchemy instrumentation unavailable: {}", e)
        return

    SQLAlchemyInstrumentor().instrument()
    _sqlalchemy_instrumented = True
    logger.info("OpenTelemetry SQLAlchemy instrumentation enabled")


def _setup_redis_instrumentation() -> None:
    """Optionally enable Redis instrumentation (env-gated, idempotent)."""
    global _redis_instrumented

    if os.getenv("OTEL_REDIS_INSTRUMENTATION_ENABLED", "").lower() != "true":
        return
    if _redis_instrumented:
        return

    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
    except ImportError as e:
        logger.warning("OpenTelemetry Redis instrumentation unavailable: {}", e)
        return

    RedisInstrumentor().instrument()
    _redis_instrumented = True
    logger.info("OpenTelemetry Redis instrumentation enabled")


def _setup_httpx_instrumentation() -> None:
    """Enable httpx instrumentation (env-gated, default true, idempotent)."""
    global _httpx_instrumented

    if os.getenv("OTEL_HTTPX_INSTRUMENTATION_ENABLED", "true").lower() != "true":
        return
    if _httpx_instrumented:
        return

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    except ImportError as e:
        logger.warning("OpenTelemetry httpx instrumentation unavailable: {}", e)
        return

    HTTPXClientInstrumentor().instrument()
    _httpx_instrumented = True
    logger.info("OpenTelemetry httpx instrumentation enabled")


def setup_otel_tracing(app: FastAPI) -> None:
    """Configure OpenTelemetry tracing and instrument the FastAPI app.

    - Sets TracerProvider with Resource(service.name="agentcore", deployment.environment=...)
    - Adds BatchSpanProcessor + OTLPSpanExporter when OTEL_EXPORTER_OTLP_ENDPOINT is set
    - Instruments FastAPI via FastAPIInstrumentor.instrument_app (idempotent, runs once)
    - Adds TraceIdMiddleware to inject X-Trace-Id response header
    - When OTLP endpoint is not set, spans exist locally (trace_id/span_id in logs) but are not exported
    """
    global _tracer_provider

    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as e:
        logger.warning("OpenTelemetry packages not available; tracing disabled: %s", e)
        return

    excluded_urls = _get_fastapi_excluded_urls()
    logger.info("OpenTelemetry FastAPI excluded_urls={}", excluded_urls)

    # Avoid re-initializing if TracerProvider is already set (e.g. by another process)
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        logger.debug("OpenTelemetry TracerProvider already set; skipping setup")
        _tracer_provider = trace.get_tracer_provider()
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls=excluded_urls,
        )
        _setup_sqlalchemy_instrumentation()
        _setup_redis_instrumentation()
        _setup_httpx_instrumentation()
        app.add_middleware(TraceIdMiddleware)
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", "agentcore")
    deployment_env = os.getenv("OTEL_RESOURCE_ATTRIBUTES", "").strip()
    attrs: dict[str, str] = {
        "service.name": service_name,
        "deployment.environment": os.getenv("DEPLOYMENT_ENVIRONMENT", "development"),
    }
    if deployment_env:
        for part in deployment_env.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                attrs[k.strip()] = v.strip()

    resource = Resource(attributes=attrs)
    provider = TracerProvider(resource=resource)

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        exporter = None
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter()
            logger.info(
                "OpenTelemetry tracing enabled with OTLP gRPC export to %s",
                otlp_endpoint,
            )
        except ImportError:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                exporter = OTLPSpanExporter()
                logger.info(
                    "OpenTelemetry tracing enabled with OTLP HTTP export to %s",
                    otlp_endpoint,
                )
            except ImportError as e:
                logger.warning(
                    "OTLP exporter not available; tracing enabled locally only: %s",
                    e,
                )
        if exporter is not None:
            provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        logger.debug(
            "OpenTelemetry tracing enabled (local only); set OTEL_EXPORTER_OTLP_ENDPOINT to export"
        )

    trace.set_tracer_provider(provider)
    _tracer_provider = provider

    # Excluded URLs are env-configurable; default excludes infra endpoints only.
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=excluded_urls,
    )
    _setup_sqlalchemy_instrumentation()
    _setup_redis_instrumentation()
    _setup_httpx_instrumentation()

    app.add_middleware(TraceIdMiddleware)


class TraceIdMiddleware:
    """ASGI middleware that injects X-Trace-Id header from the current OTel span."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_trace_id(message):
            if message["type"] == "http.response.start":
                try:
                    from opentelemetry import trace

                    span = trace.get_current_span()
                    ctx = span.get_span_context()
                    if ctx and ctx.trace_id:
                        trace_id_hex = format(ctx.trace_id, "032x")
                        headers = list(message.get("headers", []))
                        headers.append((b"x-trace-id", trace_id_hex.encode()))
                        message["headers"] = headers
                except Exception:
                    pass
            await send(message)

        await self.app(scope, receive, send_with_trace_id)


def shutdown_otel_tracing() -> None:
    """Gracefully shut down the TracerProvider, flushing pending spans."""
    global _tracer_provider
    if _tracer_provider is None:
        return
    try:
        _tracer_provider.shutdown()
        logger.debug("OpenTelemetry TracerProvider shut down")
    except Exception as e:
        logger.warning("Error shutting down TracerProvider: {}", e)
    finally:
        _tracer_provider = None
