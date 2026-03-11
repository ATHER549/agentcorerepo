"""Outlook connector API — OAuth flow, account linking, mail read/reply.

Isolated router for Outlook-specific operations.  Does NOT modify
any connector-catalogue CRUD — that remains in connector_catalogue.py.
"""
from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlparse
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from loguru import logger
from pydantic import BaseModel

from agentcore.services.cache.redis_client import get_redis_client
from agentcore.services.deps import get_settings_service

from agentcore.api.connector_catalogue import (
    EMAIL_PROVIDERS,
    _can_access_connector,
    _decrypt_provider_config,
    _encrypt_provider_config,
    _get_scope_memberships,
    _require_connector_permission,
)
from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.connector_catalogue.model import ConnectorCatalogue

router = APIRouter(prefix="/outlook", tags=["Outlook Connector"])

# ── Constants ────────────────────────────────────────────────────

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
AUTHORIZE_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
MAIL_SCOPES = "Mail.Read Mail.ReadWrite Mail.Send User.Read offline_access"

# ── OAuth state store (Redis, TTL-based) ──────────────────────────
_STATE_TTL_SECONDS = 600  # 10 minutes


async def _store_oauth_state(state: str, data: dict) -> None:
    """Store OAuth state in Redis with TTL."""
    settings_service = get_settings_service()
    redis = get_redis_client(settings_service)
    await redis.setex(f"outlook_oauth:{state}", _STATE_TTL_SECONDS, json.dumps(data))


async def _pop_oauth_state(state: str) -> dict | None:
    """Retrieve and delete OAuth state from Redis. Returns None if expired/missing."""
    settings_service = get_settings_service()
    redis = get_redis_client(settings_service)
    key = f"outlook_oauth:{state}"
    raw = await redis.get(key)
    if not raw:
        return None
    await redis.delete(key)
    return json.loads(raw)


# ── Pydantic models ─────────────────────────────────────────────

class OAuthStartResponse(BaseModel):
    authorize_url: str
    state: str


class ReadMailRequest(BaseModel):
    account_email: str
    limit: int = 10
    folder: str = "inbox"
    filter_sender: str | None = None
    filter_subject: str | None = None


class ReplyMailRequest(BaseModel):
    account_email: str
    message_id: str
    body: str
    reply_mode: str = "sender"  # sender | reply_all | custom
    custom_recipients: list[str] | None = None
    cc_recipients: list[str] | None = None


# ── Helpers ──────────────────────────────────────────────────────

async def _load_connector(
    connector_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> ConnectorCatalogue:
    """Load and validate a connector belongs to the user and is an Outlook connector."""
    await _require_connector_permission(current_user, "connectore_page")
    row = await session.get(ConnectorCatalogue, connector_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector not found")
    if row.provider not in EMAIL_PROVIDERS:
        raise HTTPException(status_code=400, detail="Not an Outlook connector")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_connector(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="Connector is outside your visibility scope")
    return row


def _odata_escape(value: str) -> str:
    """Escape single quotes for OData $filter values."""
    return value.replace("'", "''")


def _validate_path_segment(value: str, label: str) -> str:
    """Ensure a value is safe to embed in a URL path segment.

    Folder names are checked strictly (no /, \\, ..).
    Message IDs are long base64 strings that may contain '/' or '+',
    so we only reject path traversal (\\ and ..) and URL-encode later.
    """
    if not value:
        raise HTTPException(status_code=400, detail=f"{label} is required")
    if label == "message_id":
        if "\\" in value or ".." in value:
            raise HTTPException(status_code=400, detail=f"Invalid {label}: must not contain '\\' or '..'")
    else:
        if "/" in value or "\\" in value or ".." in value:
            raise HTTPException(status_code=400, detail=f"Invalid {label}: must not contain '/', '\\', or '..'")
    return value


def _get_decrypted_config(row: ConnectorCatalogue) -> dict:
    """Get decrypted provider_config for a connector."""
    return _decrypt_provider_config(row.provider, row.provider_config or {})


def _find_account(config: dict, email: str) -> dict | None:
    """Find a linked account by email (case-insensitive)."""
    for acct in config.get("linked_accounts", []):
        if acct.get("email", "").lower() == email.lower():
            return acct
    return None


async def _refresh_token_if_needed(config: dict, acct: dict, force: bool = False) -> tuple[str, bool]:
    """Refresh the access token if expired.

    Returns (access_token, was_refreshed).  Mutates *acct* in-place
    when a refresh occurs so the caller can persist the update.
    When *force* is True, skip the expiry check (used on 401 retry).
    """
    access_token = acct.get("access_token", "")
    expires_at = acct.get("token_expires_at", 0)

    # Still valid (60 s buffer) — unless force-refresh requested
    if not force and access_token and time.time() < (expires_at - 60):
        return access_token, False

    # Need to refresh
    refresh_token = acct.get("refresh_token", "")
    if not refresh_token:
        raise HTTPException(
            status_code=401,
            detail="Token expired and no refresh token available. Re-authenticate.",
        )

    tenant_id = config.get("tenant_id", "")
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")

    token_url = TOKEN_URL.format(tenant_id=tenant_id)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": MAIL_SCOPES,
            },
        )

    if resp.status_code != 200:
        logger.warning("Outlook token refresh failed: {}", resp.text[:300])
        raise HTTPException(status_code=401, detail="Token refresh failed. Re-authenticate.")

    data = resp.json()
    acct["access_token"] = data["access_token"]
    acct["refresh_token"] = data.get("refresh_token", refresh_token)
    acct["token_expires_at"] = time.time() + data.get("expires_in", 3600)
    return data["access_token"], True


