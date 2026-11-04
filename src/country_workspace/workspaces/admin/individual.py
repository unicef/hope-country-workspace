from typing import Any
from urllib.parse import parse_qs, urlencode

from django.contrib.admin import AdminSite, display, register
from django.core.exceptions import ValidationError
from django.db.models import Model, QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from country_workspace.models import Batch
from country_workspace.rdp import (
    annotate_biographic_individuals,
    annotate_biometric_individuals,
    biographic_findings_for_individual,
    biographic_operation_for_rdp,
    biometric_findings_for_individual,
    biometric_operation_for_rdp,
    qs_biographic_duplicate_individuals,
    qs_biometric_duplicate_individuals,
)


from ...state import state
from ..models import CountryHousehold, CountryIndividual
from ..sites import workspace
from .filters import (
    BiographicDuplicateFilter,
    CWLinkedAutoCompleteFilter,
    DuplicateFilter,
    HouseholdFilter,
    ImageIssueFilter,
    MultiValueFilter,
    RdpContextFilter,
    WIsValidFilter,
    WJsonFieldFilter,
    get_rdp_context,
    show_biographic_columns,
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

    def get_object(
        self,
        request: HttpRequest,
        object_id: str | None,
        from_field: str | None = None,
    ) -> CountryIndividual | None:
        if object_id is None:
            return None

        if obj := super().get_object(request, object_id, from_field):
            return obj

        if from_field is not None or (rdp := get_rdp_context(request)) is None:
            return None

        operations = [
            operation
            for operation in (biometric_operation_for_rdp(rdp=rdp), biographic_operation_for_rdp(rdp=rdp))
            if operation is not None and operation.status == operation.Status.SUCCESS
        ]
        if not operations:
            return None

        try:
            pk = self.model._meta.pk.to_python(object_id)
        except (ValidationError, ValueError):
            return None

        duplicate_pks = {
            duplicate_pk
            for operation in operations
            for duplicate_pk in self._duplicate_individuals(operation=operation).values_list("pk", flat=True)
        }
        qs = CountryIndividual.objects.filter(
            pk=pk,
            pk__in=duplicate_pks,
            removed=True,
            batch__country_office=state.tenant,
            batch__program_id=rdp.program_id,
            batch__status=Batch.BatchStatus.COMPLETE,
        )
        if biometric_operation_for_rdp(rdp=rdp) is not None:
            qs = annotate_biometric_individuals(qs, program=rdp.program, rdp=rdp)
        if biographic_operation_for_rdp(rdp=rdp) is not None:
            qs = annotate_biographic_individuals(qs, program=rdp.program, rdp=rdp)
        return qs.first()

    @staticmethod
    def _duplicate_individuals(*, operation: Any) -> QuerySet[CountryIndividual]:
        """Return individuals marked duplicate by a biometric or biographic operation."""
        if operation.operation_type == operation.Type.BIOGRAPHIC_DEDUPLICATION:
            return qs_biographic_duplicate_individuals(operation=operation)
        return qs_biometric_duplicate_individuals(operation=operation)

    def get_list_filter(self, request: HttpRequest) -> list[Any]:
        filters = list(super().get_list_filter(request))
        if show_biometric_columns(request):
            filters.extend((DuplicateFilter, ImageIssueFilter))
        if show_biographic_columns(request):
            filters.append(BiographicDuplicateFilter)
        return filters

    def get_list_display(self, request: HttpRequest) -> list[str]:
        columns = ["name_with_latin" if col == "name" else col for col in super().get_list_display(request)]
        if show_biometric_columns(request):
            if "is_duplicate" not in columns:
                columns.append("is_duplicate")
            if "has_image_issue" not in columns:
                columns.append("has_image_issue")
        if show_biographic_columns(request) and "is_biographic_duplicate" not in columns:
            columns.append("is_biographic_duplicate")
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
        if show_biometric_columns(request):
            qs = annotate_biometric_individuals(qs, program=state.program, rdp=get_rdp_context(request))
        if show_biographic_columns(request):
            qs = annotate_biographic_individuals(qs, program=state.program, rdp=get_rdp_context(request))
        return qs

    @display(description="Duplicate", boolean=True)
    def is_duplicate(self, obj: CountryIndividual) -> bool | None:
        """Display whether the individual has a duplicate finding."""
        return obj._is_duplicate if getattr(obj, "_result_available", False) else None

    @display(description="Biographic duplicate", boolean=True)
    def is_biographic_duplicate(self, obj: CountryIndividual) -> bool | None:
        """Display whether the individual has a biographic duplicate finding."""
        return obj._is_biographic_duplicate if getattr(obj, "_biographic_result_available", False) else None

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
        context["dedup_biographic_duplicates"] = None

        if original is None:
            return context

        rdp = get_rdp_context(request)

        if getattr(original, "_result_available", False):
            duplicate_rdp_ids, image_issues = biometric_findings_for_individual(individual=original, rdp=rdp)
            context["dedup_duplicates"] = self._duplicate_links(
                [{"pk": pk_, "rdp_id": rdp_id} for pk_, rdp_id in duplicate_rdp_ids.items()]
            )
            context["dedup_image_issues"] = image_issues

        if getattr(original, "_biographic_result_available", False):
            context["dedup_biographic_duplicates"] = self._duplicate_links(
                biographic_findings_for_individual(individual=original, rdp=rdp)
            )

        return context

    @staticmethod
    def _duplicate_links(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return the matches with a link to each counterpart, preserving the RDP of removed ones."""
        removed_pks = set(
            CountryIndividual.objects.filter(pk__in=[m["pk"] for m in matches], removed=True).values_list(
                "pk", flat=True
            )
        )
        links = []
        for match in matches:
            url = reverse("workspace:workspaces_countryindividual_change", args=[match["pk"]])
            if match["pk"] in removed_pks:
                url = f"{url}?{urlencode({'_changelist_filters': urlencode({'rdp_id': match['rdp_id']})})}"
            links.append(
                {"pk": match["pk"], "url": url} | {k: v for k, v in match.items() if k not in {"pk", "rdp_id"}}
            )
        return links
