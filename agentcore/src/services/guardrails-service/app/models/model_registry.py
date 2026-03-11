"""ModelRegistry SQLModel table (read-only mirror) for the Guardrails microservice.

The guardrails service reads model_registry rows to decrypt API keys needed
to initialize NeMo guardrails LLM backends. No FK constraints are defined
since this microservice does not own the model_registry table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


class ModelRegistry(SQLModel, table=True):  # type: ignore[call-arg]
    """Read-only view of model_registry used by NeMo guardrail execution."""

    __tablename__ = "model_registry"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    display_name: str = Field(nullable=False)
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    provider: str = Field(nullable=False, index=True)
    model_name: str = Field(nullable=False)
    model_type: str = Field(default="llm", index=True)
    base_url: str | None = Field(default=None)
    api_key_secret_ref: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    environment: str = Field(default="test", index=True)
    provider_config: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    capabilities: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    default_params: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    is_active: bool = Field(default=True)
    created_by: str | None = Field(default=None, nullable=True)

    org_id: UUID | None = Field(default=None, nullable=True, index=True)
    dept_id: UUID | None = Field(default=None, nullable=True, index=True)
    public_dept_ids: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_by_id: UUID | None = Field(default=None, nullable=True, index=True)
    visibility_scope: str = Field(default="private", nullable=False)
    approval_status: str = Field(default="approved", nullable=False)
    requested_by: UUID | None = Field(default=None, nullable=True, index=True)
    request_to: UUID | None = Field(default=None, nullable=True, index=True)
    source_model_id: UUID | None = Field(default=None, nullable=True, index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
