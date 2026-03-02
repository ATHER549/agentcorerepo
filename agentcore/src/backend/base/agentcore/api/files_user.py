import io
import re
import uuid
import zipfile
from collections.abc import AsyncGenerator, AsyncIterable
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlmodel import col, select
from sqlalchemy import or_

from agentcore.api.schemas import UploadFileResponse
from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.file.model import File as UserFile
from agentcore.services.database.models.knowledge_base.model import KBVisibilityEnum, KnowledgeBase
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.deps import get_settings_service, get_storage_service
from agentcore.services.storage.service import StorageService


router = APIRouter(tags=["Files"], prefix="/files")

# Set the static name of the MCP servers file
MCP_SERVERS_FILE = "_mcp_servers"
SAMPLE_DATA_DIR = Path(__file__).parent / "sample_data"


async def _build_file_visibility_filters(session: DbSession, current_user: CurrentActiveUser):
    viewer_dept_ids = select(UserDepartmentMembership.department_id).where(
        UserDepartmentMembership.user_id == current_user.id,
        UserDepartmentMembership.status == "active",
    )
    viewer_org_ids = select(UserOrganizationMembership.org_id).where(
        UserOrganizationMembership.user_id == current_user.id,
        UserOrganizationMembership.status.in_(["accepted", "active"]),
    )
    viewer_is_dept_admin_of_creator_dept = (
        select(Department.id)
        .where(
            Department.admin_user_id == current_user.id,
            Department.id.in_(
                select(UserDepartmentMembership.department_id).where(
                    UserDepartmentMembership.user_id == KnowledgeBase.created_by,
                    UserDepartmentMembership.status == "active",
                )
            ),
        )
        .exists()
    )
    private_kb_visible = (
        select(KnowledgeBase.id)
        .where(
            KnowledgeBase.id == UserFile.knowledge_base_id,
            KnowledgeBase.visibility == KBVisibilityEnum.PRIVATE,
            or_(
                KnowledgeBase.created_by == current_user.id,
                viewer_is_dept_admin_of_creator_dept,
            ),
        )
        .exists()
    )
    dept_kb_visible = (
        select(KnowledgeBase.id)
        .where(
            KnowledgeBase.id == UserFile.knowledge_base_id,
            KnowledgeBase.visibility == KBVisibilityEnum.DEPARTMENT,
            select(UserDepartmentMembership.id)
            .where(
                UserDepartmentMembership.user_id == KnowledgeBase.created_by,
                UserDepartmentMembership.status == "active",
                UserDepartmentMembership.department_id.in_(viewer_dept_ids),
            )
            .exists(),
        )
        .exists()
    )
    org_kb_visible = (
        select(KnowledgeBase.id)
        .where(
            KnowledgeBase.id == UserFile.knowledge_base_id,
            KnowledgeBase.visibility == KBVisibilityEnum.ORGANIZATION,
            select(UserOrganizationMembership.id)
            .where(
                UserOrganizationMembership.user_id == KnowledgeBase.created_by,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
                UserOrganizationMembership.org_id.in_(viewer_org_ids),
            )
            .exists(),
        )
        .exists()
    )
    return [UserFile.user_id == current_user.id, private_kb_visible, dept_kb_visible, org_kb_visible]


