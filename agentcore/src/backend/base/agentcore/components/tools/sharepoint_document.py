"""SharePoint Documents component for the Agent Builder.

Reads connector credentials from the Connectors Catalogue (configured via the
Connectors page) and exposes document operations as tools that an agent can
invoke at runtime.

Pattern mirrors OutlookMailComponent — dropdown populated from the catalogue,
no manual credential fields. Uses client-credentials (app-only) auth.
"""

import asyncio
import base64
import concurrent.futures
import threading
import time

import httpx

from agentcore.custom.custom_node.node import Node
from agentcore.inputs.inputs import (
    DropdownInput,
    MessageTextInput,
    MultilineInput,
)
from agentcore.schema.message import Message
from agentcore.template.field.base import Output
from agentcore.logging import logger


# ---------------------------------------------------------------------------
# Path traversal guard (Step 1)
# ---------------------------------------------------------------------------

def _validate_path(path: str, label: str = "path") -> None:
    """Reject path values that could escape the intended directory."""
    if not path:
        return
    if "\x00" in path:
        raise ValueError(f"Invalid {label}: null bytes are not allowed")
    if "\\" in path:
        raise ValueError(f"Invalid {label}: backslashes are not allowed (use forward slashes)")
    for segment in path.replace("//", "/").split("/"):
        if segment == "..":
            raise ValueError(f"Invalid {label}: path traversal ('..') is not allowed")


# ---------------------------------------------------------------------------
# Shared sync engine (same approach as outlook_mail.py / database_connector.py)
# ---------------------------------------------------------------------------
_sync_engine = None
_sync_engine_lock = threading.Lock()


def _get_sync_engine():
    """Return a dedicated synchronous SQLAlchemy engine (created once)."""
    global _sync_engine
    if _sync_engine is not None:
        return _sync_engine

    with _sync_engine_lock:
        if _sync_engine is not None:
            return _sync_engine

        from sqlalchemy import create_engine
        from agentcore.services.deps import get_db_service

        db_service = get_db_service()
        db_url = db_service.database_url
        if "+asyncpg" in db_url:
            db_url = db_url.replace("+asyncpg", "")

        _sync_engine = create_engine(db_url, pool_pre_ping=True, pool_size=3)
        logger.info(f"Created sync engine for SharePointDocuments: {db_url.split('@')[-1]}")
        return _sync_engine


def _run_async(coro):
    """Run an async coroutine from a synchronous context."""
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=30)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Catalogue helpers
# ---------------------------------------------------------------------------
_SHAREPOINT_PROVIDERS = {"sharepoint"}

TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


