import asyncio
import base64
import json
import os
import re
import warnings
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from multiprocessing import cpu_count
from typing import TYPE_CHECKING
from urllib.parse import urlencode
import builtins

import sys

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

import anyio
import sqlalchemy
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi_pagination import add_pagination
from loguru import logger
from pydantic import PydanticDeprecatedSince20
from pydantic_core import PydanticSerializationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from agentcore.api import health_check_router, log_router, router
from agentcore.api.openai_compat_router import router as openai_router
from agentcore.interface.components import get_and_cache_all_types_dict
from agentcore.interface.utils import setup_llm_caching
from agentcore.logging.logger import configure, reset_log_context, update_log_context
from agentcore.observability import (
    is_metrics_enabled,
    is_tracing_enabled,
    setup_otel_metrics,
    setup_otel_tracing,
    shutdown_otel_metrics,
    shutdown_otel_tracing,
)
from agentcore.middleware import ContentSizeLimitMiddleware
from agentcore.services.deps import (
    get_queue_service,
    get_scheduler_service,
    get_settings_service,
    get_telemetry_service,
    get_trigger_service,
)
from agentcore.services.utils import initialize_services, teardown_services

if TYPE_CHECKING:
    from tempfile import TemporaryDirectory

# Ignore Pydantic deprecation warnings from Langchain
warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)


import logging as _stdlib_logging


class _OTelContextDetachFilter(_stdlib_logging.Filter):
    def filter(self, record: _stdlib_logging.LogRecord) -> bool:
        return "Failed to detach context" not in record.getMessage()


_stdlib_logging.getLogger("opentelemetry.context").addFilter(_OTelContextDetachFilter())

_tasks: list[asyncio.Task] = []


class RequestCancelledMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        sentinel = object()

        async def cancel_handler():
            while True:
                if await request.is_disconnected():
                    return sentinel
                await asyncio.sleep(0.1)

        handler_task = asyncio.create_task(call_next(request))
        cancel_task = asyncio.create_task(cancel_handler())

        done, pending = await asyncio.wait([handler_task, cancel_task], return_when=asyncio.FIRST_COMPLETED)

        for task in pending:
            task.cancel()

        if cancel_task in done:
            return Response("Request was cancelled", status_code=499)
        return await handler_task


_app_ready = False


def get_lifespan(*, fix_migration=True, version=None):
    telemetry_service = get_telemetry_service()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        global _app_ready
        configure(async_file=True)

        # Startup message
        if version:
            logger.debug(f"Starting Agentcore v{version}...")
        else:
            logger.debug("Starting Agentcore...")

        temp_dirs: list[TemporaryDirectory] = []

        try:
            start_time = asyncio.get_event_loop().time()

            logger.debug("Initializing services")
            await initialize_services(fix_migration=fix_migration)
            logger.debug(f"Services initialized in {asyncio.get_event_loop().time() - start_time:.2f}s")

            current_time = asyncio.get_event_loop().time()
            logger.debug("Syncing packages to database")
            from agentcore.services.packages import sync_packages_to_db
            await sync_packages_to_db()
            logger.debug(f"Packages synced in {asyncio.get_event_loop().time() - current_time:.2f}s")

            current_time = asyncio.get_event_loop().time()
            logger.debug("Setting up LLM caching")
            setup_llm_caching()
            logger.debug(f"LLM caching setup in {asyncio.get_event_loop().time() - current_time:.2f}s")

            current_time = asyncio.get_event_loop().time()
            logger.debug("Caching types")
            all_types_dict = await get_and_cache_all_types_dict(get_settings_service())
            logger.debug(f"Types cached in {asyncio.get_event_loop().time() - current_time:.2f}s")

            current_time = asyncio.get_event_loop().time()
            logger.debug("Starting telemetry service")
            telemetry_service.start()
            logger.debug(f"started telemetry service in {asyncio.get_event_loop().time() - current_time:.2f}s")

            current_time = asyncio.get_event_loop().time()
            queue_service = get_queue_service()
            if not queue_service.is_started():  # Start if not already started
                queue_service.start()
            logger.debug(f"Agents loaded in {asyncio.get_event_loop().time() - current_time:.2f}s")

            current_time = asyncio.get_event_loop().time()
            logger.debug("Starting scheduler and trigger services")
            try:
                scheduler_service = get_scheduler_service()
                scheduler_service.start()
                await scheduler_service.load_active_schedules()

                trigger_service = get_trigger_service()
                trigger_service.start()
                await trigger_service.load_active_monitors()
                logger.debug(f"Trigger services started in {asyncio.get_event_loop().time() - current_time:.2f}s")
            except Exception as e:
                logger.warning(f"Failed to start trigger services: {e}")

            total_time = asyncio.get_event_loop().time() - start_time
            logger.debug(f"Total initialization time: {total_time:.2f}s")

            _app_ready = True
            yield

        except asyncio.CancelledError:
            logger.debug("Lifespan received cancellation signal")
        except Exception as exc:
            if "agentcore migration --fix" not in str(exc):
                logger.exception(exc)
            raise
        finally:
            _app_ready = False
            # Clean shutdown
            try:
                # Stopping Server
                logger.debug("Stopping server gracefully...")

                # Cleaning Up Services
                try:
                    await asyncio.wait_for(teardown_services(), timeout=10)
                except asyncio.TimeoutError:
                    logger.warning("Teardown services timed out.")

                # Clearing Temporary Files
                temp_dir_cleanups = [asyncio.to_thread(temp_dir.cleanup) for temp_dir in temp_dirs]
                await asyncio.gather(*temp_dir_cleanups)

                # Finalizing Shutdown
                logger.debug("Agentcore shutdown complete")

            except (sqlalchemy.exc.OperationalError, sqlalchemy.exc.DBAPIError) as e:
                # Case where the database connection is closed during shutdown
                logger.warning(f"Database teardown failed due to closed connection: {e}")
            except asyncio.CancelledError:
                # Swallow this - it's normal during shutdown
                logger.debug("Teardown cancelled during shutdown.")
            except Exception as e:  # noqa: BLE001
                logger.exception(f"Unhandled error during cleanup: {e}")

            # Flush OTel providers before logger shutdown
            try:
                shutdown_otel_tracing()
            except Exception:
                pass
            try:
                shutdown_otel_metrics()
            except Exception:
                pass

            try:
                await asyncio.shield(asyncio.sleep(0.1))  # let logger flush async logs
                await asyncio.shield(logger.complete())
            except asyncio.CancelledError:
                # Cancellation during logger flush is possible during shutdown, so we swallow it
                pass

    return lifespan


