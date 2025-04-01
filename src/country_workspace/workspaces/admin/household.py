from typing import TYPE_CHECKING

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from django.contrib.admin import register
from django.http import HttpRequest
from django.urls import reverse

from ...state import state
from ..models import CountryHousehold
from ..sites import workspace
from .filters import CWLinkedAutoCompleteFilter, WIsValidFilter
from .hh_ind import BeneficiaryBaseAdmin

from country_workspace.workspaces.admin.cleaners.actions import push_to_hope

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from ..models import CountryProgram


@register(CountryHousehold, site=workspace)
class CountryHouseholdAdmin(BeneficiaryBaseAdmin):
    list_display = ["name", "batch"]
    search_fields = ("name",)
    ordering = ("name",)
    list_per_page = 20
    list_filter = (
        ("batch", CWLinkedAutoCompleteFilter.factory(parent=None)),
        WIsValidFilter,
    )
    actions = [*BeneficiaryBaseAdmin.actions, push_to_hope]

    @property
    def title_plural(self) -> str:
        return super().title_group_plural

    def get_list_display(self, request: HttpRequest) -> list[str]:
        program: "CountryProgram | None"
        if program := self.get_selected_program(request):
            fields = [c.strip() for c in program.household_columns.split("\n")]
        else:
            fields = self.list_display
        return fields + [
            "is_valid",
        ]

    def get_queryset(self, request: HttpRequest) -> "QuerySet[CountryHousehold]":
        return (
            super()
            .get_queryset(request)
            .select_related("batch__program", "batch__program__household_checker", "batch__country_office")
            .filter(batch__country_office=state.tenant, batch__program=state.program)
        )

    @link(change_list=False, html_attrs={"title": "Shows related members."})
    def members(self, btn: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryindividual_changelist")
        obj = btn.context["original"]
        if obj:
            btn.href = f"{base}?household__exact={obj.pk}"
        btn.label = self.title_member_plural