def _fetch_sharepoint_connectors() -> list[str]:
    """Fetch SharePoint connectors from the catalogue.

    Returns list of strings: 'name | provider | site_url | uuid'
    """
    try:
        from agentcore.services.deps import get_db_service

        db_service = get_db_service()

        async def _query():
            from sqlalchemy import select
            from agentcore.services.database.models.connector_catalogue.model import (
                ConnectorCatalogue,
            )

            async with db_service.with_session() as session:
                stmt = (
                    select(ConnectorCatalogue)
                    .where(ConnectorCatalogue.provider.in_(_SHAREPOINT_PROVIDERS))
                    .where(ConnectorCatalogue.status == "connected")
                    .order_by(ConnectorCatalogue.name)
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()

                items = []
                for r in rows:
                    from agentcore.api.connector_catalogue import (
                        _decrypt_provider_config,
                    )

                    config = _decrypt_provider_config(r.provider, r.provider_config or {})
                    site_url = config.get("site_url", "no site configured")
                    items.append(f"{r.name} | {r.provider} | {site_url} | {r.id}")
                return items

        return _run_async(_query())
    except Exception as e:
        logger.warning(f"Could not fetch SharePoint connectors from catalogue: {e}")
        return []


def _get_sharepoint_config(connector_id: str) -> dict | None:
    """Fetch and decrypt SharePoint connector config by ID."""
    from uuid import UUID

    from sqlalchemy.orm import Session
    from agentcore.services.database.models.connector_catalogue.model import (
        ConnectorCatalogue,
    )

    try:
        engine = _get_sync_engine()
        with Session(engine) as session:
            row = session.get(ConnectorCatalogue, UUID(connector_id))
            if row is None:
                logger.warning(f"SharePoint connector {connector_id} not found")
                return None

            from agentcore.api.connector_catalogue import _decrypt_provider_config

            return _decrypt_provider_config(row.provider, row.provider_config or {})
    except Exception as e:
        logger.error(f"Failed to fetch SharePoint connector config: {e}", exc_info=True)
        return None


def _acquire_token_sync(config: dict) -> str:
    """Acquire a client-credentials access token synchronously.

    Caches in config dict under '_sp_access_token' / '_sp_token_expires_at'.
    """
    access_token = config.get("_sp_access_token", "")
    expires_at = config.get("_sp_token_expires_at", 0)

    if access_token and time.time() < (expires_at - 60):
        return access_token

    tenant_id = config.get("tenant_id", "")
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")

    if not all([tenant_id, client_id, client_secret]):
        raise ValueError("Missing tenant_id/client_id/client_secret in SharePoint connector config.")

    token_url = TOKEN_URL.format(tenant_id=tenant_id)
    resp = httpx.post(
        token_url,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=15,
    )

    if resp.status_code != 200:
        error_detail = resp.text[:300] if resp.text else "No details"
        raise ValueError(f"Token acquisition failed ({resp.status_code}): {error_detail}")

    data = resp.json()
    config["_sp_access_token"] = data["access_token"]
    config["_sp_token_expires_at"] = time.time() + data.get("expires_in", 3600)

    logger.info("SharePoint client-credentials token acquired")
    return data["access_token"]


# ---------------------------------------------------------------------------
# In-memory document ID mapping (mirrors MSG-1/MSG-2 from Outlook)
# ---------------------------------------------------------------------------
_doc_id_state = {"counter": 0, "map": {}}
_doc_id_lock = threading.Lock()


def _ensure_doc_id_globals():
    """Lazily initialize _doc_id_state and _doc_id_lock if not yet available."""
    global _doc_id_state, _doc_id_lock
    try:
        _doc_id_state  # noqa: B018
    except NameError:
        _doc_id_state = {"counter": 0, "map": {}}
    try:
        _doc_id_lock  # noqa: B018
    except NameError:
        _doc_id_lock = threading.Lock()


def _register_doc_id(item_id: str) -> str:
    """Store a Graph item ID and return a short human-friendly ref like 'DOC-1'."""
    _ensure_doc_id_globals()
    with _doc_id_lock:
        _doc_id_state["counter"] += 1
        ref = f"DOC-{_doc_id_state['counter']}"
        _doc_id_state["map"][ref] = item_id
    return ref


def _resolve_doc_id(ref: str) -> str:
    """Resolve a short ref (DOC-1) back to the real Graph item ID.

    Also accepts raw Graph IDs as fallback.
    """
    _ensure_doc_id_globals()
    with _doc_id_lock:
        id_map = _doc_id_state["map"]
        upper = ref.strip().upper()
        if upper in id_map:
            return id_map[upper]
        for key, val in id_map.items():
            if key.upper() == upper:
                return val
    # Fallback: caller passed a raw Graph ID directly
    return ref


def _parse_file_content(filename: str, content_bytes: bytes) -> str:
    """Parse file content using the existing attachment parser.

    Supports txt, csv, pdf, docx, xlsx, pptx via the Outlook attachment parser.
    """
    try:
        from agentcore.services.outlook.attachment_parser import parse_attachment

        b64_content = base64.b64encode(content_bytes).decode("ascii")
        result = parse_attachment(filename, b64_content)
        return result.get("text", "") if result else ""
    except Exception as e:
        logger.warning(f"Failed to parse file '{filename}': {e}")
        # Fallback: try as plain text
        try:
            return content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return f"(binary file, {len(content_bytes)} bytes — could not parse)"


# ---------------------------------------------------------------------------
# Shared HTTP client + retry wrapper (Step 2)
# ---------------------------------------------------------------------------
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_http_client: httpx.Client | None = None
_http_client_lock = threading.Lock()


def _get_http_client() -> httpx.Client:
    """Lazy-create a shared synchronous httpx.Client with connection pooling."""
    global _http_client, _http_client_lock
    try:
        _http_client_lock  # noqa: B018
    except NameError:
        _http_client_lock = threading.Lock()
    try:
        if _http_client is not None and not _http_client.is_closed:
            return _http_client
    except NameError:
        pass

    with _http_client_lock:
        try:
            if _http_client is not None and not _http_client.is_closed:
                return _http_client
        except NameError:
            pass
        _http_client = httpx.Client(
            timeout=30,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        return _http_client


def _request_sync(
    method: str,
    url: str,
    *,
    access_token: str,
    config: dict | None = None,
    headers: dict[str, str] | None = None,
    params: dict | None = None,
    json_payload: dict | None = None,
    content: bytes | None = None,
    timeout: float | None = None,
    max_retries: int = 3,
) -> httpx.Response:
    """Send an HTTP request with retry logic for 401, 429, and 5xx (Step 2).

    Handles token refresh when ``config`` is provided (mutates config in-place).
    """
    client = _get_http_client()
    current_token = access_token

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        if headers is None:
            req_headers = {"Authorization": f"Bearer {current_token}", "Content-Type": "application/json"}
        else:
            req_headers = dict(headers)
            if "Authorization" not in req_headers:
                req_headers["Authorization"] = f"Bearer {current_token}"

        try:
            kwargs: dict = {"headers": req_headers}
            if params is not None:
                kwargs["params"] = params
            if json_payload is not None:
                kwargs["json"] = json_payload
            if content is not None:
                kwargs["content"] = content
            if timeout is not None:
                kwargs["timeout"] = timeout

            resp = client.request(method, url, **kwargs)

            # 429 — rate limited
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "2"))
                retry_after = min(retry_after, 30)
                logger.warning(f"Graph API 429, retrying after {retry_after}s (attempt {attempt + 1})")
                time.sleep(retry_after)
                continue

            # 5xx — transient server error
            if resp.status_code in (500, 502, 503, 504):
                backoff = min(2 ** attempt, 8)
                logger.warning(f"Graph API {resp.status_code}, retrying after {backoff}s (attempt {attempt + 1})")
                time.sleep(backoff)
                continue

            # 401 — token expired, retry once
            if resp.status_code == 401 and attempt == 0 and config is not None:
                logger.warning("Graph API 401, re-acquiring token and retrying")
                config["_sp_access_token"] = None
                current_token = _acquire_token_sync(config)
                headers = None  # reset so next iteration rebuilds with new token
                continue

            return resp

        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            last_exc = exc
            backoff = min(2 ** attempt, 8)
            logger.warning(f"Graph API connection error: {exc}, retrying after {backoff}s")
            time.sleep(backoff)
            continue

    if last_exc:
        raise last_exc
    return resp  # type: ignore[possibly-undefined]


