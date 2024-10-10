import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class Config(AppConfig):
    name = __name__.rpartition(".")[0]

    def ready(self) -> None:
        from country_workspace.workspaces import models

        from . import admin
        from .sites import workspace

        workspace.register(models.CountryHousehold, admin.CountryHouseholdAdmin)
        workspace.register(models.CountryIndividual, admin.CountryIndividualAdmin)
        workspace.register(models.CountryProgram, admin.CountryProgramAdmin)
