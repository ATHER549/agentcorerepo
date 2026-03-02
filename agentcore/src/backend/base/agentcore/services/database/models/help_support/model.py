from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class HelpSupportQuestion(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "help_support_question"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    question: str = Field(nullable=False, max_length=500)
    answer: str = Field(nullable=False)
    created_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    updated_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HelpSupportQuestionCreate(SQLModel):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1)


class HelpSupportQuestionUpdate(SQLModel):
    question: str | None = Field(default=None, min_length=1, max_length=500)
    answer: str | None = Field(default=None, min_length=1)


class HelpSupportQuestionRead(SQLModel):
    id: UUID
    question: str
    answer: str
    created_by: UUID | None = None
    updated_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

