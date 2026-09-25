from typing import Any
from urllib.parse import parse_qs

from django.contrib.admin import AdminSite, display, register
from django.db.models import BooleanField, Exists, Model, OuterRef, QuerySet, Value
from django.http import HttpRequest

from country_workspace.models import Rdp
from ...state import state
from ..models import CountryHousehold, CountryIndividual
from ..sites import workspace
from .filters import (
    CWLinkedAutoCompleteFilter,
    DuplicateFilter,
    HouseholdFilter,
    MultiValueFilter,
    RdpContextFilter,
    WIsValidFilter,
    WJsonFieldFilter,
    get_rdp_context,
    show_duplicate_columns,
)
from .hh_ind import BeneficiaryBaseAdmin


@register(CountryIndividual, site=workspace)
class CountryIndividualAdmin(BeneficiaryBaseAdmin):
    search_fields = ("name", "id")

    list_filter = (
        ("batch", CWLinkedAutoCompleteFilter.factory(parent=None)),
        ("household", HouseholdFilter),
        RdpContextFilter,
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

    def get_list_filter(self, request: HttpRequest) -> list[Any]:
        filters = list(super().get_list_filter(request))
        if show_duplicate_columns(request):
            filters.append(DuplicateFilter)
        return filters

    def get_list_display(self, request: HttpRequest) -> list[str]:
        columns = super().get_list_display(request)
        if show_duplicate_columns(request) and "is_duplicate" not in columns:
            columns.append("is_duplicate")
        return columns

    def get_queryset(self, request: HttpRequest) -> "QuerySet[CountryIndividual]":
        qs = (
            super()
            .get_queryset(request)
            .select_related("batch__program", "batch__program__household_checker", "batch__country_office")
            .filter(batch__country_office=state.tenant, batch__program=state.program)
        )
        if not show_duplicate_columns(request):
            return qs
        marked = Rdp.duplicate_individuals.through.objects.filter(individual_id=OuterRef("pk"))
        if rdp := get_rdp_context(request):
            marked = marked.filter(rdp_id=rdp.pk)
            result_available = Value(rdp.deduplication_findings_count is not None, output_field=BooleanField())
        else:
            marked = marked.filter(rdp__program=state.program, rdp__deduplication_findings_count__isnull=False)
            completed = Rdp.objects.filter(program=state.program, deduplication_findings_count__isnull=False)
            if state.program.is_master_detail:
                marked = marked.filter(rdp__households__pk=OuterRef("household_id"))
                completed = completed.filter(households__pk=OuterRef("household_id"))
            else:
                marked = marked.filter(rdp__individuals__pk=OuterRef("pk"))
                completed = completed.filter(individuals__pk=OuterRef("pk"))
            result_available = Exists(completed)
        return qs.annotate(
            _is_duplicate=Exists(marked),
            _result_available=result_available,
        )

    @display(description="Duplicate", boolean=True)
    def is_duplicate(self, obj: CountryIndividual) -> bool | None:
        """Display the duplicate marker for the selected RDP or any past RDP."""
        return obj._is_duplicate if getattr(obj, "_result_available", False) else None

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
