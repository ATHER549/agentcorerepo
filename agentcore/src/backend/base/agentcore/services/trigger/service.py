from __future__ import annotations

import asyncio
import json
import os
import time
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


class TriggerService(Service):
    """Manages non-schedule triggers: folder monitors.

    Runs background asyncio tasks that poll external sources (local folders,
    Azure Blob, SharePoint) and invoke agent flows when new data is detected.
    """

    name = "trigger_service"

    def __init__(self) -> None:
        self._monitors: dict[str, asyncio.Task] = {}
        self._seen_files: dict[str, set[str]] = {}  # trigger_id -> set of seen file keys
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
                        return set(keys)
        except Exception as e:
            logger.warning(f"TriggerService: failed to load seen files for {trigger_config_id}: {e}")
        return set()

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

            # Keep only last 500 to prevent JSON bloat
            keys_list = list(seen)[-500:]

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

        seen = self._seen_files.get(task_id, set())
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
                seen.add(file_key)
            elif trigger_on in ("Modified Files", "Both") and file_key not in seen:
                new_files.append({
                    "name": entry.name,
                    "path": entry.path,
                    "size": entry.stat().st_size,
                    "modified": datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc).isoformat(),
                })
                seen.add(file_key)

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

        seen = self._seen_files.get(task_id, set())
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
                    seen.add(blob_key)

        self._seen_files[task_id] = seen
        return new_files

    async def _scan_sharepoint(
        self, task_id: str, config: dict, file_types: list[str], trigger_on: str,
    ) -> list[dict]:
        """Scan a SharePoint document library for new/modified files.

        Credentials are resolved from the connector_catalogue via `connector_id`
        stored in the trigger_config JSON.
        """
        try:
            from office365.runtime.auth.client_credential import ClientCredential
            from office365.sharepoint.client_context import ClientContext
        except ImportError:
            logger.error(
                "Office365-REST-Python-Client not installed. "
                "Install with: pip install Office365-REST-Python-Client"
            )
            return []

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
            library = connector_cfg.get("library", "Shared Documents")
            folder_path = connector_cfg.get("folder", config.get("sharepoint_folder", ""))
        else:
            # Fallback: legacy inline credentials (deprecated)
            site_url = config.get("sharepoint_site_url", "")
            client_id = config.get("sharepoint_client_id", "")
            client_secret = config.get("sharepoint_client_secret", "")
            library = config.get("sharepoint_library", "Shared Documents")
            folder_path = config.get("sharepoint_folder", "")

        if not site_url or not client_id or not client_secret:
            logger.warning(f"TriggerService: SharePoint trigger {task_id} missing site_url, client_id, or client_secret")
            return []

        seen = self._seen_files.get(task_id, set())
        new_files = []

        try:
            credentials = ClientCredential(client_id, client_secret)
            ctx = ClientContext(site_url).with_credentials(credentials)

            target_folder = ctx.web.get_folder_by_server_relative_url(
                f"{library}/{folder_path}" if folder_path else library
            )
            files = target_folder.files
            ctx.load(files)
            await asyncio.to_thread(ctx.execute_query)

            for sp_file in files:
                if file_types:
                    ext = Path(sp_file.name).suffix.lstrip(".")
                    if ext not in file_types:
                        continue

                modified = sp_file.time_last_modified if hasattr(sp_file, "time_last_modified") else ""
                file_key = f"{sp_file.name}:{modified}"

                if file_key not in seen:
                    new_files.append({
                        "name": sp_file.name,
                        "path": sp_file.serverRelativeUrl,
                        "size": sp_file.length if hasattr(sp_file, "length") else 0,
                        "modified": str(modified),
                    })
                    seen.add(file_key)

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

        input_request = SimplifiedAPIRequest(
            input_value=json.dumps(payload),
            input_type="chat",
            output_type="chat",
            tweaks=tweaks,
            session_id=None,
        )

        await simple_run_agent_task(
            agent=agent,
            input_request=input_request,
            api_key_user=None,
            prod_deployment=prod_deployment,
            uat_deployment=uat_deployment,
        )
