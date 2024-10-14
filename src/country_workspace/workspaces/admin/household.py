from typing import TYPE_CHECKING

from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link

from .hh_ind import CountryHouseholdIndividualBaseAdmin

if TYPE_CHECKING:
    from ..models import CountryHousehold, CountryProgram


class CountryHouseholdAdmin(CountryHouseholdIndividualBaseAdmin):
    list_display = ["name", "batch"]
    search_fields = ("name",)
    # list_filter = (("batch__program", ProgramFilter), "batch")

    # readonly_fields = ["program"]
    # exclude = [
    #     "country_office",
    #     "program",
    # ]
    change_list_template = "workspace/household/change_list.html"
    change_form_template = "workspace/household/change_form.html"
    ordering = ("name",)

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
        return super().get_queryset(request)

    @link(change_list=False)
    def members(self, btn: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryindividual_changelist")
        obj = btn.context["original"]
        btn.href = f"{base}?household__exact={obj.pk}&batch__program__exact={obj.program.pk}"
