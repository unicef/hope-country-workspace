from typing import Any
from urllib.parse import parse_qs

from django.contrib.admin import AdminSite, display, register
from django.db.models import Model, QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from country_workspace.rdp import (
    annotate_biometric_individuals,
    biometric_findings_for_individual,
)


from ...state import state
from ..models import CountryHousehold, CountryIndividual
from ..sites import workspace
from .filters import (
    CWLinkedAutoCompleteFilter,
    DuplicateFilter,
    HouseholdFilter,
    ImageIssueFilter,
    MultiValueFilter,
    RdpContextFilter,
    WIsValidFilter,
    WJsonFieldFilter,
    get_rdp_context,
    show_biometric_columns,
)
from .hh_ind import BeneficiaryBaseAdmin


@register(CountryIndividual, site=workspace)
class CountryIndividualAdmin(BeneficiaryBaseAdmin):
    # Charset-agnostic search: matches the local-script name OR its Latin spelling.
    search_fields = ("name", "id", "flex_fields__full_name_latin")

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
        if show_biometric_columns(request):
            filters.extend((DuplicateFilter, ImageIssueFilter))
        return filters

    def get_list_display(self, request: HttpRequest) -> list[str]:
        columns = ["name_with_latin" if col == "name" else col for col in super().get_list_display(request)]
        if show_biometric_columns(request):
            if "is_duplicate" not in columns:
                columns.append("is_duplicate")
            if "has_image_issue" not in columns:
                columns.append("has_image_issue")
        return columns

    @display(description="Name", ordering="name")
    def name_with_latin(self, obj: CountryIndividual) -> str:
        latin = (obj.flex_fields or {}).get("full_name_latin")
        if latin:
            return format_html('{}<br><small class="text-muted">{}</small>', obj.name, latin)
        return obj.name

    def get_queryset(self, request: HttpRequest) -> QuerySet[CountryIndividual]:
        qs = (
            super()
            .get_queryset(request)
            .select_related("batch__program", "batch__program__household_checker", "batch__country_office")
            .filter(batch__country_office=state.tenant, batch__program=state.program)
        )
        return (
            annotate_biometric_individuals(qs, program=state.program, rdp=get_rdp_context(request))
            if show_biometric_columns(request)
            else qs
        )

    @display(description="Duplicate", boolean=True)
    def is_duplicate(self, obj: CountryIndividual) -> bool | None:
        """Display whether the individual has a duplicate finding."""
        return obj._is_duplicate if getattr(obj, "_result_available", False) else None

    @display(description="Image issue", boolean=True)
    def has_image_issue(self, obj: CountryIndividual) -> bool | None:
        """Display whether the individual has an image issue."""
        return obj._has_image_issue if getattr(obj, "_result_available", False) else None

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
        context = super().get_common_context(request, pk, **kwargs)
        original = context["original"]
        context["dedup_duplicates"] = None
        context["dedup_image_issues"] = None

        if original is None or not getattr(original, "_result_available", False):
            return context

        duplicate_pks, image_issues = biometric_findings_for_individual(
            individual=original,
            rdp=get_rdp_context(request),
        )

        context["dedup_duplicates"] = [
            {
                "pk": duplicate_pk,
                "url": reverse("workspace:workspaces_countryindividual_change", args=[duplicate_pk]),
            }
            for duplicate_pk in duplicate_pks
        ]
        context["dedup_image_issues"] = image_issues
        return context
