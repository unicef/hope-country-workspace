from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from django.contrib.admin import display, register
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.db.models import BooleanField, Count, Exists, IntegerField, OuterRef, Q, Value

from country_workspace.models import Individual, RdpOperation
from country_workspace.rdp import (
    biometric_operation_for_rdp,
    qs_biometric_duplicate_individuals,
    qs_successful_biometric_duplicate_individuals,
    qs_successful_biometric_operations,
)

from ...state import state
from ..models import CountryHousehold
from ..sites import workspace
from .filters import (
    CWLinkedAutoCompleteFilter,
    DuplicateFilter,
    MultiValueFilter,
    RdpContextFilter,
    WIsValidFilter,
    WJsonFieldFilter,
    get_rdp_context,
    show_duplicate_columns,
)
from .hh_ind import BeneficiaryBaseAdmin

if TYPE_CHECKING:
    from django.db.models import QuerySet


@register(CountryHousehold, site=workspace)
class CountryHouseholdAdmin(BeneficiaryBaseAdmin):
    search_fields = ("name", "id")
    ordering = ("name",)
    list_per_page = 20
    list_filter = (
        ("batch", CWLinkedAutoCompleteFilter.factory(parent=None)),
        WIsValidFilter,
        RdpContextFilter,
        ("id", MultiValueFilter),
        ("flex_fields", WJsonFieldFilter),
    )
    object_history_template = "workspace/household/object_history.html"

    @property
    def title_plural(self) -> str:
        return super().title_group_plural or ""

    def get_list_filter(self, request: HttpRequest) -> list[Any]:
        filters = list(super().get_list_filter(request))
        if show_duplicate_columns(request):
            filters.append(DuplicateFilter)
        return filters

    def get_list_display(self, request: HttpRequest) -> list[str]:
        columns = super().get_list_display(request)
        if show_duplicate_columns(request) and "duplicate_members" not in columns:
            columns.append("duplicate_members")
        return columns

    def get_queryset(self, request: HttpRequest) -> "QuerySet[CountryHousehold]":
        qs = (
            super()
            .get_queryset(request)
            .select_related("batch__program", "batch__program__household_checker", "batch__country_office")
            .filter(batch__country_office=state.tenant, batch__program=state.program)
        )
        if not show_duplicate_columns(request):
            return qs

        rdp = get_rdp_context(request)
        if rdp:
            operation = biometric_operation_for_rdp(rdp=rdp)
            duplicates = (
                qs_biometric_duplicate_individuals(operation=operation) if operation else Individual.objects.none()
            )
            duplicate_members = Q(members__in=duplicates)
            member_count = Count("members", distinct=True)
            result_available = Value(
                operation is not None and operation.status == RdpOperation.Status.SUCCESS,
                output_field=BooleanField(),
            )
        else:
            duplicates = qs_successful_biometric_duplicate_individuals(program=state.program)
            duplicate_members = Q(members__removed=False, members__in=duplicates)
            member_count = Count("members", filter=Q(members__removed=False), distinct=True)
            result_available = Exists(
                qs_successful_biometric_operations().filter(
                    rdp__program=state.program,
                    rdp__households__pk=OuterRef("pk"),
                )
            )

        return qs.annotate(
            _member_count=member_count,
            _duplicate_member_count=Count("members", filter=duplicate_members, distinct=True),
            _result_available=result_available,
            _selected_rdp_id=Value(rdp.pk if rdp else None, output_field=IntegerField()),
        )

    @display(description="Duplicate members")
    def duplicate_members(self, obj: CountryHousehold) -> str:
        """Display marked household members relative to all actual members."""
        if not getattr(obj, "_result_available", False):
            return "-"
        value = f"{obj._duplicate_member_count}/{obj._member_count}"
        if not obj._duplicate_member_count:
            return value
        params = {"household__exact": obj.pk, "duplicates": "marked"}
        if obj._selected_rdp_id is not None:
            params["rdp_id"] = obj._selected_rdp_id
        url = reverse("workspace:workspaces_countryindividual_changelist")
        return format_html('<a href="{}?{}">{}</a>', url, urlencode(params), value)

    @link(change_list=False, html_attrs={"title": "Shows related members."})
    def members(self, btn: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryindividual_changelist")
        obj = btn.context["original"]
        if obj:
            params = {"household__exact": obj.pk}
            if (rdp_id := getattr(obj, "_selected_rdp_id", None)) is not None:
                params["rdp_id"] = rdp_id
            btn.href = f"{base}?{urlencode(params)}"
        btn.label = self.title_member_plural
