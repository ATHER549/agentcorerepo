# Path: src/backend/base/agentcore/api/teams.py
"""Microsoft Teams Bot Framework and app management endpoints.

Endpoints:
- POST /api/teams/messages - Bot Framework messaging webhook (no agentcore auth)
- GET /api/teams/oauth/authorize - Start Microsoft OAuth flow
- GET /api/teams/oauth/callback - Handle Microsoft OAuth redirect
- GET /api/teams/oauth/status - Check if user has connected Microsoft account
- DELETE /api/teams/oauth/disconnect - Remove stored Microsoft tokens
- POST /api/teams/publish - Publish an agent as a Teams app
- DELETE /api/teams/unpublish/{agent_id} - Remove agent from Teams
- GET /api/teams/status/{agent_id} - Get Teams publish status
- POST /api/teams/sync/{agent_id} - Re-sync agent's Teams app
- GET /api/teams/apps - List all published Teams apps
- GET /api/teams/health - Health check for Teams integration
"""

from __future__ import annotations

import os
import secrets
import time
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.utils import get_current_user_by_jwt
from agentcore.schema.teams import (
    TeamsAppStatusResponse,
    TeamsPublishRequest,
    TeamsPublishResponse,
)
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.teams_app.model import (
    TeamsApp,
    TeamsPublishStatusEnum,
)
from agentcore.services.deps import get_teams_service

router = APIRouter(prefix="/teams", tags=["Teams"])


# === Helper functions for per-agent bot routing ===


