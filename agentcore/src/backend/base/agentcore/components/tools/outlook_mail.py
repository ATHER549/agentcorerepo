"""Outlook Mail component for the Agent Builder.

Reads connector credentials from the Connectors Catalogue (configured via the
Connectors page) and exposes *read_mail* and *send_reply* as tools that an
agent can invoke at runtime.

Pattern mirrors DatabaseConnectorComponent — dropdown populated from the
catalogue, no manual credential fields.
"""

import asyncio
import concurrent.futures
import threading
import time

from agentcore.custom.custom_node.node import Node
from agentcore.inputs.inputs import (
    DropdownInput,
    IntInput,
    MessageTextInput,
    MultilineInput,
)
from agentcore.schema.message import Message
from agentcore.template.field.base import Output
from agentcore.logging import logger


# ---------------------------------------------------------------------------
# Shared sync engine (same approach as database_connector.py)
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
        logger.info(f"Created sync engine for OutlookMail: {db_url.split('@')[-1]}")
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
_EMAIL_PROVIDERS = {"outlook"}

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
MAIL_SCOPES = "Mail.Read Mail.ReadWrite Mail.Send User.Read offline_access"


def _fetch_outlook_connectors() -> list[str]:
    """Fetch Outlook connectors from the catalogue.

    Returns list of strings: 'name | provider | email | uuid'
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
                    .where(ConnectorCatalogue.provider.in_(_EMAIL_PROVIDERS))
                    .where(ConnectorCatalogue.status == "connected")
                    .order_by(ConnectorCatalogue.name)
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()

                items = []
                for r in rows:
                    # Decrypt to get linked account emails
                    from agentcore.api.connector_catalogue import (
                        _decrypt_provider_config,
                    )

                    config = _decrypt_provider_config(r.provider, r.provider_config or {})
                    accounts = config.get("linked_accounts", [])
                    emails = ", ".join(a.get("email", "") for a in accounts) or "no mailbox linked"
                    items.append(f"{r.name} | {r.provider} | {emails} | {r.id}")
                return items

        return _run_async(_query())
    except Exception as e:
        logger.warning(f"Could not fetch Outlook connectors from catalogue: {e}")
        return []


def _get_outlook_config(connector_id: str) -> dict | None:
    """Fetch and decrypt Outlook connector config by ID."""
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
                logger.warning(f"Outlook connector {connector_id} not found")
                return None

            from agentcore.api.connector_catalogue import _decrypt_provider_config

            return _decrypt_provider_config(row.provider, row.provider_config or {})
    except Exception as e:
        logger.error(f"Failed to fetch Outlook connector config: {e}", exc_info=True)
        return None


def _refresh_token_sync(config: dict, acct: dict, force: bool = False) -> str:
    """Refresh an expired access token synchronously. Mutates *acct* in-place.

    Returns the (possibly refreshed) access_token.
    When *force* is True, skip the expiry check and always refresh (used on 401 retry).
    """
    access_token = acct.get("access_token", "")
    expires_at = acct.get("token_expires_at", 0)

    # Still valid (60 s buffer) — unless force-refresh requested
    if not force and access_token and time.time() < (expires_at - 60):
        return access_token

    refresh_token = acct.get("refresh_token", "")
    if not refresh_token:
        raise ValueError("Token expired and no refresh token available. Re-link the mailbox on the Connectors page (click the Mail icon).")

    tenant_id = config.get("tenant_id", "")
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")

    if not all([tenant_id, client_id, client_secret]):
        raise ValueError("Missing tenant_id/client_id/client_secret for token refresh.")

    import httpx

    logger.info(f"Refreshing Outlook token (force={force}, email={acct.get('email', 'unknown')})")
    token_url = TOKEN_URL.format(tenant_id=tenant_id)
    resp = httpx.post(
        token_url,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": MAIL_SCOPES,
        },
        timeout=15,
    )

    if resp.status_code != 200:
        error_detail = resp.text[:300] if resp.text else "No details"
        logger.error(f"Token refresh failed ({resp.status_code}): {error_detail}")
        raise ValueError(f"Token refresh failed ({resp.status_code}): {error_detail}. Re-link the mailbox on the Connectors page.")

    data = resp.json()
    acct["access_token"] = data["access_token"]
    acct["refresh_token"] = data.get("refresh_token", refresh_token)
    acct["token_expires_at"] = time.time() + data.get("expires_in", 3600)

    logger.info(f"Token refreshed successfully (expires_in={data.get('expires_in', 3600)}s)")

    # Persist refreshed tokens back to DB
    _persist_updated_config(config)

    return data["access_token"]


def _persist_updated_config(config: dict) -> None:
    """Persist updated config (e.g. refreshed tokens) back to the DB.

    Best-effort — logs on failure but does not raise.
    """
    connector_id = config.get("_connector_id")
    if not connector_id:
        return

    try:
        from uuid import UUID
        from datetime import datetime, timezone

        from sqlalchemy.orm import Session
        from agentcore.api.connector_catalogue import _encrypt_provider_config
        from agentcore.services.database.models.connector_catalogue.model import (
            ConnectorCatalogue,
        )

        # Strip internal metadata before persisting
        persist_config = {k: v for k, v in config.items() if not k.startswith("_")}

        engine = _get_sync_engine()
        with Session(engine) as session:
            row = session.get(ConnectorCatalogue, UUID(connector_id))
            if row:
                row.provider_config = _encrypt_provider_config(row.provider, persist_config)
                row.updated_at = datetime.now(timezone.utc)
                session.commit()
                logger.info(f"Persisted refreshed tokens for connector {connector_id}")
    except Exception as e:
        logger.warning(f"Failed to persist refreshed tokens: {e}")


def _odata_escape(value: str) -> str:
    """Escape single quotes for OData $filter values."""
    return value.replace("'", "''")


def _validate_path_segment(value: str, label: str) -> str:
    """Ensure a value is safe to embed in a URL path segment.

    Graph API message IDs are long base64 strings that may contain '/', '+',
    '=' etc.  We only validate folder names strictly; message IDs are
    URL-encoded instead.
    """
    if not value:
        raise ValueError(f"{label} is required")
    if label != "message_id":
        # Strict check for folder names only
        if "/" in value or "\\" in value or ".." in value:
            raise ValueError(f"Invalid {label}: must not contain '/', '\\', or '..'")
    else:
        # message_id: only reject path traversal
        if "\\" in value or ".." in value:
            raise ValueError(f"Invalid {label}: must not contain '\\' or '..'")
    return value


# ---------------------------------------------------------------------------
# In-memory message ID mapping
# ---------------------------------------------------------------------------
# Uses a mutable dict container so we never need `global` keyword
# (avoids NameError when module is loaded from installed package cache).
# Protected by _msg_id_lock for thread-safety (multiple agent invocations).
_msg_id_state = {"counter": 0, "map": {}}
_msg_id_lock = threading.Lock()


def _register_message_id(graph_id: str) -> str:
    """Store a Graph message ID and return a short human-friendly ref like 'MSG-1'."""
    with _msg_id_lock:
        _msg_id_state["counter"] += 1
        ref = f"MSG-{_msg_id_state['counter']}"
        _msg_id_state["map"][ref] = graph_id
    return ref


def _resolve_message_id(ref: str) -> str:
    """Resolve a short ref (MSG-1) back to the real Graph message ID.

    Also accepts raw Graph IDs as fallback for backward compatibility.
    """
    with _msg_id_lock:
        id_map = _msg_id_state["map"]
        upper = ref.strip().upper()
        if upper in id_map:
            return id_map[upper]
        # Try case-insensitive lookup
        for key, val in id_map.items():
            if key.upper() == upper:
                return val
    # Fallback: caller passed a raw Graph ID directly
    return ref


def _fetch_attachments_sync(message_id: str, access_token: str) -> list[dict]:
    """Fetch and parse attachments for a single message (synchronous)."""
    import httpx
    from urllib.parse import quote
    from agentcore.services.outlook.attachment_parser import parse_attachments

    safe_id = quote(message_id, safe="")
    url = f"{GRAPH_BASE}/me/messages/{safe_id}/attachments"
    try:
        # No $select — contentBytes only exists on fileAttachment subtype
        # and consumer Outlook.com rejects it on the base attachment type
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning(f"Failed to fetch attachments for {message_id[:30]}... (HTTP {resp.status_code})")
            return []
        att_data = resp.json().get("value", [])
        if not att_data:
            return []
        parsed = parse_attachments(att_data)
        logger.info(f"Parsed {len(parsed)} attachment(s) for message {message_id[:30]}...")
        return parsed
    except Exception as e:
        logger.warning(f"Error fetching attachments: {e}")
        return []


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------

class OutlookMailComponent(Node):
    """Read emails and send replies via a linked Outlook mailbox.

    Select an Outlook connector from the dropdown (configured on the Connectors
    page with OAuth-linked mailboxes). The agent can then read inbox messages,
    reply, reply-all, and send new emails at runtime.
    """

    display_name = "Outlook Mail"
    description = (
        "Read, reply, reply-all, and send emails through a linked Outlook mailbox. "
        "Connect to the Connectors Catalogue to use OAuth-linked accounts."
    )
    icon = "mail"
    name = "OutlookMail"

    inputs = [
        DropdownInput(
            name="connector",
            display_name="Outlook Connector",
            info="Select an Outlook connector from the Connectors Catalogue.",
            options=[],
            value="",
            refresh_button=True,
            real_time_refresh=True,
            combobox=True,
        ),
        MessageTextInput(
            name="account_email",
            display_name="Account Email",
            info="Email address of the linked mailbox to use. Leave empty to use the first linked account.",
            value="",
            tool_mode=True,
        ),
        IntInput(
            name="max_results",
            display_name="Max Results",
            info="Maximum number of emails to return when reading.",
            value=10,
            tool_mode=True,
        ),
        MessageTextInput(
            name="folder",
            display_name="Mail Folder",
            info="Mail folder to read from (e.g. inbox, sentitems, drafts).",
            value="inbox",
            tool_mode=True,
        ),
        MessageTextInput(
            name="filter_sender",
            display_name="Filter by Sender",
            info="Only return emails from this sender address.",
            value="",
            tool_mode=True,
            advanced=True,
        ),
        MessageTextInput(
            name="filter_subject",
            display_name="Filter by Subject",
            info="Only return emails whose subject contains this text.",
            value="",
            tool_mode=True,
            advanced=True,
        ),
        MessageTextInput(
            name="message_id",
            display_name="Message ID",
            info="ID of the email to reply to (from read_mail results).",
            value="",
            tool_mode=True,
        ),
        MultilineInput(
            name="reply_body",
            display_name="Reply Body",
            info="Text content of the reply.",
            value="",
            tool_mode=True,
        ),
        MessageTextInput(
            name="to_recipients",
            display_name="To Recipients",
            info="Comma-separated email addresses to send a new email to.",
            value="",
            tool_mode=True,
        ),
        MessageTextInput(
            name="cc_recipients",
            display_name="CC Recipients",
            info="Comma-separated CC email addresses (used with send_mail).",
            value="",
            tool_mode=True,
            advanced=True,
        ),
        MessageTextInput(
            name="email_subject",
            display_name="Email Subject",
            info="Subject line for a new email (used with send_mail).",
            value="",
            tool_mode=True,
        ),
        MultilineInput(
            name="email_body",
            display_name="Email Body",
            info="Body content for a new email (used with send_mail).",
            value="",
            tool_mode=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Read Mail",
            name="read_mail",
            method="read_mail",
            types=["Message"],
        ),
        Output(
            display_name="Send Reply",
            name="send_reply",
            method="send_reply",
            types=["Message"],
        ),
        Output(
            display_name="Reply All",
            name="reply_all",
            method="reply_all",
            types=["Message"],
        ),
        Output(
            display_name="Send Mail",
            name="send_mail",
            method="send_mail",
            types=["Message"],
        ),
    ]

    def update_build_config(self, build_config: dict, field_value: str, field_name: str | None = None):
        """Refresh the connector dropdown from the Connectors Catalogue."""
        if field_name == "connector":
            try:
                options = _fetch_outlook_connectors()
                build_config["connector"]["options"] = options if options else []
                current = build_config["connector"].get("value", "")
                if current not in options:
                    build_config["connector"]["value"] = options[0] if options else ""
            except Exception as e:
                logger.warning(f"Error fetching Outlook connectors: {e}")
                build_config["connector"]["options"] = []
        return build_config

    def _get_selected_config(self) -> dict:
        """Parse the selected connector dropdown and fetch config from DB."""
        selected = self.connector
        if not selected:
            raise ValueError("No Outlook connector selected. Please select one from the dropdown.")

        # Parse: "name | provider | emails | uuid"
        parts = [p.strip() for p in selected.split("|")]
        if len(parts) < 4:
            raise ValueError(f"Invalid connector format: {selected}. Please refresh the dropdown.")

        connector_id = parts[3]
        config = _get_outlook_config(connector_id)
        if config is None:
            raise ValueError(f"Connector '{parts[0]}' not found or has been deleted. Please refresh.")

        # Stash the connector_id for token-refresh persistence
        config["_connector_id"] = connector_id
        return config

    def _resolve_account(self, config: dict) -> dict:
        """Find the target linked account from config."""
        accounts = config.get("linked_accounts", [])
        if not accounts:
            raise ValueError(
                "No linked mailbox accounts. Link a mailbox on the Connectors page first."
            )

        email = self.account_email.strip() if self.account_email else ""
        if email:
            for acct in accounts:
                if acct.get("email", "").lower() == email.lower():
                    return acct
            raise ValueError(
                f"Account '{email}' not found. Available: {', '.join(a.get('email', '') for a in accounts)}"
            )

        # Default to first account
        return accounts[0]

    def read_mail(self) -> Message:
        """Read emails from the linked Outlook mailbox."""
        try:
            config = self._get_selected_config()
            acct = self._resolve_account(config)
            access_token = _refresh_token_sync(config, acct)
        except Exception as e:
            self.status = f"Error: {e!s}"
            return Message(text=f"Failed to connect to Outlook: {e!s}")

        import httpx

        # Build Graph request
        folder = self.folder.strip() if self.folder else "inbox"
        folder = _validate_path_segment(folder, "folder")
        limit = self.max_results if self.max_results and self.max_results > 0 else 10

        url = f"{GRAPH_BASE}/me/mailFolders/{folder}/messages"
        select_fields = "id,subject,from,receivedDateTime,bodyPreview,hasAttachments,body,toRecipients,ccRecipients"
        params: dict[str, str] = {
            "$top": str(limit),
            "$select": select_fields,
            "$orderby": "receivedDateTime desc",
        }

        sender = self.filter_sender.strip() if self.filter_sender else ""
        subject = self.filter_subject.strip() if self.filter_subject else ""

        # Build OData $filter — may fail on consumer Outlook.com accounts
        filters = []
        if sender:
            filters.append(f"from/emailAddress/address eq '{_odata_escape(sender)}'")
        if subject:
            filters.append(f"contains(subject, '{_odata_escape(subject)}')")
        if filters:
            params["$filter"] = " and ".join(filters)

        try:
            resp = httpx.get(url, headers={"Authorization": f"Bearer {access_token}"}, params=params, timeout=15)
        except Exception as e:
            self.status = f"Request failed: {e!s}"
            return Message(text=f"Graph API request failed: {e!s}")

        # Retry once with force-refresh on 401 (token may have been revoked)
        if resp.status_code == 401:
            logger.warning("Graph API returned 401, force-refreshing token and retrying...")
            try:
                access_token = _refresh_token_sync(config, acct, force=True)
                resp = httpx.get(url, headers={"Authorization": f"Bearer {access_token}"}, params=params, timeout=15)
            except Exception as e:
                self.status = f"Token refresh failed: {e!s}"
                return Message(text=f"Authentication failed after retry: {e!s}. Re-link the mailbox on the Connectors page.")

        # OData $filter may fail on consumer Outlook.com accounts (400/501)
        # Fall back to fetching all messages and filtering client-side
        client_side_filter = False
        if resp.status_code in (400, 501) and "$filter" in params:
            logger.warning(
                f"Graph API $filter failed ({resp.status_code}), falling back to client-side filtering"
            )
            fallback_params = {k: v for k, v in params.items() if k != "$filter"}
            # Fetch more to compensate for client-side filtering
            fallback_params["$top"] = str(min(limit * 5, 50))
            try:
                resp = httpx.get(url, headers={"Authorization": f"Bearer {access_token}"}, params=fallback_params, timeout=15)
                client_side_filter = True
            except Exception as e:
                self.status = f"Request failed: {e!s}"
                return Message(text=f"Graph API request failed on fallback: {e!s}")

        if resp.status_code != 200:
            self.status = f"Graph API error {resp.status_code}"
            error_detail = resp.text[:300] if resp.text else "No details"
            return Message(text=f"Graph API error {resp.status_code}: {error_detail}")

        messages_raw = resp.json().get("value", [])

        # Apply client-side filters if OData $filter was not supported
        if client_side_filter:
            filtered = []
            for msg in messages_raw:
                msg_sender = msg.get("from", {}).get("emailAddress", {}).get("address", "").lower()
                msg_subject = (msg.get("subject") or "").lower()
                if sender and sender.lower() != msg_sender:
                    continue
                if subject and subject.lower() not in msg_subject:
                    continue
                filtered.append(msg)
            messages_raw = filtered[:limit]

        # Format output for the agent
        lines = []
        for msg in messages_raw:
            graph_id = msg.get("id", "")
            short_ref = _register_message_id(graph_id)

            from_addr = msg.get("from", {}).get("emailAddress", {})
            from_str = f"{from_addr.get('name', '')} <{from_addr.get('address', '')}>"
            to_list = [
                r.get("emailAddress", {}).get("address", "")
                for r in msg.get("toRecipients", [])
            ]
            cc_list = [
                r.get("emailAddress", {}).get("address", "")
                for r in msg.get("ccRecipients", [])
            ]

            entry = (
                f"---\n"
                f"**ID:** `{short_ref}`\n"
                f"**Subject:** {msg.get('subject', '(no subject)')}\n"
                f"**From:** {from_str}\n"
                f"**To:** {', '.join(to_list)}\n"
            )
            if cc_list:
                entry += f"**CC:** {', '.join(cc_list)}\n"
            entry += (
                f"**Date:** {msg.get('receivedDateTime', '')}\n"
                f"**Preview:** {msg.get('bodyPreview', '')}\n"
            )

            # Fetch and parse attachments if present
            if msg.get("hasAttachments"):
                parsed = _fetch_attachments_sync(graph_id, access_token)
                if parsed:
                    att_lines = []
                    for att in parsed:
                        fname = att.get("filename", "unknown")
                        text = att.get("text")
                        error = att.get("error")
                        if text:
                            # Truncate very long attachments to keep context manageable
                            preview = text[:3000]
                            if len(text) > 3000:
                                preview += f"\n... (truncated, {len(text)} chars total)"
                            att_lines.append(f"  - **{fname}**:\n{preview}")
                        elif error:
                            att_lines.append(f"  - **{fname}**: {error}")
                        else:
                            att_lines.append(f"  - **{fname}**: (no text extracted)")
                    entry += f"**Attachments ({len(parsed)}):**\n" + "\n".join(att_lines) + "\n"
                else:
                    entry += "**Attachments:** Yes (could not fetch content)\n"
            else:
                entry += "**Attachments:** None\n"

            lines.append(entry)

        account_email = acct.get("email", "")
        count = len(messages_raw)
        self.status = f"{count} email(s) from {account_email}"

        if not lines:
            return Message(text=f"No emails found in {folder} for {account_email}.")

        header = f"**{count} email(s)** from `{account_email}` ({folder}):\n\n"
        header += "**Note:** Use the short ID (e.g. MSG-1) when replying to an email.\n\n"
        return Message(text=header + "\n".join(lines))

    def send_reply(self) -> Message:
        """Reply to an email via the linked Outlook mailbox."""
        from urllib.parse import quote

        raw_id = self.message_id.strip() if self.message_id else ""
        body = self.reply_body.strip() if self.reply_body else ""

        if not raw_id:
            self.status = "Error: no message_id"
            return Message(text="message_id is required. Use read_mail first to get message IDs (e.g. MSG-1).")

        # Resolve short ref (MSG-1) → real Graph ID
        msg_id = _resolve_message_id(raw_id)

        try:
            msg_id = _validate_path_segment(msg_id, "message_id")
        except ValueError as e:
            self.status = f"Error: {e!s}"
            return Message(text=str(e))

        if not body:
            self.status = "Error: no reply body"
            return Message(text="reply_body is required. Provide the text content for the reply.")

        try:
            config = self._get_selected_config()
            acct = self._resolve_account(config)
            access_token = _refresh_token_sync(config, acct)
        except Exception as e:
            self.status = f"Error: {e!s}"
            return Message(text=f"Failed to connect to Outlook: {e!s}")

        import httpx

        # URL-encode the message ID to handle base64 chars like / + =
        safe_id = quote(msg_id, safe="")
        url = f"{GRAPH_BASE}/me/messages/{safe_id}/reply"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        payload = {"message": {"body": {"contentType": "Text", "content": body}}}

        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=15)
        except Exception as e:
            self.status = f"Request failed: {e!s}"
            return Message(text=f"Reply request failed: {e!s}")

        # Retry once with force-refresh on 401
        if resp.status_code == 401:
            logger.warning("Graph API reply returned 401, force-refreshing token and retrying...")
            try:
                access_token = _refresh_token_sync(config, acct, force=True)
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                resp = httpx.post(url, headers=headers, json=payload, timeout=15)
            except Exception as e:
                self.status = f"Token refresh failed: {e!s}"
                return Message(text=f"Authentication failed after retry: {e!s}. Re-link the mailbox on the Connectors page.")

        if resp.status_code not in (200, 202):
            self.status = f"Reply failed ({resp.status_code})"
            error_detail = resp.text[:300] if resp.text else "No details"
            return Message(
                text=f"Reply failed ({resp.status_code}): {error_detail}"
            )

        account_email = acct.get("email", "")
        self.status = f"Reply sent from {account_email}"
        return Message(text=f"Reply sent successfully from {account_email} (ref: {raw_id}).")

    def reply_all(self) -> Message:
        """Reply-all to an email via the linked Outlook mailbox."""
        from urllib.parse import quote

        raw_id = self.message_id.strip() if self.message_id else ""
        body = self.reply_body.strip() if self.reply_body else ""

        if not raw_id:
            self.status = "Error: no message_id"
            return Message(text="message_id is required. Use read_mail first to get message IDs (e.g. MSG-1).")

        msg_id = _resolve_message_id(raw_id)

        try:
            msg_id = _validate_path_segment(msg_id, "message_id")
        except ValueError as e:
            self.status = f"Error: {e!s}"
            return Message(text=str(e))

        if not body:
            self.status = "Error: no reply body"
            return Message(text="reply_body is required. Provide the text content for the reply.")

        try:
            config = self._get_selected_config()
            acct = self._resolve_account(config)
            access_token = _refresh_token_sync(config, acct)
        except Exception as e:
            self.status = f"Error: {e!s}"
            return Message(text=f"Failed to connect to Outlook: {e!s}")

        import httpx

        safe_id = quote(msg_id, safe="")
        url = f"{GRAPH_BASE}/me/messages/{safe_id}/replyAll"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        payload = {"message": {"body": {"contentType": "Text", "content": body}}}

        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=15)
        except Exception as e:
            self.status = f"Request failed: {e!s}"
            return Message(text=f"Reply-all request failed: {e!s}")

        if resp.status_code == 401:
            logger.warning("Graph API replyAll returned 401, force-refreshing token and retrying...")
            try:
                access_token = _refresh_token_sync(config, acct, force=True)
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                }
                resp = httpx.post(url, headers=headers, json=payload, timeout=15)
            except Exception as e:
                self.status = f"Token refresh failed: {e!s}"
                return Message(text=f"Authentication failed after retry: {e!s}. Re-link the mailbox on the Connectors page.")

        if resp.status_code not in (200, 202):
            self.status = f"Reply-all failed ({resp.status_code})"
            error_detail = resp.text[:300] if resp.text else "No details"
            return Message(text=f"Reply-all failed ({resp.status_code}): {error_detail}")

        account_email = acct.get("email", "")
        self.status = f"Reply-all sent from {account_email}"
        return Message(text=f"Reply-all sent successfully from {account_email} (ref: {raw_id}).")

    def send_mail(self) -> Message:
        """Send a new email via the linked Outlook mailbox."""
        to_raw = self.to_recipients.strip() if self.to_recipients else ""
        subject = self.email_subject.strip() if self.email_subject else ""
        body = self.email_body.strip() if self.email_body else ""

        if not to_raw:
            self.status = "Error: no recipients"
            return Message(text="to_recipients is required. Provide comma-separated email addresses.")

        if not subject:
            self.status = "Error: no subject"
            return Message(text="email_subject is required.")

        if not body:
            self.status = "Error: no body"
            return Message(text="email_body is required.")

        recipients = [r.strip() for r in to_raw.split(",") if r.strip()]
        if not recipients:
            self.status = "Error: no valid recipients"
            return Message(text="No valid email addresses found in to_recipients.")

        try:
            config = self._get_selected_config()
            acct = self._resolve_account(config)
            access_token = _refresh_token_sync(config, acct)
        except Exception as e:
            self.status = f"Error: {e!s}"
            return Message(text=f"Failed to connect to Outlook: {e!s}")

        import httpx

        url = f"{GRAPH_BASE}/me/sendMail"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        cc_raw = self.cc_recipients.strip() if self.cc_recipients else ""
        cc_list = [r.strip() for r in cc_raw.split(",") if r.strip()] if cc_raw else []

        message: dict = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": r}} for r in recipients],
        }
        if cc_list:
            message["ccRecipients"] = [{"emailAddress": {"address": r}} for r in cc_list]
        payload = {"message": message, "saveToSentItems": True}

        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=15)
        except Exception as e:
            self.status = f"Request failed: {e!s}"
            return Message(text=f"Send mail request failed: {e!s}")

        # Retry once with force-refresh on 401
        if resp.status_code == 401:
            logger.warning("Graph API sendMail returned 401, force-refreshing token and retrying...")
            try:
                access_token = _refresh_token_sync(config, acct, force=True)
                headers["Authorization"] = f"Bearer {access_token}"
                resp = httpx.post(url, headers=headers, json=payload, timeout=15)
            except Exception as e:
                self.status = f"Token refresh failed: {e!s}"
                return Message(text=f"Authentication failed after retry: {e!s}. Re-link the mailbox on the Connectors page.")

        if resp.status_code not in (200, 202):
            self.status = f"Send failed ({resp.status_code})"
            error_detail = resp.text[:300] if resp.text else "No details"
            return Message(text=f"Send mail failed ({resp.status_code}): {error_detail}")

        account_email = acct.get("email", "")
        self.status = f"Email sent from {account_email}"
        cc_info = f" (CC: {', '.join(cc_list)})" if cc_list else ""
        return Message(text=f"Email sent successfully from {account_email} to {', '.join(recipients)}{cc_info}.")
