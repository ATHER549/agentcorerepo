# Path: src/backend/base/agentcore/services/teams/bot_handler.py
"""Bot Framework activity handler for routing Teams messages to agentcore flows.

Follows the same pattern as api/a2a.py handle_message_send() for executing flows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from botbuilder.core import ActivityHandler, CardFactory, TurnContext
from botbuilder.schema import Activity, ActivityTypes, Attachment
from loguru import logger

from agentcore.services.teams.adaptive_cards import (
    error_card,
    text_response_card,
    welcome_card,
)

if TYPE_CHECKING:
    from agentcore.services.teams.conversation_store import ConversationStore


class AgentCoreTeamsBot(ActivityHandler):
    """Handles incoming Bot Framework activities and routes them to agentcore flows.

    Translates Bot Framework activities into agentcore flow executions,
    following the same pattern as the A2A protocol handler.
    """

    def __init__(self, conversation_store: ConversationStore):
        super().__init__()
        self.conversation_store = conversation_store

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        """Handle incoming message from Teams user."""
        logger.info("=== on_message_activity called ===")
        conversation_id = turn_context.activity.conversation.id
        user_text = turn_context.activity.text or ""
        user_name = turn_context.activity.from_property.name if turn_context.activity.from_property else None

        logger.info(f"Teams message received: conversation={conversation_id}, user={user_name}, text={user_text[:100]}")

        # Look up which agent/flow this conversation is mapped to
        state = await self.conversation_store.get_mapping(conversation_id)

        if not state:
            logger.info(f"No existing mapping for conversation {conversation_id}, resolving agent...")
            agent_id = await self._resolve_agent_from_channel_data(turn_context)
            if agent_id:
                state = await self.conversation_store.set_mapping(
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    user_display_name=user_name,
                    user_aad_object_id=self._get_aad_object_id(turn_context),
                )
            else:
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        text="Sorry, I couldn't determine which agent to route your message to. "
                        "Please reinstall the app or contact your administrator.",
                    )
                )
                return

        logger.info(f"Agent resolved: agent_id={state.agent_id}, session_id={state.session_id}")

        # Execute the flow
        try:
            output_text = await self._execute_flow(
                agent_id=state.agent_id,
                session_id=state.session_id,
                input_text=user_text,
            )

            # Send response as Adaptive Card
            agent_name = await self._get_agent_name(state.agent_id)
            card = text_response_card(agent_name or "AgentCore", output_text)
            attachment = CardFactory.adaptive_card(card)

            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    attachments=[attachment],
                )
            )

        except Exception as e:
            logger.exception(f"Error executing flow for conversation {conversation_id}: {e}")
            agent_name = await self._get_agent_name(state.agent_id)
            card = error_card(
                agent_name or "AgentCore",
                f"An error occurred while processing your request: {e!s}",
            )
            attachment = CardFactory.adaptive_card(card)
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    attachments=[attachment],
                )
            )

    async def on_conversation_update_activity(self, turn_context: TurnContext) -> None:
        """Handle conversation update events (e.g., bot added to conversation)."""
        await self._handle_members_added(turn_context)

    async def on_members_added_activity(self, members_added, turn_context: TurnContext) -> None:
        """Send welcome message when the bot is added to a conversation."""
        bot_id = turn_context.activity.recipient.id if turn_context.activity.recipient else None

        for member in members_added:
            if member.id == bot_id:
                # Bot was added - set up conversation mapping and send welcome
                conversation_id = turn_context.activity.conversation.id
                agent_id = await self._resolve_agent_from_channel_data(turn_context)

                if agent_id:
                    user_name = (
                        turn_context.activity.from_property.name if turn_context.activity.from_property else None
                    )
                    await self.conversation_store.set_mapping(
                        conversation_id=conversation_id,
                        agent_id=agent_id,
                        user_display_name=user_name,
                        user_aad_object_id=self._get_aad_object_id(turn_context),
                    )

                    agent_name = await self._get_agent_name(agent_id)
                    agent_desc = await self._get_agent_description(agent_id)
                    card = welcome_card(agent_name or "AgentCore", agent_desc)
                    attachment = CardFactory.adaptive_card(card)

                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            attachments=[attachment],
                        )
                    )
                else:
                    await turn_context.send_activity(
                        Activity(
                            type=ActivityTypes.message,
                            text="Welcome! This bot is connected to AgentCore. Send a message to get started.",
                        )
                    )

    async def _execute_flow(self, agent_id: str, session_id: str, input_text: str) -> str:
        """Execute an agentcore flow and return the output text.

        Follows the same pattern as a2a.py handle_message_send().
        """
        logger.info(f"=== _execute_flow: agent={agent_id}, session={session_id}, input={input_text[:50]} ===")
        from agentcore.api.a2a import _extract_output_text, _prebuild_dependencies
        from agentcore.helpers.agent import load_agent, run_agent

        # Look up the agent's owner user_id from the database
        user_id = await self._get_agent_user_id(agent_id)
        if not user_id:
            return "Agent not found."

        graph = await load_agent(user_id, agent_id=agent_id)
        await graph.initialize_run()
        await _prebuild_dependencies(graph, user_id, input_text)

        logger.info(f"Running agent flow for agent_id={agent_id}...")
        run_outputs = await run_agent(
            inputs={"input_value": input_text},
            graph=graph,
            user_id=user_id,
            session_id=session_id,
        )

        output_text = _extract_output_text(run_outputs)
        logger.info(f"Flow completed. Output length: {len(output_text) if output_text else 0}")
        return output_text or "No output generated."

    async def _resolve_agent_from_channel_data(self, turn_context: TurnContext) -> str | None:
        """Resolve agent_id for this conversation.

        Priority:
        1. _agentcore_agent_id from channel_data (set by /messages endpoint via JWT appId lookup)
        2. Database query for published agents (fallback for shared-bot mode)
        """
        # Check for agent_id hint from JWT-based routing
        if turn_context and turn_context.activity and turn_context.activity.channel_data:
            hint = turn_context.activity.channel_data.get("_agentcore_agent_id")
            if hint:
                logger.info(f"Agent resolved from JWT appId routing: {hint}")
                return hint

        # Fallback: query database for published agents
        try:
            from sqlmodel import select

            from agentcore.services.database.models.teams_app.model import TeamsApp, TeamsPublishStatusEnum
            from agentcore.services.deps import session_scope

            async with session_scope() as session:
                stmt = (
                    select(TeamsApp)
                    .where(TeamsApp.status == TeamsPublishStatusEnum.PUBLISHED)
                    .order_by(TeamsApp.created_at.desc())
                )
                results = (await session.exec(stmt)).all()

                if len(results) == 1:
                    logger.info(f"Resolved single published agent: {results[0].agent_id}")
                    return str(results[0].agent_id)
                elif len(results) > 1:
                    logger.warning(f"Multiple published Teams agents found ({len(results)}), using most recent")
                    return str(results[0].agent_id)
                else:
                    logger.warning("No published Teams agents found in database")
                    return None
        except Exception:
            logger.exception("Error resolving agent from database")
            return None

    async def _get_agent_name(self, agent_id: str) -> str | None:
        """Get agent name from database."""
        try:
            from uuid import UUID

            from agentcore.services.database.models.agent.model import Agent
            from agentcore.services.deps import session_scope

            async with session_scope() as session:
                agent = await session.get(Agent, UUID(agent_id))
                return agent.name if agent else None
        except Exception:
            logger.exception(f"Error getting agent name for {agent_id}")
            return None

    async def _get_agent_user_id(self, agent_id: str) -> str | None:
        """Get agent owner's user_id from database."""
        try:
            from uuid import UUID

            from agentcore.services.database.models.agent.model import Agent
            from agentcore.services.deps import session_scope

            async with session_scope() as session:
                agent = await session.get(Agent, UUID(agent_id))
                return str(agent.user_id) if agent else None
        except Exception:
            logger.exception(f"Error getting agent user_id for {agent_id}")
            return None

    async def _get_agent_description(self, agent_id: str) -> str | None:
        """Get agent description from database."""
        try:
            from uuid import UUID

            from agentcore.services.database.models.agent.model import Agent
            from agentcore.services.deps import session_scope

            async with session_scope() as session:
                agent = await session.get(Agent, UUID(agent_id))
                return agent.description if agent else None
        except Exception:
            logger.exception(f"Error getting agent description for {agent_id}")
            return None

    def _get_aad_object_id(self, turn_context: TurnContext) -> str | None:
        """Extract Azure AD object ID from the activity."""
        if turn_context.activity.from_property:
            return turn_context.activity.from_property.aad_object_id
        return None

    async def _handle_members_added(self, turn_context: TurnContext) -> None:
        """Process members added in conversation update."""
        if turn_context.activity.members_added:
            await self.on_members_added_activity(
                turn_context.activity.members_added,
                turn_context,
            )
