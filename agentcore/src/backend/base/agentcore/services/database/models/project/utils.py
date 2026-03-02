from uuid import UUID

from sqlmodel import and_, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.initial_setup.setup import get_or_create_default_folder
from agentcore.services.database.models.agent.model import Agent

from .constants import DEFAULT_FOLDER_DESCRIPTION, DEFAULT_FOLDER_NAME
from .model import Folder


async def create_default_folder_if_it_doesnt_exist(session: AsyncSession, user_id: UUID):
    stmt = select(Folder).where(Folder.user_id == user_id)
    folder = (await session.exec(stmt)).first()
    if not folder:
        folder = Folder(
            name=DEFAULT_FOLDER_NAME,
            user_id=user_id,
            description=DEFAULT_FOLDER_DESCRIPTION,
        )
        session.add(folder)
        await session.commit()
        await session.refresh(folder)
        await session.exec(
            update(Agent)
            .where(
                and_(
                    Agent.project_id is None,
                    Agent.user_id == user_id,
                )
            )
            .values(project_id=folder.id)
        )
        await session.commit()
    return folder


async def get_default_project_id(session: AsyncSession, user_id: UUID):
    folder = (
        await session.exec(select(Folder).where(Folder.name == DEFAULT_FOLDER_NAME, Folder.user_id == user_id))
    ).first()
    if not folder:
        folder = await get_or_create_default_folder(session, user_id)
    return folder.id
