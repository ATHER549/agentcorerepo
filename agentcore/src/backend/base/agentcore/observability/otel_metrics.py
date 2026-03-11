"""Production-grade Prometheus /metrics via OpenTelemetry Prometheus exporter.

Metrics are env-gated (off by default). When AGENTCORE_METRICS_ENABLED=true:
- Exposes /metrics (text/plain; version=0.0.4) with http_server_requests_total and
  http_server_request_duration_ms
- Uses PrometheusMetricReader + MeterProvider
- Middleware records counter + histogram per request (no high-cardinality labels)
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response


_metrics_initialized = False
_request_counter = None
_request_duration_histogram = None
_meter_provider = None


def is_metrics_enabled() -> bool:
    """Return True if Prometheus metrics should be enabled."""
    return os.getenv("AGENTCORE_METRICS_ENABLED", "").lower() == "true"


def setup_otel_metrics(app) -> None:
    """Configure OpenTelemetry metrics and add /metrics route + middleware.

    - Sets MeterProvider with PrometheusMetricReader (registers with prometheus_client REGISTRY)
    - Adds /metrics route returning Prometheus exposition format
    - Adds middleware to record http_server_requests_total and http_server_request_duration_ms
    - Idempotent: skips if already initialized
    - Reuses existing MeterProvider if one is already set (avoids dual-provider conflict)
    """
    global _metrics_initialized, _request_counter, _request_duration_histogram, _meter_provider

    if _metrics_initialized:
        return

    try:
        from opentelemetry import metrics
        from opentelemetry.exporter.prometheus import PrometheusMetricReader
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    except ImportError as e:
        from loguru import logger

        logger.warning("Prometheus metrics packages not available; metrics disabled: %s", e)
        return

    # Check if a MeterProvider is already set (e.g. by another module); reuse it if so.
    existing = metrics.get_meter_provider()
    if isinstance(existing, MeterProvider):
        from loguru import logger

        logger.debug("Reusing existing MeterProvider; skipping new provider creation")
        provider = existing
    else:
        reader = PrometheusMetricReader()
        resource = Resource.create({"service.name": "agentcore"})
        provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(provider)

    _meter_provider = provider

    meter = provider.get_meter("agentcore.metrics", "1.0.0")
    _request_counter = meter.create_counter(
        name="http_server_requests_total",
        unit="1",
        description="Total HTTP requests",
    )
    _request_duration_histogram = meter.create_histogram(
        name="http_server_request_duration_ms",
        unit="ms",
        description="HTTP request duration in milliseconds",
    )

    from agentcore.observability.metrics_registry import init_instruments
    init_instruments(meter)

    provider.get_meter("http.server", "0.0.0")

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint():
        import asyncio

        from fastapi.responses import Response

        output = await asyncio.to_thread(generate_latest)
        return Response(content=output, media_type=CONTENT_TYPE_LATEST)

    class MetricsMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            if _request_counter is None or _request_duration_histogram is None:
                return await call_next(request)
            if request.url.path == "/metrics":
                return await call_next(request)
            start = time.perf_counter()
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start) * 1000.0
            route = request.scope.get("route")
            path = route.path if route else (request.scope.get("path") or request.url.path)
            method = request.method or "UNKNOWN"
            status_code = str(response.status_code)
            labels = {"method": method, "route": path, "status_code": status_code}
            try:
                _request_counter.add(1, labels)
                _request_duration_histogram.record(duration_ms, labels)
            except Exception:
                pass
            if response.status_code >= 400:
                from agentcore.observability.metrics_registry import record_api_error
                record_api_error(status_code, path)
            return response

    app.add_middleware(MetricsMiddleware)
    _metrics_initialized = True


def shutdown_otel_metrics() -> None:
    """Gracefully shut down the MeterProvider, flushing pending metrics."""
    global _meter_provider
    if _meter_provider is None:
        return
    try:
        from loguru import logger

        _meter_provider.shutdown()
        logger.debug("OpenTelemetry MeterProvider shut down")
    except Exception as e:
        from loguru import logger

        logger.warning("Error shutting down MeterProvider: {}", e)
    finally:
        _meter_provider = None