async def _resolve_default_scope(session: DbSession, current_user: CurrentActiveUser) -> tuple[uuid.UUID, uuid.UUID]:
    membership = (
        await session.exec(
            select(UserDepartmentMembership.org_id, UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == current_user.id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="No active department scope found for user")
    return membership[0], membership[1]


async def _resolve_upload_scope(
    session: DbSession,
    current_user: CurrentActiveUser,
    visibility: str | None,
    public_scope: str | None,
    org_id: str | None,
    dept_id: str | None,
) -> tuple[KBVisibilityEnum, uuid.UUID, uuid.UUID | None]:
    normalized_visibility = (visibility or "PRIVATE").strip().upper()
    if normalized_visibility not in {"PRIVATE", "PUBLIC", "DEPARTMENT", "ORGANIZATION"}:
        raise HTTPException(status_code=400, detail="Unsupported visibility")

    if normalized_visibility == "PRIVATE":
        resolved_org_id, resolved_dept_id = await _resolve_default_scope(session, current_user)
        return KBVisibilityEnum.PRIVATE, resolved_org_id, resolved_dept_id

    if normalized_visibility == "PUBLIC":
        if not public_scope:
            raise HTTPException(status_code=400, detail="public_scope is required for public visibility")
        normalized_visibility = "ORGANIZATION" if public_scope.strip().lower() == "organization" else "DEPARTMENT"

    if normalized_visibility == "DEPARTMENT":
        memberships = (
            await session.exec(
                select(UserDepartmentMembership.org_id, UserDepartmentMembership.department_id).where(
                    UserDepartmentMembership.user_id == current_user.id,
                    UserDepartmentMembership.status == "active",
                )
            )
        ).all()
        if not memberships:
            raise HTTPException(status_code=403, detail="No active department scope found for user")
        allowed = {(m[0], m[1]) for m in memberships}
        if org_id and dept_id:
            parsed_org_id = uuid.UUID(org_id)
            parsed_dept_id = uuid.UUID(dept_id)
            if (parsed_org_id, parsed_dept_id) not in allowed:
                raise HTTPException(status_code=403, detail="Selected department is outside your scope")
            return KBVisibilityEnum.DEPARTMENT, parsed_org_id, parsed_dept_id
        default_org_id, default_dept_id = sorted(allowed, key=lambda x: (str(x[0]), str(x[1])))[0]
        return KBVisibilityEnum.DEPARTMENT, default_org_id, default_dept_id

    # ORGANIZATION
    org_memberships = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == current_user.id,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
        )
    ).all()
    allowed_orgs = {r if isinstance(r, uuid.UUID) else r[0] for r in org_memberships}
    if not allowed_orgs:
        raise HTTPException(status_code=403, detail="No active organization scope found for user")
    parsed_org_id = uuid.UUID(org_id) if org_id else sorted(allowed_orgs, key=str)[0]
    if parsed_org_id not in allowed_orgs:
        raise HTTPException(status_code=403, detail="Selected organization is outside your scope")
    return KBVisibilityEnum.ORGANIZATION, parsed_org_id, None


def sanitize_knowledge_base_name(raw_name: str) -> str:
    clean_name = raw_name.strip()
    clean_name = clean_name.replace("\\", "_").replace("/", "_")
    clean_name = re.sub(r"[^A-Za-z0-9 _.-]", "_", clean_name)
    return re.sub(r"\s+", " ", clean_name).strip(" .")


async def _can_access_existing_kb(session: DbSession, current_user: CurrentActiveUser, kb: KnowledgeBase) -> bool:
    if kb.created_by == current_user.id:
        return True
    if kb.visibility == KBVisibilityEnum.PRIVATE:
        creator_dept_ids = (
            await session.exec(
                select(UserDepartmentMembership.department_id).where(
                    UserDepartmentMembership.user_id == kb.created_by,
                    UserDepartmentMembership.status == "active",
                )
            )
        ).all()
        if not creator_dept_ids:
            return False
        return (
            await session.exec(
                select(Department.id)
                .where(
                    Department.admin_user_id == current_user.id,
                    Department.id.in_(list(creator_dept_ids)),
                )
            )
        ).first() is not None
    if kb.visibility == KBVisibilityEnum.DEPARTMENT:
        viewer_dept_ids = select(UserDepartmentMembership.department_id).where(
            UserDepartmentMembership.user_id == current_user.id,
            UserDepartmentMembership.status == "active",
        )
        return (
            await session.exec(
                select(UserDepartmentMembership.id).where(
                    UserDepartmentMembership.user_id == kb.created_by,
                    UserDepartmentMembership.status == "active",
                    UserDepartmentMembership.department_id.in_(viewer_dept_ids),
                )
            )
        ).first() is not None
    viewer_org_ids = select(UserOrganizationMembership.org_id).where(
        UserOrganizationMembership.user_id == current_user.id,
        UserOrganizationMembership.status.in_(["accepted", "active"]),
    )
    return (
        await session.exec(
            select(UserOrganizationMembership.id).where(
                UserOrganizationMembership.user_id == kb.created_by,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
                UserOrganizationMembership.org_id.in_(viewer_org_ids),
            )
        )
    ).first() is not None


