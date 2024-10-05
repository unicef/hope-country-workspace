import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class Config(AppConfig):
    name = __name__.rpartition(".")[0]

    def ready(self) -> None:
        from country_workspace.models import Household, Individual

        from . import admin
        from .sites import workspace

        workspace.register(Household, admin.CountryHouseholdAdmin)
        workspace.register(Individual, admin.CountryIndividualAdmin)
