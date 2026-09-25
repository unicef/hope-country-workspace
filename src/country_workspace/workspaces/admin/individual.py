from typing import Any
from urllib.parse import parse_qs

from django.contrib.admin import AdminSite, display, register
from django.db.models import Model, QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from ...state import state
from ..models import CountryHousehold, CountryIndividual
from ..sites import workspace
from .filters import CWLinkedAutoCompleteFilter, HouseholdFilter, WIsValidFilter, MultiValueFilter, WJsonFieldFilter
from .hh_ind import BeneficiaryBaseAdmin


@register(CountryIndividual, site=workspace)
class CountryIndividualAdmin(BeneficiaryBaseAdmin):
    # Charset-agnostic search: matches the local-script name OR its Latin spelling.
    search_fields = ("name", "id", "flex_fields__full_name_latin")

    list_filter = (
        ("batch", CWLinkedAutoCompleteFilter.factory(parent=None)),
        ("household", HouseholdFilter),
        WIsValidFilter,
        ("id", MultiValueFilter),
        ("flex_fields", WJsonFieldFilter),
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

    def get_list_display(self, request: HttpRequest) -> list[str]:
        # Show the Latin spelling in small text underneath the name, wherever "name" would
        # otherwise be shown, without requiring every program to reconfigure its columns.
        return ["name_with_latin" if col == "name" else col for col in super().get_list_display(request)]

    @display(description="Name", ordering="name")
    def name_with_latin(self, obj: CountryIndividual) -> str:
        latin = (obj.flex_fields or {}).get("full_name_latin")
        if latin:
            return format_html('{}<br><small class="text-muted">{}</small>', obj.name, latin)
        return obj.name

    def get_queryset(self, request: HttpRequest) -> "QuerySet[CountryHousehold]":
        return (
            super()
            .get_queryset(request)
            .select_related("batch__program", "batch__program__household_checker", "batch__country_office")
            .filter(batch__country_office=state.tenant, batch__program=state.program)
        )

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
