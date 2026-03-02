from fastapi import HTTPException
from pydantic import BaseModel

from agentcore.api.utils import get_suggestion_message
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.agent.utils import get_outdated_components


class InvalidChatInputError(Exception):
    pass


# create a pidantic documentation for this class
class ExceptionBody(BaseModel):
    message: str | list[str]
    traceback: str | list[str] | None = None
    description: str | list[str] | None = None
    code: str | None = None
    suggestion: str | list[str] | None = None


class APIException(HTTPException):
    def __init__(self, exception: Exception, agent: Agent | None = None, status_code: int = 500):
        body = self.build_exception_body(exception, agent)
        super().__init__(status_code=status_code, detail=body.model_dump_json())

    @staticmethod
    def build_exception_body(exc: str | list[str] | Exception, agent: Agent | None) -> ExceptionBody:
        body = {"message": str(exc)}
        if agent:
            outdated_components = get_outdated_components(agent)
            if outdated_components:
                body["suggestion"] = get_suggestion_message(outdated_components)
        return ExceptionBody(**body)
