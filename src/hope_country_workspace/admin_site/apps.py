import logging

from django.contrib.admin.apps import SimpleAdminConfig

logger = logging.getLogger(__name__)


class AdminConfig(SimpleAdminConfig):
    default_site = "hope_country_workspace.admin_site.site.CWAdminSite"

    def ready(self) -> None:
        from django.contrib.admin import autodiscover

        autodiscover()
