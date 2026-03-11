from __future__ import annotations

import asyncio
import json
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from loguru import logger

from agentcore.services.base import Service


# ---------------------------------------------------------------------------
# Connector catalogue helpers (async)
# ---------------------------------------------------------------------------

async def _get_storage_connector_config(connector_id: str) -> dict | None:
    """Fetch and decrypt provider_config for a storage connector from the DB."""
    from uuid import UUID as _UUID
    try:
        from agentcore.services.deps import get_db_service
        from agentcore.services.database.models.connector_catalogue.model import ConnectorCatalogue
        from agentcore.api.connector_catalogue import _decrypt_provider_config

        db_service = get_db_service()
        async with db_service.with_session() as session:
            row = await session.get(ConnectorCatalogue, _UUID(str(connector_id)))
            if row is None:
                logger.warning(f"TriggerService: connector {connector_id} not found")
                return None

            raw = row.provider_config or {}
            try:
                config = _decrypt_provider_config(row.provider, raw)
            except Exception as e:
                logger.error(f"TriggerService: failed to decrypt provider_config: {e}")
                config = raw

            return {"provider": row.provider, **config}
    except Exception as e:
        logger.error(f"TriggerService: failed to load connector config {connector_id}: {e}", exc_info=True)
        return None


def _odata_escape(value: str) -> str:
    """Escape single quotes for OData filter values."""
    return value.replace("'", "''")


