from typing import Any
from urllib.parse import parse_qs

from django.contrib.admin import AdminSite, register
from django.db.models import Model, QuerySet
from django.http import HttpRequest

from ...state import state
from ..models import CountryHousehold, CountryIndividual, CountryProgram
from ..sites import workspace
from .filters import CWLinkedAutoCompleteFilter, HouseholdFilter, WIsValidFilter, MultiValueFilter
from .hh_ind import BeneficiaryBaseAdmin


@register(CountryIndividual, site=workspace)
class CountryIndividualAdmin(BeneficiaryBaseAdmin):
    list_display = [
        "name",
        "household",
    ]
    search_fields = ("name",)

    list_filter = (
        ("batch", CWLinkedAutoCompleteFilter.factory(parent=None)),
        ("household", HouseholdFilter),
        WIsValidFilter,
        ("id", MultiValueFilter),
    )
    exclude = [
        "household",
        # "country_office",
        # "program",
        "user_fields",
    ]
    ordering = ("name",)

    @property
    def title_plural(self) -> str:
        return super().title_member_plural or ""

    def __init__(self, model: Model, admin_site: "AdminSite") -> None:
        self._selected_household = None
        super().__init__(model, admin_site)

    def get_queryset(self, request: HttpRequest) -> "QuerySet[CountryHousehold]":
        return (
            super()
            .get_queryset(request)
            .select_related("batch__program", "batch__program__household_checker", "batch__country_office")
            .filter(batch__country_office=state.tenant, batch__program=state.program)
        )

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
        self,
        request: HttpRequest,
        obj: "CountryIndividual | None" = None,
    ) -> CountryHousehold | None:
        from country_workspace.workspaces.models import CountryHousehold

        self._selected_household = None
        if "household__exact" in request.GET:
            self._selected_household = CountryHousehold.objects.get(pk=request.GET["household__exact"])
        elif cl_flt := request.GET.get("_changelist_filters", ""):
            if prg := parse_qs(cl_flt).get("household__exact"):
                self._selected_household = CountryHousehold.objects.get(pk=prg[0])
        elif obj:
            self._selected_household = obj.household
        return self._selected_household

    def get_common_context(self, request: HttpRequest, pk: str | None = None, **kwargs: Any) -> dict[str, Any]:
        kwargs["selected_household"] = self.get_selected_household(request)
        return super().get_common_context(request, pk, **kwargs)
