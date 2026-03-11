"""MCP SSE client for HTTP-based MCP servers."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx
from anyio import ClosedResourceError
from mcp import ClientSession
from mcp.shared.exceptions import McpError

from app.mcp_clients.helpers import process_headers
from app.mcp_clients.session_manager import MCPSessionManager

logger = logging.getLogger(__name__)

HTTP_NOT_FOUND = 404
HTTP_BAD_REQUEST = 400
HTTP_INTERNAL_SERVER_ERROR = 500


class MCPSseClient:
    def __init__(self, session_manager: MCPSessionManager):
        self.session: ClientSession | None = None
        self._connection_params: dict | None = None
        self._connected = False
        self._session_context: str | None = None
        self._session_manager = session_manager

    async def validate_url(self, url: str | None, headers: dict[str, str] | None = None) -> tuple[bool, str]:
        """Validate the SSE URL before attempting connection."""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False, "Invalid URL format. Must include scheme (http/https) and host."

            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get(
                        url, timeout=2.0, headers={"Accept": "text/event-stream", **(headers or {})}
                    )

                    if response.status_code == HTTP_NOT_FOUND:
                        return True, ""

                    if (
                        HTTP_BAD_REQUEST <= response.status_code < HTTP_INTERNAL_SERVER_ERROR
                        and response.status_code != HTTP_NOT_FOUND
                    ):
                        return False, f"Server returned client error status: {response.status_code}"

                except httpx.TimeoutException:
                    return True, ""
                except httpx.NetworkError:
                    return False, "Network error. Could not reach the server."
                else:
                    return True, ""

        except (httpx.HTTPError, ValueError, OSError) as e:
            return False, f"URL validation error: {e!s}"

    async def pre_check_redirect(self, url: str | None, headers: dict[str, str] | None = None) -> str | None:
        """Check for redirects and return the final URL."""
        if url is None:
            return url
        try:
            async with httpx.AsyncClient(follow_redirects=False) as client:
                response = await client.get(
                    url, timeout=2.0, headers={"Accept": "text/event-stream", **(headers or {})}
                )
                if response.status_code == httpx.codes.TEMPORARY_REDIRECT:
                    return response.headers.get("Location", url)
        except (httpx.RequestError, httpx.HTTPError) as e:
            logger.warning(f"Error checking redirects: {e}")
        return url

    async def _connect_to_server(
        self,
        url: str | None,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 30,
        sse_read_timeout_seconds: int = 30,
    ) -> list:
        """Connect to MCP server using SSE transport."""
        validated_headers = process_headers(headers)

        if url is None:
            msg = "URL is required for SSE mode"
            raise ValueError(msg)
        is_valid, error_msg = await self.validate_url(url, validated_headers)
        if not is_valid:
            msg = f"Invalid SSE URL ({url}): {error_msg}"
            raise ValueError(msg)

        url = await self.pre_check_redirect(url, validated_headers)

        self._connection_params = {
            "url": url,
            "headers": validated_headers,
            "timeout_seconds": timeout_seconds,
            "sse_read_timeout_seconds": sse_read_timeout_seconds,
        }

        if not self._session_context:
            param_hash = uuid.uuid4().hex[:8]
            self._session_context = f"default_sse_{param_hash}"

        session = await self._get_or_create_session()
        response = await session.list_tools()
        self._connected = True
        return response.tools

    async def connect_to_server(self, url: str, headers: dict[str, str] | None = None) -> list:
        """Connect to MCP server using SSE transport with timeout."""
        return await asyncio.wait_for(
            self._connect_to_server(url, headers),
            timeout=self._session_manager.server_timeout,
        )

    def set_session_context(self, context_id: str):
        """Set the session context for session reuse."""
        self._session_context = context_id

    async def _get_or_create_session(self) -> ClientSession:
        """Get or create a persistent session for the current context."""
        if not self._session_context or not self._connection_params:
            msg = "Session context and params must be set"
            raise ValueError(msg)

        self.session = await self._session_manager.get_session(self._session_context, self._connection_params, "sse")
        return self.session

    async def _terminate_remote_session(self) -> None:
        """Attempt to explicitly terminate the remote MCP session via HTTP DELETE."""
        if not self._connection_params or "url" not in self._connection_params:
            return

        url: str = self._connection_params["url"]

        session_id = None
        if getattr(self, "session", None) is not None:
            session_id = getattr(self.session, "session_id", None) or getattr(self.session, "id", None)

        headers: dict[str, str] = dict(self._connection_params.get("headers", {}))
        if session_id:
            headers["Mcp-Session-Id"] = str(session_id)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.delete(url, headers=headers)
        except Exception as e:
            logger.debug(f"Unable to send session DELETE to '{url}': {e}")

    async def run_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Run a tool with the given arguments using context-specific session."""
        if not self._connected or not self._connection_params:
            msg = "Session not initialized or disconnected. Call connect_to_server first."
            raise ValueError(msg)

        if not self._session_context:
            param_hash = uuid.uuid4().hex[:8]
            self._session_context = f"default_sse_{param_hash}"

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
        await self._terminate_remote_session()

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
