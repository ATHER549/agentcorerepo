from agentcore.services.base import Service
from agentcore.services.factory import ServiceFactory
from agentcore.services.job_queue.service import JobQueueService


class JobQueueServiceFactory(ServiceFactory):
    def __init__(self):
        super().__init__(JobQueueService)

    def create(self) -> Service:
        return JobQueueService()