async def _save_updated_config(
    session: DbSession,
    row: ConnectorCatalogue,
    config: dict,
    current_user_id: UUID,
) -> None:
    """Encrypt and save updated provider_config back to the connector row."""
    row.provider_config = _encrypt_provider_config(row.provider, config)
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = current_user_id
    try:
        await session.commit()
        await session.refresh(row)
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to save Outlook connector config: {}", exc)
        raise HTTPException(status_code=500, detail="Failed to save connector configuration")


# ── OAuth endpoints ──────────────────────────────────────────────

@router.get("/{connector_id}/oauth/start")
async def start_oauth(
    connector_id: UUID,
    request: Request,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> OAuthStartResponse:
    """Generate Microsoft OAuth authorize URL for Outlook Mail scopes."""
    row = await _load_connector(connector_id, current_user, session)
    config = _get_decrypted_config(row)

    tenant_id = config.get("tenant_id", "")
    client_id = config.get("client_id", "")

    if not tenant_id or not client_id:
        raise HTTPException(
            status_code=400,
            detail="tenant_id and client_id are required in provider_config",
        )

    # Auto-derive redirect_uri from the current request's base URL
    # Azure AD requires "https://" or "http://localhost" — 127.0.0.1 is rejected
    base = str(request.base_url).rstrip("/")
    base = base.replace("://127.0.0.1", "://localhost")
    redirect_uri = base + "/api/outlook/oauth/callback"

    # Determine frontend origin for post-OAuth redirect
    # The Referer/Origin header tells us where the user's browser actually is
    frontend_origin = ""
    referer = request.headers.get("referer", "")
    if referer:
        parsed = urlparse(referer)
        frontend_origin = f"{parsed.scheme}://{parsed.netloc}"

    # Generate state token and store in Redis
    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, {
        "connector_id": str(connector_id),
        "user_id": str(current_user.id),
        "redirect_uri": redirect_uri,
        "frontend_origin": frontend_origin,
    })

    # Build authorize URL
    base = AUTHORIZE_URL.format(tenant_id=tenant_id)
    params = urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": MAIL_SCOPES,
        "state": state,
        "response_mode": "query",
        "prompt": "select_account",
    })
    authorize_url = f"{base}?{params}"

    return OAuthStartResponse(authorize_url=authorize_url, state=state)


