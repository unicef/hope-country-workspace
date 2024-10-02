import logging

from django.contrib.admin.apps import SimpleAdminConfig

logger = logging.getLogger(__name__)


class AdminConfig(SimpleAdminConfig):
    default_site = "hope_country_workspace.admin_site.site.CWAdminSite"

    # def ready(self) -> None:
    #     from django.utils.module_loading import autodiscover_modules
    #
    #     # autodiscover_modules("admin", register_to=site)
