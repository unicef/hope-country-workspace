from typing import TYPE_CHECKING

from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from admin_extra_buttons.api import button, confirm_action, link
from adminfilters.autocomplete import AutoCompleteFilter

from ..models import Program
from ..sync.office import sync_programs
from .base import BaseModelAdmin

if TYPE_CHECKING:
    from admin_extra_buttons.buttons import LinkButton


@admin.register(Program)
class ProgramAdmin(BaseModelAdmin):
    list_display = ("name", "sector", "status", "active")
    search_fields = ("name",)
    list_filter = (("country_office", AutoCompleteFilter), "status", "active", "sector")
    ordering = ("name",)

    @link(change_list=False)
    def view_in_workspace(self, btn: "LinkButton") -> None:
        obj = btn.context["original"]
        base = reverse("workspace:workspaces_countryprogram_change", args=[obj.pk])
        btn.href = base

    @link(change_list=False)
    def population(self, btn: "LinkButton") -> None:
        base = reverse("admin:country_workspace_individual_changelist")
        obj = btn.context["original"]
        btn.href = f"{base}?program__exact={obj.pk}&country_office__exact={obj.country_office.pk}"

    @button()
    def zap(self, request: HttpRequest, pk: str) -> None:
        obj: Program = self.get_object(request, pk)

        def _action(request: HttpRequest) -> HttpResponse:
            obj.households.all().delete()

        return confirm_action(
            self,
            request,
            _action,
            "Confirm action",
            description="Continuing will erase all the beneficiaries from this program",
            success_message="Successfully executed",
        )

        # base = reverse("admin:country_workspace_individual_changelist")
        # btn.href = f"{base}?household__exact={obj.pk}"

    @button()
    def sync(self, request: HttpRequest) -> None:
        sync_programs()
