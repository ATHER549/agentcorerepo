import asyncio
import json
import os
import re
import warnings
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from multiprocess import cpu_count
from typing import TYPE_CHECKING
from urllib.parse import urlencode
import builtins
from agentcore.services.auth.decorators import verify_permissions
builtins.verify_permissions = verify_permissions
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
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import PydanticDeprecatedSince20
from pydantic_core import PydanticSerializationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from agentcore.api import health_check_router, log_router, router
from agentcore.api.openai_compat_router import router as openai_router
from agentcore.interface.components import get_and_cache_all_types_dict
from agentcore.interface.utils import setup_llm_caching
from agentcore.logging.logger import configure
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


def get_lifespan(*, fix_migration=True, version=None):
    telemetry_service = get_telemetry_service()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
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
            yield

        except asyncio.CancelledError:
            logger.debug("Lifespan received cancellation signal")
        except Exception as exc:
            if "agentcore migration --fix" not in str(exc):
                logger.exception(exc)
            raise
        finally:
            # Clean shutdown
            try:
                # Stopping Server
                logger.debug("Stopping server gracefully...")

                # Shut down MCP sessions first (STDIO subprocesses block if left to GC)
                try:
                    from agentcore.base.mcp.util import cleanup_all_mcp_sessions
                    await asyncio.wait_for(cleanup_all_mcp_sessions(), timeout=5)
                except asyncio.TimeoutError:
                    logger.warning("MCP session cleanup timed out.")
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"MCP session cleanup error: {e}")

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

    @app.exception_handler(Exception)
    async def exception_handler(_request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            logger.error(f"HTTPException: {exc}", exc_info=exc)
            return JSONResponse(
                status_code=exc.status_code,
                content={"message": str(exc.detail)},
            )
        logger.error(f"unhandled error: {exc}", exc_info=exc)
        return JSONResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content={"message": str(exc)},
        )

    # Exclude API routes from OTEL instrumentation to prevent HTTP traces
    # from polluting Langfuse with "POST /api/..." instead of actual agent names.
    # Agent tracing is handled separately by the TracingService with proper names.
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="/api/.*,/health,/health_check",
    )

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
