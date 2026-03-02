# Path: src/backend/base/agentcore/services/teams/service.py
"""TeamsService - manages Bot Framework adapter, conversation store, and Graph API client."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from loguru import logger

from agentcore.services.base import Service
from agentcore.services.teams.conversation_store import ConversationStore

if TYPE_CHECKING:
    from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings

    from agentcore.services.teams.bot_handler import AgentCoreTeamsBot
    from agentcore.services.teams.graph_api import TeamsGraphAPIClient


class TeamsService(Service):
    name = "teams_service"

    # Redis key prefix for storing delegated Graph API tokens per user
    TOKEN_PREFIX = "teams:graph_token:"
    TOKEN_TTL = 86400 * 30  # 30 days (refresh token lifetime)

    def __init__(self, settings_service):
        super().__init__()
        self._settings_service = settings_service
        self._adapter: BotFrameworkAdapter | None = None
        self._adapter_cache: dict[str, BotFrameworkAdapter] = {}
        self._bot: AgentCoreTeamsBot | None = None
        self._conversation_store: ConversationStore | None = None

    @property
    def settings(self):
        return self._settings_service.settings

    @property
    def is_configured(self) -> bool:
        """Check if Teams integration is configured."""
        return bool(self.settings.teams_bot_app_id and self.settings.teams_bot_app_secret)

    def _get_tenant_id(self) -> str:
        """Get the Teams tenant ID."""
        tenant_id = self.settings.teams_bot_tenant_id
        if not tenant_id:
            tenant_id = os.getenv("AZURE_TENANT_ID")
        if not tenant_id:
            msg = "No tenant ID configured. Set TEAMS_BOT_TENANT_ID or AZURE_TENANT_ID."
            raise ValueError(msg)
        return tenant_id

    def _get_graph_client_id(self) -> str:
        """Get the client ID for Graph API (may differ from bot app ID)."""
        return self.settings.teams_graph_client_id or self.settings.teams_bot_app_id

    def _get_graph_client_secret(self) -> str:
        """Get the client secret for Graph API."""
        return self.settings.teams_graph_client_secret or self.settings.teams_bot_app_secret

    def get_redirect_uri(self) -> str:
        """Get the OAuth redirect URI for Graph API."""
        if self.settings.teams_graph_redirect_uri:
            return self.settings.teams_graph_redirect_uri
        return os.getenv(
            "LOCALHOST_TEAMS_GRAPH_REDIRECT_URI",
            f"http://{os.getenv('LOCALHOST_HOST', 'localhost')}:{os.getenv('BACKEND_PORT', '7860')}/api/teams/oauth/callback",
        )

    def get_adapter(
        self,
        bot_app_id: str | None = None,
        bot_app_secret: str | None = None,
    ) -> BotFrameworkAdapter:
        """Get or create a Bot Framework adapter.

        If bot_app_id is provided and differs from the global one, creates/returns
        a cached per-agent adapter. Otherwise returns the default shared adapter.
        """
        global_app_id = self.settings.teams_bot_app_id

        # Per-agent adapter
        if bot_app_id and bot_app_id != global_app_id:
            if bot_app_id not in self._adapter_cache:
                from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext

                if not bot_app_secret:
                    msg = f"bot_app_secret required for per-agent adapter (app_id={bot_app_id})"
                    raise ValueError(msg)

                adapter_settings = BotFrameworkAdapterSettings(
                    app_id=bot_app_id,
                    app_password=bot_app_secret,
                    channel_auth_tenant=self._get_tenant_id(),
                )
                adapter = BotFrameworkAdapter(adapter_settings)

                async def _on_turn_error(context: TurnContext, error: Exception):
                    logger.exception(f"Bot adapter on_turn_error (app_id={bot_app_id}): {error}")
                    try:
                        await context.send_activity("An error occurred while processing your message.")
                    except Exception:
                        logger.error("Failed to send error message to user")

                adapter.on_turn_error = _on_turn_error
                self._adapter_cache[bot_app_id] = adapter
                logger.info(f"Created per-agent Bot Framework adapter for app_id={bot_app_id}")

            return self._adapter_cache[bot_app_id]

        # Default shared adapter
        if self._adapter is None:
            from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext

            if not self.is_configured:
                msg = "Teams bot is not configured. Set TEAMS_BOT_APP_ID and TEAMS_BOT_APP_SECRET."
                raise ValueError(msg)

            adapter_settings = BotFrameworkAdapterSettings(
                app_id=self.settings.teams_bot_app_id,
                app_password=self.settings.teams_bot_app_secret,
                channel_auth_tenant=self._get_tenant_id(),
            )
            self._adapter = BotFrameworkAdapter(adapter_settings)

            async def _on_turn_error(context: TurnContext, error: Exception):
                logger.exception(f"Bot adapter on_turn_error: {error}")
                try:
                    await context.send_activity("An error occurred while processing your message.")
                except Exception:
                    logger.error("Failed to send error message to user")

            self._adapter.on_turn_error = _on_turn_error
            logger.info("Bot Framework adapter initialized with error handler")

        return self._adapter

    def get_bot(self) -> AgentCoreTeamsBot:
        """Get or create the bot handler."""
        if self._bot is None:
            from agentcore.services.teams.bot_handler import AgentCoreTeamsBot

            self._bot = AgentCoreTeamsBot(
                conversation_store=self.get_conversation_store(),
            )
            logger.info("AgentCore Teams bot handler initialized")

        return self._bot

    def get_conversation_store(self) -> ConversationStore:
        """Get or create the conversation store."""
        if self._conversation_store is None:
            cache_service = None
            try:
                from agentcore.services.deps import get_cache_service

                cache_service = get_cache_service()
            except Exception:
                logger.warning("Cache service unavailable, using in-memory conversation store")

            self._conversation_store = ConversationStore(cache_service=cache_service)
            logger.info("Teams conversation store initialized")

        return self._conversation_store

    def _get_cache_service(self):
        """Get the cache service for token storage."""
        try:
            from agentcore.services.deps import get_cache_service
            return get_cache_service()
        except Exception:
            return None

    async def store_user_tokens(self, user_id: str, token_data: dict) -> None:
        """Store Graph API tokens for a user in Redis."""
        key = f"{self.TOKEN_PREFIX}{user_id}"
        data = json.dumps(token_data)

        cache = self._get_cache_service()
        if cache:
            try:
                await cache.set(key, data, expiration=self.TOKEN_TTL)
                logger.info(f"Stored Graph API tokens for user {user_id}")
                return
            except Exception:
                logger.warning(f"Failed to store tokens in Redis for user {user_id}")

        # Fallback: store in-memory (lost on restart, but works for dev)
        if not hasattr(self, "_token_fallback"):
            self._token_fallback = {}
        self._token_fallback[user_id] = token_data

    async def get_user_tokens(self, user_id: str) -> dict | None:
        """Retrieve stored Graph API tokens for a user."""
        key = f"{self.TOKEN_PREFIX}{user_id}"

        cache = self._get_cache_service()
        if cache:
            try:
                data = await cache.get(key)
                if data:
                    return json.loads(data)
            except Exception:
                logger.warning(f"Failed to get tokens from Redis for user {user_id}")

        # Fallback
        if hasattr(self, "_token_fallback"):
            return self._token_fallback.get(user_id)
        return None

    async def delete_user_tokens(self, user_id: str) -> None:
        """Remove stored Graph API tokens for a user."""
        key = f"{self.TOKEN_PREFIX}{user_id}"

        cache = self._get_cache_service()
        if cache:
            try:
                await cache.delete(key)
            except Exception:
                pass

        if hasattr(self, "_token_fallback"):
            self._token_fallback.pop(user_id, None)

    def get_graph_client(
        self,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_expires_at: float | None = None,
    ) -> TeamsGraphAPIClient:
        """Create a Graph API client with delegated tokens.

        Each call creates a new instance since tokens are per-user.
        """
        from agentcore.services.teams.graph_api import TeamsGraphAPIClient

        tenant_id = self._get_tenant_id()
        client_id = self._get_graph_client_id()
        client_secret = self._get_graph_client_secret()

        if not all([tenant_id, client_id, client_secret]):
            msg = (
                "Graph API is not configured. Set TEAMS_GRAPH_CLIENT_ID, "
                "TEAMS_GRAPH_CLIENT_SECRET, and TEAMS_BOT_TENANT_ID (or AZURE_TENANT_ID)."
            )
            raise ValueError(msg)

        graph_client = TeamsGraphAPIClient(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at,
        )
        logger.info("Microsoft Graph API client initialized")
        return graph_client

    async def get_graph_client_for_user(self, user_id: str) -> TeamsGraphAPIClient | None:
        """Get a Graph API client with the user's stored delegated tokens.

        Returns None if the user hasn't connected their Microsoft account.
        """
        tokens = await self.get_user_tokens(user_id)
        if not tokens:
            return None

        return self.get_graph_client(
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_expires_at=tokens.get("expires_at"),
        )
