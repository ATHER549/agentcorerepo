from agentcore.services.base import Service
from agentcore.services.factory import ServiceFactory
from agentcore.services.trigger.service import TriggerService


class TriggerServiceFactory(ServiceFactory):
    def __init__(self):
        super().__init__(TriggerService)

    def create(self) -> Service:
        return TriggerService()
