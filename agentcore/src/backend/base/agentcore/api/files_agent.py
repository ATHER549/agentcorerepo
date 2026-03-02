import hashlib
from datetime import datetime, timezone
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.api.v1_schemas import UploadFileResponse
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.deps import get_settings_service, get_storage_service
from agentcore.services.settings.service import SettingsService
from agentcore.services.storage.service import StorageService
from agentcore.services.storage.utils import build_content_type_from_extension

router = APIRouter(tags=["Files"], prefix="/files")


# Create dep that gets the agent_id from the request
# then finds it in the database and returns it while
# using the current user as the owner
async def get_agent(
    agent_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
):
    # AttributeError: 'SelectOfScalar' object has no attribute 'first'
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You don't have access to this agent")
    return agent


@router.post("/upload/{agent_id}", status_code=HTTPStatus.CREATED)
async def upload_file(
    *,
    file: UploadFile,
    agent: Annotated[Agent, Depends(get_agent)],
    current_user: CurrentActiveUser,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
) -> UploadFileResponse:
    try:
        max_file_size_upload = settings_service.settings.max_file_size_upload
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    if file.size > max_file_size_upload * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"File size is larger than the maximum file size {max_file_size_upload}MB."
        )

    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You don't have access to this agent")

    try:
        file_content = await file.read()
        timestamp = datetime.now(tz=timezone.utc).astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        file_name = file.filename or hashlib.sha256(file_content).hexdigest()
        full_file_name = f"{timestamp}_{file_name}"
        folder = str(agent.id)
        await storage_service.save_file(agent_id=folder, file_name=full_file_name, data=file_content)
        return UploadFileResponse(agent_id=str(agent.id), file_path=f"{folder}/{full_file_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/download/{agent_id}/{file_name}")
async def download_file(
    file_name: str, agent_id: UUID, storage_service: Annotated[StorageService, Depends(get_storage_service)]
):
    agent_id_str = str(agent_id)
    extension = file_name.split(".")[-1]

    if not extension:
        raise HTTPException(status_code=500, detail=f"Extension not found for file {file_name}")
    try:
        content_type = build_content_type_from_extension(extension)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    if not content_type:
        raise HTTPException(status_code=500, detail=f"Content type not found for extension {extension}")

    try:
        file_content = await storage_service.get_file(agent_id=agent_id_str, file_name=file_name)
        headers = {
            "Content-Disposition": f"attachment; filename={file_name} filename*=UTF-8''{file_name}",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(file_content)),
        }
        return StreamingResponse(BytesIO(file_content), media_type=content_type, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/images/{agent_id}/{file_name}")
async def download_image(file_name: str, agent_id: UUID):
    storage_service = get_storage_service()
    extension = file_name.split(".")[-1]
    agent_id_str = str(agent_id)

    if not extension:
        raise HTTPException(status_code=500, detail=f"Extension not found for file {file_name}")
    try:
        content_type = build_content_type_from_extension(extension)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    if not content_type:
        raise HTTPException(status_code=500, detail=f"Content type not found for extension {extension}")
    if not content_type.startswith("image"):
        raise HTTPException(status_code=500, detail=f"Content type {content_type} is not an image")

    try:
        file_content = await storage_service.get_file(agent_id=agent_id_str, file_name=file_name)
        return StreamingResponse(BytesIO(file_content), media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/profile_pictures/{folder_name}/{file_name}")
async def download_profile_picture(
    folder_name: str,
    file_name: str,
):
    try:
        storage_service = get_storage_service()
        extension = file_name.split(".")[-1]
        config_dir = storage_service.settings_service.settings.config_dir
        config_path = Path(config_dir)  # type: ignore[arg-type]
        folder_path = config_path / "profile_pictures" / folder_name
        content_type = build_content_type_from_extension(extension)
        file_content = await storage_service.get_file(agent_id=folder_path, file_name=file_name)  # type: ignore[arg-type]
        return StreamingResponse(BytesIO(file_content), media_type=content_type)

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Profile picture not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/profile_pictures/list")
async def list_profile_pictures():
    try:
        storage_service = get_storage_service()
        config_dir = storage_service.settings_service.settings.config_dir
        config_path = Path(config_dir)  # type: ignore[arg-type]

        people_path = config_path / "profile_pictures/People"
        space_path = config_path / "profile_pictures/Space"

        people = await storage_service.list_files(agent_id=people_path)  # type: ignore[arg-type]
        space = await storage_service.list_files(agent_id=space_path)  # type: ignore[arg-type]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    files = [f"People/{i}" for i in people]
    files += [f"Space/{i}" for i in space]

    return {"files": files}


@router.get("/list/{agent_id}")
async def list_files(
    agent: Annotated[Agent, Depends(get_agent)],
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    try:
        files = await storage_service.list_files(agent_id=str(agent.id))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"files": files}


@router.delete("/delete/{agent_id}/{file_name}")
async def delete_file(
    file_name: str,
    agent: Annotated[Agent, Depends(get_agent)],
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    try:
        await storage_service.delete_file(agent_id=str(agent.id), file_name=file_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"message": f"File {file_name} deleted successfully"}
