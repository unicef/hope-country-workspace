from typing import Any
from urllib.parse import parse_qs, urlencode

from django.contrib.admin import display, register
from django.core.exceptions import ValidationError
from django.db.models import Exists, Q, QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from country_workspace.models import Batch, Rdp, RdpOperationFinding
from country_workspace.state import state
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual
from country_workspace.workspaces.sites import workspace

from .filters import (
    CWLinkedAutoCompleteFilter,
    HouseholdFilter,
    MultiValueFilter,
    WIsValidFilter,
    WJsonFieldFilter,
    get_rdp_context,
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
        return (
            super()
            .get_queryset(request)
            .select_related("batch__program", "batch__program__household_checker", "batch__country_office")
            .filter(batch__country_office=state.tenant, batch__program=state.program)
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
        context.update(
            self._get_navigation_context(
                request,
                context["original"],
                context["selected_rdp"],
                master_detail=context["master_detail"],
            )
        )
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

    def get_list_display(self, request: HttpRequest) -> list[str]:
        return ["name_with_latin" if column == "name" else column for column in super().get_list_display(request)]

    @display(description="Name", ordering="name")
    def name_with_latin(self, obj: CountryIndividual) -> str:
        latin = (obj.flex_fields or {}).get("full_name_latin")
        if latin:
            return format_html('{}<br><small class="text-muted">{}</small>', obj.name, latin)
        return obj.name
