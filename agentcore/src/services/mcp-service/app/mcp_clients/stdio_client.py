"""MCP STDIO client for subprocess-based MCP servers."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import uuid
from typing import Any

from anyio import ClosedResourceError
from mcp import ClientSession, StdioServerParameters
from mcp.shared.exceptions import McpError

from app.mcp_clients.session_manager import MCPSessionManager

logger = logging.getLogger(__name__)


class MCPStdioClient:
    def __init__(self, session_manager: MCPSessionManager):
        self.session: ClientSession | None = None
        self._connection_params = None
        self._connected = False
        self._session_context: str | None = None
        self._session_manager = session_manager

    async def _connect_to_server(self, command_str: str, env: dict[str, str] | None = None) -> list:
        """Connect to MCP server using stdio transport (SDK style)."""
        command = command_str.split(" ")
        env_data: dict[str, str] = {"DEBUG": "true", "PATH": os.environ.get("PATH", ""), **(env or {})}

        if platform.system() == "Windows":
            server_params = StdioServerParameters(
                command="cmd",
                args=[
                    "/c",
                    f"{command[0]} {' '.join(command[1:])} || echo Command failed with exit code %errorlevel% 1>&2",
                ],
                env=env_data,
            )
        else:
            server_params = StdioServerParameters(
                command="bash",
                args=["-c", f"exec {command_str} || echo 'Command failed with exit code $?' >&2"],
                env=env_data,
            )

        self._connection_params = server_params

        if not self._session_context:
            param_hash = uuid.uuid4().hex[:8]
            self._session_context = f"default_{param_hash}"

        session = await self._get_or_create_session()
        response = await session.list_tools()
        self._connected = True
        return response.tools

    async def connect_to_server(self, command_str: str, env: dict[str, str] | None = None) -> list:
        """Connect to MCP server using stdio transport with timeout."""
        return await asyncio.wait_for(
            self._connect_to_server(command_str, env),
            timeout=self._session_manager.server_timeout,
        )

    def set_session_context(self, context_id: str):
        """Set the session context for session reuse."""
        self._session_context = context_id

    async def _get_or_create_session(self) -> ClientSession:
        """Get or create a persistent session for the current context."""
        if not self._session_context or not self._connection_params:
            msg = "Session context and connection params must be set"
            raise ValueError(msg)

        return await self._session_manager.get_session(self._session_context, self._connection_params, "stdio")

    async def run_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Run a tool with the given arguments using context-specific session."""
        if not self._connected or not self._connection_params:
            msg = "Session not initialized or disconnected. Call connect_to_server first."
            raise ValueError(msg)

        if not self._session_context:
            param_hash = uuid.uuid4().hex[:8]
            self._session_context = f"default_{param_hash}"

        max_retries = 2
        last_error_type = None

        for attempt in range(max_retries):
            try:
                logger.debug(f"Attempting to run tool '{tool_name}' (attempt {attempt + 1}/{max_retries})")
                session = await self._get_or_create_session()

                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments=arguments),
                    timeout=30.0,
                )
            except Exception as e:
                current_error_type = type(e).__name__
                logger.warning(f"Tool '{tool_name}' failed on attempt {attempt + 1}: {current_error_type} - {e}")

                is_closed_resource_error = isinstance(e, ClosedResourceError)
                is_mcp_connection_error = isinstance(e, McpError) and "Connection closed" in str(e)
                is_timeout_error = isinstance(e, (asyncio.TimeoutError, TimeoutError))

                if last_error_type == current_error_type and attempt > 0:
                    logger.error(f"Repeated {current_error_type} error for tool '{tool_name}', not retrying")
                    break

                last_error_type = current_error_type

                if (is_closed_resource_error or is_mcp_connection_error) and attempt < max_retries - 1:
                    logger.warning(f"MCP session connection issue for tool '{tool_name}', retrying with fresh session...")
                    if self._session_context:
                        await self._session_manager.cleanup_session(self._session_context)
                    await asyncio.sleep(0.5)
                    continue

                if is_timeout_error and attempt < max_retries - 1:
                    logger.warning(f"Tool '{tool_name}' timed out, retrying...")
                    await asyncio.sleep(1.0)
                    continue

                if (
                    isinstance(e, (ConnectionError, TimeoutError, OSError, ValueError))
                    or is_closed_resource_error
                    or is_mcp_connection_error
                    or is_timeout_error
                ):
                    msg = f"Failed to run tool '{tool_name}' after {attempt + 1} attempts: {e}"
                    logger.error(msg)
                    self._connected = False
                    raise ValueError(msg) from e
                raise
            else:
                logger.debug(f"Tool '{tool_name}' completed successfully")
                return result

        msg = f"Failed to run tool '{tool_name}': Maximum retries exceeded with repeated {last_error_type} errors"
        logger.error(msg)
        raise ValueError(msg)

    async def disconnect(self):
        """Properly close the connection and clean up resources."""
        if self._session_context:
            await self._session_manager.cleanup_session(self._session_context)

        self.session = None
        self._connection_params = None
        self._connected = False
        self._session_context = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
