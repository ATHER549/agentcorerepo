"""Microsoft Graph SharePoint client — isolated from Teams and Outlook modules.

Handles client-credentials OAuth token lifecycle and all SharePoint document
operations (list drives, list items, read/upload files, search, create folders).

Uses app-only (client credentials) authentication — no user delegation needed.
Does NOT import from ``services/teams/`` or ``services/outlook/`` — completely independent.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from loguru import logger

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


# ── Path traversal guard (Step 1) ─────────────────────────────────

def _validate_path(path: str, label: str = "path") -> None:
    """Reject path values that could escape the intended directory.

    Raises ValueError on ``..``, backslashes, or null bytes.
    """
    if not path:
        return
    if "\x00" in path:
        raise ValueError(f"Invalid {label}: null bytes are not allowed")
    if "\\" in path:
        raise ValueError(f"Invalid {label}: backslashes are not allowed (use forward slashes)")
    # Normalise consecutive slashes and check each segment
    for segment in path.replace("//", "/").split("/"):
        if segment == "..":
            raise ValueError(f"Invalid {label}: path traversal ('..') is not allowed")


class SharePointGraphClient:
    """Client for Microsoft Graph SharePoint API operations.

    Uses client credentials flow (app-only) — no user interaction required.
    Requires Azure AD app with Sites.Read.All / Sites.ReadWrite.All / Files.ReadWrite.All
    (Application type) permissions with admin consent.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        site_url: str,
    ):
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._site_url = site_url
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._site_id: str | None = None
        # Shared HTTP client (Step 2)
        self._client: httpx.AsyncClient | None = None
        # Drive ID cache (Step 3)
        self._drive_cache: dict[str, str] = {}

    # ── Shared HTTP client (Step 2) ────────────────────────────────

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Lazy-create a shared AsyncClient with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def close(self) -> None:
        """Close the shared HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json: dict | None = None,
        content: bytes | None = None,
        timeout: float | None = None,
        max_retries: int = 3,
    ) -> httpx.Response:
        """Send an HTTP request with retry logic for 401, 429, and 5xx errors."""
        client = await self._ensure_client()
        if headers is None:
            headers = await self._headers()

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                kwargs: dict[str, Any] = {"headers": headers}
                if params is not None:
                    kwargs["params"] = params
                if json is not None:
                    kwargs["json"] = json
                if content is not None:
                    kwargs["content"] = content
                if timeout is not None:
                    kwargs["timeout"] = timeout

                resp = await client.request(method, url, **kwargs)

                # 429 — rate limited
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", "2"))
                    retry_after = min(retry_after, 30)  # safety cap
                    logger.warning(f"Graph API 429, retrying after {retry_after}s (attempt {attempt + 1})")
                    await asyncio.sleep(retry_after)
                    continue

                # 5xx — transient server error
                if resp.status_code in (500, 502, 503, 504):
                    backoff = min(2 ** attempt, 8)
                    logger.warning(f"Graph API {resp.status_code}, retrying after {backoff}s (attempt {attempt + 1})")
                    await asyncio.sleep(backoff)
                    continue

                # 401 — token expired, retry once
                if resp.status_code == 401 and attempt == 0:
                    logger.warning("Graph API 401, re-acquiring token and retrying")
                    self.invalidate_token()
                    headers = await self._headers()
                    continue

                resp.raise_for_status()
                return resp

            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
                backoff = min(2 ** attempt, 8)
                logger.warning(f"Graph API connection error: {exc}, retrying after {backoff}s")
                await asyncio.sleep(backoff)
                continue

        # Exhausted retries
        if last_exc:
            raise last_exc
        raise httpx.HTTPStatusError(
            f"Request failed after {max_retries} retries",
            request=httpx.Request(method, url),
            response=resp,  # type: ignore[possibly-undefined]
        )

    # ── Authentication (client credentials) ───────────────────────

    async def _acquire_token(self) -> str:
        """Acquire an app-only access token via client credentials flow.

        Caches the token and refreshes when within 60s of expiry.
        """
        if self._access_token and time.time() < (self._token_expires_at - 60):
            return self._access_token

        token_url = TOKEN_URL.format(tenant_id=self._tenant_id)
        client = await self._ensure_client()
        resp = await client.post(
            token_url,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        logger.debug("SharePoint client-credentials token acquired")
        return self._access_token

    async def _headers(self) -> dict[str, str]:
        """Return Authorization header with a valid Bearer token."""
        token = await self._acquire_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def invalidate_token(self) -> None:
        """Force token re-acquisition on next request (used for 401 retry)."""
        self._access_token = None
        self._token_expires_at = 0.0

    # ── Pagination helper (Step 5) ─────────────────────────────────

    async def _paginate(
        self,
        url: str,
        params: dict[str, str] | None = None,
        max_pages: int = 10,
    ) -> list[dict]:
        """Follow @odata.nextLink to collect all pages (up to max_pages)."""
        all_items: list[dict] = []
        current_url = url
        current_params = params

        for _ in range(max_pages):
            resp = await self._request("GET", current_url, params=current_params)
            data = resp.json()
            all_items.extend(data.get("value", []))

            next_link = data.get("@odata.nextLink")
            if not next_link:
                break
            # nextLink includes query params already
            current_url = next_link
            current_params = None

        return all_items

    # ── Site resolution ───────────────────────────────────────────

    def _parse_site_url(self) -> tuple[str, str]:
        """Extract hostname and site path from the configured site_url.

        Examples:
            https://contoso.sharepoint.com/sites/Marketing
            → ("contoso.sharepoint.com", "/sites/Marketing")

            https://contoso.sharepoint.com
            → ("contoso.sharepoint.com", "")
        """
        parsed = urlparse(self._site_url)
        hostname = parsed.hostname or parsed.netloc
        path = parsed.path.rstrip("/")
        return hostname, path

    async def resolve_site_id(self) -> str:
        """Resolve the configured site URL to a Graph site ID. Cached after first call."""
        if self._site_id:
            return self._site_id

        hostname, path = self._parse_site_url()

        if path:
            url = f"{GRAPH_BASE}/sites/{hostname}:{path}"
        else:
            url = f"{GRAPH_BASE}/sites/{hostname}"

        resp = await self._request("GET", url)
        self._site_id = resp.json()["id"]
        logger.debug(f"Resolved SharePoint site ID: {self._site_id}")
        return self._site_id

    # ── Drive (document library) operations ───────────────────────

    async def list_drives(self) -> list[dict]:
        """List all document libraries (drives) for the site."""
        site_id = await self.resolve_site_id()
        url = f"{GRAPH_BASE}/sites/{site_id}/drives"
        return await self._paginate(url)

    async def resolve_drive_id(self, library_name: str = "Shared Documents") -> str:
        """Find a drive ID by library display name (case-insensitive).

        Falls back to the first drive if no match found. Results are cached (Step 3).
        """
        cache_key = library_name.lower()
        if cache_key in self._drive_cache:
            return self._drive_cache[cache_key]

        drives = await self.list_drives()
        if not drives:
            msg = "No document libraries found on this SharePoint site."
            raise ValueError(msg)

        drive_id: str | None = None
        for drive in drives:
            if drive.get("name", "").lower() == cache_key:
                drive_id = drive["id"]
                break

        if drive_id is None:
            # Fallback: first drive
            logger.warning(
                f"Library '{library_name}' not found, using first drive: {drives[0].get('name')}"
            )
            drive_id = drives[0]["id"]

        self._drive_cache[cache_key] = drive_id
        return drive_id

    # ── File / folder operations ──────────────────────────────────

    async def list_items(
        self,
        drive_id: str,
        folder_path: str = "",
        top: int = 50,
    ) -> list[dict]:
        """List files and folders in a drive path.

        Args:
            drive_id: The drive (document library) ID.
            folder_path: Path within the drive (e.g. "Reports/2024"). Empty = root.
            top: Maximum items per page.
        """
        _validate_path(folder_path, "folder_path")

        if folder_path and folder_path.strip("/"):
            safe_path = quote(folder_path.strip("/"), safe="/")
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_path}:/children"
        else:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root/children"

        params: dict[str, str] = {
            "$top": str(top),
            "$select": "id,name,size,lastModifiedDateTime,createdDateTime,webUrl,file,folder",
        }

        return await self._paginate(url, params)

    async def read_file(self, drive_id: str, item_id: str) -> bytes:
        """Download file content by item ID.

        Returns raw bytes of the file.
        """
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{quote(item_id, safe='')}/content"
        headers = await self._headers()
        # Remove Content-Type for download
        headers.pop("Content-Type", None)
        resp = await self._request("GET", url, headers=headers, timeout=60)
        return resp.content

    async def get_file_metadata(self, drive_id: str, item_id: str) -> dict:
        """Get metadata for a single file/folder by item ID."""
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{quote(item_id, safe='')}"
        resp = await self._request("GET", url)
        return resp.json()

    async def upload_file(
        self,
        drive_id: str,
        folder_path: str,
        filename: str,
        content: bytes,
    ) -> dict:
        """Upload a file to a folder in the drive.

        Files <=4MB use simple PUT. Files >4MB use resumable upload session (Step 7).

        Args:
            drive_id: The drive (document library) ID.
            folder_path: Folder path (e.g. "Reports/2024"). Empty = root.
            filename: Name for the uploaded file.
            content: Raw bytes to upload.

        Returns:
            The created driveItem metadata dict.
        """
        _validate_path(folder_path, "folder_path")
        _validate_path(filename, "filename")

        # Delegate large files to upload session (Step 7)
        if len(content) > 4 * 1024 * 1024:
            return await self.upload_large_file(drive_id, folder_path, filename, content)

        headers = await self._headers()
        headers["Content-Type"] = "application/octet-stream"

        if folder_path and folder_path.strip("/"):
            safe_folder = quote(folder_path.strip("/"), safe="/")
            safe_name = quote(filename, safe="")
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_folder}/{safe_name}:/content"
        else:
            safe_name = quote(filename, safe="")
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_name}:/content"

        resp = await self._request("PUT", url, headers=headers, content=content, timeout=30)
        return resp.json()

    async def upload_large_file(
        self,
        drive_id: str,
        folder_path: str,
        filename: str,
        content: bytes,
    ) -> dict:
        """Upload a large file (>4MB) using a Graph upload session (Step 7).

        Creates an upload session and sends content in 3.2MB chunks
        (aligned to Graph API's 320KiB boundary requirement).
        """
        # Build the item path for the upload session
        if folder_path and folder_path.strip("/"):
            safe_folder = quote(folder_path.strip("/"), safe="/")
            safe_name = quote(filename, safe="")
            session_url = (
                f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_folder}/{safe_name}:/createUploadSession"
            )
        else:
            safe_name = quote(filename, safe="")
            session_url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_name}:/createUploadSession"

        session_payload = {
            "item": {
                "@microsoft.graph.conflictBehavior": "replace",
                "name": filename,
            }
        }

        resp = await self._request("POST", session_url, json=session_payload)
        session_data = resp.json()
        upload_url = session_data["uploadUrl"]

        total_size = len(content)
        chunk_size = 3_200_000  # 3.2MB — multiple of 320KiB (327680)
        offset = 0

        try:
            while offset < total_size:
                end = min(offset + chunk_size, total_size)
                chunk = content[offset:end]
                content_range = f"bytes {offset}-{end - 1}/{total_size}"

                chunk_headers = {
                    "Content-Length": str(len(chunk)),
                    "Content-Range": content_range,
                }

                resp = await self._request(
                    "PUT",
                    upload_url,
                    headers=chunk_headers,
                    content=chunk,
                    timeout=60,
                )

                offset = end

            return resp.json()

        except Exception:
            # Cleanup: cancel the upload session on failure
            try:
                client = await self._ensure_client()
                await client.delete(upload_url, timeout=10)
            except Exception:
                pass
            raise

    async def search_files(self, drive_id: str, query: str) -> list[dict]:
        """Search for files by keyword within a drive.

        Args:
            drive_id: The drive (document library) ID.
            query: Search keyword.
        """
        safe_query = query.replace("'", "''")
        url = f"{GRAPH_BASE}/drives/{drive_id}/root/search(q='{safe_query}')"

        # Step 6: $select to reduce payload size
        params = {
            "$select": "id,name,size,lastModifiedDateTime,webUrl,file,folder",
        }

        return await self._paginate(url, params)

    async def create_folder(
        self,
        drive_id: str,
        parent_path: str,
        folder_name: str,
    ) -> dict:
        """Create a new folder in the drive.

        Args:
            drive_id: The drive (document library) ID.
            parent_path: Parent folder path (empty = root).
            folder_name: Name for the new folder.

        Returns:
            The created driveItem metadata dict.
        """
        _validate_path(parent_path, "parent_path")
        _validate_path(folder_name, "folder_name")

        if parent_path and parent_path.strip("/"):
            safe_parent = quote(parent_path.strip("/"), safe="/")
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_parent}:/children"
        else:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root/children"

        payload: dict[str, Any] = {
            "name": folder_name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        }

        resp = await self._request("POST", url, json=payload)
        return resp.json()
