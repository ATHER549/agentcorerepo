from agentcore.services.chat.service import ChatService
from agentcore.services.factory import ServiceFactory


class ChatServiceFactory(ServiceFactory):
    def __init__(self) -> None:
        super().__init__(ChatService)

    def create(self) -> ChatService:
        return ChatService()

