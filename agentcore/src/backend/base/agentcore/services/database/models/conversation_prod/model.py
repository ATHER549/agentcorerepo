# Path: src/backend/agentcore/services/database/models/conversation_prod/model.py
#
# Clone of the dev ConversationTable for PROD environment.
# Adds deployment_id FK to link conversations to a specific PROD deployment version.

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated, Optional
from uuid import UUID, uuid4

from pydantic import ConfigDict, field_serializer, field_validator
from sqlalchemy import Index, Text
from sqlmodel import JSON, Column, Field, Relationship, SQLModel

from agentcore.schema.content_block import ContentBlock
from agentcore.schema.properties import Properties
from agentcore.schema.validators import str_to_naive_timestamp_validator

if TYPE_CHECKING:
    from agentcore.schema.message import Message

    from agentcore.services.database.models.agent_deployment_prod.model import AgentDeploymentProd


class ConversationProdBase(SQLModel):
    timestamp: Annotated[datetime, str_to_naive_timestamp_validator] = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    sender: str
    sender_name: str
    session_id: str
    text: str = Field(sa_column=Column(Text))
    files: list[str] = Field(default_factory=list)
    error: bool = Field(default=False)
    edit: bool = Field(default=False)

    properties: Properties = Field(default_factory=Properties)
    category: str = Field(default="message")
    content_blocks: list[ContentBlock] = Field(default_factory=list)

    @field_serializer("timestamp")
    def serialize_timestamp(self, value):
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value

    @field_validator("files", mode="before")
    @classmethod
    def validate_files(cls, value):
        if not value:
            value = []
        return value

    @classmethod
    def from_message(cls, message: "Message", agent_id: str | UUID | None = None, deployment_id: UUID | None = None):
        if not message.sender or not message.sender_name:
            msg = "The message does not have the required fields (sender, sender_name)."
            raise ValueError(msg)
        if message.files:
            image_paths = []
            for file in message.files:
                if hasattr(file, "path") and hasattr(file, "url") and file.path:
                    session_id = message.session_id
                    if session_id:
                        image_paths.append(f"{session_id}{file.path.split(str(session_id))[1]}")
                    else:
                        image_paths.append(file.path)
            if image_paths:
                message.files = image_paths

        if isinstance(message.timestamp, str):
            try:
                timestamp = datetime.strptime(message.timestamp, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    timestamp = datetime.strptime(message.timestamp, "%Y-%m-%d %H:%M:%S %Z")
                    timestamp = timestamp.replace(tzinfo=None)
                except ValueError:
                    timestamp = datetime.fromisoformat(message.timestamp)
                    if timestamp.tzinfo is not None:
                        timestamp = timestamp.replace(tzinfo=None)
        else:
            timestamp = message.timestamp
            if timestamp and timestamp.tzinfo is not None:
                timestamp = timestamp.replace(tzinfo=None)
        if not agent_id and message.agent_id:
            agent_id = message.agent_id

        message_text = "" if not isinstance(message.text, str) else message.text

        properties = (
            message.properties.model_dump_json()
            if hasattr(message.properties, "model_dump_json")
            else message.properties
        )
        content_blocks = []
        for content_block in message.content_blocks or []:
            content = content_block.model_dump_json() if hasattr(content_block, "model_dump_json") else content_block
            content_blocks.append(content)

        if isinstance(agent_id, str):
            try:
                agent_id = UUID(agent_id)
            except ValueError as exc:
                msg = f"Agent ID {agent_id} is not a valid UUID"
                raise ValueError(msg) from exc

        result = cls(
            sender=message.sender,
            sender_name=message.sender_name,
            text=message_text,
            session_id=message.session_id,
            files=message.files or [],
            timestamp=timestamp,
            agent_id=agent_id,
            deployment_id=deployment_id,
            properties=properties,
            category=message.category,
            content_blocks=content_blocks,
        )
        return result


class ConversationProdTable(ConversationProdBase, table=True):  # type: ignore[call-arg]
    model_config = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True)
    __tablename__ = "conversation_prod"
    id: UUID = Field(default_factory=uuid4, primary_key=True)

    agent_id: UUID | None = Field(default=None, index=True)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True)
    deployment_id: UUID | None = Field(
        default=None,
        foreign_key="agent_deployment_prod.id",
        index=True,
        description="Link to the specific PROD deployment version",
    )
    files: list[str] = Field(sa_column=Column(JSON))
    properties: dict | Properties = Field(default_factory=lambda: Properties().model_dump(), sa_column=Column(JSON))  # type: ignore[assignment]
    category: str = Field(sa_column=Column(Text))
    content_blocks: list[dict | ContentBlock] = Field(default_factory=list, sa_column=Column(JSON))  # type: ignore[assignment]

    # Relationships
    deployment: Optional["AgentDeploymentProd"] = Relationship()

    __table_args__ = (
        Index("ix_conversation_prod_session", "session_id"),
        Index("ix_conversation_prod_agent", "agent_id"),
        Index("ix_conversation_prod_org", "org_id"),
        Index("ix_conversation_prod_dept", "dept_id"),
        Index("ix_conversation_prod_deployment", "deployment_id"),
    )

    @field_validator("agent_id", mode="before")
    @classmethod
    def validate_agent_id(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            value = UUID(value)
        return value

    @field_validator("properties", "content_blocks", mode="before")
    @classmethod
    def validate_properties_or_content_blocks(cls, value):
        if isinstance(value, list):
            return [cls.validate_properties_or_content_blocks(item) for item in value]
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, str):
            return json.loads(value)
        return value

    @field_serializer("properties", "content_blocks")
    @classmethod
    def serialize_properties_or_content_blocks(cls, value) -> dict | list[dict]:
        if isinstance(value, list):
            return [cls.serialize_properties_or_content_blocks(item) for item in value]
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, str):
            return json.loads(value)
        return value


class ConversationProdRead(ConversationProdBase):
    id: UUID
    agent_id: UUID | None = Field()
    org_id: UUID | None = None
    dept_id: UUID | None = None
    deployment_id: UUID | None = None


class ConversationProdCreate(ConversationProdBase):
    deployment_id: UUID | None = None


class ConversationProdUpdate(SQLModel):
    text: str | None = None
    sender: str | None = None
    sender_name: str | None = None
    session_id: str | None = None
    files: list[str] | None = None
    edit: bool | None = None
    error: bool | None = None
    properties: Properties | None = None
