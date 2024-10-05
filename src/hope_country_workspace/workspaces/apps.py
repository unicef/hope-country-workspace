import logging

from django.apps import AppConfig


logger = logging.getLogger(__name__)


class Config(AppConfig):
    name = __name__.rpartition(".")[0]

    def ready(self) -> None:
        from . import admin, models
        from .sites import workspace
        from hope_country_workspace.models import Household

        workspace.register(Household, admin.CountryHouseholdAdmin)