def _extract_app_id_from_jwt(auth_header: str) -> str | None:
    """Extract the appId claim from a Bot Framework JWT without verification.

    The Bot Framework SDK handles full JWT verification. We just need the appId
    to select the correct adapter before that verification happens.
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    try:
        import base64
        import json as _json

        token = auth_header.split(" ", 1)[1]
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("appid") or payload.get("azp") or payload.get("aud")
    except Exception:
        logger.debug("Could not extract appId from JWT, falling back to default adapter")
        return None


async def _resolve_adapter_for_app_id(teams_service, bot_app_id: str | None):
    """Look up the per-agent adapter for the given appId.

    Returns: (adapter, agent_id_hint)
    """
    if not bot_app_id:
        return teams_service.get_adapter(), None

    # If it matches the global bot, use default adapter
    if bot_app_id == teams_service.settings.teams_bot_app_id:
        return teams_service.get_adapter(), None

    # Look up per-agent bot in database
    from agentcore.services.deps import session_scope

    async with session_scope() as session:
        stmt = (
            select(TeamsApp)
            .where(TeamsApp.bot_app_id == bot_app_id)
            .where(TeamsApp.status == TeamsPublishStatusEnum.PUBLISHED)
        )
        teams_app = (await session.exec(stmt)).first()

        if teams_app and teams_app.bot_app_secret:
            adapter = teams_service.get_adapter(
                bot_app_id=bot_app_id,
                bot_app_secret=teams_app.bot_app_secret,
            )
            return adapter, str(teams_app.agent_id)

    # Fallback to default adapter
    return teams_service.get_adapter(), None


# === Bot Framework Webhook (NO agentcore auth - Bot Framework validates its own JWT) ===


@router.post("/messages")
async def teams_messages_endpoint(request: Request) -> Response:
    """Incoming messages from Teams via Bot Framework."""
    logger.info("=== Teams /messages endpoint hit ===")
    teams_service = get_teams_service()

    try:
        from botbuilder.schema import Activity

        body = await request.json()
        logger.info(
            f"Activity type: {body.get('type')}, "
            f"from: {body.get('from', {}).get('name', 'unknown')}, "
            f"text: {str(body.get('text', ''))[:100]}"
        )

        auth_header = request.headers.get("Authorization", "")
        logger.info(f"Auth header present: {bool(auth_header)}, length: {len(auth_header)}")

        # Route to the correct per-agent adapter based on JWT appId
        bot_app_id = _extract_app_id_from_jwt(auth_header)
        logger.info(f"Extracted bot_app_id from JWT: {bot_app_id}")

        adapter, agent_id_hint = await _resolve_adapter_for_app_id(teams_service, bot_app_id)
        logger.info(f"Resolved adapter (agent_id_hint={agent_id_hint})")

        activity = Activity().deserialize(body)

        # Inject agent_id hint so bot handler can skip ambiguous DB query
        if agent_id_hint:
            if not activity.channel_data:
                activity.channel_data = {}
            activity.channel_data["_agentcore_agent_id"] = agent_id_hint

        bot = teams_service.get_bot()
        response = await adapter.process_activity(activity, auth_header, bot.on_turn)
        logger.info(f"process_activity completed, response status: {response.status if response else 'None (200)'}")

        if response:
            return Response(
                content=response.body,
                status_code=response.status,
            )
        return Response(status_code=200)

    except Exception as e:
        logger.exception(f"Error processing Teams message: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


# === Diagnostic Endpoint ===


@router.get("/test-message")
async def test_bot_message() -> dict:
    """Diagnostic: verify the bot message processing pipeline without Teams."""
    teams_service = get_teams_service()
    result = {"configured": teams_service.is_configured}

    if not teams_service.is_configured:
        return result

    try:
        adapter = teams_service.get_adapter()
        result["adapter"] = "ok"
    except Exception as e:
        result["adapter"] = f"error: {e!s}"

    try:
        bot = teams_service.get_bot()
        result["bot"] = "ok"

        # Test agent resolution (same logic as when a message arrives)
        agent_id = await bot._resolve_agent_from_channel_data(None)
        result["resolved_agent_id"] = agent_id
        if agent_id:
            agent_name = await bot._get_agent_name(agent_id)
            result["resolved_agent_name"] = agent_name
    except Exception as e:
        result["bot"] = f"error: {e!s}"

    return result


# === OAuth Endpoints (for Microsoft Graph delegated auth) ===


@router.get("/oauth/authorize")
async def teams_oauth_authorize(
    db: DbSession,
    token: str = Query(..., description="JWT access token"),
) -> RedirectResponse:
    """Start the Microsoft OAuth flow.

    Redirects the user to Microsoft login to authorize Graph API access.
    Called from a popup window in the frontend.
    Token is passed as query param because window.open() cannot set headers.
    """
    # Manually validate the JWT token passed as query param
    current_user = await get_current_user_by_jwt(token, db)

    teams_service = get_teams_service()
    redirect_uri = teams_service.get_redirect_uri()

    # Generate state parameter for CSRF protection
    state = f"{current_user.id}:{secrets.token_urlsafe(16)}"

    # Store state in cache for verification on callback
    cache = teams_service._get_cache_service()
    if cache:
        try:
            await cache.set(f"teams:oauth_state:{state}", str(current_user.id), expiration=600)
        except Exception:
            pass

    graph_client = teams_service.get_graph_client()
    authorize_url = graph_client.get_authorize_url(redirect_uri=redirect_uri, state=state)

    return RedirectResponse(url=authorize_url)


@router.get("/oauth/callback")
async def teams_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> HTMLResponse:
    """Handle the Microsoft OAuth callback.

    Exchanges the authorization code for tokens and stores them.
    Returns HTML that closes the popup and notifies the parent window.
    """
    if error:
        logger.error(f"OAuth error: {error} - {error_description}")
        return _oauth_popup_response("error", error=error, description=error_description)

    if not code or not state:
        return HTMLResponse(content="<html><body><p>Missing code or state.</p></body></html>", status_code=400)

    teams_service = get_teams_service()

    # Extract user_id from state
    try:
        user_id_str = state.split(":")[0]
    except Exception:
        return HTMLResponse(content="<html><body><p>Invalid state.</p></body></html>", status_code=400)

    # Verify state in cache (CSRF protection)
    cache = teams_service._get_cache_service()
    if cache:
        try:
            stored = await cache.get(f"teams:oauth_state:{state}")
            if stored and stored != user_id_str:
                logger.warning("OAuth state mismatch")
            await cache.delete(f"teams:oauth_state:{state}")
        except Exception:
            pass

    # Exchange code for tokens
    try:
        redirect_uri = teams_service.get_redirect_uri()
        graph_client = teams_service.get_graph_client()
        token_data = await graph_client.exchange_code_for_tokens(code, redirect_uri)

        # Store tokens for this user
        stored_data = {
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "expires_at": time.time() + token_data.get("expires_in", 3600),
        }
        await teams_service.store_user_tokens(user_id_str, stored_data)

        logger.info(f"Stored Graph API tokens for user {user_id_str}")
        return _oauth_popup_response("success")

    except Exception as e:
        logger.exception(f"Failed to exchange OAuth code: {e}")
        return _oauth_popup_response("error", error="token_exchange_failed", description=str(e))


def _oauth_popup_response(
    result: str,
    error: str | None = None,
    description: str | None = None,
) -> HTMLResponse:
    """Generate an HTML response that communicates with the parent window and closes."""
    safe_error = (error or "").replace("'", "\\'").replace('"', '\\"')
    safe_desc = (description or "").replace("'", "\\'").replace('"', '\\"')

    if result == "success":
        message_js = "{ type: 'teams-oauth-success' }"
        text = "Successfully connected to Microsoft. This window will close."
    else:
        message_js = f"{{ type: 'teams-oauth-error', error: '{safe_error}', description: '{safe_desc}' }}"
        text = f"Authentication failed: {description or error}. This window will close."

    return HTMLResponse(
        content=f"""<html><body>
