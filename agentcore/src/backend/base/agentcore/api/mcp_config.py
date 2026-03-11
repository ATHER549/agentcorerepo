import contextlib
import json
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.api.files_user import MCP_SERVERS_FILE, delete_file, download_file, get_file_by_name, upload_user_file
from agentcore.logging import logger
from agentcore.services.mcp_service_client import test_mcp_connection_via_service
from agentcore.services.deps import get_settings_service, get_storage_service

router = APIRouter(tags=["MCP"], prefix="/mcp")


async def upload_server_config(
    server_config: dict,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service=Depends(get_storage_service),
    settings_service=Depends(get_settings_service),
):
    content_str = json.dumps(server_config)
    content_bytes = content_str.encode("utf-8")  # Convert to bytes
    file_obj = BytesIO(content_bytes)  # Use BytesIO for binary data

    upload_file = UploadFile(file=file_obj, filename=MCP_SERVERS_FILE + ".json", size=len(content_str))

    return await upload_user_file(
        file=upload_file,
        session=session,
        current_user=current_user,
        storage_service=storage_service,
        settings_service=settings_service,
    )


async def get_server_list(
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service=Depends(get_storage_service),
    settings_service=Depends(get_settings_service),
):
    # Read the server configuration from a file using the files api
    server_config_file = await get_file_by_name(MCP_SERVERS_FILE, current_user, session)

    # Attempt to download the configuration file content
    try:
        server_config_bytes = await download_file(
            server_config_file.id if server_config_file else None,
            current_user,
            session,
            storage_service=storage_service,
            return_content=True,
        )
    except (FileNotFoundError, HTTPException):
        # Storage file missing - DB entry may be stale. Remove it and recreate.
        if server_config_file:
            with contextlib.suppress(Exception):
                await delete_file(server_config_file.id, current_user, session, storage_service)

        # Create a fresh empty config
        await upload_server_config(
            {"mcpServers": {}},
            current_user,
            session,
            storage_service=storage_service,
            settings_service=settings_service,
        )

        # Fetch and download again
        server_config_file = await get_file_by_name(MCP_SERVERS_FILE, current_user, session)
        if not server_config_file:
            raise HTTPException(status_code=500, detail="Failed to create _mcp_servers.json") from None

        server_config_bytes = await download_file(
            server_config_file.id,
            current_user,
            session,
            storage_service=storage_service,
            return_content=True,
        )

    # Parse JSON content
    try:
        servers = json.loads(server_config_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid server configuration file format.") from None

    return servers


async def get_server(
    server_name: str,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service=Depends(get_storage_service),
    settings_service=Depends(get_settings_service),
    server_list: dict | None = None,
):
    """Get a specific server configuration."""
    if server_list is None:
        server_list = await get_server_list(current_user, session, storage_service, settings_service)

    if server_name not in server_list["mcpServers"]:
        return None

    return server_list["mcpServers"][server_name]


# Define a Get servers endpoint
@router.get("/servers")
async def get_servers(
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service=Depends(get_storage_service),
    settings_service=Depends(get_settings_service),
    action_count: bool | None = None,
):
    """Get the list of available servers."""
    import asyncio

    server_list = await get_server_list(current_user, session, storage_service, settings_service)

    if not action_count:
        # Return only the server names, with mode and toolsCount as None
        return [{"name": server_name, "mode": None, "toolsCount": None} for server_name in server_list["mcpServers"]]

    # Check all of the tool counts for each server concurrently
    async def check_server(server_name: str) -> dict:
        server_info: dict[str, str | int | None] = {"name": server_name, "mode": None, "toolsCount": None}
        try:
            cfg = server_list["mcpServers"][server_name]
            # Build a test-connection request for the MCP microservice
            body: dict = {}
            if "url" in cfg:
                body["mode"] = "sse"
                body["url"] = cfg["url"]
                if cfg.get("headers"):
                    body["headers"] = cfg["headers"]
                server_info["mode"] = "sse"
            elif "command" in cfg:
                body["mode"] = "stdio"
                body["command"] = cfg["command"]
                if cfg.get("args"):
                    body["args"] = cfg["args"]
                server_info["mode"] = "stdio"
            if cfg.get("env"):
                body["env_vars"] = cfg["env"]

            result = await test_mcp_connection_via_service(body)
            if result.get("success"):
                tools_count = result.get("tools_count", 0)
                server_info["toolsCount"] = tools_count
                if tools_count == 0:
                    server_info["error"] = "No tools found"
            else:
                server_info["error"] = result.get("message", "Connection failed")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error checking server {server_name}: {e}")
            server_info["error"] = f"Error loading server: {e}"
        return server_info

    # Run all server checks concurrently
    tasks = [check_server(server) for server in server_list["mcpServers"]]
    return await asyncio.gather(*tasks, return_exceptions=True)


@router.get("/servers/{server_name}")
async def get_server_endpoint(
    server_name: str,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service=Depends(get_storage_service),
    settings_service=Depends(get_settings_service),
):
    """Get a specific server."""
    return await get_server(server_name, current_user, session, storage_service, settings_service)


async def update_server(
    server_name: str,
    server_config: dict,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service=Depends(get_storage_service),
    settings_service=Depends(get_settings_service),
    *,
    check_existing: bool = False,
    delete: bool = False,
):
    server_list = await get_server_list(current_user, session, storage_service, settings_service)

    # Validate server name
    if check_existing and server_name in server_list["mcpServers"]:
        raise HTTPException(status_code=500, detail="Server already exists.")

    # Handle the delete case
    if delete:
        if server_name in server_list["mcpServers"]:
            del server_list["mcpServers"][server_name]
        else:
            raise HTTPException(status_code=500, detail="Server not found.")
    else:
        server_list["mcpServers"][server_name] = server_config

    # Remove the existing file
    server_config_file = await get_file_by_name(MCP_SERVERS_FILE, current_user, session)

    if server_config_file:
        await delete_file(server_config_file.id, current_user, session, storage_service)

    # Upload the updated server configuration
    await upload_server_config(
        server_list, current_user, session, storage_service=storage_service, settings_service=settings_service
    )

    return await get_server(
        server_name,
        current_user,
        session,
        storage_service,
        settings_service,
        server_list=server_list,
    )


@router.post("/servers/{server_name}")
async def add_server(
    server_name: str,
    server_config: dict,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service=Depends(get_storage_service),
    settings_service=Depends(get_settings_service),
):
    return await update_server(
        server_name,
        server_config,
        current_user,
        session,
        storage_service,
        settings_service,
        check_existing=True,
    )


@router.patch("/servers/{server_name}")
async def update_server_endpoint(
    server_name: str,
    server_config: dict,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service=Depends(get_storage_service),
    settings_service=Depends(get_settings_service),
):
    return await update_server(
        server_name,
        server_config,
        current_user,
        session,
        storage_service,
        settings_service,
    )


@router.delete("/servers/{server_name}")
async def delete_server(
    server_name: str,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service=Depends(get_storage_service),
    settings_service=Depends(get_settings_service),
):
    return await update_server(
        server_name,
        {},
        current_user,
        session,
        storage_service,
        settings_service,
        delete=True,
    )
