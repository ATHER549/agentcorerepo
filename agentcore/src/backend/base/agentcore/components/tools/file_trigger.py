"""File Trigger component.

Monitors Azure Blob Storage or SharePoint for new or changed files.
Credentials are NOT stored inline — a connector is selected from the
Connectors Catalogue (configured on the Connectors page). This keeps
secrets centralised and auditable.

For production scheduling, configure automations in the Automations page.

**How to use in a flow:**

    FileTrigger ──[Files]──► Multimodal Document Loader ──► LLM

With *Download Files* enabled, FileTrigger downloads files to a temp
directory and outputs local file paths.  Connect the *Files* output to
the Multimodal Document Loader (or any node that accepts file paths)
for content extraction.

With *Download Files* disabled, only file metadata is returned (name,
path, type, size) — useful for routing or filtering before downloading.
"""

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone

from loguru import logger

from agentcore.base.data.utils import TEXT_FILE_TYPES
from agentcore.custom.custom_node.node import Node
from agentcore.io import (
    BoolInput,
    DropdownInput,
    IntInput,
    MessageTextInput,
    MultiselectInput,
    Output,
)
from agentcore.schema.data import Data
from agentcore.schema.message import Message
from agentcore.utils.constants import MESSAGE_SENDER_USER


# ---------------------------------------------------------------------------
# Async helper (same pattern as database_connector.py)
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine from a synchronous context.

    NOTE: import concurrent.futures locally because components are loaded
    via exec() from string, so module-level imports may not be in scope.
    """
    import concurrent.futures as _cf

    try:
        asyncio.get_running_loop()
        with _cf.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=30)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Catalogue helpers
# ---------------------------------------------------------------------------

_STORAGE_TYPE_TO_PROVIDER = {
    "Azure Blob Storage": "azure_blob",
    "SharePoint": "sharepoint",
}


def _fetch_storage_connectors(provider_key: str) -> list[str]:
    """Return connector dropdown options for a given provider.

    Format: "name | provider | target_info | uuid"
    """
    try:
        from agentcore.services.deps import get_db_service

        db_service = get_db_service()

        async def _query():
            from sqlalchemy import select
            from agentcore.services.database.models.connector_catalogue.model import ConnectorCatalogue

            async with db_service.with_session() as session:
                stmt = (
                    select(ConnectorCatalogue)
                    .where(ConnectorCatalogue.provider == provider_key)
                    .order_by(ConnectorCatalogue.name)
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()
                options = []
                for r in rows:
                    cfg = r.provider_config or {}
                    if provider_key == "azure_blob":
                        target = cfg.get("container_name", "—")
                    else:  # sharepoint
                        target = cfg.get("site_url", "—")
                    options.append(f"{r.name} | {r.provider} | {target} | {r.id}")
                return options

        return _run_async(_query())
    except Exception as e:
        logger.warning(f"Could not fetch storage connectors from catalogue: {e}")
        return []


def _get_storage_connector_config(connector_id: str) -> dict | None:
    """Fetch and decrypt a storage connector's provider_config from the DB."""
    from uuid import UUID

    try:
        from agentcore.services.deps import get_db_service

        db_service = get_db_service()

        async def _query():
            from agentcore.services.database.models.connector_catalogue.model import ConnectorCatalogue

            async with db_service.with_session() as session:
                row = await session.get(ConnectorCatalogue, UUID(connector_id))
                if row is None:
                    logger.warning(f"Storage connector {connector_id} not found")
                    return None

                raw_config = row.provider_config or {}
                try:
                    from agentcore.api.connector_catalogue import _decrypt_provider_config
                    config = _decrypt_provider_config(row.provider, raw_config)
                except Exception as e:
                    logger.error(f"Failed to decrypt provider_config: {e}")
                    config = raw_config

                return {"provider": row.provider, **config}

        return _run_async(_query())
    except Exception as e:
        logger.error(f"Failed to fetch storage connector config for {connector_id}: {e}", exc_info=True)
        return None


def _parse_connector_id(connector_value: str) -> str | None:
    """Extract UUID from a connector dropdown option string.

    Format: "name | provider | target | uuid"
    """
    if not connector_value:
        return None
    parts = connector_value.split("|")
    if len(parts) >= 4:
        return parts[-1].strip()
    # Maybe the value IS a plain UUID
    return connector_value.strip()


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------

