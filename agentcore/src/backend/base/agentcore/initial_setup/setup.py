from uuid import UUID

from loguru import logger
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.database.models.folder.constants import DEFAULT_FOLDER_DESCRIPTION, DEFAULT_FOLDER_NAME
from agentcore.services.database.models.folder.model import Folder


async def get_or_create_default_folder(session: AsyncSession, user_id: UUID) -> Folder:
    folder = (
        await session.exec(select(Folder).where(Folder.name == DEFAULT_FOLDER_NAME, Folder.user_id == user_id))
    ).first()
    if not folder:
        folder = Folder(
            name=DEFAULT_FOLDER_NAME,
            user_id=user_id,
            description=DEFAULT_FOLDER_DESCRIPTION,
        )
        session.add(folder)
        await session.commit()
        await session.refresh(folder)
    return folder