import logging

from django.apps import AppConfig
from django.contrib.admin.apps import SimpleAdminConfig

logger = logging.getLogger(__name__)


class Config(AppConfig):
    name = __name__.rpartition(".")[0]

    def ready(self) -> None:
        from .sites import workspace
        from . import admin
        from . import models
        workspace.register(models.CountryHousehold, admin.CountryHouseholddAdmin)