@router.get("/oauth/callback")
async def oauth_callback(
    session: DbSession,
    code: str = Query(""),
    state: str = Query(...),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
) -> RedirectResponse:
    """Exchange authorization code for tokens, link account to connector.

    This endpoint is called by Microsoft's redirect — no JWT auth required.
    The *state* parameter encodes the connector_id and user_id.
    """
    # Try to recover frontend_origin from state for all redirects
    # (peek at state early so even error redirects go to the right place)
    state_data = await _pop_oauth_state(state) if state else None
    fe = state_data.get("frontend_origin", "") if state_data else ""

    # Handle OAuth errors from Microsoft
    if error:
        logger.warning("Outlook OAuth error: {} — {}", error, error_description)
        return RedirectResponse(
            url=f"{fe}/connectors?error=outlook_oauth_failed&detail={quote(error_description or error)}",
        )

    if not code:
        raise HTTPException(status_code=400, detail="Authorization code missing")

    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    connector_id = UUID(state_data["connector_id"])
    user_id = UUID(state_data["user_id"])
    redirect_uri = state_data.get("redirect_uri", "")

    # Load connector (no auth check — validated via state token)
    row = await session.get(ConnectorCatalogue, connector_id)
    if not row or row.provider not in EMAIL_PROVIDERS:
        raise HTTPException(status_code=404, detail="Connector not found")

    config = _get_decrypted_config(row)

    tenant_id = config.get("tenant_id", "")
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")

    # Exchange code for tokens
    token_url = TOKEN_URL.format(tenant_id=tenant_id)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": MAIL_SCOPES,
            },
        )

    if resp.status_code != 200:
        logger.error("Outlook token exchange failed: {}", resp.text[:500])
        return RedirectResponse(url=f"{fe}/connectors?error=outlook_token_exchange_failed")

    token_data = resp.json()
    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)

    # Get user profile from Graph /me
    async with httpx.AsyncClient(timeout=10) as client:
        me_resp = await client.get(
            f"{GRAPH_BASE}/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if me_resp.status_code != 200:
        logger.error("Outlook /me call failed: {}", me_resp.text[:300])
        return RedirectResponse(url=f"{fe}/connectors?error=outlook_profile_fetch_failed")

    me_data = me_resp.json()
    email = (me_data.get("mail") or me_data.get("userPrincipalName") or "").lower()
    display_name = me_data.get("displayName", "")

    if not email:
        return RedirectResponse(url=f"{fe}/connectors?error=outlook_no_email")

    # Validate mailbox access — reject guest accounts / unlicensed users
    async with httpx.AsyncClient(timeout=10) as client:
        inbox_resp = await client.get(
            f"{GRAPH_BASE}/me/mailFolders/inbox",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if inbox_resp.status_code != 200:
        logger.warning(
            f"Outlook mailbox validation failed for {email}: "
            f"{inbox_resp.status_code} — {inbox_resp.text[:200]}"
        )
        return RedirectResponse(
            url=f"{fe}/connectors?error=outlook_no_mailbox"
        )

    # Build linked account entry
    linked_accounts: list[dict] = config.get("linked_accounts", [])
    now_iso = datetime.now(timezone.utc).isoformat()

    new_acct = {
        "email": email,
        "display_name": display_name,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expires_at": time.time() + expires_in,
        "linked_at": now_iso,
    }

    # Update existing or append new
    found = False
    for i, acct in enumerate(linked_accounts):
        if acct.get("email", "").lower() == email.lower():
            linked_accounts[i] = new_acct
            found = True
            break
    if not found:
        linked_accounts.append(new_acct)

    config["linked_accounts"] = linked_accounts

    # Encrypt and save
    row.provider_config = _encrypt_provider_config(row.provider, config)
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = user_id
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to save linked Outlook account: {}", exc)
        return RedirectResponse(url=f"{fe}/connectors?error=outlook_save_failed")

    logger.info("Outlook account {} linked to connector {}", email, connector_id)

    return RedirectResponse(
        url=f"{fe}/connectors?success=outlook_account_linked&email={quote(email)}",
    )


# ── Account management ──────────────────────────────────────────

@router.get("/{connector_id}/accounts")
async def list_accounts(
    connector_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[dict]:
    """List linked Outlook accounts for a connector (tokens masked)."""
    row = await _load_connector(connector_id, current_user, session)
    config = _get_decrypted_config(row)

    accounts = []
    for acct in config.get("linked_accounts", []):
        accounts.append({
            "email": acct.get("email", ""),
            "display_name": acct.get("display_name", ""),
            "linked_at": acct.get("linked_at", ""),
            "token_expires_at": acct.get("token_expires_at"),
        })
    return accounts


@router.delete("/{connector_id}/accounts/{email}")
async def unlink_account(
    connector_id: UUID,
    email: str,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Remove a linked account from the connector."""
    row = await _load_connector(connector_id, current_user, session)
    config = _get_decrypted_config(row)

    linked_accounts = config.get("linked_accounts", [])
    original_count = len(linked_accounts)
    linked_accounts = [
        a for a in linked_accounts
        if a.get("email", "").lower() != email.lower()
    ]

    if len(linked_accounts) == original_count:
        raise HTTPException(status_code=404, detail=f"Account '{email}' not found")

    config["linked_accounts"] = linked_accounts
    await _save_updated_config(session, row, config, current_user.id)

    return {"message": f"Account '{email}' unlinked successfully"}


# ── Mail operations ──────────────────────────────────────────────

@router.post("/{connector_id}/read")
async def read_mail(
    connector_id: UUID,
    req: ReadMailRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Read inbox messages from a linked Outlook account."""
    row = await _load_connector(connector_id, current_user, session)
    config = _get_decrypted_config(row)

    acct = _find_account(config, req.account_email)
    if not acct:
        raise HTTPException(
            status_code=404,
            detail=f"Account '{req.account_email}' not linked",
        )

    # Refresh token if needed
    access_token, was_refreshed = await _refresh_token_if_needed(config, acct)

    # Persist refreshed tokens only when something changed
    if was_refreshed:
        await _save_updated_config(session, row, config, current_user.id)

    # Build Graph request
    safe_folder = _validate_path_segment(req.folder, "folder")
    url = f"{GRAPH_BASE}/me/mailFolders/{safe_folder}/messages"
    params: dict[str, str] = {
        "$top": str(req.limit),
        "$select": "id,subject,from,receivedDateTime,bodyPreview,hasAttachments,body,toRecipients,ccRecipients",
        "$orderby": "receivedDateTime desc",
    }

    filters = []
    if req.filter_sender:
        filters.append(f"from/emailAddress/address eq '{_odata_escape(req.filter_sender)}'")
    if req.filter_subject:
        filters.append(f"contains(subject, '{_odata_escape(req.filter_subject)}')")
    if filters:
        params["$filter"] = " and ".join(filters)

    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers, params=params)

    # Retry once with force-refresh on 401
    if resp.status_code == 401:
        logger.warning("read_mail: Graph API 401, force-refreshing token and retrying")
        access_token, _ = await _refresh_token_if_needed(config, acct, force=True)
        if _:
            await _save_updated_config(session, row, config, current_user.id)
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers, params=params)

    # OData $filter may fail on consumer Outlook.com accounts (400/501)
    # Fall back to client-side filtering
    client_side_filter = False
    if resp.status_code in (400, 501) and "$filter" in params:
        logger.warning(
            f"read_mail: OData $filter failed ({resp.status_code}), falling back to client-side"
        )
        fallback_params = {k: v for k, v in params.items() if k != "$filter"}
        fallback_params["$top"] = str(min(req.limit * 5, 50))
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers, params=fallback_params)
        client_side_filter = True

    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Graph API error {resp.status_code}: {resp.text[:300]}",
        )

    messages_raw = resp.json().get("value", [])

    # Apply client-side filters if OData was not supported
    if client_side_filter:
        filtered = []
        for msg in messages_raw:
            msg_sender = msg.get("from", {}).get("emailAddress", {}).get("address", "").lower()
            msg_subject = (msg.get("subject") or "").lower()
            if req.filter_sender and req.filter_sender.lower() != msg_sender:
                continue
            if req.filter_subject and req.filter_subject.lower() not in msg_subject:
                continue
            filtered.append(msg)
        messages_raw = filtered[:req.limit]

    # Format messages
    messages = []
    for msg in messages_raw:
        messages.append({
            "id": msg.get("id"),
            "subject": msg.get("subject"),
            "from": msg.get("from", {}).get("emailAddress", {}),
            "receivedDateTime": msg.get("receivedDateTime"),
            "bodyPreview": msg.get("bodyPreview"),
            "body": msg.get("body", {}).get("content", ""),
            "bodyContentType": msg.get("body", {}).get("contentType", "text"),
            "hasAttachments": msg.get("hasAttachments", False),
            "toRecipients": [
                r.get("emailAddress", {}) for r in msg.get("toRecipients", [])
            ],
            "ccRecipients": [
                r.get("emailAddress", {}) for r in msg.get("ccRecipients", [])
            ],
        })

    return {
        "account_email": req.account_email,
        "folder": req.folder,
        "count": len(messages),
        "messages": messages,
    }