class TriggerService(Service):
    """Manages non-schedule triggers: folder monitors and email monitors.

    Runs background asyncio tasks that poll external sources (local folders,
    Azure Blob, SharePoint, Outlook mailboxes) and invoke agent flows when
    new data is detected.
    """

    name = "trigger_service"

    def __init__(self) -> None:
        self._monitors: dict[str, asyncio.Task] = {}
        self._seen_files: dict[str, OrderedDict] = {}  # trigger_id -> OrderedDict of seen file keys
        self._started = False

    def start(self) -> None:
        """Start the trigger service."""
        self._started = True
        logger.info("TriggerService started")
        self.set_ready()

    async def teardown(self) -> None:
        """Cancel all monitor tasks and clean up.

        Persists seen-file sets to the DB before shutdown so they survive restart.
        """
        # Persist all seen files before shutting down
        for task_id in list(self._seen_files.keys()):
            try:
                await self._persist_seen_files(UUID(task_id))
            except Exception as e:
                logger.warning(f"Failed to persist seen files for {task_id} on teardown: {e}")

        for task_id, task in self._monitors.items():
            if not task.done():
                task.cancel()
                logger.debug(f"Cancelled monitor task {task_id}")
        self._monitors.clear()
        self._seen_files.clear()
        self._started = False
        logger.info("TriggerService shut down")

    async def load_active_monitors(self) -> None:
        """Load all active file trigger monitors from the database."""
        from agentcore.services.deps import get_db_service

        try:
            db_service = get_db_service()
            async with db_service.with_session() as session:
                from agentcore.services.database.models.trigger_config.crud import (
                    get_active_triggers_by_type,
                )
                from agentcore.services.database.models.trigger_config.model import TriggerTypeEnum

                # Load folder monitors
                folder_triggers = await get_active_triggers_by_type(session, TriggerTypeEnum.FOLDER_MONITOR)
                for trigger in folder_triggers:
                    await self.register_folder_monitor(trigger)

                logger.info(f"Loaded {len(folder_triggers)} active folder monitors")

                # Load email monitors
                email_triggers = await get_active_triggers_by_type(session, TriggerTypeEnum.EMAIL_MONITOR)
                for trigger in email_triggers:
                    await self.register_email_monitor(trigger)

                logger.info(f"Loaded {len(email_triggers)} active email monitors")
        except Exception as e:
            logger.warning(f"Failed to load active monitors (table may not exist yet): {e}")

    async def sync_folder_monitors_for_agent(
        self,
        session,
        agent_id,
        environment: str,
        version: str,
        deployment_id,
        flow_data: dict,
        created_by,
    ) -> None:
        """Called on publish. Scans the agent snapshot for FolderMonitor nodes and
        auto-creates trigger_config entries so admins can toggle them on/off from
        the Automations page. The connector/settings stay in the builder node —
        we just mirror them into the trigger table so the service can poll.
        """
        from agentcore.services.database.models.trigger_config.crud import (
            create_trigger_config,
            get_triggers_by_agent_id,
        )
        from agentcore.services.database.models.trigger_config.model import (
            TriggerConfigCreate,
            TriggerTypeEnum,
        )

        nodes = flow_data.get("nodes", [])
        node_types = [n.get("data", {}).get("type", "?") for n in nodes]
        logger.info(f"Agent {agent_id} snapshot has {len(nodes)} node(s), types: {node_types}")
        # Accept both old ("FolderMonitor") and new ("FileTrigger") node types
        _FILE_TRIGGER_TYPES = {"FolderMonitor", "FileTrigger"}
        fm_nodes = [n for n in nodes if n.get("data", {}).get("type") in _FILE_TRIGGER_TYPES]

        if not fm_nodes:
            logger.info(f"No FileTrigger nodes in agent {agent_id} snapshot — skipping sync")
            return

        logger.info(f"Syncing {len(fm_nodes)} FileTrigger node(s) for agent {agent_id}")

        # Find existing folder-monitor triggers for this agent+env
        existing = await get_triggers_by_agent_id(session, agent_id, active_only=False)
        existing_fm = [
            t for t in existing
            if t.trigger_type == TriggerTypeEnum.FOLDER_MONITOR and t.environment == environment
        ]

        # Build a lookup: (node_id, deployment_id) → existing trigger
        # We key by BOTH node_id AND deployment_id so that a new version of
        # the same agent creates a NEW trigger entry instead of overwriting.
        existing_by_key: dict[tuple[str, str], object] = {}
        existing_by_node_only: dict[str, object] = {}
        for t in existing_fm:
            nid = (t.trigger_config or {}).get("node_id")
            did = str(t.deployment_id) if t.deployment_id else None
            if nid and did:
                existing_by_key[(nid, did)] = t
            if nid:
                existing_by_node_only.setdefault(nid, [])
                existing_by_node_only[nid].append(t)

        dep_id_str = str(deployment_id)

        for node in fm_nodes:
            node_id = node.get("id")
            template = node.get("data", {}).get("node", {}).get("template", {})
            storage_type = template.get("storage_type", {}).get("value", "Azure Blob Storage")
            connector_raw = template.get("connector", {}).get("value", "") or ""
            file_types = template.get("file_types", {}).get("value", [])

            # Parse "name | provider | target | uuid" → extract uuid
            parts = connector_raw.split("|")
            connector_id = parts[-1].strip() if len(parts) >= 4 else connector_raw.strip()

            # Check if THIS exact deployment already has a trigger for this node
            exact_match = existing_by_key.get((node_id, dep_id_str))

            if exact_match:
                # ── SAME deployment re-synced: update in-place ──
                old_cfg = dict(exact_match.trigger_config or {})
                old_cfg["storage_type"] = storage_type
                old_cfg["connector_id"] = connector_id
                old_cfg["file_types"] = file_types
                old_cfg["node_id"] = node_id
                old_cfg.setdefault("poll_interval_seconds", 30)
                old_cfg.setdefault("trigger_on", "New Files")
                old_cfg.setdefault("batch_size", 10)
                exact_match.trigger_config = old_cfg
                exact_match.is_active = True
                session.add(exact_match)
                await session.commit()
                await session.refresh(exact_match)

                await self.unregister(exact_match.id)
                try:
                    await self.register_folder_monitor(exact_match)
                except Exception as e:
                    logger.warning(f"Failed to re-register folder monitor for node {node_id}: {e}")
                logger.info(f"Updated existing folder monitor {exact_match.id} for node {node_id} (same deployment)")
            else:
                # ── NEW deployment version → deactivate old triggers for this
                #    node and create a fresh entry ──
                old_triggers_for_node = existing_by_node_only.get(node_id, [])
                for old_t in old_triggers_for_node:
                    if old_t.is_active:
                        old_t.is_active = False
                        session.add(old_t)
                        await self.unregister(old_t.id)
                        logger.info(
                            f"Deactivated old folder monitor {old_t.id} "
                            f"(superseded by new deployment {deployment_id})"
                        )

                record = await create_trigger_config(
                    session,
                    TriggerConfigCreate(
                        agent_id=agent_id,
                        deployment_id=deployment_id,
                        trigger_type=TriggerTypeEnum.FOLDER_MONITOR,
                        trigger_config={
                            "storage_type": storage_type,
                            "connector_id": connector_id,
                            "poll_interval_seconds": 30,
                            "file_types": file_types,
                            "trigger_on": "New Files",
                            "batch_size": 10,
                            "node_id": node_id,
                        },
                        is_active=True,
                        environment=environment,
                        version=version,
                        created_by=created_by,
                    ),
                )
                try:
                    await self.register_folder_monitor(record)
                except Exception as e:
                    logger.warning(f"Failed to register folder monitor for node {node_id}: {e}")
                logger.info(f"Created new folder monitor {record.id} for node {node_id} (new deployment)")

        await session.commit()

    async def register_folder_monitor(self, trigger_record) -> None:
        """Register a folder monitor from a TriggerConfigTable record."""
        task_id = str(trigger_record.id)
        if task_id in self._monitors:
            await self.unregister(trigger_record.id)

        config = trigger_record.trigger_config or {}
        # Load previously seen files from DB so we don't re-process on restart
        self._seen_files[task_id] = await self._load_seen_files(trigger_record.id)

        task = asyncio.create_task(
            self._folder_monitor_loop(
                trigger_config_id=trigger_record.id,
                agent_id=trigger_record.agent_id,
                config=config,
                environment=trigger_record.environment,
                version=trigger_record.version,
            ),
            name=f"folder_monitor_{task_id}",
        )
        self._monitors[task_id] = task
        logger.info(f"Registered folder monitor {task_id} for agent {trigger_record.agent_id}")

    async def register_email_monitor(self, trigger_record) -> None:
        """Register an email monitor from a TriggerConfigTable record."""
        task_id = str(trigger_record.id)
        if task_id in self._monitors:
            await self.unregister(trigger_record.id)

        config = trigger_record.trigger_config or {}
        self._seen_files[task_id] = await self._load_seen_files(trigger_record.id)

        task = asyncio.create_task(
            self._email_monitor_loop(
                trigger_config_id=trigger_record.id,
                agent_id=trigger_record.agent_id,
                config=config,
                environment=trigger_record.environment,
                version=trigger_record.version,
            ),
            name=f"email_monitor_{task_id}",
        )
        self._monitors[task_id] = task
        logger.info(f"Registered email monitor {task_id} for agent {trigger_record.agent_id}")

    async def unregister(self, trigger_config_id: UUID) -> bool:
        """Unregister and cancel a monitor task."""
        task_id = str(trigger_config_id)
        # Persist seen files before unregistering so they survive restart
        await self._persist_seen_files(trigger_config_id)
        task = self._monitors.pop(task_id, None)
        self._seen_files.pop(task_id, None)
        if task and not task.done():
            task.cancel()
            logger.info(f"Unregistered monitor {task_id}")
            return True
        return False

    # ── Seen-files persistence ──────────────────────────────────────────────

    async def _load_seen_files(self, trigger_config_id: UUID) -> set[str]:
        """Load persisted seen-file keys from the trigger_config JSON.

        The keys are stored under ``_seen_keys`` inside the ``trigger_config``
        column so they survive server restarts.
        """
        try:
            from agentcore.services.deps import get_db_service
            from agentcore.services.database.models.trigger_config.crud import (
                get_trigger_config_by_id,
            )

            db_service = get_db_service()
            async with db_service.with_session() as session:
                record = await get_trigger_config_by_id(session, trigger_config_id)
                if record and record.trigger_config:
                    keys = record.trigger_config.get("_seen_keys", [])
                    if isinstance(keys, list):
                        return OrderedDict.fromkeys(keys)
        except Exception as e:
            logger.warning(f"TriggerService: failed to load seen files for {trigger_config_id}: {e}")
        return OrderedDict()

    async def _persist_seen_files(self, trigger_config_id: UUID) -> None:
        """Save the in-memory seen-file keys to the trigger_config JSON.

        Only the most recent 500 keys are kept to prevent unbounded growth.
        """
        task_id = str(trigger_config_id)
        seen = self._seen_files.get(task_id)
        if seen is None:
            return

        try:
            from agentcore.services.deps import get_db_service
            from agentcore.services.database.models.trigger_config.crud import (
                get_trigger_config_by_id,
            )

            # Keep only last 10,000 to prevent JSON bloat
            keys_list = list(seen)[-10_000:]

            db_service = get_db_service()
            async with db_service.with_session() as session:
                record = await get_trigger_config_by_id(session, trigger_config_id)
                if record:
                    config = dict(record.trigger_config or {})
                    config["_seen_keys"] = keys_list
                    record.trigger_config = config
                    record.updated_at = datetime.now(timezone.utc)
                    session.add(record)
                    await session.commit()
        except Exception as e:
            logger.warning(f"TriggerService: failed to persist seen files for {trigger_config_id}: {e}")

    # ── File Trigger Loop ──────────────────────────────────────────────────

    async def _folder_monitor_loop(
        self,
        trigger_config_id: UUID,
        agent_id: UUID,
        config: dict,
        environment: str,
        version: str | None,
    ) -> None:
        """Poll a folder for new/changed files and trigger the agent flow."""
        storage_type = config.get("storage_type", "Local")
        poll_interval = config.get("poll_interval_seconds", 30)
        batch_size = config.get("batch_size", 10)
        trigger_on = config.get("trigger_on", "New Files")
        file_types = config.get("file_types", [])
        task_id = str(trigger_config_id)

        logger.info(
            f"Folder monitor started: storage={storage_type}, "
            f"poll={poll_interval}s, batch={batch_size}"
        )

        while True:
            try:
                await asyncio.sleep(poll_interval)

                new_files = []
                if storage_type == "Local":
                    new_files = await self._scan_local_folder(task_id, config, file_types, trigger_on)
                elif storage_type == "Azure Blob Storage":
                    new_files = await self._scan_azure_blob(task_id, config, file_types, trigger_on)
                elif storage_type == "SharePoint":
                    new_files = await self._scan_sharepoint(task_id, config, file_types, trigger_on)

                if not new_files:
                    continue

                # Apply batch size limit
                if batch_size > 0:
                    new_files = new_files[:batch_size]

                logger.info(f"Folder monitor {task_id}: found {len(new_files)} new files")

                # Trigger the agent flow with file list
                await self._execute_trigger(
                    trigger_config_id=trigger_config_id,
                    agent_id=agent_id,
                    payload={"files": new_files, "storage_type": storage_type},
                    environment=environment,
                    version=version,
                    trigger_config=config,
                )

                # Move processed files if configured
                if config.get("move_processed", True) and storage_type == "Local":
                    await self._move_processed_files(config, new_files)

                # Persist seen files to DB so they survive server restart
                await self._persist_seen_files(trigger_config_id)

            except asyncio.CancelledError:
                logger.debug(f"Folder monitor {task_id} cancelled")
                # Persist before shutdown
                await self._persist_seen_files(trigger_config_id)
                break
            except Exception:
                logger.exception(f"Error in folder monitor {task_id}")
                await asyncio.sleep(poll_interval)

    async def _scan_local_folder(
        self, task_id: str, config: dict, file_types: list[str], trigger_on: str,
    ) -> list[dict]:
        """Scan a local folder for new/modified files."""
        folder_path = config.get("folder_path", ".")
        if not os.path.isdir(folder_path):
            logger.warning(f"Folder monitor {task_id}: path '{folder_path}' does not exist")
            return []

        seen = self._seen_files.get(task_id, OrderedDict())
        new_files = []

        for entry in os.scandir(folder_path):
            if not entry.is_file():
                continue

            # Filter by file type
            if file_types:
                ext = Path(entry.name).suffix.lstrip(".")
                if ext not in file_types:
                    continue

            file_key = f"{entry.name}:{entry.stat().st_mtime}"

            if trigger_on in ("New Files", "Both") and entry.name not in {
                k.split(":")[0] for k in seen
            }:
                new_files.append({
                    "name": entry.name,
                    "path": entry.path,
                    "size": entry.stat().st_size,
                    "modified": datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc).isoformat(),
                })
                seen[file_key] = None
            elif trigger_on in ("Modified Files", "Both") and file_key not in seen:
                new_files.append({
                    "name": entry.name,
                    "path": entry.path,
                    "size": entry.stat().st_size,
                    "modified": datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc).isoformat(),
                })
                seen[file_key] = None

        self._seen_files[task_id] = seen
        return new_files

    async def _scan_azure_blob(
        self, task_id: str, config: dict, file_types: list[str], trigger_on: str,
    ) -> list[dict]:
        """Scan an Azure Blob container for new/modified blobs.

        Credentials are resolved from the connector_catalogue via `connector_id`
        stored in the trigger_config JSON.
        """
        try:
            from azure.storage.blob.aio import BlobServiceClient
        except ImportError:
            logger.error("azure-storage-blob not installed. Install with: pip install azure-storage-blob")
            return []

        # Resolve credentials from connector catalogue
        connector_id = config.get("connector_id")
        if connector_id:
            connector_cfg = await _get_storage_connector_config(str(connector_id))
            if not connector_cfg:
                logger.error(f"TriggerService: could not load Azure connector {connector_id}")
                return []
            connection_string = connector_cfg.get("connection_string", "")
            container_name = connector_cfg.get("container_name", "")
            prefix = connector_cfg.get("blob_prefix", config.get("azure_prefix", ""))
        else:
            # Fallback: legacy inline credentials (deprecated)
            connection_string = config.get("azure_connection_string", "")
            container_name = config.get("azure_container", "")
            prefix = config.get("azure_prefix", "")

        if not connection_string or not container_name:
            logger.warning(f"TriggerService: Azure Blob trigger {task_id} missing connection_string or container_name")
            return []

        seen = self._seen_files.get(task_id, OrderedDict())
        new_files = []

        async with BlobServiceClient.from_connection_string(connection_string) as client:
            container = client.get_container_client(container_name)
            async for blob in container.list_blobs(name_starts_with=prefix or None):
                if file_types:
                    ext = Path(blob.name).suffix.lstrip(".")
                    if ext not in file_types:
                        continue

                blob_key = f"{blob.name}:{blob.last_modified.isoformat() if blob.last_modified else ''}"

                if blob_key not in seen:
                    new_files.append({
                        "name": blob.name,
                        "path": f"azure://{container_name}/{blob.name}",
                        "size": blob.size,
                        "modified": blob.last_modified.isoformat() if blob.last_modified else None,
                    })
                    seen[blob_key] = None

        self._seen_files[task_id] = seen
        return new_files

    async def _scan_sharepoint(
        self, task_id: str, config: dict, file_types: list[str], trigger_on: str,
    ) -> list[dict]:
        """Scan a SharePoint document library for new/modified files.

        Uses Microsoft Graph API (client-credentials) instead of Office365-REST-Python-Client
        so that only Graph API permissions are needed (Sites.Read.All / Sites.ReadWrite.All).

        Credentials are resolved from the connector_catalogue via `connector_id`
        stored in the trigger_config JSON.
        """
        import httpx
        from urllib.parse import urlparse

        GRAPH = "https://graph.microsoft.com/v1.0"

        # Resolve credentials from connector catalogue
        connector_id = config.get("connector_id")
        if connector_id:
            connector_cfg = await _get_storage_connector_config(str(connector_id))
            if not connector_cfg:
                logger.error(f"TriggerService: could not load SharePoint connector {connector_id}")
                return []
            site_url = connector_cfg.get("site_url", "")
            client_id = connector_cfg.get("client_id", "")
            client_secret = connector_cfg.get("client_secret", "")
            tenant_id = connector_cfg.get("tenant_id", "")
            library = connector_cfg.get("library", "Shared Documents")
            folder_path = connector_cfg.get("folder", config.get("sharepoint_folder", ""))
        else:
            # Fallback: legacy inline credentials (deprecated)
            site_url = config.get("sharepoint_site_url", "")
            client_id = config.get("sharepoint_client_id", "")
            client_secret = config.get("sharepoint_client_secret", "")
            tenant_id = config.get("sharepoint_tenant_id", "")
            library = config.get("sharepoint_library", "Shared Documents")
            folder_path = config.get("sharepoint_folder", "")

        if not site_url or not client_id or not client_secret:
            logger.warning(f"TriggerService: SharePoint trigger {task_id} missing site_url, client_id, or client_secret")
            return []

        if not tenant_id:
            logger.warning(f"TriggerService: SharePoint trigger {task_id} missing tenant_id for Graph API")
            return []

        seen = self._seen_files.get(task_id, OrderedDict())
        new_files = []

        try:
            # 1. Acquire token
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            token_resp = await asyncio.to_thread(
                lambda: httpx.post(token_url, data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                }, timeout=15)
            )
            if token_resp.status_code != 200:
                logger.error(f"TriggerService: Graph token error for trigger {task_id}: {token_resp.text[:300]}")
                return []
            access_token = token_resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {access_token}"}

            # 2. Resolve site ID
            parsed = urlparse(site_url)
            hostname = parsed.hostname or parsed.netloc
            path = parsed.path.rstrip("/")
            site_api = f"{GRAPH}/sites/{hostname}:{path}" if path else f"{GRAPH}/sites/{hostname}"
            site_resp = await asyncio.to_thread(
                lambda: httpx.get(site_api, headers=headers, timeout=15)
            )
            if site_resp.status_code != 200:
                logger.error(f"TriggerService: failed to resolve site for trigger {task_id}: {site_resp.text[:300]}")
                return []
            site_id = site_resp.json()["id"]

            # 3. Resolve drive ID
            drives_resp = await asyncio.to_thread(
                lambda: httpx.get(f"{GRAPH}/sites/{site_id}/drives", headers=headers, timeout=15)
            )
            if drives_resp.status_code != 200:
                logger.error(f"TriggerService: failed to list drives for trigger {task_id}")
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
                logger.error(f"TriggerService: no drives found for trigger {task_id}")
                return []

            # 4. List files
            if folder_path:
                items_url = f"{GRAPH}/drives/{drive_id}/root:/{folder_path}:/children?$top=200"
            else:
                items_url = f"{GRAPH}/drives/{drive_id}/root/children?$top=200"
            items_resp = await asyncio.to_thread(
                lambda: httpx.get(items_url, headers=headers, timeout=15)
            )
            if items_resp.status_code != 200:
                logger.error(f"TriggerService: failed to list items for trigger {task_id}: {items_resp.text[:300]}")
                return []
            items = items_resp.json().get("value", [])

            # Filter to files only
            for item in items:
                if "file" not in item:
                    continue
                file_name = item.get("name", "")
                if file_types:
                    ext = Path(file_name).suffix.lstrip(".")
                    if ext not in file_types:
                        continue

                modified = item.get("lastModifiedDateTime", "")
                file_key = f"{file_name}:{modified}"

                if file_key not in seen:
                    new_files.append({
                        "name": file_name,
                        "path": item.get("webUrl", ""),
                        "item_id": item.get("id", ""),
                        "size": item.get("size", 0),
                        "modified": str(modified),
                    })
                    seen[file_key] = None

        except Exception:
            logger.exception(f"Error scanning SharePoint for trigger {task_id}")

        self._seen_files[task_id] = seen
        return new_files

    async def _move_processed_files(self, config: dict, files: list[dict]) -> None:
        """Move processed local files to a 'processed' subfolder."""
        folder_path = config.get("folder_path", ".")
        processed_dir = os.path.join(folder_path, "processed")
        os.makedirs(processed_dir, exist_ok=True)

        for file_info in files:
            src = file_info.get("path", "")
            if src and os.path.isfile(src):
                dst = os.path.join(processed_dir, os.path.basename(src))
                try:
                    await asyncio.to_thread(os.rename, src, dst)
                except OSError:
                    logger.warning(f"Could not move {src} to {dst}")

    # ── Email Monitor Loop ─────────────────────────────────────────────────

    async def _email_monitor_loop(
        self,
        trigger_config_id: UUID,
        agent_id: UUID,
        config: dict,
        environment: str,
        version: str | None,
    ) -> None:
        """Poll an Outlook mailbox for new emails and trigger the agent flow.

        Supports fetching full email body and parsing attachments (pdf, docx,
        xlsx, pptx, csv, txt) when the corresponding config flags are enabled.
        """
        connector_id = config.get("connector_id", "")
        poll_interval = config.get("poll_interval_seconds", 60)
        account_email = config.get("account_email", "")
        mail_folder = config.get("mail_folder", "inbox")
        filter_sender = config.get("filter_sender", "")
        filter_subject = config.get("filter_subject", "")
        filter_body = config.get("filter_body", "")
        filter_importance = config.get("filter_importance", "")
        filter_has_attachments = config.get("filter_has_attachments", False)
        unread_only = config.get("unread_only", True)
        mark_as_read = config.get("mark_as_read", False)
        max_results = config.get("max_results", 10)
        fetch_full_body = config.get("fetch_full_body", True)
        fetch_attachments = config.get("fetch_attachments", True)
        task_id = str(trigger_config_id)

        logger.info(
            f"Email monitor started: connector={connector_id}, "
            f"account={account_email or '(first)'}, folder={mail_folder}, "
            f"poll={poll_interval}s, max_results={max_results}, "
            f"unread_only={unread_only}, mark_as_read={mark_as_read}, "
            f"full_body={fetch_full_body}, attachments={fetch_attachments}"
        )

        first_run = True
        while True:
            try:
                # Sleep at top EXCEPT on first run — scan immediately when started
                if first_run:
                    first_run = False
                else:
                    await asyncio.sleep(poll_interval)

                # 1. Load connector config (encrypted) from DB
                connector_cfg = await _get_storage_connector_config(str(connector_id))
                if not connector_cfg:
                    logger.warning(f"Email monitor {task_id}: connector {connector_id} not found")
                    continue

                # 2. Get linked account + refresh token
                accounts = connector_cfg.get("linked_accounts", [])
                if not accounts:
                    logger.warning(f"Email monitor {task_id}: no linked mailbox")
                    continue

                # Select account by email if configured, otherwise first
                acct = None
                if account_email:
                    for a in accounts:
                        if a.get("email", "").lower() == account_email.lower():
                            acct = a
                            break
                    if not acct:
                        logger.warning(
                            f"Email monitor {task_id}: configured account '{account_email}' "
                            f"not found, falling back to first account"
                        )
                if not acct:
                    acct = accounts[0]

                access_token = await self._refresh_outlook_token(connector_cfg, acct, connector_id)

                # 3. Build Graph API request with OData filters
                safe_folder = mail_folder.replace("/", "").replace("\\", "").replace("..", "") or "inbox"
                url = f"https://graph.microsoft.com/v1.0/me/mailFolders/{safe_folder}/messages"
                # Include body in $select when full body is requested
                select_fields = "id,subject,from,receivedDateTime,bodyPreview,hasAttachments,toRecipients,importance,isRead"
                if fetch_full_body:
                    select_fields += ",body"
                params: dict[str, str] = {
                    "$top": str(max_results),
                    "$select": select_fields,
                    "$orderby": "receivedDateTime desc",
                }
                filters = []
                if unread_only:
                    filters.append("isRead eq false")
                if filter_sender:
                    filters.append(f"from/emailAddress/address eq '{_odata_escape(filter_sender)}'")
                if filter_subject:
                    filters.append(f"contains(subject, '{_odata_escape(filter_subject)}')")
                if filter_body:
                    filters.append(f"contains(body/content, '{_odata_escape(filter_body)}')")
                if filter_importance and filter_importance != "all":
                    filters.append(f"importance eq '{_odata_escape(filter_importance)}'")
                if filter_has_attachments:
                    filters.append("hasAttachments eq true")
                if filters:
                    params["$filter"] = " and ".join(filters)

                # 4. Call Graph API
                import httpx

                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        url,
                        headers={"Authorization": f"Bearer {access_token}"},
                        params=params,
                        timeout=15,
                    )

                if resp.status_code == 401:
                    logger.warning(f"Email monitor {task_id}: Graph API 401 — force-refreshing token")
                    access_token = await self._refresh_outlook_token(connector_cfg, acct, connector_id, force=True)
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(
                            url,
                            headers={"Authorization": f"Bearer {access_token}"},
                            params=params,
                            timeout=15,
                        )
                    if resp.status_code != 200:
                        logger.error(f"Email monitor {task_id}: Graph API {resp.status_code} after token refresh")
                        continue

                # OData $filter may fail on consumer Outlook.com accounts (400/501)
                # Fall back to client-side filtering
                client_side_filter = False
                if resp.status_code in (400, 501) and "$filter" in params:
                    logger.warning(f"Email monitor {task_id}: OData $filter failed ({resp.status_code}), using client-side filter")
                    fallback_params = {k: v for k, v in params.items() if k != "$filter"}
                    fallback_params["$top"] = "50"
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(
                            url,
                            headers={"Authorization": f"Bearer {access_token}"},
                            params=fallback_params,
                            timeout=15,
                        )
                    client_side_filter = True

                if resp.status_code != 200:
                    logger.warning(f"Email monitor {task_id}: Graph API {resp.status_code}")
                    continue

                messages = resp.json().get("value", [])

                # Apply client-side filters if OData $filter was not supported
                if client_side_filter and messages:
                    filtered = []
                    for m in messages:
                        m_sender = m.get("from", {}).get("emailAddress", {}).get("address", "").lower()
                        m_subject = (m.get("subject") or "").lower()
                        m_body = (m.get("bodyPreview") or "").lower()
                        if filter_sender and filter_sender.lower() != m_sender:
                            continue
                        if filter_subject and filter_subject.lower() not in m_subject:
                            continue
                        if filter_body and filter_body.lower() not in m_body:
                            continue
                        filtered.append(m)
                    messages = filtered

                # 5. Filter to unseen messages only
                seen = self._seen_files.get(task_id, OrderedDict())
                new_messages = []
                for msg in messages:
                    msg_id = msg.get("id", "")
                    if msg_id and msg_id not in seen:
                        new_messages.append(msg)
                        seen[msg_id] = None  # OrderedDict append (preserves insertion order)
                # Cap seen set to prevent unbounded memory growth
                _MAX_SEEN = 10_000
                if len(seen) > _MAX_SEEN:
                    excess = len(seen) - _MAX_SEEN
                    for _ in range(excess):
                        seen.popitem(last=False)  # evicts OLDEST, not random
                self._seen_files[task_id] = seen

                if not new_messages:
                    continue

                logger.info(f"Email monitor {task_id}: found {len(new_messages)} new email(s)")

                # 6. Build enhanced payload with full body + attachments
                email_payload = []
                for msg in new_messages:
                    from_addr = msg.get("from", {}).get("emailAddress", {})
                    entry: dict = {
                        "id": msg.get("id"),
                        "subject": msg.get("subject", ""),
                        "from_name": from_addr.get("name", ""),
                        "from_email": from_addr.get("address", ""),
                        "received": msg.get("receivedDateTime", ""),
                        "preview": msg.get("bodyPreview", ""),
                        "has_attachments": msg.get("hasAttachments", False),
                        "importance": msg.get("importance", "normal"),
                        "is_read": msg.get("isRead", False),
                    }

                    # Include full email body when enabled
                    if fetch_full_body:
                        body_obj = msg.get("body", {})
                        entry["body"] = body_obj.get("content", "")
                        entry["body_type"] = body_obj.get("contentType", "text")

                    # Fetch and parse attachments when enabled
                    if fetch_attachments and msg.get("hasAttachments"):
                        entry["attachments"] = await self._fetch_and_parse_attachments(
                            msg["id"], access_token, task_id,
                        )
                    elif fetch_attachments:
                        entry["attachments"] = []

                    email_payload.append(entry)

                await self._execute_trigger(
                    trigger_config_id=trigger_config_id,
                    agent_id=agent_id,
                    payload={"emails": email_payload, "trigger_type": "email_monitor"},
                    environment=environment,
                    version=version,
                    trigger_config=config,
                )

                # 7. Mark processed emails as read if configured
                if mark_as_read:
                    await self._mark_emails_as_read(
                        [m.get("id") for m in new_messages if m.get("id")],
                        access_token,
                        task_id,
                    )

                await self._persist_seen_files(trigger_config_id)

            except asyncio.CancelledError:
                logger.debug(f"Email monitor {task_id} cancelled")
                await self._persist_seen_files(trigger_config_id)
                break
            except Exception:
                logger.exception(f"Error in email monitor {task_id}")
                await asyncio.sleep(poll_interval)

    async def _mark_emails_as_read(
        self,
        message_ids: list[str],
        access_token: str,
        task_id: str,
    ) -> None:
        """Mark processed emails as read via Graph API PATCH.

        Best-effort — logs on failure but does not raise.
        """
        import httpx
        from urllib.parse import quote

        for msg_id in message_ids:
            try:
                safe_id = quote(msg_id, safe="")
                url = f"https://graph.microsoft.com/v1.0/me/messages/{safe_id}"
                async with httpx.AsyncClient() as client:
                    resp = await client.patch(
                        url,
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json",
                        },
                        json={"isRead": True},
                        timeout=10,
                    )
                if resp.status_code not in (200, 204):
                    logger.warning(
                        f"Email monitor {task_id}: failed to mark {msg_id[:20]}... "
                        f"as read ({resp.status_code})"
                    )
            except Exception as e:
                logger.warning(
                    f"Email monitor {task_id}: error marking {msg_id[:20]}... as read: {e}"
                )

    async def _fetch_and_parse_attachments(
        self,
        message_id: str,
        access_token: str,
        task_id: str,
    ) -> list[dict]:
        """Fetch attachments for a message from Graph API and parse to text.

        Uses the existing ``attachment_parser.py`` which supports pdf, docx,
        xlsx, pptx, csv, and txt formats with a 10 MB / 20 attachment cap.
        """
        import httpx
        from urllib.parse import quote

        safe_id = quote(message_id, safe="")
        url = f"https://graph.microsoft.com/v1.0/me/messages/{safe_id}/attachments"
        try:
            # No $select — contentBytes only exists on fileAttachment subtype
            # and consumer Outlook.com rejects it on the base attachment type
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=30,
                )
            if resp.status_code != 200:
                logger.warning(
                    f"Email monitor {task_id}: failed to fetch attachments "
                    f"for message {message_id[:20]}... (HTTP {resp.status_code})"
                )
                return []

            attachments_data = resp.json().get("value", [])
            if not attachments_data:
                return []

            from agentcore.services.outlook.attachment_parser import parse_attachments

            parsed = parse_attachments(attachments_data)
            logger.info(
                f"Email monitor {task_id}: parsed {len(parsed)} attachment(s) "
                f"for message {message_id[:20]}..."
            )
            return parsed

        except Exception as e:
            logger.warning(
                f"Email monitor {task_id}: error fetching/parsing attachments "
                f"for message {message_id[:20]}...: {e}"
            )
            return []

    async def _refresh_outlook_token(self, config: dict, acct: dict, connector_id: str, force: bool = False) -> str:
        """Refresh an Outlook OAuth token if expired, returning a valid access token."""
        access_token = acct.get("access_token", "")
        expires_at = acct.get("token_expires_at", 0)

        if not force and access_token and time.time() < (expires_at - 60):
            return access_token

        logger.info(f"Outlook token refresh: force={force}, expired={time.time() >= (expires_at - 60)}")

        refresh_token = acct.get("refresh_token", "")
        if not refresh_token:
            raise ValueError("Token expired, no refresh token. Re-link mailbox.")

        import httpx

        token_url = f"https://login.microsoftonline.com/{config.get('tenant_id')}/oauth2/v2.0/token"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_url,
                data={
                    "client_id": config.get("client_id"),
                    "client_secret": config.get("client_secret"),
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": "Mail.Read Mail.ReadWrite Mail.Send User.Read offline_access",
                },
                timeout=15,
            )

        if resp.status_code != 200:
            raise ValueError(f"Token refresh failed ({resp.status_code})")

        data = resp.json()
        acct["access_token"] = data["access_token"]
        acct["refresh_token"] = data.get("refresh_token", refresh_token)
        acct["token_expires_at"] = time.time() + data.get("expires_in", 3600)

        # Persist refreshed tokens back to DB
        await self._persist_outlook_tokens(config, connector_id)
        return data["access_token"]

    async def _persist_outlook_tokens(self, config: dict, connector_id: str) -> None:
        """Persist refreshed Outlook tokens to the connector_catalogue row."""
        try:
            from agentcore.services.deps import get_db_service
            from agentcore.services.database.models.connector_catalogue.model import ConnectorCatalogue
            from agentcore.api.connector_catalogue import _encrypt_provider_config

            persist_config = {k: v for k, v in config.items() if k != "provider"}
            db_service = get_db_service()
            async with db_service.with_session() as session:
                row = await session.get(ConnectorCatalogue, UUID(str(connector_id)))
                if row:
                    row.provider_config = _encrypt_provider_config(row.provider, persist_config)
                    session.add(row)
                    await session.commit()
        except Exception as e:
            logger.warning(f"Failed to persist refreshed Outlook tokens: {e}")

    # ── Common Execution ───────────────────────────────────────────────────

    async def _execute_trigger(
        self,
        trigger_config_id: UUID,
        agent_id: UUID,
        payload: dict,
        environment: str,
        version: str | None,
        trigger_config: dict | None = None,
    ) -> None:
        """Execute the agent flow with the trigger payload."""
        from agentcore.services.deps import get_db_service

        start_time = time.perf_counter()

        try:
            db_service = get_db_service()
            async with db_service.with_session() as session:
                from agentcore.services.database.models.trigger_config.crud import (
                    log_trigger_execution,
                    update_trigger_last_run,
                )
                from agentcore.services.database.models.trigger_config.model import (
                    TriggerExecutionStatusEnum,
                )

                await log_trigger_execution(
                    session,
                    trigger_config_id=trigger_config_id,
                    agent_id=agent_id,
                    status=TriggerExecutionStatusEnum.STARTED,
                    payload=payload,
                )
                await update_trigger_last_run(session, trigger_config_id)

            # Run the agent flow
            await self._run_agent_flow(
                agent_id, environment, version, trigger_config_id, payload,
                trigger_config=trigger_config,
            )

            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            async with db_service.with_session() as session:
                await log_trigger_execution(
                    session,
                    trigger_config_id=trigger_config_id,
                    agent_id=agent_id,
                    status=TriggerExecutionStatusEnum.SUCCESS,
                    execution_duration_ms=elapsed_ms,
                )

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            logger.exception(f"Trigger execution failed: {exc}")

            try:
                async with db_service.with_session() as session:
                    from agentcore.services.database.models.trigger_config.crud import log_trigger_execution
                    from agentcore.services.database.models.trigger_config.model import TriggerExecutionStatusEnum

                    await log_trigger_execution(
                        session,
                        trigger_config_id=trigger_config_id,
                        agent_id=agent_id,
                        status=TriggerExecutionStatusEnum.ERROR,
                        error_message=str(exc),
                        execution_duration_ms=elapsed_ms,
                    )
            except Exception:
                logger.exception("Failed to log trigger execution error")

    async def _run_agent_flow(
        self,
        agent_id: UUID,
        environment: str,
        version: str | None,
        trigger_config_id: UUID,
        payload: dict,
        trigger_config: dict | None = None,
    ) -> None:
        """Invoke the agent flow using the existing execution pipeline."""
        import json

        from agentcore.services.deps import get_db_service

        db_service = get_db_service()
        async with db_service.with_session() as session:
            from sqlmodel import select

            from agentcore.services.database.models.agent.model import Agent

            stmt = select(Agent).where(Agent.id == agent_id)
            result = await session.exec(stmt)
            agent = result.first()

            if not agent:
                msg = f"Agent {agent_id} not found"
                raise ValueError(msg)

        from agentcore.api.endpoints import _resolve_agent_data_for_env, simple_run_agent_task
        from agentcore.api.schemas import SimplifiedAPIRequest

        agent.data, prod_deployment, uat_deployment = await _resolve_agent_data_for_env(
            agent_id=agent.id,
            env=environment,
            version=version,  # None → latest active published deployment
        )

        # Build tweaks to inject file metadata into the FolderMonitor node
        # so it skips the storage scan and uses pre-detected files instead.
        tweaks = {}
        if trigger_config and payload.get("files"):
            node_id = trigger_config.get("node_id")
            if node_id:
                tweaks[node_id] = {
                    "_trigger_files": json.dumps(payload["files"]),
                }

        from uuid import uuid4

        input_request = SimplifiedAPIRequest(
            input_value=json.dumps(payload),
            input_type="chat",
            output_type="chat",
            tweaks=tweaks,
            session_id=str(uuid4()),
        )

        await simple_run_agent_task(
            agent=agent,
            input_request=input_request,
            api_key_user=None,
            prod_deployment=prod_deployment,
            uat_deployment=uat_deployment,
        )
