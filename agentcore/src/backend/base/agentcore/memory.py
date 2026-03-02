import asyncio
import json
from collections.abc import Sequence
from datetime import timezone
from uuid import UUID

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage
from loguru import logger
from sqlalchemy import delete
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.schema.message import Message
from agentcore.services.database.models.conversation.model import ConversationRead, ConversationTable
from agentcore.services.deps import session_scope
from agentcore.utils.async_helpers import run_until_complete


def _get_variable_query(
    sender: str | None = None,
    sender_name: str | None = None,
    session_id: str | UUID | None = None,
    order_by: str | None = "timestamp",
    order: str | None = "DESC",
    agent_id: UUID | None = None,
    limit: int | None = None,
):
    stmt = select(ConversationTable).where(ConversationTable.error == False)  # noqa: E712
    if sender:
        stmt = stmt.where(ConversationTable.sender == sender)
    if sender_name:
        stmt = stmt.where(ConversationTable.sender_name == sender_name)
    if session_id:
        stmt = stmt.where(ConversationTable.session_id == session_id)
    if agent_id:
        stmt = stmt.where(ConversationTable.agent_id == agent_id)
    if order_by:
        col = getattr(ConversationTable, order_by).desc() if order == "DESC" else getattr(ConversationTable, order_by).asc()
        stmt = stmt.order_by(col)
    if limit:
        stmt = stmt.limit(limit)
    return stmt


def get_messages(
    sender: str | None = None,
    sender_name: str | None = None,
    session_id: str | UUID | None = None,
    order_by: str | None = "timestamp",
    order: str | None = "DESC",
    agent_id: UUID | None = None,
    limit: int | None = None,
) -> list[Message]:
    """Retrieves messages from the monitor service based on the provided filters.
    """
    return run_until_complete(aget_messages(sender, sender_name, session_id, order_by, order, agent_id, limit))


async def aget_messages(
    sender: str | None = None,
    sender_name: str | None = None,
    session_id: str | UUID | None = None,
    order_by: str | None = "timestamp",
    order: str | None = "DESC",
    agent_id: UUID | None = None,
    limit: int | None = None,
) -> list[Message]:
    """Retrieves messages from the monitor service based on the provided filters.

    Args:
        sender (Optional[str]): The sender of the messages (e.g., "Machine" or "User")
        sender_name (Optional[str]): The name of the sender.
        session_id (Optional[str]): The session ID associated with the messages.
        order_by (Optional[str]): The field to order the messages by. Defaults to "timestamp".
        order (Optional[str]): The order in which to retrieve the messages. Defaults to "DESC".
        agent_id (Optional[UUID]): The Agent ID associated with the messages.
        limit (Optional[int]): The maximum number of messages to retrieve.

    Returns:
        List[Data]: A list of Data objects representing the retrieved messages.
    """
    async with session_scope() as session:
        stmt = _get_variable_query(sender, sender_name, session_id, order_by, order, agent_id, limit)
        messages = await session.exec(stmt)
        return [await Message.create(**d.model_dump()) for d in messages]


def add_messages(messages: Message | list[Message], agent_id: str | UUID | None = None):
   
    return run_until_complete(aadd_messages(messages, agent_id=agent_id))


async def aadd_messages(messages: Message | list[Message], agent_id: str | UUID | None = None):
    """Add a message to the monitor service."""
    if not isinstance(messages, list):
        messages = [messages]

    if not all(isinstance(message, Message) for message in messages):
        types = ", ".join([str(type(message)) for message in messages])
        msg = f"The messages must be instances of Message. Found: {types}"
        raise ValueError(msg)

    try:
        messages_models = [ConversationTable.from_message(msg, agent_id=agent_id) for msg in messages]
        async with session_scope() as session:
            messages_models = await aadd_messagetables(messages_models, session)
        result_messages = []
        for model in messages_models:
            dump = model.model_dump()
            result_messages.append(await Message.create(**dump))
        return result_messages
    except Exception as e:
        logger.exception(e)
        raise


async def aupdate_messages(messages: Message | list[Message]) -> list[Message]:
    if not isinstance(messages, list):
        messages = [messages]

    async with session_scope() as session:
        updated_messages: list[ConversationTable] = []
        for message in messages:
            msg = await session.get(ConversationTable, message.id)
            if msg:
                # CRITICAL: Save the original timestamp from database BEFORE any update
                # This is the authoritative creation time that must never change
                original_timestamp = msg.timestamp
                
                # Exclude timestamp from updates to preserve the original creation time
                msg = msg.sqlmodel_update(message.model_dump(exclude_unset=True, exclude_none=True, exclude={"timestamp"}))
                
                # CRITICAL: Force restore the original timestamp after sqlmodel_update
                msg.timestamp = original_timestamp
                
                # Convert agent_id to UUID if it's a string
                if msg.agent_id and isinstance(msg.agent_id, str):
                    msg.agent_id = UUID(msg.agent_id)
                session.add(msg)
                await session.commit()
                await session.refresh(msg)
                updated_messages.append(msg)
            else:
                logger.debug(f"Message with id {message.id} not found, skipping update")
        return [ConversationRead.model_validate(message, from_attributes=True) for message in updated_messages]


