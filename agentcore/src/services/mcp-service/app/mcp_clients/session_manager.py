"""MCP Session Manager with session pooling, idle timeout, and periodic cleanup."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from anyio import ClosedResourceError
from mcp import ClientSession

logger = logging.getLogger(__name__)

SESSION_CLEANUP_TIMEOUT = 3  # Max seconds to wait when cleaning up a single session

# Global registry of all MCPSessionManager instances for teardown
_all_session_managers: set["MCPSessionManager"] = set()


class MCPSessionManager:
    """Manages persistent MCP sessions with proper context manager lifecycle.

    Addresses memory leaks by:
    1. Session reuse based on server identity rather than unique context IDs
    2. Maximum session limits per server to prevent resource exhaustion
    3. Idle timeout for automatic session cleanup
    4. Periodic cleanup of stale sessions
    """

    def __init__(
        self,
        max_sessions_per_server: int = 10,
        session_idle_timeout: int = 400,
        session_cleanup_interval: int = 120,
        server_timeout: int = 20,
    ):
        self.max_sessions_per_server = max_sessions_per_server
        self.session_idle_timeout = session_idle_timeout
        self.session_cleanup_interval = session_cleanup_interval
        self.server_timeout = server_timeout

        # Structure: server_key -> {"sessions": {session_id: session_info}, "last_cleanup": timestamp}
        self.sessions_by_server: dict[str, dict] = {}
        self._background_tasks: set[asyncio.Task] = set()
        # Backwards-compatibility maps: which context_id uses which (server_key, session_id)
        self._context_to_session: dict[str, tuple[str, str]] = {}
        # Reference count for each active (server_key, session_id)
        self._session_refcount: dict[tuple[str, str], int] = {}
        self._cleanup_task: asyncio.Task | None = None
        self._start_cleanup_task()
        _all_session_managers.add(self)

    def _start_cleanup_task(self):
        """Start the periodic cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            self._background_tasks.add(self._cleanup_task)
            self._cleanup_task.add_done_callback(self._background_tasks.discard)

    async def _periodic_cleanup(self):
        """Periodically clean up idle sessions."""
        while True:
            try:
                await asyncio.sleep(self.session_cleanup_interval)
                await self._cleanup_idle_sessions()
            except asyncio.CancelledError:
                break
            except (RuntimeError, KeyError, ClosedResourceError, ValueError, asyncio.TimeoutError) as e:
                logger.warning(f"Error in periodic cleanup: {e}")

    async def _cleanup_idle_sessions(self):
        """Clean up sessions that have been idle for too long."""
        current_time = asyncio.get_event_loop().time()
        servers_to_remove = []

        for server_key, server_data in self.sessions_by_server.items():
            sessions = server_data.get("sessions", {})
            sessions_to_remove = []

            for session_id, session_info in sessions.items():
                if current_time - session_info["last_used"] > self.session_idle_timeout:
                    sessions_to_remove.append(session_id)

            for session_id in sessions_to_remove:
                logger.info(f"Cleaning up idle session {session_id} for server {server_key}")
                await self._cleanup_session_by_id(server_key, session_id)

            if not sessions:
                servers_to_remove.append(server_key)

        for server_key in servers_to_remove:
            del self.sessions_by_server[server_key]

    def _get_server_key(self, connection_params: Any, transport_type: str) -> str:
        """Generate a consistent server key based on connection parameters."""
        if transport_type == "stdio":
            if hasattr(connection_params, "command"):
                command_str = f"{connection_params.command} {' '.join(connection_params.args or [])}"
                env_str = str(sorted((connection_params.env or {}).items()))
                key_input = f"{command_str}|{env_str}"
                return f"stdio_{hash(key_input)}"
        elif transport_type == "sse" and isinstance(connection_params, dict) and "url" in connection_params:
            url = connection_params["url"]
            headers = str(sorted((connection_params.get("headers", {})).items()))
            key_input = f"{url}|{headers}"
            return f"sse_{hash(key_input)}"

        return f"{transport_type}_{hash(str(connection_params))}"

    async def _validate_session_connectivity(self, session: ClientSession) -> bool:
        """Validate that the session is actually usable by testing a simple operation."""
        try:
            response = await asyncio.wait_for(session.list_tools(), timeout=3.0)
        except (asyncio.TimeoutError, ConnectionError, OSError, ValueError) as e:
            logger.debug(f"Session connectivity test failed (standard error): {e}")
            return False
        except Exception as e:
            error_str = str(e)
            if (
                "ClosedResourceError" in str(type(e))
                or "Connection closed" in error_str
                or "Connection lost" in error_str
                or "Connection failed" in error_str
                or "Transport closed" in error_str
                or "Stream closed" in error_str
            ):
                logger.debug(f"Session connectivity test failed (MCP connection error): {e}")
                return False
            logger.warning(f"Unexpected error in connectivity test: {e}")
            raise
        else:
            if response is None:
                logger.debug("Session connectivity test failed: received None response")
                return False
            try:
                tools = getattr(response, "tools", None)
                if tools is None:
                    logger.debug("Session connectivity test failed: no tools attribute in response")
                    return False
            except (AttributeError, TypeError) as e:
                logger.debug(f"Session connectivity test failed while validating response: {e}")
                return False
            else:
                logger.debug(f"Session connectivity test passed: found {len(tools)} tools")
                return True

    async def get_session(self, context_id: str, connection_params: Any, transport_type: str) -> ClientSession:
        """Get or create a session with improved reuse strategy."""
        server_key = self._get_server_key(connection_params, transport_type)

        if server_key not in self.sessions_by_server:
            self.sessions_by_server[server_key] = {"sessions": {}, "last_cleanup": asyncio.get_event_loop().time()}

        server_data = self.sessions_by_server[server_key]
        sessions = server_data["sessions"]

        # Try to find a healthy existing session
        for session_id, session_info in list(sessions.items()):
            session = session_info["session"]
            task = session_info["task"]

            if not task.done():
                session_info["last_used"] = asyncio.get_event_loop().time()

                if await self._validate_session_connectivity(session):
                    logger.debug(f"Reusing existing session {session_id} for server {server_key}")
                    self._context_to_session[context_id] = (server_key, session_id)
                    self._session_refcount[(server_key, session_id)] = (
                        self._session_refcount.get((server_key, session_id), 0) + 1
                    )
                    return session
                logger.info(f"Session {session_id} for server {server_key} failed health check, cleaning up")
                await self._cleanup_session_by_id(server_key, session_id)
            else:
                logger.info(f"Session {session_id} for server {server_key} task is done, cleaning up")
                await self._cleanup_session_by_id(server_key, session_id)

        # Check maximum sessions
        if len(sessions) >= self.max_sessions_per_server:
            oldest_session_id = min(sessions.keys(), key=lambda x: sessions[x]["last_used"])
            logger.info(
                f"Maximum sessions reached for server {server_key}, removing oldest session {oldest_session_id}"
            )
            await self._cleanup_session_by_id(server_key, oldest_session_id)

        # Create new session
        session_id = f"{server_key}_{len(sessions)}"
        logger.info(f"Creating new session {session_id} for server {server_key}")

        if transport_type == "stdio":
            session, task = await self._create_stdio_session(session_id, connection_params)
        elif transport_type == "sse":
            session, task = await self._create_sse_session(session_id, connection_params)
        else:
            msg = f"Unknown transport type: {transport_type}"
            raise ValueError(msg)

        sessions[session_id] = {
            "session": session,
            "task": task,
            "type": transport_type,
            "last_used": asyncio.get_event_loop().time(),
        }

        self._context_to_session[context_id] = (server_key, session_id)
        self._session_refcount[(server_key, session_id)] = 1

        return session

    async def _create_stdio_session(self, session_id: str, connection_params: Any) -> tuple[ClientSession, asyncio.Task]:
        """Create a new stdio session as a background task."""
        from mcp.client.stdio import stdio_client

        session_future: asyncio.Future[ClientSession] = asyncio.get_event_loop().create_future()

        async def session_task():
            try:
                async with stdio_client(connection_params) as (read, write):
                    session = ClientSession(read, write)
                    async with session:
                        await session.initialize()
                        session_future.set_result(session)

                        import anyio
                        event = anyio.Event()
                        try:
                            await event.wait()
                        except asyncio.CancelledError:
                            logger.info(f"Session {session_id} is shutting down")
            except Exception as e:
                if not session_future.done():
                    session_future.set_exception(e)

        task = asyncio.create_task(session_task())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        try:
            session = await asyncio.wait_for(session_future, timeout=float(self.server_timeout))
        except asyncio.TimeoutError as timeout_err:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self._background_tasks.discard(task)
            msg = f"Timeout waiting for STDIO session {session_id} to initialize"
            logger.error(msg)
            raise ValueError(msg) from timeout_err

        return session, task

    async def _create_sse_session(self, session_id: str, connection_params: dict) -> tuple[ClientSession, asyncio.Task]:
        """Create a new SSE session as a background task."""
        from mcp.client.sse import sse_client

        session_future: asyncio.Future[ClientSession] = asyncio.get_event_loop().create_future()

        async def session_task():
            try:
                async with sse_client(
                    connection_params["url"],
                    connection_params["headers"],
                    connection_params["timeout_seconds"],
                    connection_params["sse_read_timeout_seconds"],
                ) as (read, write):
                    session = ClientSession(read, write)
                    async with session:
                        await session.initialize()
                        session_future.set_result(session)

                        import anyio
                        event = anyio.Event()
                        try:
                            await event.wait()
                        except asyncio.CancelledError:
                            logger.info(f"Session {session_id} is shutting down")
            except Exception as e:
                if not session_future.done():
                    session_future.set_exception(e)

        task = asyncio.create_task(session_task())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        try:
            session = await asyncio.wait_for(session_future, timeout=float(self.server_timeout))
        except asyncio.TimeoutError as timeout_err:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self._background_tasks.discard(task)
            msg = f"Timeout waiting for SSE session {session_id} to initialize"
            logger.error(msg)
            raise ValueError(msg) from timeout_err

        return session, task

    async def _cleanup_session_by_id(self, server_key: str, session_id: str):
        """Clean up a specific session by server key and session ID."""
        if server_key not in self.sessions_by_server:
            return

        server_data = self.sessions_by_server[server_key]
        if isinstance(server_data, dict) and "sessions" in server_data:
            sessions = server_data["sessions"]
        else:
            sessions = server_data

        if session_id not in sessions:
            return

        session_info = sessions[session_id]
        timeout = SESSION_CLEANUP_TIMEOUT
        try:
            if "task" in session_info:
                task = session_info["task"]
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        logger.debug("Task for session %s cancelled/timed out", session_id)
        except Exception as e:
            logger.warning(f"Error cleaning up session {session_id}: {e}")
        finally:
            del sessions[session_id]

    async def cleanup_all(self):
        """Clean up all sessions."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task

        tasks_to_cancel = []
        for server_key in list(self.sessions_by_server.keys()):
            server_data = self.sessions_by_server[server_key]
            sessions = server_data.get("sessions", server_data) if isinstance(server_data, dict) and "sessions" in server_data else server_data
            for session_id, session_info in list(sessions.items()):
                if "task" in session_info:
                    task = session_info["task"]
                    if not task.done():
                        task.cancel()
                        tasks_to_cancel.append(task)

        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()
                tasks_to_cancel.append(task)

        if tasks_to_cancel:
            await asyncio.wait(tasks_to_cancel, timeout=SESSION_CLEANUP_TIMEOUT)

        self.sessions_by_server.clear()
        self._context_to_session.clear()
        self._session_refcount.clear()
        self._background_tasks.clear()
        _all_session_managers.discard(self)

    async def cleanup_session(self, context_id: str):
        """Cleanup by context_id with reference counting."""
        mapping = self._context_to_session.get(context_id)
        if not mapping:
            logger.debug(f"No session mapping found for context_id {context_id}")
            return

        server_key, session_id = mapping
        ref_key = (server_key, session_id)
        remaining = self._session_refcount.get(ref_key, 1) - 1

        if remaining <= 0:
            await self._cleanup_session_by_id(server_key, session_id)
            self._session_refcount.pop(ref_key, None)
        else:
            self._session_refcount[ref_key] = remaining

        self._context_to_session.pop(context_id, None)


async def cleanup_all_mcp_sessions() -> None:
    """Shut down every MCPSessionManager that was ever created."""
    managers = list(_all_session_managers)
    if not managers:
        return
    logger.debug(f"Cleaning up {len(managers)} MCP session manager(s)...")
    await asyncio.gather(
        *(m.cleanup_all() for m in managers),
        return_exceptions=True,
    )
    _all_session_managers.clear()
    logger.debug("MCP session cleanup complete")
