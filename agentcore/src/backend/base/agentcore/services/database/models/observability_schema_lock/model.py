from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, SQLModel


class ObservabilitySchemaLock(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "observability_schema_lock"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    version_tag: str = Field(sa_column=Column(String(128), nullable=False, unique=True, index=True))
    schema_fingerprint: str = Field(sa_column=Column(String(128), nullable=False))
    validated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
