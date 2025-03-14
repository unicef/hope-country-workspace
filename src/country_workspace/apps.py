from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class HCWAdminConfig(AdminConfig):
    default_site = "country_workspace.admin_site.HCWAdminSite"


class HCWConfig(AppConfig):
    name = __name__.rpartition(".")[0]
    verbose_name = "Country Workspace"

    def ready(self) -> None:
        import admin_extra_buttons.api
        import django_celery_boost.admin

        import country_workspace.compat.admin_extra_buttons as c

        from .utils import flags  # noqa

        admin_extra_buttons.api.confirm_action = c.confirm_action
        django_celery_boost.admin.confirm_action = c.confirm_action