def _graph_get_sync(url: str, access_token: str, params: dict | None = None, timeout: int = 15, config: dict | None = None) -> httpx.Response:
    """Synchronous GET to Graph API with retry."""
    return _request_sync("GET", url, access_token=access_token, config=config, params=params, timeout=timeout)


def _graph_post_sync(url: str, access_token: str, json_payload: dict, timeout: int = 15, config: dict | None = None) -> httpx.Response:
    """Synchronous POST to Graph API with retry."""
    return _request_sync("POST", url, access_token=access_token, config=config, json_payload=json_payload, timeout=timeout)


def _graph_put_sync(url: str, access_token: str, content: bytes, timeout: int = 30, config: dict | None = None) -> httpx.Response:
    """Synchronous PUT to Graph API (for file upload) with retry."""
    return _request_sync(
        "PUT", url,
        access_token=access_token,
        config=config,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/octet-stream"},
        content=content,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Drive ID cache (Step 3)
# ---------------------------------------------------------------------------
_drive_id_cache: dict[str, str] = {}
_drive_id_cache_lock = threading.Lock()


def _resolve_site_id_sync(config: dict, access_token: str) -> str:
    """Resolve the SharePoint site URL to a Graph site ID (cached in config)."""
    cached = config.get("_site_id")
    if cached:
        return cached

    from urllib.parse import urlparse

    site_url = config.get("site_url", "")
    parsed = urlparse(site_url)
    hostname = parsed.hostname or parsed.netloc
    path = parsed.path.rstrip("/")

    if path:
        url = f"{GRAPH_BASE}/sites/{hostname}:{path}"
    else:
        url = f"{GRAPH_BASE}/sites/{hostname}"

    resp = _graph_get_sync(url, access_token, config=config)
    if resp.status_code != 200:
        raise ValueError(f"Failed to resolve SharePoint site ({resp.status_code}): {resp.text[:300]}")

    site_id = resp.json()["id"]
    config["_site_id"] = site_id
    return site_id


def _ensure_drive_cache_globals():
    """Lazily initialize _drive_id_cache and _drive_id_cache_lock if not yet available."""
    global _drive_id_cache, _drive_id_cache_lock
    try:
        _drive_id_cache  # noqa: B018
    except NameError:
        _drive_id_cache = {}
    try:
        _drive_id_cache_lock  # noqa: B018
    except NameError:
        _drive_id_cache_lock = threading.Lock()


def _resolve_drive_id_sync(site_id: str, library_name: str, access_token: str, config: dict | None = None) -> str:
    """Resolve a library name to a drive ID. Results are cached (Step 3)."""
    _ensure_drive_cache_globals()
    cache_key = f"{site_id}:{library_name.lower()}"

    with _drive_id_cache_lock:
        if cache_key in _drive_id_cache:
            return _drive_id_cache[cache_key]

    url = f"{GRAPH_BASE}/sites/{site_id}/drives"
    resp = _graph_get_sync(url, access_token, config=config)
    if resp.status_code != 200:
        raise ValueError(f"Failed to list drives ({resp.status_code}): {resp.text[:300]}")

    drives = resp.json().get("value", [])
    if not drives:
        raise ValueError("No document libraries found on this SharePoint site.")

    drive_id: str | None = None
    for drive in drives:
        if drive.get("name", "").lower() == library_name.lower():
            drive_id = drive["id"]
            break

    if drive_id is None:
        # Fallback: first drive
        logger.warning(f"Library '{library_name}' not found, using first drive: {drives[0].get('name')}")
        drive_id = drives[0]["id"]

    with _drive_id_cache_lock:
        _drive_id_cache[cache_key] = drive_id

    return drive_id


# ---------------------------------------------------------------------------
# Pagination helper (Step 5)
# ---------------------------------------------------------------------------

def _paginate_sync(url: str, access_token: str, params: dict | None = None, max_pages: int = 10, config: dict | None = None) -> list[dict]:
    """Follow @odata.nextLink to collect all pages (up to max_pages)."""
    all_items: list[dict] = []
    current_url = url
    current_params = params

    for _ in range(max_pages):
        resp = _graph_get_sync(current_url, access_token, params=current_params, config=config)
        if resp.status_code != 200:
            raise ValueError(f"Graph API error ({resp.status_code}): {resp.text[:300]}")

        data = resp.json()
        all_items.extend(data.get("value", []))

        next_link = data.get("@odata.nextLink")
        if not next_link:
            break
        # nextLink includes query params already
        current_url = next_link
        current_params = None

    return all_items


# ---------------------------------------------------------------------------
# Large file upload helper (Step 7)
# ---------------------------------------------------------------------------

def _upload_large_sync(
    drive_id: str,
    folder_path: str,
    filename: str,
    content_bytes: bytes,
    access_token: str,
    config: dict | None = None,
) -> dict:
    """Upload a large file (>4MB) using a Graph upload session.

    Creates an upload session and sends content in 3.2MB chunks
    (aligned to Graph API's 320KiB boundary requirement).
    """
    from urllib.parse import quote

    if folder_path:
        safe_folder = quote(folder_path.strip("/"), safe="/")
        safe_name = quote(filename, safe="")
        session_url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_folder}/{safe_name}:/createUploadSession"
    else:
        safe_name = quote(filename, safe="")
        session_url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_name}:/createUploadSession"

    session_payload = {
        "item": {
            "@microsoft.graph.conflictBehavior": "replace",
            "name": filename,
        }
    }

    resp = _graph_post_sync(session_url, access_token, session_payload, config=config)
    if resp.status_code not in (200, 201):
        raise ValueError(f"Failed to create upload session ({resp.status_code}): {resp.text[:300]}")

    upload_url = resp.json()["uploadUrl"]
    total_size = len(content_bytes)
    chunk_size = 3_200_000  # 3.2MB — multiple of 320KiB
    offset = 0

    try:
        client = _get_http_client()
        while offset < total_size:
            end = min(offset + chunk_size, total_size)
            chunk = content_bytes[offset:end]
            content_range = f"bytes {offset}-{end - 1}/{total_size}"

            chunk_resp = client.put(
                upload_url,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": content_range,
                },
                content=chunk,
                timeout=60,
            )

            if chunk_resp.status_code not in (200, 201, 202):
                raise ValueError(f"Chunk upload failed ({chunk_resp.status_code}): {chunk_resp.text[:300]}")

            offset = end

        return chunk_resp.json()  # type: ignore[possibly-undefined]

    except Exception:
        # Cleanup: cancel the upload session on failure
        try:
            client = _get_http_client()
            client.delete(upload_url, timeout=10)
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------

