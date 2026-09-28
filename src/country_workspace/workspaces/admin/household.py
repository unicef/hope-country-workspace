from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from django.contrib.admin import display, register
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from country_workspace.rdp import annotate_biometric_households

from ...state import state
from ..models import CountryHousehold
from ..sites import workspace
from .filters import (
    CWLinkedAutoCompleteFilter,
    DuplicateMembersFilter,
    ImageIssueMembersFilter,
    MultiValueFilter,
    RdpContextFilter,
    WIsValidFilter,
    WJsonFieldFilter,
    get_rdp_context,
    show_biometric_columns,
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
        if show_biometric_columns(request):
            filters.extend((DuplicateMembersFilter, ImageIssueMembersFilter))
        return filters

    def get_list_display(self, request: HttpRequest) -> list[str]:
        columns = super().get_list_display(request)
        if show_biometric_columns(request):
            if "duplicate_members" not in columns:
                columns.append("duplicate_members")
            if "image_issue_members" not in columns:
                columns.append("image_issue_members")
        return columns

    def get_queryset(self, request: HttpRequest) -> "QuerySet[CountryHousehold]":
        qs = (
            super()
            .get_queryset(request)
            .select_related("batch__program", "batch__program__household_checker", "batch__country_office")
            .filter(batch__country_office=state.tenant, batch__program=state.program)
        )
        return (
            annotate_biometric_households(qs, program=state.program, rdp=get_rdp_context(request))
            if show_biometric_columns(request)
            else qs
        )

    @display(description="Duplicate members")
    def duplicate_members(self, obj: CountryHousehold) -> str:
        """Display marked household members relative to all actual members."""
        if not getattr(obj, "_result_available", False):
            return "-"

        value = f"{obj._duplicate_member_count}/{obj._member_count}"
        if not obj._duplicate_member_count:
            return value

        params = {"household__exact": obj.pk, "duplicates": "with"}
        if obj._selected_rdp_id is not None:
            params["rdp_id"] = obj._selected_rdp_id

        url = reverse("workspace:workspaces_countryindividual_changelist")
        return format_html('<a href="{}?{}">{}</a>', url, urlencode(params), value)

    @display(description="Image issue members")
    def image_issue_members(self, obj: CountryHousehold) -> str:
        """Display members with biometric image issues relative to all actual members."""
        if not getattr(obj, "_result_available", False):
            return "-"
        return f"{obj._image_issue_member_count}/{obj._member_count}"

    def get_common_context(self, request: HttpRequest, pk: str | None = None, **kwargs: Any) -> dict[str, Any]:
        context = super().get_common_context(request, pk, **kwargs)
        original = context["original"]

        context["dedup_member_count"] = None
        context["dedup_duplicate_member_count"] = None
        context["dedup_image_issue_member_count"] = None

        if original is None or not getattr(original, "_result_available", False):
            return context

        context["dedup_member_count"] = original._member_count
        context["dedup_duplicate_member_count"] = original._duplicate_member_count
        context["dedup_image_issue_member_count"] = original._image_issue_member_count
        return context

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
