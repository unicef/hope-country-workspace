from typing import Any
from urllib.parse import parse_qs, urlencode

from django.contrib.admin import display, register
from django.core.exceptions import ValidationError
from django.db.models import Exists, Q, QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from country_workspace.models import Batch, Rdp, RdpOperationFinding
from country_workspace.rdp import annotate_biometric_individuals, biometric_findings_for_individual
from country_workspace.state import state
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual
from country_workspace.workspaces.sites import workspace

from .filters import (
    CWLinkedAutoCompleteFilter,
    DuplicateFilter,
    HouseholdFilter,
    ImageIssueFilter,
    MultiValueFilter,
    WIsValidFilter,
    WJsonFieldFilter,
    get_rdp_context,
    show_program_biometric_results,
)
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

    def get_queryset(self, request: HttpRequest) -> QuerySet[CountryIndividual]:
        qs = (
            super()
            .get_queryset(request)
            .select_related("batch__program", "batch__program__household_checker", "batch__country_office")
            .filter(batch__country_office=state.tenant, batch__program=state.program)
        )
        return (
            annotate_biometric_individuals(qs, program=state.program, rdp=None)
            if show_program_biometric_results(request)
            else qs
        )

    def get_object(
        self, request: HttpRequest, object_id: str | None, from_field: str | None = None
    ) -> CountryIndividual | None:
        if object_id is None:
            return None

        if obj := super().get_object(request, object_id, from_field):
            return obj

        if from_field is not None or (rdp := get_rdp_context(request)) is None:
            return None

        if not self._can_view_operation_findings(request, rdp):
            return None

        try:
            pk = self.model._meta.pk.to_python(object_id)
        except (ValidationError, ValueError):
            return None

        findings = RdpOperationFinding.objects.filter(
            Q(individual_id=pk) | Q(related_individual_id=pk),
            operation__rdp=rdp,
        )
        return CountryIndividual.objects.filter(
            Exists(findings),
            pk=pk,
            batch__country_office=state.tenant,
            batch__program_id=rdp.program_id,
            batch__status=Batch.BatchStatus.COMPLETE,
        ).first()

    def get_common_context(self, request: HttpRequest, pk: str | None = None, **kwargs: Any) -> dict[str, Any]:
        context = super().get_common_context(request, pk, **kwargs)
        original = context["original"]
        rdp = context["selected_rdp"]
        context.update(self._get_navigation_context(request, original, rdp, master_detail=context["master_detail"]))
        context["dedup_duplicates"] = None
        context["dedup_image_issues"] = None

        if rdp is not None or original is None or not getattr(original, "_result_available", False):
            return context

        duplicate_rdp_ids, image_issues = biometric_findings_for_individual(individual=original)
        removed_duplicate_pks = set(
            CountryIndividual.objects.filter(pk__in=duplicate_rdp_ids, removed=True).values_list("pk", flat=True)
        )

        duplicates: list[dict[str, int | str]] = []
        for duplicate_pk, rdp_id in duplicate_rdp_ids.items():
            query = (
                {"_changelist_filters": urlencode({"rdp_id": rdp_id})}
                if duplicate_pk in removed_duplicate_pks
                else None
            )
            duplicates.append(
                {
                    "pk": duplicate_pk,
                    "url": reverse("workspace:workspaces_countryindividual_change", args=[duplicate_pk], query=query),
                }
            )

        context["dedup_duplicates"] = duplicates
        context["dedup_image_issues"] = image_issues
        return context

    def _get_navigation_context(
        self, request: HttpRequest, obj: CountryIndividual | None, rdp: Rdp | None, *, master_detail: bool | None
    ) -> dict[str, Any]:
        household = self.get_selected_household(request, obj) if master_detail else None
        params = {"rdp_id": rdp.pk} if rdp else {}
        context = {
            "selected_household": household,
            "households_url": (
                reverse("workspace:workspaces_countryhousehold_changelist", query=params)
                if master_detail and self.admin_site.get_model_admin(CountryHousehold).has_view_permission(request)
                else None
            ),
        }
        if household:
            context["household_url"] = reverse(
                "workspace:workspaces_countryhousehold_change",
                args=[household.pk],
                query={"_changelist_filters": urlencode(params)} if params else None,
            )
            params["household__exact"] = household.pk
        context["individuals_url"] = reverse("workspace:workspaces_countryindividual_changelist", query=params)
        return context

    def get_selected_household(
        self, request: HttpRequest, obj: CountryIndividual | None = None
    ) -> CountryHousehold | None:
        household_id: int | str | None
        if obj is not None:
            household_id = obj.household_id
        else:
            household_id = request.GET.get("household__exact")
            if household_id is None:
                preserved = parse_qs(request.GET.get("_changelist_filters", ""), keep_blank_values=True)
                household_id = preserved.get("household__exact", [None])[-1]

        if household_id is None:
            return None

        household_admin = self.admin_site.get_model_admin(CountryHousehold)
        if (household := household_admin.get_object(request, str(household_id))) is None:
            return None
        return household if household_admin.has_view_permission(request, household) else None

    def get_list_filter(self, request: HttpRequest) -> list[Any]:
        filters = list(super().get_list_filter(request))
        if show_program_biometric_results(request):
            filters.extend((DuplicateFilter, ImageIssueFilter))
        return filters

    def get_list_display(self, request: HttpRequest) -> list[str]:
        columns = ["name_with_latin" if col == "name" else col for col in super().get_list_display(request)]
        if show_program_biometric_results(request):
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

    @display(description="Duplicate", boolean=True)
    def is_duplicate(self, obj: CountryIndividual) -> bool | None:
        """Display whether the individual has a duplicate finding."""
        return obj._is_duplicate if getattr(obj, "_result_available", False) else None

    @display(description="Image issue", boolean=True)
    def has_image_issue(self, obj: CountryIndividual) -> bool | None:
        """Display whether the individual has an image issue."""
        return obj._has_image_issue if getattr(obj, "_result_available", False) else None