async def aadd_messagetables(messages: list[ConversationTable], session: AsyncSession):
    try:
        try:
            for message in messages:
                session.add(message)
            await session.commit()
        except asyncio.CancelledError:
            await session.rollback()
            return await aadd_messagetables(messages, session)
        for message in messages:
            await session.refresh(message)
    except asyncio.CancelledError as e:
        logger.exception(e)
        error_msg = "Operation cancelled"
        raise ValueError(error_msg) from e
    except Exception as e:
        logger.exception(e)
        raise

    new_messages = []
    for msg in messages:
        msg.properties = json.loads(msg.properties) if isinstance(msg.properties, str) else msg.properties  # type: ignore[arg-type]
        msg.content_blocks = [json.loads(j) if isinstance(j, str) else j for j in msg.content_blocks]  # type: ignore[arg-type]
        msg.category = msg.category or ""
        new_messages.append(msg)

    return [ConversationRead.model_validate(message, from_attributes=True) for message in new_messages]


def delete_messages(session_id: str) -> None:
    return run_until_complete(adelete_messages(session_id))


async def adelete_messages(session_id: str) -> None:
    """Delete messages from the monitor service based on the provided session ID.

    Args:
        session_id (str): The session ID associated with the messages to delete.
    """
    async with session_scope() as session:
        stmt = (
            delete(ConversationTable)
            .where(col(ConversationTable.session_id) == session_id)
            .execution_options(synchronize_session="fetch")
        )
        await session.exec(stmt)


async def delete_message(id_: str) -> None:
    """Delete a message from the monitor service based on the provided ID.

    Args:
        id_ (str): The ID of the message to delete.
    """
    async with session_scope() as session:
        message = await session.get(ConversationTable, id_)
        if message:
            await session.delete(message)
            await session.commit()


def store_message(
    message: Message,
    agent_id: str | UUID | None = None,
) -> list[Message]:

    return run_until_complete(astore_message(message, agent_id=agent_id))


async def astore_message(
    message: Message,
    agent_id: str | UUID | None = None,
) -> list[Message]:
    """Stores a message in the memory.

    Args:
        message (Message): The message to store.
        agent_id (Optional[str]): The agent ID associated with the message.
            When running from the CustomComponent you can access this using `self.graph.agent_id`.

    Returns:
        List[Message]: A list of data containing the stored message.

    Raises:
        ValueError: If any of the required parameters (session_id, sender, sender_name) is not provided.
    """
    if not message:
        logger.warning("No message provided.")
        return []

    if not message.session_id or not message.sender or not message.sender_name:
        msg = (
            f"All of session_id, sender, and sender_name must be provided. Session ID: {message.session_id},"
            f" Sender: {message.sender}, Sender Name: {message.sender_name}"
        )
        raise ValueError(msg)
    
    msg_id = message.data.get("id") if hasattr(message, "data") else None
    if msg_id:
        # if message has an id and exists in the database, update it
        result = await aupdate_messages([message])
        if result:
            return result
        # Message not in DB yet — fall through to insert
    if agent_id and not isinstance(agent_id, UUID):
        agent_id = UUID(agent_id)
    return await aadd_messages([message], agent_id=agent_id)


class LCBuiltinChatMemory(BaseChatMessageHistory):

    def __init__(
        self,
        agent_id: str,
        session_id: str,
    ) -> None:
        self.agent_id = agent_id
        self.session_id = session_id

    @property
    def messages(self) -> list[BaseMessage]:
        messages = get_messages(
            session_id=self.session_id,
        )
        return [m.to_lc_message() for m in messages if not m.error]  # Exclude error messages

    async def aget_messages(self) -> list[BaseMessage]:
        messages = await aget_messages(
            session_id=self.session_id,
        )
        return [m.to_lc_message() for m in messages if not m.error]  # Exclude error messages

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        for lc_message in messages:
            message = Message.from_lc_message(lc_message)
            message.session_id = self.session_id
            store_message(message, agent_id=self.agent_id)

    async def aadd_messages(self, messages: Sequence[BaseMessage]) -> None:
        for lc_message in messages:
            message = Message.from_lc_message(lc_message)
            message.session_id = self.session_id
            await astore_message(message, agent_id=self.agent_id)

    def clear(self) -> None:
        delete_messages(self.session_id)

    async def aclear(self) -> None:
        await adelete_messages(self.session_id)
