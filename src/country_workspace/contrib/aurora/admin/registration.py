from adminfilters.autocomplete import AutoCompleteFilter
from django.contrib import admin
from django.http import HttpRequest

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.contrib.aurora.models import Registration
from country_workspace.admin.sync import SyncAdminMixin, SyncAdminConfig, StepConfig


@admin.register(Registration)
class RegistrationAdmin(SyncAdminMixin, BaseModelAdmin):
    list_display = ("name", "project", "active", "last_synced")
    list_filter = (
        ("project", AutoCompleteFilter),
        "active",
    )
    search_fields = ("name",)
    ordering = ("name",)
    autocomplete_fields = ("project",)
    sync_config = SyncAdminConfig(
        step_handler=StepConfig(path="country_workspace.contrib.aurora.context_aurora.SyncStep", name="REGISTRATIONS"),
        sync_handler="country_workspace.contrib.aurora.context_aurora.sync_context_aurora",
    )

    @admin.display(ordering="last_modified")
    def last_synced(self, obj: Registration) -> str:
        return obj.last_modified

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Registration | None = None) -> bool:
        return False
