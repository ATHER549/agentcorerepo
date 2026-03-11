from agentcore.services.base import Service
from agentcore.services.factory import ServiceFactory
from agentcore.services.scheduler.service import SchedulerService


class SchedulerServiceFactory(ServiceFactory):
    def __init__(self):
        super().__init__(SchedulerService)

    def create(self) -> Service:
        return SchedulerService()