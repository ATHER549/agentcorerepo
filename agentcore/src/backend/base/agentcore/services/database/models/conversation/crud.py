from uuid import UUID

from agentcore.services.database.models.conversation.model import ConversationTable, ConversationUpdate
from agentcore.services.deps import session_scope
from agentcore.utils.async_helpers import run_until_complete


async def _update_message(message_id: UUID | str, message: ConversationUpdate | dict):
    if not isinstance(message, ConversationUpdate):
        message = ConversationUpdate(**message)
    async with session_scope() as session:
        db_message = await session.get(ConversationTable, message_id)
        if not db_message:
            msg = "Message not found"
            raise ValueError(msg)
        message_dict = message.model_dump(exclude_unset=True, exclude_none=True)
        db_message.sqlmodel_update(message_dict)
        session.add(db_message)
        await session.commit()
        await session.refresh(db_message)
        return db_message


def update_message(message_id: UUID | str, message: ConversationUpdate | dict):
    return run_until_complete(_update_message(message_id, message))
