from typing import TYPE_CHECKING

from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import button, link

from .hh_ind import CountryHouseholdIndividualBaseAdmin

if TYPE_CHECKING:
    from ..models import CountryHousehold, CountryProgram


class CountryHouseholdAdmin(CountryHouseholdIndividualBaseAdmin):
    list_display = ["name", "program"]
    search_fields = ("name",)
    # readonly_fields = ["program"]
    exclude = [
        "country_office",
        "program",
    ]
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

    # def get_checker(self, request, obj=None) -> "DataChecker":
    #     if obj:
    #         return obj.program.household_checker
    #     elif p := self.get_selected_program(request):
    #         return p.household_checker
    #     raise Http404("No Household checkers available")

    @link(change_list=False)
    def members(self, btn: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryindividual_changelist")
        obj = btn.context["original"]
        btn.href = f"{base}?household__exact={obj.pk}&program__exact={obj.program.pk}"

    @button()
    def import_file(self, request: HttpRequest, pk: str) -> None:
        pass