async def _get_or_create_knowledge_base(
    session: DbSession,
    current_user: CurrentActiveUser,
    knowledge_base_name: str,
    visibility: KBVisibilityEnum,
    org_id: uuid.UUID,
    dept_id: uuid.UUID | None,
) -> KnowledgeBase:
    existing = (
        await session.exec(
            select(KnowledgeBase).where(
                KnowledgeBase.name == knowledge_base_name,
                KnowledgeBase.org_id == org_id,
                KnowledgeBase.dept_id == dept_id,
            )
        )
    ).first()
    if existing:
        if not await _can_access_existing_kb(session, current_user, existing):
            raise HTTPException(status_code=403, detail="Not authorized to use this knowledge base")
        return existing

    kb = KnowledgeBase(
        name=knowledge_base_name,
        visibility=visibility,
        org_id=org_id,
        dept_id=dept_id,
        created_by=current_user.id,
    )
    session.add(kb)
    await session.flush()
    return kb


async def byte_stream_generator(file_input, chunk_size: int = 8192) -> AsyncGenerator[bytes, None]:
    """Convert bytes object or stream into an async generator that yields chunks."""
    if isinstance(file_input, bytes):
        # Handle bytes object
        for i in range(0, len(file_input), chunk_size):
            yield file_input[i : i + chunk_size]
    # Handle stream object
    elif hasattr(file_input, "read"):
        while True:
            chunk = await file_input.read(chunk_size) if callable(file_input.read) else file_input.read(chunk_size)
            if not chunk:
                break
            yield chunk
    else:
        # Handle async iterator
        async for chunk in file_input:
            yield chunk


async def fetch_file_object(file_id: uuid.UUID, current_user: CurrentActiveUser, session: DbSession):
    # Fetch the file from the DB
    visibility_filters = await _build_file_visibility_filters(session, current_user)
    stmt = select(UserFile).where(UserFile.id == file_id).where(or_(*visibility_filters))
    results = await session.exec(stmt)
    file = results.first()

    # Check if the file exists
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    return file


async def save_file_routine(file, storage_service, current_user: CurrentActiveUser, file_content=None, file_name=None):
    """Routine to save the file content to the storage service."""
    file_id = uuid.uuid4()

    if not file_content:
        file_content = await file.read()
    if not file_name:
        file_name = file.filename

    # Save the file using the storage service.
    await storage_service.save_file(agent_id=str(current_user.id), file_name=file_name, data=file_content)

    return file_id, file_name


def get_storage_relative_path(file_path: str, user_id: uuid.UUID) -> str:
    """Convert stored DB path into storage-relative path under user root."""
    user_prefix = f"{user_id}/"
    if file_path.startswith(user_prefix):
        return file_path[len(user_prefix) :]
    return file_path


