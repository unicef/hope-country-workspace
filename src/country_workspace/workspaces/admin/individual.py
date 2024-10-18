from typing import Any, Optional

from django.contrib.admin import AdminSite
from django.db.models import Model
from django.http import HttpRequest

from ...state import state
from ..filters import HouseholdFilter, ProgramFilter
from ..models import CountryHousehold, CountryIndividual, CountryProgram
from .hh_ind import BeneficiaryBaseAdmin


class CountryIndividualAdmin(BeneficiaryBaseAdmin):
    list_display = [
        "name",
        "household",
    ]
    search_fields = ("name",)
    list_filter = (
        ("batch__program", ProgramFilter),
        ("household", HouseholdFilter),
    )
    exclude = [
        "household",
        # "country_office",
        # "program",
        "user_fields",
    ]
    change_list_template = "workspace/individual/change_list.html"
    change_form_template = "workspace/individual/change_form.html"
    ordering = ("name",)

    def __init__(self, model: Model, admin_site: AdminSite):
        self._selected_household = None
        super().__init__(model, admin_site)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(batch__country_office=state.tenant)

    def get_list_display(self, request: HttpRequest) -> list[str]:
        program: CountryProgram | None
        if program := self.get_selected_program(request):
            fields = [c.strip() for c in program.individual_columns.split("\n")]
        else:
            fields = self.list_display
        return fields + [
            "is_valid",
        ]

    def get_selected_household(
        self, request: HttpRequest, obj: "Optional[CountryIndividual]" = None
    ) -> CountryHousehold | None:
        from country_workspace.workspaces.models import CountryHousehold

        self._selected_household = None
        if "household__exact" in request.GET:
            self._selected_household = CountryHousehold.objects.get(pk=request.GET["household__exact"])
        elif obj:
            self._selected_household = obj.household
        return self._selected_household

    def get_common_context(self, request: HttpRequest, pk: Optional[str] = None, **kwargs: Any) -> dict[str, Any]:
        kwargs["selected_household"] = self.get_selected_household(request)
        return super().get_common_context(request, pk, **kwargs)
