from django.contrib import admin
from django.http import HttpRequest

from adminfilters.autocomplete import LinkedAutoCompleteFilter
from admin_extra_buttons.api import button

from ..models import Registration
from .base import BaseModelAdmin


@admin.register(Registration)
class RegistrationAdmin(BaseModelAdmin):
    list_display = ("name", "reference_pk", "program")
    list_filter = (
        ("country_office", LinkedAutoCompleteFilter.factory(parent=None)),
        ("program", LinkedAutoCompleteFilter.factory(parent="country_office")),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Registration | None = None) -> bool:
        return False

    @button()
    def sync(self, request: HttpRequest) -> None:
        from country_workspace.contrib.hope.sync.office import sync_registrations

        totals = sync_registrations()
        self.message_user(request, f"{totals['add']} created - {totals['upd']} updated - {totals['skipped']} skipped")
