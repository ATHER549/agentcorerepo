import json
import logging
import os
import sys
from collections import deque
from contextvars import ContextVar
from pathlib import Path
from threading import Lock, Semaphore
from typing import TypedDict

import orjson
from loguru import logger
from platformdirs import user_cache_dir
from rich.logging import RichHandler
from typing_extensions import NotRequired, override

from agentcore.settings import DEV

# Request-scoped correlation context (contextvars)
_LOG_CONTEXT: ContextVar[dict] = ContextVar("log_context", default={})


def reset_log_context() -> None:
    """Reset the request-scoped log context at request start."""
    _LOG_CONTEXT.set({})


def update_log_context(**fields: str | int | float | None) -> None:
    """Update the request-scoped log context with additional fields."""
    ctx = _LOG_CONTEXT.get().copy()
    ctx.update({k: v for k, v in fields.items() if v is not None})
    _LOG_CONTEXT.set(ctx)


def get_log_context() -> dict:
    """Get the current request-scoped log context."""
    return _LOG_CONTEXT.get().copy()


def _get_otel_trace_ids() -> tuple[str | None, str | None]:
    """Best-effort: read trace_id and span_id from OpenTelemetry current span. Returns (None, None) if OTel not active."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.is_recording():
            ctx = span.get_span_context()
            if ctx:
                return (format(ctx.trace_id, "032x") if ctx.trace_id else None, format(ctx.span_id, "016x") if ctx.span_id else None)
    except Exception:
        pass
    return (None, None)


VALID_LOG_LEVELS = ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
# Human-readable
DEFAULT_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> - <level>{level: <8}</level> - {module} - <level>{message}</level>"
)


class SizedLogBuffer:
    def __init__(
        self,
        max_readers: int = 20,  # max number of concurrent readers for the buffer
    ):
        """A buffer for storing log messages for the log retrieval API.

        The buffer can be overwritten by an env variable AGENTCORE_LOG_RETRIEVER_BUFFER_SIZE
        because the logger is initialized before the settings_service are loaded.
        """
        self.buffer: deque = deque()

        self._max_readers = max_readers
        self._wlock = Lock()
        self._rsemaphore = Semaphore(max_readers)
        self._max = 0

    def get_write_lock(self) -> Lock:
        return self._wlock

    def write(self, message: str) -> None:
        record = json.loads(message)
        log_entry = record["text"]
        epoch = int(record["record"]["time"]["timestamp"] * 1000)
        with self._wlock:
            if len(self.buffer) >= self.max:
                for _ in range(len(self.buffer) - self.max + 1):
                    self.buffer.popleft()
            self.buffer.append((epoch, log_entry))

    def __len__(self) -> int:
        return len(self.buffer)

    def get_after_timestamp(self, timestamp: int, lines: int = 5) -> dict[int, str]:
        rc = {}

        self._rsemaphore.acquire()
        try:
            with self._wlock:
                for ts, msg in self.buffer:
                    if lines == 0:
                        break
                    if ts >= timestamp and lines > 0:
                        rc[ts] = msg
                        lines -= 1
        finally:
            self._rsemaphore.release()

        return rc

    def get_before_timestamp(self, timestamp: int, lines: int = 5) -> dict[int, str]:
        self._rsemaphore.acquire()
        try:
            with self._wlock:
                as_list = list(self.buffer)
            max_index = -1
            for i, (ts, _) in enumerate(as_list):
                if ts >= timestamp:
                    max_index = i
                    break
            if max_index == -1:
                return self.get_last_n(lines)
            rc = {}
            start_from = max(max_index - lines, 0)
            for i, (ts, msg) in enumerate(as_list):
                if start_from <= i < max_index:
                    rc[ts] = msg
            return rc
        finally:
            self._rsemaphore.release()

    def get_last_n(self, last_idx: int) -> dict[int, str]:
        self._rsemaphore.acquire()
        try:
            with self._wlock:
                as_list = list(self.buffer)
            return dict(as_list[-last_idx:])
        finally:
            self._rsemaphore.release()

    @property
    def max(self) -> int:
        # Get it dynamically to allow for env variable changes
        if self._max == 0:
            env_buffer_size = os.getenv("AGENTCORE_LOG_RETRIEVER_BUFFER_SIZE", "0")
            if env_buffer_size.isdigit():
                self._max = int(env_buffer_size)
        return self._max

    @max.setter
    def max(self, value: int) -> None:
        self._max = value

    def enabled(self) -> bool:
        return self.max > 0

    def max_size(self) -> int:
        return self.max


# log buffer for capturing log messages
log_buffer = SizedLogBuffer()


def serialize_log(record):
    """Output JSON with correlation keys ALWAYS. One JSON per line for container stdout."""
    trace_id, span_id = _get_otel_trace_ids()
    ctx = get_log_context()
    extra = record.get("extra") or {}
    for key in ("trace_id", "span_id", "user_id", "session_id", "agent_id", "agent_id_or_name", "project_id", "http_method", "http_route", "status_code", "latency_ms", "event"):
        if key in extra and extra[key] is not None:
            ctx = {**ctx, key: extra[key]}
    subset = {
        "timestamp": record["time"].timestamp(),
        "level": record["level"].name,
        "module": record["module"],
        "message": record["message"],
        "trace_id": ctx.get("trace_id") or trace_id,
        "span_id": ctx.get("span_id") or span_id,
        "user_id": ctx.get("user_id"),
        "session_id": ctx.get("session_id"),
        "agent_id": ctx.get("agent_id"),
        "agent_id_or_name": ctx.get("agent_id_or_name"),
        "project_id": ctx.get("project_id"),
        "http_method": ctx.get("http_method"),
        "http_route": ctx.get("http_route"),
        "status_code": ctx.get("status_code"),
        "latency_ms": ctx.get("latency_ms"),
        "event": ctx.get("event"),
    }
    return orjson.dumps(subset).decode("utf-8")


def patching(record) -> None:
    try:
        serialized = serialize_log(record)
    except Exception:
        serialized = "{}"
    try:
        record["extra"] = {**(record.get("extra") or {}), "serialized": serialized}
    except (TypeError, ValueError):
        pass
    if DEV is False:
        record.pop("exception", None)


def _jsonl_from_record(record) -> str:
    """Build JSON line from record. Never raises."""
    serialized = (record.get("extra") or {}).get("serialized")
    if serialized:
        return serialized
    try:
        return serialize_log(record)
    except Exception:
        t, l = record.get("time"), record.get("level")
        ts = t.timestamp() if t and hasattr(t, "timestamp") else 0.0
        lvl = l.name if l and hasattr(l, "name") else "INFO"
        return orjson.dumps({
            "timestamp": ts, "level": lvl, "module": record.get("module", ""),
            "message": record.get("message", ""),
            "trace_id": None, "span_id": None, "user_id": None, "session_id": None,
            "agent_id": None, "agent_id_or_name": None, "project_id": None,
            "http_method": None, "http_route": None, "status_code": None, "latency_ms": None,
            "event": None,
        }).decode("utf-8")


def _make_jsonl_sink(filepath: Path):
    """Return a sink that writes JSON lines to file. Bypasses format_map entirely."""

    def sink(message) -> None:
        try:
            record = message.record
            json_str = _jsonl_from_record(record)
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json_str + "\n")
                f.flush()
        except Exception:
            pass

    return sink


class LogConfig(TypedDict):
    log_level: NotRequired[str]
    log_file: NotRequired[Path]
    disable: NotRequired[bool]
    log_env: NotRequired[str]
    log_format: NotRequired[str]


def is_valid_log_format(format_string) -> bool:
    """Validates a logging format string by attempting to format it with a dummy LogRecord.

    Args:
        format_string (str): The format string to validate.

    Returns:
        bool: True if the format string is valid, False otherwise.
    """
    record = logging.LogRecord(
        name="dummy", level=logging.INFO, pathname="dummy_path", lineno=0, msg="dummy message", args=None, exc_info=None
    )

    formatter = logging.Formatter(format_string)

    try:
        # Attempt to format the record
        formatter.format(record)
    except (KeyError, ValueError, TypeError):
        logger.error("Invalid log format string passed, fallback to default")
        return False
    return True


def configure(
    *,
    log_level: str | None = None,
    log_file: Path | None = None,
    disable: bool | None = False,
    log_env: str | None = None,
    log_format: str | None = None,
    async_file: bool = False,
    log_rotation: str | None = None,
) -> None:
    if disable and log_level is None and log_file is None:
        logger.disable("agentcore")
    if os.getenv("AGENTCORE_LOG_LEVEL", "").upper() in VALID_LOG_LEVELS and log_level is None:
        log_level = os.getenv("AGENTCORE_LOG_LEVEL")
    if log_level is None:
        log_level = "INFO"  # Default to INFO for production visibility (access logs, startup info)

    if log_file is None:
        env_log_file = os.getenv("AGENTCORE_LOG_FILE", "")
        log_file = Path(env_log_file) if env_log_file else None

    if log_env is None:
        log_env = os.getenv("AGENTCORE_LOG_ENV", "")

    logger.remove()  # Remove default handlers
    logger.patch(patching)
    if log_env.lower() == "container" or log_env.lower() == "container_json":
        def _stdout_jsonl_sink(message) -> None:
            try:
                json_str = _jsonl_from_record(message.record)
                sys.stdout.write(json_str + "\n")
                sys.stdout.flush()
            except Exception:
                pass
        logger.add(sink=_stdout_jsonl_sink, format="{message}", level=log_level.upper())
    elif log_env.lower() == "container_csv":
        logger.add(sys.stdout, format="{time:YYYY-MM-DD HH:mm:ss.SSS} {level} {file} {line} {function} {message}")
    else:
        if os.getenv("AGENTCORE_LOG_FORMAT") and log_format is None:
            log_format = os.getenv("AGENTCORE_LOG_FORMAT")

        if log_format is None or not is_valid_log_format(log_format):
            log_format = DEFAULT_LOG_FORMAT
        # pretty print to rich stdout development-friendly but poor performance, It's better for debugger.
        # suggest directly print to stdout in production
        log_stdout_pretty = os.getenv("AGENTCORE_PRETTY_LOGS", "true").lower() == "true"
        if log_stdout_pretty:
            logger.configure(
                handlers=[
                    {
                        "sink": RichHandler(rich_tracebacks=True, markup=True),
                        "format": log_format,
                        "level": log_level.upper(),
                    }
                ]
            )
        else:
            logger.add(sys.stdout, level=log_level.upper(), format=log_format, backtrace=True, diagnose=True)

        if not log_file:
            cache_dir = Path(user_cache_dir("agentcore"))
            logger.debug(f"Cache directory: {cache_dir}")
            log_file = cache_dir / "agentcore.log"
            logger.debug(f"Log file: {log_file}")

        if os.getenv("AGENTCORE_LOG_ROTATION") and log_rotation is None:
            log_rotation = os.getenv("AGENTCORE_LOG_ROTATION")
        elif log_rotation is None:
            log_rotation = "1 day"

        try:
            logger.add(
                sink=log_file,
                level="DEBUG",
                format=log_format,
                serialize=True,
                enqueue=async_file,
                rotation=log_rotation,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Error setting up log file")

    if log_buffer.enabled():
        logger.add(sink=log_buffer.write, format="{time} {level} {message}", serialize=True)

    _log_file_sink_enabled = os.getenv("AGENTCORE_LOG_FILE_SINK_ENABLED", "true").lower() not in ("false", "0")
    if _log_file_sink_enabled:
        _loguru_dir = Path.cwd() / "loguru" if (Path.cwd() / "pyproject.toml").exists() else Path(__file__).resolve().parent.parent.parent.parent.parent.parent / "loguru"
        _loguru_dir.mkdir(parents=True, exist_ok=True)
        _loguru_file = _loguru_dir / "agentcore.jsonl"
        logger.add(sink=_make_jsonl_sink(_loguru_file), format="{message}", level=log_level.upper())

    logger.debug(f"Logger set up with log level: {log_level}")

    setup_uvicorn_logger()
    setup_gunicorn_logger()


def setup_uvicorn_logger() -> None:
    """Intercept uvicorn loggers and route them to loguru."""
    # Get all uvicorn loggers
    loggers = (logging.getLogger(name) for name in logging.root.manager.loggerDict if name.startswith("uvicorn."))
    for uvicorn_logger in loggers:
        uvicorn_logger.handlers = []
    
    # Set up main uvicorn logger and access logger
    logging.getLogger("uvicorn").handlers = [InterceptHandler()]
    logging.getLogger("uvicorn.access").handlers = [InterceptHandler()]
    logging.getLogger("uvicorn.error").handlers = [InterceptHandler()]
    
    # Set log levels to allow all messages through (loguru will filter)
    logging.getLogger("uvicorn").setLevel(logging.DEBUG)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.DEBUG)


def setup_gunicorn_logger() -> None:
    logging.getLogger("gunicorn.error").handlers = [InterceptHandler()]
    logging.getLogger("gunicorn.access").handlers = [InterceptHandler()]


class InterceptHandler(logging.Handler):
    """Intercept standard logging and route to loguru."""

    @override
    def emit(self, record) -> None:
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__ and frame.f_back:
            frame = frame.f_back
            depth += 1

        ctx = get_log_context()
        ctx_filtered = {k: v for k, v in ctx.items() if v is not None}
        logger.opt(depth=depth, exception=record.exc_info).bind(**ctx_filtered).log(level, record.getMessage())