@router.post("/{connector_id}/reply")
async def reply_mail(
    connector_id: UUID,
    req: ReplyMailRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Reply to an email via Microsoft Graph."""
    row = await _load_connector(connector_id, current_user, session)
    config = _get_decrypted_config(row)

    acct = _find_account(config, req.account_email)
    if not acct:
        raise HTTPException(
            status_code=404,
            detail=f"Account '{req.account_email}' not linked",
        )

    # Refresh token if needed
    access_token, was_refreshed = await _refresh_token_if_needed(config, acct)
    if was_refreshed:
        await _save_updated_config(session, row, config, current_user.id)

    from urllib.parse import quote

    safe_msg_id = _validate_path_segment(req.message_id, "message_id")
    safe_msg_id = quote(safe_msg_id, safe="")  # URL-encode base64 chars (/, +, =)

    async def _graph_post(url: str, json_payload: dict) -> httpx.Response:
        """POST to Graph API with 401 retry."""
        nonlocal access_token
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=json_payload)
        if resp.status_code == 401:
            logger.warning("reply_mail: Graph API 401, force-refreshing token and retrying")
            access_token, refreshed = await _refresh_token_if_needed(config, acct, force=True)
            if refreshed:
                await _save_updated_config(session, row, config, current_user.id)
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, headers=headers, json=json_payload)
        return resp

    if req.reply_mode == "sender":
        url = f"{GRAPH_BASE}/me/messages/{safe_msg_id}/reply"
        payload = {"message": {"body": {"contentType": "Text", "content": req.body}}}
        resp = await _graph_post(url, payload)

        if resp.status_code not in (200, 202):
            raise HTTPException(
                status_code=400,
                detail=f"Reply failed ({resp.status_code}): {resp.text[:300]}",
            )
        return {"success": True, "message": "Reply sent successfully", "reply_mode": "sender"}

    elif req.reply_mode == "reply_all":
        url = f"{GRAPH_BASE}/me/messages/{safe_msg_id}/replyAll"
        payload = {"message": {"body": {"contentType": "Text", "content": req.body}}}
        resp = await _graph_post(url, payload)

        if resp.status_code not in (200, 202):
            raise HTTPException(
                status_code=400,
                detail=f"Reply-all failed ({resp.status_code}): {resp.text[:300]}",
            )
        return {"success": True, "message": "Reply-all sent successfully", "reply_mode": "reply_all"}

    elif req.reply_mode == "custom":
        if not req.custom_recipients:
            raise HTTPException(
                status_code=400,
                detail="custom_recipients required for custom reply mode",
            )

        # Fetch original subject for the reply
        async with httpx.AsyncClient(timeout=10) as client:
            orig_resp = await client.get(
                f"{GRAPH_BASE}/me/messages/{safe_msg_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"$select": "subject"},
            )

        subject = "Re: "
        if orig_resp.status_code == 200:
            orig_subject = orig_resp.json().get("subject", "")
            subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"

        message: dict = {
            "subject": subject,
            "body": {"contentType": "Text", "content": req.body},
            "toRecipients": [{"emailAddress": {"address": r}} for r in req.custom_recipients],
        }
        if req.cc_recipients:
            message["ccRecipients"] = [{"emailAddress": {"address": r}} for r in req.cc_recipients]

        url = f"{GRAPH_BASE}/me/sendMail"
        resp = await _graph_post(url, {"message": message, "saveToSentItems": True})

        if resp.status_code not in (200, 202):
            raise HTTPException(
                status_code=400,
                detail=f"Send failed ({resp.status_code}): {resp.text[:300]}",
            )
        return {
            "success": True,
            "message": f"Sent to {', '.join(req.custom_recipients)}",
            "reply_mode": "custom",
        }

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported reply_mode: '{req.reply_mode}'. Use sender, reply_all, or custom.",
        )
