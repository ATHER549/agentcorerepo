from loguru import logger
from typing_extensions import override

from agentcore.services.factory import ServiceFactory
from agentcore.services.session.service import SessionService
from agentcore.services.settings.service import SettingsService
from agentcore.services.storage.service import StorageService


class StorageServiceFactory(ServiceFactory):
    def __init__(self) -> None:
        super().__init__(
            StorageService,
        )

    @override
    def create(self, session_service: SessionService, settings_service: SettingsService):
        storage_type = settings_service.settings.storage_type

        if storage_type.lower() == "azure":
            from .azure import AzureBlobStorageService

            logger.info("Using Azure Blob Storage.")
            return AzureBlobStorageService(session_service, settings_service)

        if storage_type.lower() != "local":
            logger.warning(f"Storage type {storage_type} not supported. Using local storage.")

        from .local import LocalStorageService

        return LocalStorageService(session_service, settings_service)
