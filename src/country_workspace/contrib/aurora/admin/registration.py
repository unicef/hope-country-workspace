from django.contrib import admin
from django.http import HttpRequest

from adminfilters.autocomplete import AutoCompleteFilter
from admin_extra_buttons.api import button

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.contrib.aurora.models import Registration
from country_workspace.contrib.aurora.sync import sync_registrations


@admin.register(Registration)
class RegistrationAdmin(BaseModelAdmin):
    list_display = ("name", "project", "active", "last_synced")
    list_filter = (
        ("project", AutoCompleteFilter),
        "active",
    )
    search_fields = ("name",)
    ordering = ("name",)
    autocomplete_fields = ("project",)

    @admin.display(ordering="last_modified")
    def last_synced(self, obj: Registration) -> str:
        return obj.last_modified

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Registration | None = None) -> bool:
        return False

    @button()
    def sync(self, request: HttpRequest) -> None:
        totals = sync_registrations()
        self.message_user(request, f"{totals['add']} created - {totals['upd']} updated - {totals['skip']} skipped")