@router.post("", status_code=HTTPStatus.CREATED)
@router.post("/", status_code=HTTPStatus.CREATED)
async def upload_user_file(
    file: Annotated[UploadFile, File(...)],
    session: DbSession,
    current_user: CurrentActiveUser,
    storage_service=Depends(get_storage_service),
    settings_service=Depends(get_settings_service),
    knowledge_base_name: Annotated[str | None, Form()] = None,
    visibility: Annotated[str | None, Form()] = None,
    public_scope: Annotated[str | None, Form()] = None,
    org_id: Annotated[str | None, Form()] = None,
    dept_id: Annotated[str | None, Form()] = None,
) -> UploadFileResponse:

    """Upload a file for the current user and track it in the database."""
    # Get the max allowed file size from settings (in MB)
    try:
        max_file_size_upload = settings_service.settings.max_file_size_upload
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Settings error: {e}") from e

    # Validate that a file is actually provided
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Validate file size (convert MB to bytes)
    if file.size > max_file_size_upload * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File size is larger than the maximum file size {max_file_size_upload}MB.",
        )

    # Create a new database record for the uploaded file.
    try:
        # Enforce unique constraint on name, except for the special _mcp_servers file
        new_filename = file.filename
        try:
            root_filename, file_extension = new_filename.rsplit(".", 1)
        except ValueError:
            root_filename, file_extension = new_filename, ""

        # Special handling for the MCP servers config file: always keep the same root filename
        if root_filename == MCP_SERVERS_FILE:
            # Check if an existing record exists; if so, delete it to replace with the new one
            existing_mcp_file = await get_file_by_name(root_filename, current_user, session)
            if existing_mcp_file:
                await delete_file(existing_mcp_file.id, current_user, session, storage_service)
            unique_filename = new_filename
        else:
            # For normal files, ensure unique name by appending a count if necessary
            stmt = select(UserFile).where(col(UserFile.name).like(f"{root_filename}%"))
            existing_files = await session.exec(stmt)
            files = existing_files.all()  # Fetch all matching records

            if files:
                counts = []

                # Extract the count from the filename
                for my_file in files:
                    match = re.search(r"\((\d+)\)(?=\.\w+$|$)", my_file.name)
                    if match:
                        counts.append(int(match.group(1)))

                count = max(counts) if counts else 0
                root_filename = f"{root_filename} ({count + 1})"

            # Create the unique filename with extension for storage
            unique_filename = f"{root_filename}.{file_extension}" if file_extension else root_filename

        safe_knowledge_base_name = ""
        knowledge_base: KnowledgeBase | None = None
        if knowledge_base_name:
            safe_knowledge_base_name = sanitize_knowledge_base_name(knowledge_base_name)
            if not safe_knowledge_base_name:
                raise HTTPException(status_code=400, detail="Invalid knowledge base name")
            kb_visibility, kb_org_id, kb_dept_id = await _resolve_upload_scope(
                session=session,
                current_user=current_user,
                visibility=visibility,
                public_scope=public_scope,
                org_id=org_id,
                dept_id=dept_id,
            )
            knowledge_base = await _get_or_create_knowledge_base(
                session=session,
                current_user=current_user,
                knowledge_base_name=safe_knowledge_base_name,
                visibility=kb_visibility,
                org_id=kb_org_id,
                dept_id=kb_dept_id,
            )

        # For KB uploads, include KB id in storage path for stable unique mapping.
        # Final physical path stays rooted by user id in storage service:
        # <storage>/<user_id>/<kb_id>/<kb_name>/<file_name>
        if knowledge_base and safe_knowledge_base_name:
            storage_file_name = f"{knowledge_base.id}/{safe_knowledge_base_name}/{unique_filename}"
        else:
            storage_file_name = unique_filename

        # Read file content and save with unique filename
        try:
            file_id, stored_file_name = await save_file_routine(
                file, storage_service, current_user, file_name=storage_file_name
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error saving file: {e}") from e

        # Compute the file size based on the path
        file_size = await storage_service.get_file_size(
            agent_id=str(current_user.id),
            file_name=stored_file_name,
        )

        # Create a new file record
        new_file = UserFile(
            id=file_id,
            user_id=current_user.id,
            org_id=knowledge_base.org_id if knowledge_base else None,
            dept_id=knowledge_base.dept_id if knowledge_base else None,
            knowledge_base_id=knowledge_base.id if knowledge_base else None,
            name=root_filename,
            path=f"{current_user.id}/{storage_file_name}",
            size=file_size,
        )
        session.add(new_file)

        await session.commit()
        await session.refresh(new_file)
    except HTTPException:
        raise
    except Exception as e:
        # Optionally, you could also delete the file from disk if the DB insert fails.
        raise HTTPException(status_code=500, detail=f"Database error: {e}") from e

    return UploadFileResponse(agent_id=str(current_user.id), file_path=Path(new_file.path))


async def get_file_by_name(
    file_name: str,  # The name of the file to search for
    current_user: CurrentActiveUser,
    session: DbSession,
) -> UserFile | None:
    """Get the file associated with a given file name for the current user."""
    try:
        # Fetch from the UserFile table
        stmt = select(UserFile).where(UserFile.user_id == current_user.id).where(UserFile.name == file_name)
        result = await session.exec(stmt)

        return result.first() or None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching file: {e}") from e


async def load_sample_files(current_user: CurrentActiveUser, session: DbSession, storage_service: StorageService):
    # Check if the sample files in the SAMPLE_DATA_DIR exist
    for sample_file_path in Path(SAMPLE_DATA_DIR).iterdir():
        sample_file_name = sample_file_path.name
        root_filename, _ = sample_file_name.rsplit(".", 1)

        # Check if the sample file exists in the storage service
        existing_sample_file = await get_file_by_name(
            file_name=root_filename, current_user=current_user, session=session
        )
        if existing_sample_file:
            continue

        # Read the binary data of the sample file
        binary_data = sample_file_path.read_bytes()

        # Write the sample file content to the storage service
        file_id, _ = await save_file_routine(
            sample_file_path,
            storage_service,
            current_user,
            file_content=binary_data,
            file_name=sample_file_name,
        )
        file_size = await storage_service.get_file_size(
            agent_id=str(current_user.id),
            file_name=sample_file_name,
        )
        # Create a UserFile object for the sample file
        sample_file = UserFile(
            id=file_id,
            user_id=current_user.id,
            name=root_filename,
            path=sample_file_name,
            size=file_size,
        )

        session.add(sample_file)

        await session.commit()
        await session.refresh(sample_file)


@router.get("")
@router.get("/", status_code=HTTPStatus.OK)
async def list_files(
    current_user: CurrentActiveUser,
    session: DbSession,
    # storage_service: Annotated[StorageService, Depends(get_storage_service)],
) -> list[UserFile]:
    """List the files available to the current user."""
    try:
        visibility_filters = await _build_file_visibility_filters(session, current_user)
        stmt = select(UserFile).where(or_(*visibility_filters))
        results = await session.exec(stmt)

        full_list = list(results)

        # Filter out the _mcp_servers file
        return [file for file in full_list if file.name != MCP_SERVERS_FILE]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing files: {e}") from e


@router.delete("/batch/", status_code=HTTPStatus.OK)
async def delete_files_batch(
    file_ids: list[uuid.UUID],
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    """Delete multiple files by their IDs."""
    try:
        visibility_filters = await _build_file_visibility_filters(session, current_user)
        # Fetch all files from the DB
        stmt = select(UserFile).where(col(UserFile.id).in_(file_ids), or_(*visibility_filters))
        results = await session.exec(stmt)
        files = results.all()

        if not files:
            raise HTTPException(status_code=404, detail="No files found")

        # Delete all files from the storage service
        for file in files:
            storage_path = get_storage_relative_path(file.path, file.user_id)
            await storage_service.delete_file(agent_id=str(file.user_id), file_name=storage_path)
            await session.delete(file)

        # Delete all files from the database
        await session.commit()  # Commit deletion

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()  # Rollback on failure
        raise HTTPException(status_code=500, detail=f"Error deleting files: {e}") from e

    return {"message": f"{len(files)} files deleted successfully"}


@router.post("/batch/", status_code=HTTPStatus.OK)
async def download_files_batch(
    file_ids: list[uuid.UUID],
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    """Download multiple files as a zip file by their IDs."""
    try:
        visibility_filters = await _build_file_visibility_filters(session, current_user)
        # Fetch all files from the DB
        stmt = select(UserFile).where(col(UserFile.id).in_(file_ids), or_(*visibility_filters))
        results = await session.exec(stmt)
        files = results.all()

        if not files:
            raise HTTPException(status_code=404, detail="No files found")

        # Create a byte stream to hold the ZIP file
        zip_stream = io.BytesIO()

        # Create a ZIP file
        with zipfile.ZipFile(zip_stream, "w") as zip_file:
            for file in files:
                # Get the file content from storage
                storage_path = get_storage_relative_path(file.path, file.user_id)
                file_content = await storage_service.get_file(
                    agent_id=str(file.user_id), file_name=storage_path
                )

                # Get the file extension from the original filename
                file_extension = Path(file.path).suffix
                # Create the filename with extension
                filename_with_extension = f"{file.name}{file_extension}"

                # Write the file to the ZIP with the proper extension
                zip_file.writestr(filename_with_extension, file_content)

        # Seek to the beginning of the byte stream
        zip_stream.seek(0)

        # Generate the filename with the current datetime
        current_time = datetime.now(tz=ZoneInfo("UTC")).astimezone().strftime("%Y%m%d_%H%M%S")
        filename = f"{current_time}_agentcore_files.zip"

        return StreamingResponse(
            zip_stream,
            media_type="application/x-zip-compressed",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading files: {e}") from e


async def read_file_content(file_stream: AsyncIterable[bytes] | bytes, *, decode: bool = True) -> str | bytes:
    """Read file content from a stream or bytes into a string or bytes.

    Args:
        file_stream: An async iterable yielding bytes or a bytes object.
        decode: If True, decode the content to UTF-8; otherwise, return bytes.

    Returns:
        The file content as a string (if decode=True) or bytes.

    Raises:
        ValueError: If the stream yields non-bytes chunks.
        HTTPException: If decoding fails or an error occurs while reading.
    """
    content = b""
    try:
        if isinstance(file_stream, bytes):
            content = file_stream
        else:
            async for chunk in file_stream:
                if not isinstance(chunk, bytes):
                    msg = "File stream must yield bytes"
                    raise TypeError(msg)
                content += chunk
        if not decode:
            return content
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=500, detail="Invalid file encoding") from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"Error reading file: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error reading file: {exc}") from exc


@router.get("/{file_id}")
async def download_file(
    file_id: uuid.UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
    *,
    return_content: bool = False,
):
    """Download a file by its ID or return its content as a string/bytes.

    Args:
        file_id: UUID of the file.
        current_user: Authenticated user.
        session: Database session.
        storage_service: File storage service.
        return_content: If True, return raw content (str) instead of StreamingResponse.

    Returns:
        StreamingResponse for client downloads or str for internal use.
    """
    try:
        # Fetch the file from the DB
        file = await fetch_file_object(file_id, current_user, session)
        if not file:
            raise HTTPException(status_code=404, detail="File not found")

        storage_path = get_storage_relative_path(file.path, file.user_id)

        # Get file stream
        file_stream = await storage_service.get_file(agent_id=str(file.user_id), file_name=storage_path)

        if file_stream is None:
            raise HTTPException(status_code=404, detail="File stream not available")

        # If return_content is True, read the file content and return it
        if return_content:
            return await read_file_content(file_stream, decode=True)

        # For streaming, ensure file_stream is an async iterator returning bytes
        byte_stream = byte_stream_generator(file_stream)

        # Create the filename with extension
        file_extension = Path(file.path).suffix
        filename_with_extension = f"{file.name}{file_extension}"

        # Return the file as a streaming response
        return StreamingResponse(
            byte_stream,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename_with_extension}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading file: {e}") from e


@router.put("/{file_id}")
async def edit_file_name(
    file_id: uuid.UUID,
    name: str,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> UploadFileResponse:
    """Edit the name of a file by its ID."""
    try:
        # Fetch the file from the DB
        file = await fetch_file_object(file_id, current_user, session)

        # Update the file name
        file.name = name
        await session.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error editing file: {e}") from e

    return UploadFileResponse(agent_id=str(current_user.id), file_path=Path(file.path))


@router.delete("/{file_id}")
async def delete_file(
    file_id: uuid.UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    """Delete a file by its ID."""
    try:
        # Fetch the file object
        file_to_delete = await fetch_file_object(file_id, current_user, session)
        if not file_to_delete:
            raise HTTPException(status_code=404, detail="File not found")

        # Delete the file from the storage service
        storage_path = get_storage_relative_path(file_to_delete.path, file_to_delete.user_id)
        await storage_service.delete_file(agent_id=str(file_to_delete.user_id), file_name=storage_path)

        # Delete from the database
        await session.delete(file_to_delete)
        await session.commit()

    except HTTPException:
        # Re-raise HTTPException to avoid being caught by the generic exception handler
        raise
    except Exception as e:
        # Log and return a generic server error
        logger.error("Error deleting file %s: %s", file_id, e)
        raise HTTPException(status_code=500, detail=f"Error deleting file: {e}") from e
    return {"detail": f"File {file_to_delete.name} deleted successfully"}


@router.delete("")
@router.delete("/", status_code=HTTPStatus.OK)
async def delete_all_files(
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
):
    """Delete all files for the current user."""
    try:
        visibility_filters = await _build_file_visibility_filters(session, current_user)
        # Fetch all files from the DB
        stmt = select(UserFile).where(or_(*visibility_filters))
        results = await session.exec(stmt)
        files = results.all()

        # Delete all files from the storage service
        for file in files:
            storage_path = get_storage_relative_path(file.path, file.user_id)
            await storage_service.delete_file(agent_id=str(file.user_id), file_name=storage_path)
            await session.delete(file)

        # Delete all files from the database
        await session.commit()  # Commit deletion

    except Exception as e:
        await session.rollback()  # Rollback on failure
        raise HTTPException(status_code=500, detail=f"Error deleting files: {e}") from e

    return {"message": "All files deleted successfully"}