class FileTrigger(Node):
    display_name = "File Trigger"
    description = (
        "Monitors Azure Blob Storage or SharePoint for new or changed files. "
        "Downloads files to a temp directory and outputs local file paths. "
        "Connect to the Multimodal Document Loader for text extraction."
    )
    icon = "FolderSearch"
    name = "FileTrigger"

    inputs = [
        DropdownInput(
            name="storage_type",
            display_name="Storage Type",
            options=["Azure Blob Storage", "SharePoint"],
            value="Azure Blob Storage",
            info="Select the cloud storage backend to monitor.",
            real_time_refresh=True,
        ),
        # --- Cloud storage: connector selector ---
        DropdownInput(
            name="connector",
            display_name="Connector",
            info=(
                "Select a connector configured on the Connectors page. "
                "The connector holds the credentials for Azure Blob or SharePoint."
            ),
            options=[],
            value="",
            refresh_button=True,
            real_time_refresh=True,
        ),
        # --- Download toggle ---
        BoolInput(
            name="download_files",
            display_name="Download Files",
            value=True,
            info=(
                "When ON, downloads files to a temp directory and outputs local paths "
                "(connect to Multimodal Document Loader for extraction). "
                "When OFF, outputs metadata only (file name, path, size)."
            ),
        ),
        # --- Common ---
        MultiselectInput(
            name="file_types",
            display_name="File Types",
            options=TEXT_FILE_TYPES,
            value=[],
            info="File types to monitor. Leave empty for all supported types.",
        ),
        DropdownInput(
            name="trigger_on",
            display_name="Trigger On",
            options=["New Files", "Modified Files", "Both"],
            value="New Files",
            info="When to trigger: on new files only, modified files only, or both.",
        ),
        IntInput(
            name="batch_size",
            display_name="Batch Size",
            value=10,
            info="Maximum files to process per trigger. 0 = unlimited.",
        ),
        MessageTextInput(
            name="session_id",
            display_name="Session ID",
            info="The session ID for this trigger. If empty, a new session is created per execution.",
            advanced=True,
        ),
        MessageTextInput(
            name="_trigger_files",
            display_name="Injected Trigger Files",
            value="",
            info="Internal: JSON data injected by TriggerService. Do not edit manually.",
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Files",
            name="files",
            method="files_output",
            output_types=["Data"],
            is_list=True,
        ),
        Output(
            display_name="Trigger Info",
            name="trigger_info",
            method="info_output",
        ),
    ]

    def update_build_config(self, build_config, field_value, field_name=None):
        """Refresh connector options when storage_type changes."""
        storage_type = build_config["storage_type"]["value"]

        provider_key = _STORAGE_TYPE_TO_PROVIDER.get(storage_type)
        if provider_key:
            options = _fetch_storage_connectors(provider_key)
            build_config["connector"]["options"] = options
            if options and not build_config["connector"].get("value"):
                build_config["connector"]["value"] = options[0]

        return build_config

    # ── Azure Blob ─────────────────────────────────────────────────────────

    async def _scan_azure_blob(self) -> list[Data]:
        """Scan Azure Blob Storage — list files, optionally download to temp dir."""

        connector_id = _parse_connector_id(self.connector)
        if not connector_id:
            logger.warning("FileTrigger: no connector selected for Azure Blob Storage")
            return []

        config = _get_storage_connector_config(connector_id)
        if not config:
            logger.error(f"FileTrigger: could not load connector config for {connector_id}")
            return []

        connection_string = config.get("connection_string", "")
        container_name = config.get("container_name", "")
        prefix = config.get("blob_prefix", "")

        if not connection_string or not container_name:
            logger.error("FileTrigger: Azure connector is missing connection_string or container_name")
            return []

        download = self.download_files

        def _do_scan():
            try:
                from azure.storage.blob import BlobServiceClient
            except ImportError:
                raise ImportError(
                    "azure-storage-blob is required. Install with: pip install azure-storage-blob"
                )

            types = self.file_types if self.file_types else TEXT_FILE_TYPES
            batch_size = self.batch_size

            logger.info(f"FileTrigger: connecting to container={container_name}, prefix={prefix!r}")
            blob_service = BlobServiceClient.from_connection_string(connection_string)
            container_client = blob_service.get_container_client(container_name)
            blobs = list(container_client.list_blobs(name_starts_with=prefix if prefix else None))
            logger.info(f"FileTrigger: found {len(blobs)} total blobs: {[b.name for b in blobs]}")
            logger.info(f"FileTrigger: file_types filter={types}")

            # Normalize types — accept both "txt" and ".txt"
            norm_types = set()
            for t in types:
                t = t.strip().lower()
                if t.startswith("."):
                    t = t[1:]
                norm_types.add(t)

            filtered = [
                b for b in blobs
                if not norm_types or (b.name.rsplit(".", 1)[-1].lower() if "." in b.name else "") in norm_types
            ]
            logger.info(f"FileTrigger: {len(filtered)} blobs after filter: {[b.name for b in filtered]}")
            if batch_size and batch_size > 0:
                filtered = filtered[:batch_size]

            # Create temp dir for downloads
            temp_dir = tempfile.mkdtemp(prefix="agentcore_fm_") if download else None

            data_list = []
            for blob in filtered:
                try:
                    file_name = blob.name.rsplit("/", 1)[-1]
                    ext = file_name.rsplit(".", 1)[-1] if "." in file_name else ""
                    local_path = ""

                    if download and temp_dir:
                        blob_client = container_client.get_blob_client(blob.name)
                        raw_bytes = blob_client.download_blob().readall()
                        local_path = os.path.join(temp_dir, file_name)
                        with open(local_path, "wb") as f:
                            f.write(raw_bytes)

                    data_list.append(
                        Data(
                            data={
                                "text": local_path,
                                "file_name": file_name,
                                "file_path": local_path,
                                "file_type": ext,
                                "source": f"azure://{container_name}/{blob.name}",
                                "size_bytes": blob.size or 0,
                                "last_modified": (
                                    blob.last_modified.isoformat() if blob.last_modified else ""
                                ),
                                "storage_type": "Azure Blob Storage",
                                "connector_id": connector_id,
                            }
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to process blob {blob.name}: {e}")

            return data_list

        return await asyncio.to_thread(_do_scan)

    # ── SharePoint ─────────────────────────────────────────────────────────

    async def _scan_sharepoint(self) -> list[Data]:
        """Scan SharePoint document library — list files, optionally download to temp dir.

        Uses Microsoft Graph API (client-credentials) instead of Office365-REST-Python-Client
        so that only Graph API permissions are needed (Sites.Read.All / Sites.ReadWrite.All).
        """

        connector_id = _parse_connector_id(self.connector)
        if not connector_id:
            logger.warning("FileTrigger: no connector selected for SharePoint")
            return []

        config = _get_storage_connector_config(connector_id)
        if not config:
            logger.error(f"FileTrigger: could not load connector config for {connector_id}")
            return []

        site_url = config.get("site_url", "")
        client_id = config.get("client_id", "")
        client_secret = config.get("client_secret", "")
        tenant_id = config.get("tenant_id", "")
        library = config.get("library", "Shared Documents")
        folder = config.get("folder", "")

        if not site_url or not client_id or not client_secret:
            logger.error("FileTrigger: SharePoint connector is missing site_url, client_id, or client_secret")
            return []

        download = self.download_files

        def _do_scan():
            import httpx
            from urllib.parse import urlparse

            GRAPH = "https://graph.microsoft.com/v1.0"
            types = self.file_types if self.file_types else TEXT_FILE_TYPES
            batch_size = self.batch_size

            # Normalize types
            norm_types = set()
            for t in types:
                t_clean = t.strip().lower().lstrip(".")
                if t_clean:
                    norm_types.add(t_clean)

            # 1. Acquire token via client credentials
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            token_resp = httpx.post(token_url, data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
            }, timeout=15)
            if token_resp.status_code != 200:
                logger.error(f"FileTrigger: failed to get Graph token: {token_resp.text[:300]}")
                return []
            access_token = token_resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {access_token}"}

            # 2. Resolve site ID
            parsed = urlparse(site_url)
            hostname = parsed.hostname or parsed.netloc
            path = parsed.path.rstrip("/")
            site_api = f"{GRAPH}/sites/{hostname}:{path}" if path else f"{GRAPH}/sites/{hostname}"
            site_resp = httpx.get(site_api, headers=headers, timeout=15)
            if site_resp.status_code != 200:
                logger.error(f"FileTrigger: failed to resolve site: {site_resp.text[:300]}")
                return []
            site_id = site_resp.json()["id"]

            # 3. Resolve drive ID
            drives_resp = httpx.get(f"{GRAPH}/sites/{site_id}/drives", headers=headers, timeout=15)
            if drives_resp.status_code != 200:
                logger.error(f"FileTrigger: failed to list drives: {drives_resp.text[:300]}")
                return []
            drives = drives_resp.json().get("value", [])
            drive_id = None
            for d in drives:
                if d.get("name", "").lower() == library.lower():
                    drive_id = d["id"]
                    break
            if not drive_id and drives:
                drive_id = drives[0]["id"]
            if not drive_id:
                logger.error("FileTrigger: no drives found on SharePoint site")
                return []

            # 4. List files (root or subfolder)
            if folder:
                items_url = f"{GRAPH}/drives/{drive_id}/root:/{folder}:/children?$top=200"
            else:
                items_url = f"{GRAPH}/drives/{drive_id}/root/children?$top=200"
            items_resp = httpx.get(items_url, headers=headers, timeout=15)
            if items_resp.status_code != 200:
                logger.error(f"FileTrigger: failed to list items: {items_resp.text[:300]}")
                return []
            items = items_resp.json().get("value", [])

            # Filter to files only (exclude folders), then by type
            files = [i for i in items if "file" in i]
            if norm_types:
                files = [
                    f for f in files
                    if (f["name"].rsplit(".", 1)[-1].lower() if "." in f["name"] else "") in norm_types
                ]
            if batch_size and batch_size > 0:
                files = files[:batch_size]

            # 5. Build results, optionally download
            temp_dir = tempfile.mkdtemp(prefix="agentcore_fm_") if download else None
            data_list = []

            for item in files:
                try:
                    file_name = item["name"]
                    ext = file_name.rsplit(".", 1)[-1] if "." in file_name else ""
                    local_path = ""
                    file_size = item.get("size", 0)

                    if download and temp_dir:
                        dl_url = f"{GRAPH}/drives/{drive_id}/items/{item['id']}/content"
                        dl_resp = httpx.get(dl_url, headers=headers, timeout=60, follow_redirects=True)
                        if dl_resp.status_code == 200:
                            local_path = os.path.join(temp_dir, file_name)
                            with open(local_path, "wb") as out_f:
                                out_f.write(dl_resp.content)
                            file_size = len(dl_resp.content)

                    data_list.append(
                        Data(
                            data={
                                "text": local_path,
                                "file_name": file_name,
                                "file_path": local_path,
                                "file_type": ext,
                                "source": f"sharepoint://{site_url}/{library}/{folder}/{file_name}".replace("//", "/").replace("sharepoint:/", "sharepoint://"),
                                "size_bytes": file_size,
                                "last_modified": item.get("lastModifiedDateTime", ""),
                                "storage_type": "SharePoint",
                                "connector_id": connector_id,
                            }
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to process SharePoint file {item.get('name', '?')}: {e}")

            return data_list

        return await asyncio.to_thread(_do_scan)

    # ── Download from injected metadata (TriggerService path) ──────────────

    async def _download_from_metadata(self, file_metas: list[dict]) -> list[Data]:
        """Download files using metadata injected by TriggerService via tweaks.

        TriggerService already detected new files and passes their metadata
        (name, path, size, modified). This method downloads them by path
        without re-listing the container.
        """
        connector_id = _parse_connector_id(self.connector)
        if not connector_id:
            logger.warning("FileTrigger: no connector for _download_from_metadata")
            return [Data(data=meta) for meta in file_metas]

        config = _get_storage_connector_config(connector_id)
        if not config:
            logger.error(f"FileTrigger: could not load connector for _download_from_metadata")
            return [Data(data=meta) for meta in file_metas]

        storage_type = self.storage_type
        download = self.download_files

        def _do_download():
            temp_dir = tempfile.mkdtemp(prefix="agentcore_fm_") if download else None
            data_list = []

            for meta in file_metas:
                file_name = meta.get("name", "unknown")
                blob_path = meta.get("path", "")
                ext = file_name.rsplit(".", 1)[-1] if "." in file_name else ""
                local_path = ""

                if download and temp_dir and blob_path:
                    try:
                        if storage_type == "Azure Blob Storage":
                            from azure.storage.blob import BlobServiceClient
                            conn_str = config.get("connection_string", "")
                            container = config.get("container_name", "")
                            blob_service = BlobServiceClient.from_connection_string(conn_str)
                            container_client = blob_service.get_container_client(container)
                            blob_client = container_client.get_blob_client(blob_path)
                            raw_bytes = blob_client.download_blob().readall()
                            local_path = os.path.join(temp_dir, file_name)
                            with open(local_path, "wb") as f:
                                f.write(raw_bytes)
                        elif storage_type == "SharePoint":
                            import httpx as _httpx
                            from urllib.parse import urlparse as _urlparse

                            _GRAPH = "https://graph.microsoft.com/v1.0"
                            _tenant = config.get("tenant_id", "")
                            _cid = config.get("client_id", "")
                            _csec = config.get("client_secret", "")
                            _site_url = config.get("site_url", "")

                            # Get token
                            _tok_resp = _httpx.post(
                                f"https://login.microsoftonline.com/{_tenant}/oauth2/v2.0/token",
                                data={"grant_type": "client_credentials", "client_id": _cid,
                                      "client_secret": _csec, "scope": "https://graph.microsoft.com/.default"},
                                timeout=15,
                            )
                            if _tok_resp.status_code == 200:
                                _token = _tok_resp.json()["access_token"]
                                _headers = {"Authorization": f"Bearer {_token}"}

                                # Use item_id if available (from Graph-based trigger)
                                item_id = meta.get("item_id", "")
                                if item_id:
                                    # Resolve drive_id from site
                                    _parsed = _urlparse(_site_url)
                                    _host = _parsed.hostname or _parsed.netloc
                                    _path = _parsed.path.rstrip("/")
                                    _site_api = f"{_GRAPH}/sites/{_host}:{_path}" if _path else f"{_GRAPH}/sites/{_host}"
                                    _sr = _httpx.get(_site_api, headers=_headers, timeout=15)
                                    if _sr.status_code == 200:
                                        _sid = _sr.json()["id"]
                                        _dr = _httpx.get(f"{_GRAPH}/sites/{_sid}/drives", headers=_headers, timeout=15)
                                        if _dr.status_code == 200:
                                            _drives = _dr.json().get("value", [])
                                            _did = _drives[0]["id"] if _drives else ""
                                            if _did:
                                                _dl = _httpx.get(
                                                    f"{_GRAPH}/drives/{_did}/items/{item_id}/content",
                                                    headers=_headers, timeout=60, follow_redirects=True,
                                                )
                                                if _dl.status_code == 200:
                                                    local_path = os.path.join(temp_dir, file_name)
                                                    with open(local_path, "wb") as f:
                                                        f.write(_dl.content)
                    except Exception as e:
                        logger.warning(f"FileTrigger: failed to download {file_name}: {e}")

                data_list.append(
                    Data(
                        data={
                            "text": local_path,
                            "file_name": file_name,
                            "file_path": local_path,
                            "file_type": ext,
                            "source": meta.get("path", ""),
                            "size_bytes": meta.get("size", 0),
                            "last_modified": meta.get("modified", ""),
                            "storage_type": storage_type,
                            "connector_id": connector_id,
                        }
                    )
                )
            return data_list

        return await asyncio.to_thread(_do_download)

    # ── Outputs ────────────────────────────────────────────────────────────

    async def files_output(self) -> list[Data]:
        """Detect files from cloud storage, optionally download, return as list of Data."""
        logger.info(f"FileTrigger.files_output() called — storage_type={self.storage_type}, connector={self.connector}, download={self.download_files}")

        # 1. Check for TriggerService-injected metadata (skip scan)
        if hasattr(self, "_trigger_files") and self._trigger_files:
            try:
                injected = json.loads(self._trigger_files)
                if isinstance(injected, list) and injected:
                    logger.info(f"FileTrigger: using {len(injected)} injected trigger files")
                    data_list = await self._download_from_metadata(injected)
                    self.status = data_list
                    return data_list
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"FileTrigger: failed to parse injected trigger files: {e}")

        # 2. Normal scan (Playground / builder)
        storage_type = self.storage_type
        if storage_type == "Azure Blob Storage":
            data_list = await self._scan_azure_blob()
        elif storage_type == "SharePoint":
            data_list = await self._scan_sharepoint()
        else:
            data_list = []

        # 3. Handle empty result
        if not data_list:
            no_files = Data(
                data={
                    "text": "No files found matching the configured filter criteria.",
                    "file_name": "",
                    "file_path": "",
                    "file_type": "",
                    "source": storage_type,
                    "size_bytes": 0,
                }
            )
            self.status = [no_files]
            return [no_files]

        self.status = data_list
        return data_list

    async def info_output(self) -> Message:
        """Return trigger metadata as a Message."""
        now = datetime.now(timezone.utc)
        storage_type = self.storage_type

        metadata: dict = {
            "trigger_type": "file_trigger",
            "storage_type": storage_type,
            "triggered_at": now.isoformat(),
            "trigger_on": self.trigger_on,
            "batch_size": self.batch_size,
            "connector": self.connector,
        }

        message = await Message.create(
            text=f"File trigger fired ({storage_type})",
            sender=MESSAGE_SENDER_USER,
            sender_name="FileTrigger",
            session_id=self.session_id if hasattr(self, "session_id") and self.session_id else "",
            properties={"trigger_metadata": metadata},
        )

        self.status = message
        return message