def create_app():
    """Create the FastAPI app and include the router."""
    from agentcore.utils.version import get_version_info
   
    __version__ = get_version_info()["version"]
    configure()
    lifespan = get_lifespan(version=__version__)
    app = FastAPI(
        title="AgentCore",
        version=__version__,
        lifespan=lifespan,
    )

    def _decode_jwt_payload_unverified(token: str) -> dict | None:
        """Decode JWT payload without verification. Never log token. Returns None on any error."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            decoded = base64.urlsafe_b64decode(payload_b64)
            return json.loads(decoded)
        except Exception:
            return None

    @app.middleware("http")
    async def correlation_logging_middleware(request: Request, call_next):
        """Request-scoped correlation context for JSON logs. Never breaks requests."""
        reset_log_context()
        start = asyncio.get_event_loop().time()
        status_code = None
        try:
            update_log_context(
                http_method=request.method,
                http_route=request.scope.get("path") or request.url.path,
            )
            path = request.url.path or ""
            uuid_match = re.findall(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                path,
            )
            if "/agents/" in path or "/upload/" in path or "/run/" in path or "/build/" in path or "/approvals/" in path:
                for m in uuid_match:
                    seg = path[: path.index(m)].rstrip("/").split("/")[-1] if m in path else ""
                    if seg in ("agents", "agent", "upload", "run", "build") or "approval" in seg:
                        update_log_context(agent_id=m, agent_id_or_name=m)
                        break
            if "/projects/" in path:
                for m in uuid_match:
                    if path.index(m) > path.index("/projects/"):
                        update_log_context(project_id=m)
                        break
            session_id = request.headers.get("x-session-id") or request.query_params.get("session_id")
            if session_id:
                update_log_context(session_id=session_id)
            try:
                auth = request.headers.get("Authorization")
                if auth and auth.startswith("Bearer "):
                    token = auth[7:].strip()
                    if token:
                        payload = _decode_jwt_payload_unverified(token)
                        if payload:
                            user_id = payload.get("sub") or payload.get("oid")
                            if user_id:
                                update_log_context(user_id=str(user_id))
                for name, val in request.cookies.items():
                    if "token" in name.lower() and val:
                        payload = _decode_jwt_payload_unverified(val)
                        if payload:
                            user_id = payload.get("sub") or payload.get("oid")
                            if user_id:
                                update_log_context(user_id=str(user_id))
                                break
            except Exception:
                pass
        except Exception:
            pass
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            if request.url.path != "/metrics":
                latency_ms = int((asyncio.get_event_loop().time() - start) * 1000) if start else None
                try:
                    update_log_context(status_code=status_code, latency_ms=latency_ms, event="http_request")
                    logger.info("http_request")
                except Exception:
                    pass

    app.add_middleware(
        ContentSizeLimitMiddleware,
    )

    cors_allowed_origins = os.getenv(
        "CORS_ALLOWED_ORIGINS",
        os.getenv("CORS_ALLOW_ORIGIN", os.getenv("LOCALHOST_FRONTEND_ORIGIN", "http://localhost:3000")),
    )
    origins = [origin.strip() for origin in re.split(r"[;,]", cors_allowed_origins) if origin.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


    class BoundaryCheckMiddleware:
     
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http" or "/api/files/upload" not in scope.get("path", ""):
                await self.app(scope, receive, send)
                return

            # Only validate boundary for file upload requests
            headers = {k: v for k, v in scope.get("headers", [])}
            content_type = headers.get(b"content-type", b"").decode()

            if not content_type or "multipart/form-data" not in content_type or "boundary=" not in content_type:
                response = JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    content={"detail": "Content-Type header must be 'multipart/form-data' with a boundary parameter."},
                )
                await response(scope, receive, send)
                return

            boundary = content_type.split("boundary=")[-1].strip()

            if not re.match(r"^[\w\-]{1,70}$", boundary):
                response = JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    content={"detail": "Invalid boundary format"},
                )
                await response(scope, receive, send)
                return

            # Read body to validate boundary markers
            body = b""
            while True:
                message = await receive()
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    break

            boundary_start = f"--{boundary}".encode()
            boundary_end = f"--{boundary}--\r\n".encode()
            boundary_end_no_newline = f"--{boundary}--".encode()

            if not body.startswith(boundary_start) or not body.endswith((boundary_end, boundary_end_no_newline)):
                response = JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    content={"detail": "Invalid multipart formatting"},
                )
                await response(scope, receive, send)
                return

            # Replay the consumed body for downstream handlers
            body_sent = False

            async def replay_receive():
                nonlocal body_sent
                if not body_sent:
                    body_sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await self.app(scope, replay_receive, send)

    class QueryStringFlattenMiddleware:
        """Flattens comma-separated query string values.

        Raw ASGI middleware — no response buffering.
        """

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            from urllib.parse import parse_qsl

            qs = scope.get("query_string", b"").decode()
            if "," in qs:
                pairs = parse_qsl(qs, keep_blank_values=True)
                flattened: list[tuple[str, str]] = []
                for key, value in pairs:
                    flattened.extend((key, entry) for entry in value.split(","))
                scope["query_string"] = urlencode(flattened, doseq=True).encode("utf-8")

            await self.app(scope, receive, send)

    app.add_middleware(QueryStringFlattenMiddleware)
    app.add_middleware(BoundaryCheckMiddleware)

    settings = get_settings_service().settings

    app.include_router(router)
    app.include_router(health_check_router)
    app.include_router(log_router)
    app.include_router(openai_router, prefix="")

    @app.get("/ready", include_in_schema=False)
    async def readiness_probe():
        if _app_ready:
            return JSONResponse(content={"status": "ready"}, status_code=200)
        return JSONResponse(content={"status": "not_ready"}, status_code=503)

    @app.exception_handler(Exception)
    async def exception_handler(_request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            logger.error("HTTPException: {}", exc, exc_info=exc)
            return JSONResponse(
                status_code=exc.status_code,
                content={"message": str(exc.detail)},
            )
        from agentcore.observability.metrics_registry import record_error
        record_error(type(exc).__name__, "api")
        logger.error("unhandled error: {}", exc, exc_info=exc)
        return JSONResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content={"message": str(exc)},
        )

    # OpenTelemetry tracing: env-gated (off by default). When enabled, creates real spans
    # so Loguru correlation logs get non-null trace_id/span_id from trace.get_current_span().
    if is_tracing_enabled():
        setup_otel_tracing(app)

    # Prometheus /metrics: env-gated (AGENTCORE_METRICS_ENABLED=true). Exposes http_server_* metrics.
    if is_metrics_enabled():
        setup_otel_metrics(app)

    add_pagination(app)

    return app


def get_number_of_workers(workers=None):
    if workers == -1 or workers is None:
        workers = (cpu_count() * 2) + 1
    logger.debug(f"Number of workers: {workers}")
    return workers

if __name__ == "__main__":
    import uvicorn

    configure()
    uvicorn.run(
        "agentcore.main:create_app",
        host="127.0.0.1",
        port=7860,
        workers=get_number_of_workers(),
        log_level="error",
        reload=True,
        loop="asyncio",
    )
