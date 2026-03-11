# Path: src/backend/base/agentcore/services/teams/factory.py
"""Factory for creating TeamsService instances."""

from __future__ import annotations

from typing import override

from agentcore.services.factory import ServiceFactory
from agentcore.services.settings.service import SettingsService
from agentcore.services.teams.service import TeamsService


class TeamsServiceFactory(ServiceFactory):
    def __init__(self) -> None:
        super().__init__(TeamsService)

    @override
    def create(self, settings_service: SettingsService) -> TeamsService:  # type: ignore[override]
        return TeamsService(settings_service)
