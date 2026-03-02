"""Agent Registry / Catalogue API.
Provides a public marketplace for discovering, browsing, and cloning
published agents. Only agents with PUBLISHED status, PUBLIC visibility,
and is_active=True appear in the registry.

Registry entries are auto-managed by ``registry_service.sync_agent_registry``
whenever a deployment's visibility, status, or is_active flag changes.

Endpoints:
    GET    /registry                        — Browse/search the agent catalogue
    GET    /registry/{registry_id}          — Get details of a specific registry entry
    POST   /registry/{registry_id}/clone    — Clone (Copy) a registry agent into your workspace
    POST   /registry/{registry_id}/rate     — Rate a registry entry (1-5 stars)
    GET    /registry/{registry_id}/ratings  — Get ratings for a registry entry
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlmodel import col, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.agent_deployment_prod.model import (
    AgentDeploymentProd,
)
from agentcore.services.database.models.agent_deployment_uat.model import (
    AgentDeploymentUAT,
)
from agentcore.services.database.models.agent_registry.model import (
    AgentRegistry,
    AgentRegistryRating,
    RegistryDeploymentEnvEnum,
    RegistryVisibilityEnum,
)
from agentcore.services.database.models.folder.model import Folder
from agentcore.services.database.models.user.model import User

router = APIRouter(prefix="/registry", tags=["Registry"])


# ═══════════════════════════════════════════════════════════════════════════
# Response Schemas
# ═══════════════════════════════════════════════════════════════════════════


class RegistryEntryResponse(BaseModel):
    """A single entry in the agent catalogue (browse / search results).

    Maps to the UI card:
        - title, summary, tags, rating, rating_count
        - listed_by_username = "by <author>"
    """

    id: UUID
    org_id: UUID | None = None
    agent_id: UUID
    agent_deployment_id: UUID
    deployment_env: str  # "UAT" or "PROD"
    title: str
    summary: str | None = None
    tags: list | None = None
    rating: float | None = None
    rating_count: int = 0
    visibility: str
    listed_by: UUID
    listed_by_username: str | None = None
    listed_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RegistryEntryDetailResponse(RegistryEntryResponse):
    """Detailed view of a registry entry including deployment metadata.

    Returned by the "View" action — includes version, descriptions, and
    deployer info fetched from the deployment table.
    """

    version_number: str | None = None
    agent_description: str | None = None
    publish_description: str | None = None
    deployed_by: UUID | None = None
    deployed_by_username: str | None = None
    deployed_at: datetime | None = None


class RegistryPreviewResponse(BaseModel):
    """Read-only canvas payload for previewing a registry agent."""

    registry_id: UUID
    title: str
    deployment_env: str
    version_number: str | None = None
    snapshot: dict


class RegistryListResponse(BaseModel):
    """Paginated list of registry entries."""

    items: list[RegistryEntryResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class RegistryCloneRequest(BaseModel):
    """Request body for cloning (Copy button) an agent from the registry."""

    project_id: UUID = Field(
        description="Target project (folder) to place the cloned agent into",
    )
    new_name: str | None = Field(
        default=None,
        description="Name for the cloned agent. If omitted, uses '<original_name> (Copy)'",
    )


class RegistryCloneResponse(BaseModel):
    """Response after cloning a registry agent into a new agent."""

    agent_id: UUID
    agent_name: str
    project_id: UUID
    cloned_from_registry_id: UUID
    cloned_from_deployment_id: UUID
    environment_source: str  # "uat" or "prod"


class RateRequest(BaseModel):
    """Request body for rating a registry entry (star rating)."""

    score: float = Field(
        ge=1.0,
        le=5.0,
        description="Rating score from 1.0 to 5.0",
    )
    review: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional review text",
    )


class RateResponse(BaseModel):
    """Response after rating a registry entry."""

    registry_id: UUID
    user_id: UUID
    score: float
    review: str | None = None
    new_average: float
    new_count: int


class RatingItem(BaseModel):
    """A single rating entry."""

    user_id: UUID
    username: str | None = None
    score: float
    review: str | None = None
    created_at: datetime


class RatingsResponse(BaseModel):
    """List of ratings for a registry entry."""

    registry_id: UUID
    average_rating: float | None = None
    total_ratings: int
    items: list[RatingItem]


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.get("", response_model=RegistryListResponse, status_code=200)
async def browse_registry(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    search: str | None = Query(
        default=None,
        description="Free-text search across title, summary, and tags",
    ),
    tag: str | None = Query(
        default=None,
        description="Filter by a specific tag (exact match within the tags array)",
    ),
    deployment_env: RegistryDeploymentEnvEnum | None = Query(
        default=None,
        description="Filter by deployment environment (UAT or PROD) — top-level dropdown in UI",
    ),
    sort_by: str = Query(
        default="listed_at",
        description="Sort field: 'listed_at', 'title', 'rating', 'rating_count'",
    ),
    sort_order: str = Query(
        default="desc",
        description="Sort direction: 'asc' or 'desc'",
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
):
    """Browse and search the agent registry / catalogue.

    Only shows agents that are **PUBLISHED + PUBLIC + ACTIVE** in their
    deployment environment. The UI renders each entry as a card with
    title, author, summary, tags, rating, and a "Copy" (clone) button.

    The ``deployment_env`` query parameter maps to the environment dropdown
    in the UI header (UAT / PROD / All).

    Returns:
        RegistryListResponse with paginated results and metadata.
    """
    try:
        # Only show PUBLIC entries (published + active is enforced by registry_service)
        stmt = select(AgentRegistry).where(
            AgentRegistry.visibility == RegistryVisibilityEnum.PUBLIC,
        )

        # Free-text search across title, summary
        if search:
            search_pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    AgentRegistry.title.ilike(search_pattern),  # type: ignore[union-attr]
                    AgentRegistry.summary.ilike(search_pattern),  # type: ignore[union-attr]
                )
            )

        # Tag filter
        if tag:
            # JSON array contains — works for PostgreSQL
            # For tags stored as JSON array, use cast + contains
            stmt = stmt.where(
                AgentRegistry.tags.cast(str).ilike(f"%{tag}%"),  # type: ignore[union-attr]
            )

        # Environment filter
        if deployment_env:
            stmt = stmt.where(AgentRegistry.deployment_env == deployment_env)

        # Count total before pagination
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.exec(count_stmt)).one()

        # Sorting
        sort_column_map = {
            "listed_at": AgentRegistry.listed_at,
            "title": AgentRegistry.title,
            "rating": AgentRegistry.rating,
            "rating_count": AgentRegistry.rating_count,
            "created_at": AgentRegistry.created_at,
        }
        sort_col = sort_column_map.get(sort_by, AgentRegistry.listed_at)
        if sort_order.lower() == "asc":
            stmt = stmt.order_by(col(sort_col).asc())
        else:
            stmt = stmt.order_by(col(sort_col).desc())

        # Pagination
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)

        records = (await session.exec(stmt)).all()

        # Enrich with lister username
        items: list[RegistryEntryResponse] = []
        lister_ids = {r.listed_by for r in records}
        lister_map: dict[UUID, str] = {}
        if lister_ids:
            users = (await session.exec(
                select(User).where(User.id.in_(lister_ids))  # type: ignore[union-attr]
            )).all()
            lister_map = {u.id: u.username for u in users}

        for r in records:
            items.append(
                RegistryEntryResponse(
                    id=r.id,
                    org_id=r.org_id,
                    agent_id=r.agent_id,
                    agent_deployment_id=r.agent_deployment_id,
                    deployment_env=r.deployment_env.value,
                    title=r.title,
                    summary=r.summary,
                    tags=r.tags,
                    rating=r.rating,
                    rating_count=r.rating_count,
                    visibility=r.visibility.value,
                    listed_by=r.listed_by,
                    listed_by_username=lister_map.get(r.listed_by),
                    listed_at=r.listed_at,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
            )

        total_pages = max(1, (total + page_size - 1) // page_size)

        return RegistryListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error browsing registry: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{registry_id}", response_model=RegistryEntryDetailResponse, status_code=200)
async def get_registry_entry(
    *,
    session: DbSession,
    registry_id: UUID,
    current_user: CurrentActiveUser,
):
    """Get detailed information about a specific registry entry.
    Returns the registry entry enriched with deployment metadata (version,
    description, deployer info) by joining with the corresponding deployment
    table (agent_deployment_uat or agent_deployment_prod).
    Args:
        session: Async database session.
        registry_id: UUID of the registry entry.
        current_user: The authenticated user.
    Returns:
        RegistryEntryDetailResponse with full entry + deployment details.
    Raises:
        404: Registry entry not found or not publicly visible.
    """
    try:
        entry = (await session.exec(
            select(AgentRegistry).where(
                AgentRegistry.id == registry_id,
                AgentRegistry.visibility == RegistryVisibilityEnum.PUBLIC,
            )
        )).first()

        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Registry entry {registry_id} not found or not publicly visible",
            )

        # Fetch lister username
        lister = await session.get(User, entry.listed_by)
        lister_username = lister.username if lister else None

        # Fetch deployment details based on environment
        version_number: str | None = None
        agent_description: str | None = None
        publish_description: str | None = None
        deployed_by: UUID | None = None
        deployed_by_username: str | None = None
        deployed_at: datetime | None = None

        if entry.deployment_env == RegistryDeploymentEnvEnum.PROD:
            deploy_record = await session.get(AgentDeploymentProd, entry.agent_deployment_id)
            if deploy_record:
                version_number = f"v{deploy_record.version_number}"
                agent_description = deploy_record.agent_description
                publish_description = deploy_record.publish_description
                deployed_by = deploy_record.deployed_by
                deployed_at = deploy_record.deployed_at
        elif entry.deployment_env == RegistryDeploymentEnvEnum.UAT:
            deploy_record = await session.get(AgentDeploymentUAT, entry.agent_deployment_id)
            if deploy_record:
                version_number = f"v{deploy_record.version_number}"
                agent_description = deploy_record.agent_description
                publish_description = deploy_record.publish_description
                deployed_by = deploy_record.deployed_by
                deployed_at = deploy_record.deployed_at

        # Fetch deployer username
        if deployed_by:
            deployer = await session.get(User, deployed_by)
            deployed_by_username = deployer.username if deployer else None

        return RegistryEntryDetailResponse(
            id=entry.id,
            org_id=entry.org_id,
            agent_id=entry.agent_id,
            agent_deployment_id=entry.agent_deployment_id,
            deployment_env=entry.deployment_env.value,
            title=entry.title,
            summary=entry.summary,
            tags=entry.tags,
            rating=entry.rating,
            rating_count=entry.rating_count,
            visibility=entry.visibility.value,
            listed_by=entry.listed_by,
            listed_by_username=lister_username,
            listed_at=entry.listed_at,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            version_number=version_number,
            agent_description=agent_description,
            publish_description=publish_description,
            deployed_by=deployed_by,
            deployed_by_username=deployed_by_username,
            deployed_at=deployed_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting registry entry {registry_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{registry_id}/preview", response_model=RegistryPreviewResponse, status_code=200)
async def get_registry_preview(
    *,
    session: DbSession,
    registry_id: UUID,
    current_user: CurrentActiveUser,
):
    """Return the frozen deployment snapshot for read-only canvas preview."""
    try:
        entry = (await session.exec(
            select(AgentRegistry).where(
                AgentRegistry.id == registry_id,
                AgentRegistry.visibility == RegistryVisibilityEnum.PUBLIC,
            )
        )).first()

        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Registry entry {registry_id} not found or not publicly visible",
            )

        version_number: str | None = None
        snapshot: dict | None = None

        if entry.deployment_env == RegistryDeploymentEnvEnum.PROD:
            deploy_record = await session.get(AgentDeploymentProd, entry.agent_deployment_id)
        else:
            deploy_record = await session.get(AgentDeploymentUAT, entry.agent_deployment_id)

        if not deploy_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Deployment record {entry.agent_deployment_id} referenced by "
                    f"registry entry {registry_id} no longer exists"
                ),
            )

        snapshot = deploy_record.agent_snapshot
        version_number = f"v{deploy_record.version_number}"

        if not snapshot:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Deployment record has no snapshot data to preview",
            )

        return RegistryPreviewResponse(
            registry_id=entry.id,
            title=entry.title,
            deployment_env=entry.deployment_env.value,
            version_number=version_number,
            snapshot=snapshot,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting registry preview {registry_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{registry_id}/clone", response_model=RegistryCloneResponse, status_code=201)
async def clone_from_registry(
    *,
    session: DbSession,
    registry_id: UUID,
    body: RegistryCloneRequest,
    current_user: CurrentActiveUser,
):
    """Clone an agent from the registry into the current user's workspace.
    This is the primary "Copy on Edit" flow for the Agent Catalogue:
    Sequence:
        1. User browses the registry and finds an agent they want to use
        2. Clicks "Clone" / "Use This Agent" → selects target folder
        3. System looks up the registry entry → finds the deployment record
        4. Reads the frozen agent_snapshot from the deployment
        5. INSERT new agent with:
           - user_id = current_user (NOT the original author)
           - project_id = selected folder
           - data = frozen snapshot (the flow JSON)
           - name = original title + " (Copy)" or custom name
           - cloned_from_deployment_id = deployment record UUID (lineage)
        6. User can now edit THEIR copy independently
        7. Original author's agent is UNTOUCHED
    Works for both chat agents and autonomous agents since the snapshot
    contains the complete flow definition (nodes + edges).
    Args:
        session: Async database session.
        registry_id: UUID of the registry entry to clone from.
        body: Clone configuration (project_id, optional new_name).
        current_user: The authenticated user who will own the clone.
    Returns:
        RegistryCloneResponse with the new agent's details.
    Raises:
        404: Registry entry not found, deployment record missing, or folder not found.
        400: Deployment snapshot has no usable flow data.
    """
    try:
        # 1. Look up registry entry (must be PUBLIC)
        entry = (await session.exec(
            select(AgentRegistry).where(
                AgentRegistry.id == registry_id,
                AgentRegistry.visibility == RegistryVisibilityEnum.PUBLIC,
            )
        )).first()

        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Registry entry {registry_id} not found or not publicly visible",
            )

        # 2. Fetch the deployment record to get the frozen snapshot
        snapshot: dict | None = None
        agent_description: str | None = None
        env_source: str

        if entry.deployment_env == RegistryDeploymentEnvEnum.PROD:
            deploy_record = await session.get(AgentDeploymentProd, entry.agent_deployment_id)
            env_source = "prod"
        else:
            deploy_record = await session.get(AgentDeploymentUAT, entry.agent_deployment_id)
            env_source = "uat"

        if not deploy_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Deployment record {entry.agent_deployment_id} referenced by "
                    f"registry entry {registry_id} no longer exists"
                ),
            )

        snapshot = deploy_record.agent_snapshot
        agent_description = deploy_record.agent_description

        if not snapshot:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Deployment record has no snapshot data to clone from",
            )

        # 3. Verify target folder exists and belongs to user
        folder = (await session.exec(
            select(Folder).where(
                Folder.id == body.project_id,
                Folder.user_id == current_user.id,
            )
        )).first()

        if not folder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder {body.project_id} not found or not owned by you",
            )

        # 4. Determine agent name with uniqueness handling
        base_name = body.new_name or f"{entry.title} (Copy)"

        existing = (await session.exec(
            select(Agent).where(Agent.name == base_name, Agent.user_id == current_user.id)
        )).first()

        if existing:
            # Find next available numbered copy
            like_pattern = f"{base_name} (%"
            copies = (await session.exec(
                select(Agent).where(
                    Agent.name.like(like_pattern),  # type: ignore[union-attr]
                    Agent.user_id == current_user.id,
                )
            )).all()

            if copies:
                extract_number = re.compile(rf"^{re.escape(base_name)} \((\d+)\)$")
                numbers = []
                for c in copies:
                    match = extract_number.search(c.name)
                    if match:
                        numbers.append(int(match.groups()[0]))
                if numbers:
                    base_name = f"{base_name} ({max(numbers) + 1})"
                else:
                    base_name = f"{base_name} (1)"
            else:
                base_name = f"{base_name} (1)"

        # 5. Create the new agent from the snapshot
        new_agent = Agent(
            name=base_name,
            description=agent_description,
            data=snapshot,
            user_id=current_user.id,
            project_id=body.project_id,
            cloned_from_deployment_id=entry.agent_deployment_id,
            updated_at=datetime.now(timezone.utc),
        )
        session.add(new_agent)
        await session.commit()
        await session.refresh(new_agent)

        logger.info(
            f"User {current_user.id} cloned agent from registry {registry_id} "
            f"({env_source} deployment {entry.agent_deployment_id}) → "
            f"new agent '{base_name}' ({new_agent.id})"
        )

        return RegistryCloneResponse(
            agent_id=new_agent.id,
            agent_name=new_agent.name,
            project_id=new_agent.project_id,
            cloned_from_registry_id=registry_id,
            cloned_from_deployment_id=entry.agent_deployment_id,
            environment_source=env_source,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cloning from registry entry {registry_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ═══════════════════════════════════════════════════════════════════════════
# Rating Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/{registry_id}/rate", response_model=RateResponse, status_code=200)
async def rate_registry_entry(
    *,
    session: DbSession,
    registry_id: UUID,
    body: RateRequest,
    current_user: CurrentActiveUser,
):
    """Rate a registry entry (1-5 stars).

    Each user can rate a registry entry exactly once. Submitting again
    updates the existing rating (upsert). The average rating and count
    on the registry entry are recalculated after each rating.

    Args:
        session: Async database session.
        registry_id: UUID of the registry entry to rate.
        body: Rating details (score 1.0-5.0, optional review text).
        current_user: The authenticated user submitting the rating.

    Returns:
        RateResponse with the new average and count.
    """
    try:
        # Verify registry entry exists and is PUBLIC
        entry = (await session.exec(
            select(AgentRegistry).where(
                AgentRegistry.id == registry_id,
                AgentRegistry.visibility == RegistryVisibilityEnum.PUBLIC,
            )
        )).first()

        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Registry entry {registry_id} not found or not publicly visible",
            )

        # Upsert rating — check if user already rated this entry
        existing_rating = (await session.exec(
            select(AgentRegistryRating).where(
                AgentRegistryRating.registry_id == registry_id,
                AgentRegistryRating.user_id == current_user.id,
            )
        )).first()

        now = datetime.now(timezone.utc)

        if existing_rating:
            existing_rating.score = body.score
            existing_rating.review = body.review
            existing_rating.updated_at = now
            session.add(existing_rating)
        else:
            new_rating = AgentRegistryRating(
                registry_id=registry_id,
                user_id=current_user.id,
                score=body.score,
                review=body.review,
                created_at=now,
                updated_at=now,
            )
            session.add(new_rating)

        await session.flush()

        # Recalculate average rating and count from all ratings
        avg_result = (await session.exec(
            select(
                func.avg(AgentRegistryRating.score),
                func.count(AgentRegistryRating.id),
            ).where(AgentRegistryRating.registry_id == registry_id)
        )).first()

        new_avg = round(float(avg_result[0]), 2) if avg_result[0] else 0.0
        new_count = int(avg_result[1]) if avg_result[1] else 0

        # Update denormalized rating on the registry entry
        entry.rating = new_avg
        entry.rating_count = new_count
        entry.updated_at = now
        session.add(entry)

        await session.commit()

        logger.info(
            f"User {current_user.id} rated registry entry {registry_id}: "
            f"{body.score}/5.0 → avg={new_avg}, count={new_count}"
        )

        return RateResponse(
            registry_id=registry_id,
            user_id=current_user.id,
            score=body.score,
            review=body.review,
            new_average=new_avg,
            new_count=new_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rating registry entry {registry_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{registry_id}/ratings", response_model=RatingsResponse, status_code=200)
async def get_registry_ratings(
    *,
    session: DbSession,
    registry_id: UUID,
    current_user: CurrentActiveUser,
):
    """Get all ratings for a registry entry.

    Returns the individual ratings with usernames, plus the aggregate
    average and total count.

    Args:
        session: Async database session.
        registry_id: UUID of the registry entry.
        current_user: The authenticated user.

    Returns:
        RatingsResponse with all ratings and aggregate stats.
    """
    try:
        # Verify entry exists
        entry = (await session.exec(
            select(AgentRegistry).where(
                AgentRegistry.id == registry_id,
                AgentRegistry.visibility == RegistryVisibilityEnum.PUBLIC,
            )
        )).first()

        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Registry entry {registry_id} not found or not publicly visible",
            )

        # Fetch all ratings
        ratings = (await session.exec(
            select(AgentRegistryRating)
            .where(AgentRegistryRating.registry_id == registry_id)
            .order_by(col(AgentRegistryRating.created_at).desc())
        )).all()

        # Enrich with usernames
        user_ids = {r.user_id for r in ratings}
        user_map: dict[UUID, str] = {}
        if user_ids:
            users = (await session.exec(
                select(User).where(User.id.in_(user_ids))  # type: ignore[union-attr]
            )).all()
            user_map = {u.id: u.username for u in users}

        items = [
            RatingItem(
                user_id=r.user_id,
                username=user_map.get(r.user_id),
                score=r.score,
                review=r.review,
                created_at=r.created_at,
            )
            for r in ratings
        ]

        return RatingsResponse(
            registry_id=registry_id,
            average_rating=entry.rating,
            total_ratings=entry.rating_count,
            items=items,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching ratings for registry entry {registry_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
