from typing import TYPE_CHECKING

from admin_extra_buttons.api import button, link
from adminfilters.autocomplete import AutoCompleteFilter
from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from ..cache.manager import cache_manager
from ..compat.admin_extra_buttons import confirm_action
from ..models import Program
from ..contrib.hope.sync.context_programs import SyncStep
from .base import BaseModelAdmin
from .sync import SyncAdminMixin, SyncConfig, ContextProgramsSyncHandler


if TYPE_CHECKING:
    from admin_extra_buttons.buttons import LinkButton


@admin.register(Program)
class ProgramAdmin(SyncAdminMixin, BaseModelAdmin):
    list_display = (
        "name",
        "sector",
        "status",
        "enabled",
        "beneficiary_group",
        "beneficiary_validator",
        "household_checker",
        "individual_checker",
    )
    search_fields = ("name",)
    list_filter = (
        ("country_office", AutoCompleteFilter),
        "status",
        "sector",
        "enabled",
        "beneficiary_group",
        "beneficiary_validator",
        "household_checker",
        "individual_checker",
    )
    ordering = ("name",)
    autocomplete_fields = ("country_office",)
    sync_config = SyncConfig(model=Program, step=SyncStep.PROGRAMS, sync_handler=ContextProgramsSyncHandler())

    @button()
    def invalidate_cache(self, request: HttpRequest, pk: str) -> None:
        obj: Program = Program.objects.select_related("country_office").get(pk=pk)
        cache_manager.incr_cache_version(program=obj)

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