<script>
if (window.opener) {{ window.opener.postMessage({message_js}, '*'); }}
setTimeout(function() {{ window.close(); }}, 1000);
</script>
<p>{text}</p>
</body></html>""",
        status_code=200,
    )


@router.get("/oauth/status")
async def teams_oauth_status(
    current_user: CurrentActiveUser,
) -> dict:
    """Check if the current user has connected their Microsoft account."""
    teams_service = get_teams_service()
    tokens = await teams_service.get_user_tokens(str(current_user.id))

    return {
        "connected": tokens is not None and bool(tokens.get("access_token") or tokens.get("refresh_token")),
    }


@router.delete("/oauth/disconnect")
async def teams_oauth_disconnect(
    current_user: CurrentActiveUser,
) -> dict:
    """Disconnect the user's Microsoft account (remove stored tokens)."""
    teams_service = get_teams_service()
    await teams_service.delete_user_tokens(str(current_user.id))
    return {"disconnected": True}


# === Management Endpoints (require agentcore auth) ===


@router.post("/publish", response_model=TeamsPublishResponse)
async def publish_agent_to_teams(
    request: TeamsPublishRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> TeamsPublishResponse:
    """Publish an agent as a Teams app.

    Requires the user to have connected their Microsoft account first.
    """
    teams_service = get_teams_service()

    # Get the user's delegated Graph API client
    graph_client = await teams_service.get_graph_client_for_user(str(current_user.id))
    if not graph_client:
        raise HTTPException(
            status_code=401,
            detail="Connect your Microsoft account first. Use the 'Connect Microsoft Account' button.",
        )

    # Validate agent exists and user owns it
    agent = await session.get(Agent, request.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {request.agent_id} not found")
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You don't own this agent")

    # Check if already published
    stmt = (
        select(TeamsApp)
        .where(TeamsApp.agent_id == request.agent_id)
        .where(TeamsApp.status.in_([TeamsPublishStatusEnum.PUBLISHED, TeamsPublishStatusEnum.UPLOADED]))
    )
    existing = (await session.exec(stmt)).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Agent is already published to Teams with status: {existing.status.value}",
        )

    try:
        from agentcore.services.teams.manifest import create_teams_app_package, generate_icons, generate_manifest

        # Use per-agent bot credentials if provided, otherwise fall back to global
        bot_app_id = request.bot_app_id or teams_service.settings.teams_bot_app_id
        bot_app_secret = request.bot_app_secret  # None if using global
        base_url = teams_service.settings.teams_bot_endpoint_base or os.getenv(
            "LOCALHOST_TEAMS_BOT_BASE_URL",
            "https://localhost:7860",
        )

        display_name = request.display_name or agent.name
        short_description = request.short_description or agent.description or f"AgentCore: {agent.name}"

        manifest = generate_manifest(
            agent=agent,
            bot_app_id=bot_app_id,
            display_name=display_name,
            short_description=short_description,
            long_description=request.long_description,
            base_url=base_url,
        )

        color_icon, outline_icon = generate_icons(display_name)
        zip_package = create_teams_app_package(manifest, color_icon, outline_icon)

        # Find the previous external ID before any cleanup (needed for 409 fallback)
        prev_id_stmt = (
            select(TeamsApp)
            .where(TeamsApp.agent_id == request.agent_id)
            .where(TeamsApp.teams_app_external_id.isnot(None))
            .order_by(TeamsApp.created_at.desc())
        )
        prev_record = (await session.exec(prev_id_stmt)).first()
        prev_external_id = prev_record.teams_app_external_id if prev_record else None

        # Upload to Teams catalog via Graph API (delegated token)
        # If the app already exists (409), fall back to updating it
        manifest_id = manifest["id"]
        try:
            external_id = await graph_client.upload_app_to_catalog(zip_package)
        except ValueError:
            # 409 - manifest ID already exists in catalog. Update instead.
            # First try our DB record, then query the Graph API to find the app
            fallback_id = prev_external_id
            if not fallback_id:
                fallback_id = await graph_client.find_app_by_manifest_id(manifest_id)

            if fallback_id:
                # Bump version so the update isn't rejected with another 409
                import time as _time

                manifest["version"] = f"1.0.{int(_time.time())}"
                zip_package = create_teams_app_package(manifest, color_icon, outline_icon)
                await graph_client.update_app_in_catalog(fallback_id, zip_package)
                external_id = fallback_id
                logger.info(f"Updated existing Teams app {external_id} (re-publish after unpublish)")
            else:
                raise HTTPException(
                    status_code=409,
                    detail="An app with this manifest ID already exists in the catalog "
                    "but could not be found via Graph API. "
                    "Please delete it from the Teams Admin Center first.",
                )

        # Clean up old FAILED and UNPUBLISHED records for this agent (after successful upload)
        cleanup_stmt = (
            select(TeamsApp)
            .where(TeamsApp.agent_id == request.agent_id)
            .where(TeamsApp.status.in_([TeamsPublishStatusEnum.FAILED, TeamsPublishStatusEnum.UNPUBLISHED]))
        )
        old_records = (await session.exec(cleanup_stmt)).all()
        for old in old_records:
            await session.delete(old)

        # Persist refreshed tokens
        updated_tokens = graph_client.get_token_data()
        await teams_service.store_user_tokens(str(current_user.id), updated_tokens)

        # Store in database
        from datetime import datetime, timezone

        teams_app = TeamsApp(
            agent_id=request.agent_id,
            teams_app_external_id=external_id,
            bot_app_id=bot_app_id,
            bot_app_secret=bot_app_secret,
            display_name=display_name,
            short_description=short_description,
            status=TeamsPublishStatusEnum.PUBLISHED,
            published_by=current_user.id,
            published_at=datetime.now(timezone.utc),
            manifest_data=manifest,
        )
        session.add(teams_app)
        await session.commit()
        await session.refresh(teams_app)

        logger.info(f"Agent {agent.name} published to Teams as {display_name} (external_id={external_id}, own_bot={bool(bot_app_secret)})")

        return TeamsPublishResponse(
            teams_app_id=teams_app.id,
            agent_id=request.agent_id,
            status=TeamsPublishStatusEnum.PUBLISHED.value,
            teams_external_id=external_id,
            message=f"Successfully published '{display_name}' to Teams app catalog",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to publish agent {request.agent_id} to Teams: {e}")

        from datetime import datetime, timezone

        teams_app = TeamsApp(
            agent_id=request.agent_id,
            bot_app_id=teams_service.settings.teams_bot_app_id or "",
            display_name=request.display_name or agent.name,
            short_description=request.short_description or agent.description,
            status=TeamsPublishStatusEnum.FAILED,
            published_by=current_user.id,
            last_error=str(e),
        )
        session.add(teams_app)
        await session.commit()

        raise HTTPException(
            status_code=500,
            detail=f"Failed to publish to Teams: {e!s}",
        ) from e


@router.delete("/unpublish/{agent_id}", response_model=TeamsPublishResponse)
async def unpublish_agent_from_teams(
    agent_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> TeamsPublishResponse:
    """Remove an agent's Teams app from the org catalog."""
    stmt = (
        select(TeamsApp)
        .where(TeamsApp.agent_id == agent_id)
        .where(TeamsApp.status == TeamsPublishStatusEnum.PUBLISHED)
    )
    teams_app = (await session.exec(stmt)).first()
    if not teams_app:
        raise HTTPException(status_code=404, detail="Agent is not published to Teams")

    agent = await session.get(Agent, agent_id)
    if not agent or agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You don't own this agent")

    try:
        teams_service = get_teams_service()

        if teams_app.teams_app_external_id:
            graph_client = await teams_service.get_graph_client_for_user(str(current_user.id))
            if graph_client:
                await graph_client.delete_app_from_catalog(teams_app.teams_app_external_id)
                updated_tokens = graph_client.get_token_data()
                await teams_service.store_user_tokens(str(current_user.id), updated_tokens)

        # Evict per-agent adapter from cache
        if teams_app.bot_app_secret and teams_app.bot_app_id:
            teams_service._adapter_cache.pop(teams_app.bot_app_id, None)

        teams_app.status = TeamsPublishStatusEnum.UNPUBLISHED
        session.add(teams_app)
        await session.commit()

        logger.info(f"Agent {agent_id} unpublished from Teams")

        return TeamsPublishResponse(
            teams_app_id=teams_app.id,
            agent_id=agent_id,
            status=TeamsPublishStatusEnum.UNPUBLISHED.value,
            message="Successfully unpublished from Teams",
        )

    except Exception as e:
        logger.exception(f"Failed to unpublish agent {agent_id} from Teams: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to unpublish: {e!s}") from e


@router.get("/status/{agent_id}", response_model=TeamsAppStatusResponse)
async def get_teams_publish_status(
    agent_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> TeamsAppStatusResponse:
    """Get the Teams publish status for an agent."""
    stmt = (
        select(TeamsApp)
        .where(TeamsApp.agent_id == agent_id)
        .order_by(TeamsApp.created_at.desc())
    )
    teams_app = (await session.exec(stmt)).first()
    if not teams_app:
        raise HTTPException(status_code=404, detail="No Teams publication found for this agent")

    return TeamsAppStatusResponse(
        agent_id=agent_id,
        status=teams_app.status.value,
        teams_external_id=teams_app.teams_app_external_id,
        display_name=teams_app.display_name,
        published_at=teams_app.published_at,
        last_error=teams_app.last_error,
        has_own_bot=bool(teams_app.bot_app_secret),
        bot_app_id=teams_app.bot_app_id,
    )


@router.post("/sync/{agent_id}", response_model=TeamsPublishResponse)
async def sync_teams_app(
    agent_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> TeamsPublishResponse:
    """Re-sync an agent's Teams app (re-generate manifest and update in catalog)."""
    stmt = (
        select(TeamsApp)
        .where(TeamsApp.agent_id == agent_id)
        .where(TeamsApp.status == TeamsPublishStatusEnum.PUBLISHED)
    )
    teams_app = (await session.exec(stmt)).first()
    if not teams_app:
        raise HTTPException(status_code=404, detail="Agent is not published to Teams")

    agent = await session.get(Agent, agent_id)
    if not agent or agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You don't own this agent")

    try:
        from agentcore.services.teams.manifest import create_teams_app_package, generate_icons, generate_manifest

        teams_service = get_teams_service()
        base_url = teams_service.settings.teams_bot_endpoint_base or os.getenv(
            "LOCALHOST_TEAMS_BOT_BASE_URL",
            "https://localhost:7860",
        )

        parts = teams_app.manifest_version.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        new_version = ".".join(parts)

        manifest = generate_manifest(
            agent=agent,
            bot_app_id=teams_app.bot_app_id,
            display_name=teams_app.display_name,
            short_description=teams_app.short_description,
            base_url=base_url,
            version=new_version,
        )
        color_icon, outline_icon = generate_icons(teams_app.display_name)
        zip_package = create_teams_app_package(manifest, color_icon, outline_icon)

        graph_client = await teams_service.get_graph_client_for_user(str(current_user.id))
        if not graph_client:
            raise HTTPException(status_code=401, detail="Connect your Microsoft account first.")

        await graph_client.update_app_in_catalog(teams_app.teams_app_external_id, zip_package)

        updated_tokens = graph_client.get_token_data()
        await teams_service.store_user_tokens(str(current_user.id), updated_tokens)

        from datetime import datetime, timezone

        teams_app.manifest_version = new_version
        teams_app.manifest_data = manifest
        teams_app.updated_at = datetime.now(timezone.utc)
        session.add(teams_app)
        await session.commit()

        logger.info(f"Agent {agent_id} Teams app synced to version {new_version}")

        return TeamsPublishResponse(
            teams_app_id=teams_app.id,
            agent_id=agent_id,
            status=TeamsPublishStatusEnum.PUBLISHED.value,
            teams_external_id=teams_app.teams_app_external_id,
            message=f"Successfully synced Teams app to version {new_version}",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to sync Teams app for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync: {e!s}") from e


@router.get("/apps", response_model=list[TeamsAppStatusResponse])
async def list_teams_apps(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[TeamsAppStatusResponse]:
    """List all agents published to Teams by the current user."""
    stmt = (
        select(TeamsApp)
        .where(TeamsApp.published_by == current_user.id)
        .where(TeamsApp.status != TeamsPublishStatusEnum.UNPUBLISHED)
        .order_by(TeamsApp.created_at.desc())
    )
    apps = (await session.exec(stmt)).all()

    return [
        TeamsAppStatusResponse(
            agent_id=app.agent_id,
            status=app.status.value,
            teams_external_id=app.teams_app_external_id,
            display_name=app.display_name,
            published_at=app.published_at,
            last_error=app.last_error,
            has_own_bot=bool(app.bot_app_secret),
            bot_app_id=app.bot_app_id,
        )
        for app in apps
    ]


@router.get("/health")
async def teams_health() -> dict:
    """Health check for Teams integration."""
    teams_service = get_teams_service()

    result = {
        "configured": teams_service.is_configured,
        "bot_app_id": teams_service.settings.teams_bot_app_id or "not set",
        "endpoint_base": teams_service.settings.teams_bot_endpoint_base or "not set",
    }

    if teams_service.is_configured:
        try:
            teams_service.get_adapter()
            result["adapter"] = "ok"
        except Exception as e:
            result["adapter"] = f"error: {e!s}"

        try:
            teams_service.get_graph_client()
            result["graph_api"] = "configured (delegated auth)"
        except Exception as e:
            result["graph_api"] = f"error: {e!s}"

    return result