class SharePointDocumentComponent(Node):
    """Read, upload, and search documents in a SharePoint document library.

    Select a SharePoint connector from the dropdown (configured on the Connectors
    page). The agent can then list, read, upload, and search documents at runtime.
    """

    display_name = "SharePoint Documents"
    description = (
        "List, read, upload, and search documents in a SharePoint document library. "
        "Connect to the Connectors Catalogue to use app-registered SharePoint sites."
    )
    icon = "file-text"
    name = "SharePointDocuments"

    inputs = [
        DropdownInput(
            name="connector",
            display_name="SharePoint Connector",
            info="Select a SharePoint connector from the Connectors Catalogue.",
            options=[],
            value="",
            refresh_button=True,
            real_time_refresh=True,
            combobox=True,
        ),
        MessageTextInput(
            name="library",
            display_name="Library Name",
            info="Document library name (e.g. 'Shared Documents'). Leave empty for default.",
            value="Shared Documents",
            tool_mode=True,
        ),
        MessageTextInput(
            name="folder_path",
            display_name="Folder Path",
            info="Folder path within the library (e.g. 'Reports/2024'). Leave empty for root.",
            value="",
            tool_mode=True,
        ),
        MessageTextInput(
            name="file_id",
            display_name="File ID",
            info="DOC-N short ref or raw Graph item ID (from list_documents results).",
            value="",
            tool_mode=True,
        ),
        MessageTextInput(
            name="search_query",
            display_name="Search Query",
            info="Keyword to search for within the document library.",
            value="",
            tool_mode=True,
        ),
        MessageTextInput(
            name="upload_filename",
            display_name="Upload Filename",
            info="Filename for the uploaded document (e.g. 'report.txt').",
            value="",
            tool_mode=True,
        ),
        MultilineInput(
            name="upload_content",
            display_name="Upload Content",
            info="Text content to upload as a file.",
            value="",
            tool_mode=True,
        ),
        MessageTextInput(
            name="folder_name",
            display_name="New Folder Name",
            info="Name for a new folder to create.",
            value="",
            tool_mode=True,
        ),
    ]

    outputs = [
        Output(
            display_name="List Documents",
            name="list_documents",
            method="list_documents",
            types=["Message"],
        ),
        Output(
            display_name="Read Document",
            name="read_document",
            method="read_document",
            types=["Message"],
        ),
        Output(
            display_name="Upload Document",
            name="upload_document",
            method="upload_document",
            types=["Message"],
        ),
        Output(
            display_name="Search Documents",
            name="search_documents",
            method="search_documents",
            types=["Message"],
        ),
        Output(
            display_name="Create Folder",
            name="create_folder",
            method="create_folder",
            types=["Message"],
        ),
    ]

    def update_build_config(self, build_config: dict, field_value: str, field_name: str | None = None):
        """Refresh the connector dropdown from the Connectors Catalogue."""
        if field_name == "connector":
            try:
                options = _fetch_sharepoint_connectors()
                build_config["connector"]["options"] = options if options else []
                current = build_config["connector"].get("value", "")
                if current not in options:
                    build_config["connector"]["value"] = options[0] if options else ""
            except Exception as e:
                logger.warning(f"Error fetching SharePoint connectors: {e}")
                build_config["connector"]["options"] = []
        return build_config

    def _get_selected_config(self) -> dict:
        """Parse the selected connector dropdown and fetch config from DB."""
        selected = self.connector
        if not selected:
            raise ValueError("No SharePoint connector selected. Please select one from the dropdown.")

        # Parse: "name | provider | site_url | uuid"
        parts = [p.strip() for p in selected.split("|")]
        if len(parts) < 4:
            raise ValueError(f"Invalid connector format: {selected}. Please refresh the dropdown.")

        connector_id = parts[3]
        config = _get_sharepoint_config(connector_id)
        if config is None:
            raise ValueError(f"Connector '{parts[0]}' not found or has been deleted. Please refresh.")

        config["_connector_id"] = connector_id
        return config

    def _get_client_context(self) -> tuple[dict, str, str, str]:
        """Get config, access token, site ID, and drive ID for the selected connector.

        Returns (config, access_token, site_id, drive_id).
        """
        config = self._get_selected_config()
        access_token = _acquire_token_sync(config)
        site_id = _resolve_site_id_sync(config, access_token)
        library_name = self.library.strip() if self.library else "Shared Documents"
        drive_id = _resolve_drive_id_sync(site_id, library_name, access_token, config=config)
        return config, access_token, site_id, drive_id

    def list_documents(self) -> Message:
        """List documents in the SharePoint library."""
        try:
            config, access_token, site_id, drive_id = self._get_client_context()
        except Exception as e:
            self.status = f"Error: {e!s}"
            return Message(text=f"Failed to connect to SharePoint: {e!s}")

        folder_path = self.folder_path.strip() if self.folder_path else ""

        # Step 1: path validation
        try:
            _validate_path(folder_path, "folder_path")
        except ValueError as e:
            self.status = f"Error: {e!s}"
            return Message(text=str(e))

        from urllib.parse import quote

        if folder_path:
            safe_path = quote(folder_path.strip("/"), safe="/")
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_path}:/children"
        else:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root/children"

        params = {
            "$top": "50",
            "$select": "id,name,size,lastModifiedDateTime,createdDateTime,webUrl,file,folder",
        }

        # Step 5: pagination
        try:
            items = _paginate_sync(url, access_token, params=params, config=config)
        except Exception as e:
            self.status = f"Request failed: {e!s}"
            return Message(text=f"Graph API request failed: {e!s}")

        lines = []
        for item in items:
            item_id = item.get("id", "")
            short_ref = _register_doc_id(item_id)
            name = item.get("name", "unknown")
            is_folder = "folder" in item

            if is_folder:
                child_count = item.get("folder", {}).get("childCount", 0)
                entry = (
                    f"---\n"
                    f"**ID:** `{short_ref}`\n"
                    f"**Name:** {name}/\n"
                    f"**Type:** Folder ({child_count} items)\n"
                    f"**Modified:** {item.get('lastModifiedDateTime', '')}\n"
                )
            else:
                size = item.get("size", 0)
                mime = item.get("file", {}).get("mimeType", "")
                size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} MB"
                entry = (
                    f"---\n"
                    f"**ID:** `{short_ref}`\n"
                    f"**Name:** {name}\n"
                    f"**Type:** File ({mime})\n"
                    f"**Size:** {size_str}\n"
                    f"**Modified:** {item.get('lastModifiedDateTime', '')}\n"
                )

            lines.append(entry)

        library_name = self.library.strip() if self.library else "Shared Documents"
        count = len(items)
        self.status = f"{count} item(s) in {library_name}"

        if not lines:
            path_desc = f" in {folder_path}" if folder_path else ""
            return Message(text=f"No items found{path_desc} in library '{library_name}'.")

        path_desc = f" / {folder_path}" if folder_path else ""
        header = f"**{count} item(s)** in `{library_name}{path_desc}`:\n\n"
        header += "**Note:** Use the short ID (e.g. DOC-1) when reading a document.\n\n"
        return Message(text=header + "\n".join(lines))

    def read_document(self) -> Message:
        """Read/download a document from SharePoint and parse its content."""
        raw_id = self.file_id.strip() if self.file_id else ""
        if not raw_id:
            self.status = "Error: no file_id"
            return Message(text="file_id is required. Use list_documents first to get document IDs (e.g. DOC-1).")

        item_id = _resolve_doc_id(raw_id)

        try:
            config, access_token, site_id, drive_id = self._get_client_context()
        except Exception as e:
            self.status = f"Error: {e!s}"
            return Message(text=f"Failed to connect to SharePoint: {e!s}")

        from urllib.parse import quote

        # Get metadata (retry handled by _request_sync)
        meta_url = f"{GRAPH_BASE}/drives/{drive_id}/items/{quote(item_id, safe='')}"
        try:
            meta_resp = _graph_get_sync(meta_url, access_token, config=config)
        except Exception as e:
            self.status = f"Request failed: {e!s}"
            return Message(text=f"Failed to fetch file metadata: {e!s}")

        if meta_resp.status_code != 200:
            self.status = f"Graph API error {meta_resp.status_code}"
            return Message(text=f"Failed to get file metadata ({meta_resp.status_code}): {meta_resp.text[:300]}")

        metadata = meta_resp.json()
        filename = metadata.get("name", "unknown")
        size = metadata.get("size", 0)

        # Check if it's a folder
        if "folder" in metadata:
            self.status = "Error: item is a folder"
            return Message(text=f"'{filename}' is a folder, not a file. Use list_documents to browse its contents.")

        # Download content (retry handled by _request_sync)
        content_url = f"{GRAPH_BASE}/drives/{drive_id}/items/{quote(item_id, safe='')}/content"
        try:
            content_resp = _request_sync(
                "GET", content_url,
                access_token=access_token,
                config=config,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=60,
            )
        except Exception as e:
            self.status = f"Download failed: {e!s}"
            return Message(text=f"Failed to download file: {e!s}")

        if content_resp.status_code != 200:
            self.status = f"Download error {content_resp.status_code}"
            return Message(text=f"Failed to download file ({content_resp.status_code}): {content_resp.text[:300]}")

        content_bytes = content_resp.content

        # Parse content
        parsed_text = _parse_file_content(filename, content_bytes)

        size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} MB"

        # Truncate very long content
        if len(parsed_text) > 10000:
            parsed_text = parsed_text[:10000] + f"\n\n... (truncated, {len(parsed_text)} chars total)"

        self.status = f"Read: {filename} ({size_str})"
        result = (
            f"**Document:** {filename}\n"
            f"**Size:** {size_str}\n"
            f"**Modified:** {metadata.get('lastModifiedDateTime', '')}\n"
            f"**URL:** {metadata.get('webUrl', '')}\n\n"
            f"---\n\n"
            f"{parsed_text}"
        )
        return Message(text=result)

    def upload_document(self) -> Message:
        """Upload a text file to SharePoint."""
        filename = self.upload_filename.strip() if self.upload_filename else ""
        content = self.upload_content.strip() if self.upload_content else ""

        if not filename:
            self.status = "Error: no filename"
            return Message(text="upload_filename is required. Provide a name for the file (e.g. 'report.txt').")

        if not content:
            self.status = "Error: no content"
            return Message(text="upload_content is required. Provide the text content to upload.")

        try:
            config, access_token, site_id, drive_id = self._get_client_context()
        except Exception as e:
            self.status = f"Error: {e!s}"
            return Message(text=f"Failed to connect to SharePoint: {e!s}")

        folder_path = self.folder_path.strip() if self.folder_path else ""

        # Step 1: path validation
        try:
            _validate_path(folder_path, "folder_path")
            _validate_path(filename, "filename")
        except ValueError as e:
            self.status = f"Error: {e!s}"
            return Message(text=str(e))

        content_bytes = content.encode("utf-8")

        # Step 7: large file upload support
        if len(content_bytes) > 4 * 1024 * 1024:
            try:
                result = _upload_large_sync(drive_id, folder_path, filename, content_bytes, access_token, config=config)
            except Exception as e:
                self.status = f"Upload failed: {e!s}"
                return Message(text=f"Large file upload failed: {e!s}")

            web_url = result.get("webUrl", "")
            self.status = f"Uploaded: {filename}"
            path_desc = f" to {folder_path}" if folder_path else ""
            return Message(text=f"File '{filename}' uploaded successfully{path_desc}.\n\n**URL:** {web_url}")

        from urllib.parse import quote

        if folder_path:
            safe_folder = quote(folder_path.strip("/"), safe="/")
            safe_name = quote(filename, safe="")
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_folder}/{safe_name}:/content"
        else:
            safe_name = quote(filename, safe="")
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_name}:/content"

        # Retry handled by _graph_put_sync / _request_sync
        try:
            resp = _graph_put_sync(url, access_token, content_bytes, config=config)
        except Exception as e:
            self.status = f"Upload failed: {e!s}"
            return Message(text=f"Upload request failed: {e!s}")

        if resp.status_code not in (200, 201):
            self.status = f"Upload failed ({resp.status_code})"
            return Message(text=f"Upload failed ({resp.status_code}): {resp.text[:300]}")

        result = resp.json()
        web_url = result.get("webUrl", "")
        self.status = f"Uploaded: {filename}"

        path_desc = f" to {folder_path}" if folder_path else ""
        return Message(text=f"File '{filename}' uploaded successfully{path_desc}.\n\n**URL:** {web_url}")

    def search_documents(self) -> Message:
        """Search for documents by keyword in the SharePoint library."""
        query = self.search_query.strip() if self.search_query else ""
        if not query:
            self.status = "Error: no search query"
            return Message(text="search_query is required. Provide a keyword to search for.")

        try:
            config, access_token, site_id, drive_id = self._get_client_context()
        except Exception as e:
            self.status = f"Error: {e!s}"
            return Message(text=f"Failed to connect to SharePoint: {e!s}")

        safe_query = query.replace("'", "''")
        url = f"{GRAPH_BASE}/drives/{drive_id}/root/search(q='{safe_query}')"

        # Step 5: pagination + Step 6: $select
        params = {
            "$select": "id,name,size,lastModifiedDateTime,webUrl,file,folder",
        }

        try:
            items = _paginate_sync(url, access_token, params=params, config=config)
        except Exception as e:
            self.status = f"Search failed: {e!s}"
            return Message(text=f"Search request failed: {e!s}")

        lines = []
        for item in items:
            item_id = item.get("id", "")
            short_ref = _register_doc_id(item_id)
            name = item.get("name", "unknown")
            is_folder = "folder" in item

            size = item.get("size", 0)
            size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} MB"

            entry = (
                f"---\n"
                f"**ID:** `{short_ref}`\n"
                f"**Name:** {name}{'/' if is_folder else ''}\n"
                f"**Type:** {'Folder' if is_folder else 'File'}\n"
                f"**Size:** {size_str}\n"
                f"**Modified:** {item.get('lastModifiedDateTime', '')}\n"
            )
            lines.append(entry)

        count = len(items)
        self.status = f"Search: {count} result(s) for '{query}'"

        if not lines:
            return Message(text=f"No documents found matching '{query}'.")

        header = f"**{count} result(s)** for search query `{query}`:\n\n"
        header += "**Note:** Use the short ID (e.g. DOC-1) when reading a document.\n\n"
        return Message(text=header + "\n".join(lines))

    def create_folder(self) -> Message:
        """Create a new folder in the SharePoint library (Step 8)."""
        folder_name = self.folder_name.strip() if self.folder_name else ""
        if not folder_name:
            self.status = "Error: no folder_name"
            return Message(text="folder_name is required. Provide a name for the new folder.")

        folder_path = self.folder_path.strip() if self.folder_path else ""

        # Step 1: path validation
        try:
            _validate_path(folder_name, "folder_name")
            _validate_path(folder_path, "folder_path")
        except ValueError as e:
            self.status = f"Error: {e!s}"
            return Message(text=str(e))

        try:
            config, access_token, site_id, drive_id = self._get_client_context()
        except Exception as e:
            self.status = f"Error: {e!s}"
            return Message(text=f"Failed to connect to SharePoint: {e!s}")

        from urllib.parse import quote

        if folder_path:
            safe_parent = quote(folder_path.strip("/"), safe="/")
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_parent}:/children"
        else:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root/children"

        payload = {
            "name": folder_name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        }

        try:
            resp = _graph_post_sync(url, access_token, payload, config=config)
        except Exception as e:
            self.status = f"Create folder failed: {e!s}"
            return Message(text=f"Failed to create folder: {e!s}")

        if resp.status_code not in (200, 201):
            self.status = f"Create folder failed ({resp.status_code})"
            return Message(text=f"Failed to create folder ({resp.status_code}): {resp.text[:300]}")

        result = resp.json()
        web_url = result.get("webUrl", "")
        self.status = f"Created folder: {folder_name}"

        path_desc = f" in {folder_path}" if folder_path else " at root"
        return Message(text=f"Folder '{folder_name}' created successfully{path_desc}.\n\n**URL:** {web_url}")
