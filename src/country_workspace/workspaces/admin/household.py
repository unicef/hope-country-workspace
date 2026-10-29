from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from django.contrib.admin import display, register
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from country_workspace.rdp import annotate_biometric_households
from country_workspace.state import state
from country_workspace.workspaces.models import CountryHousehold
from country_workspace.workspaces.sites import workspace

from .filters import (
    CWLinkedAutoCompleteFilter,
    DuplicateMembersFilter,
    ImageIssueMembersFilter,
    MultiValueFilter,
    WIsValidFilter,
    WJsonFieldFilter,
    get_rdp_context,
    show_program_biometric_results,
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
        ("id", MultiValueFilter),
        ("flex_fields", WJsonFieldFilter),
    )
    object_history_template = "workspace/household/object_history.html"

    @property
    def title_plural(self) -> str:
        return super().title_group_plural or ""

    def get_queryset(self, request: HttpRequest) -> "QuerySet[CountryHousehold]":
        qs = (
            super()
            .get_queryset(request)
            .select_related("batch__program", "batch__program__household_checker", "batch__country_office")
            .filter(batch__country_office=state.tenant, batch__program=state.program)
        )
        return (
            annotate_biometric_households(qs, program=state.program, rdp=None)
            if show_program_biometric_results(request)
            else qs
        )

    def get_common_context(self, request: HttpRequest, pk: str | None = None, **kwargs: Any) -> dict[str, Any]:
        context = super().get_common_context(request, pk, **kwargs)
        original = context["original"]
        context["dedup_member_count"] = None
        context["dedup_duplicate_member_count"] = None
        context["dedup_image_issue_member_count"] = None

        if context["selected_rdp"] is not None or original is None or not getattr(original, "_result_available", False):
            return context

        context["dedup_member_count"] = original._member_count
        context["dedup_duplicate_member_count"] = original._duplicate_member_count
        context["dedup_image_issue_member_count"] = original._image_issue_member_count
        return context

    def get_list_filter(self, request: HttpRequest) -> list[Any]:
        filters = list(super().get_list_filter(request))
        if show_program_biometric_results(request):
            filters.extend((DuplicateMembersFilter, ImageIssueMembersFilter))
        return filters

    def get_list_display(self, request: HttpRequest) -> list[str]:
        columns = super().get_list_display(request)
        if show_program_biometric_results(request):
            if "duplicate_members" not in columns:
                columns.append("duplicate_members")
            if "image_issue_members" not in columns:
                columns.append("image_issue_members")
        return columns

    @display(description="Duplicate members")
    def duplicate_members(self, obj: CountryHousehold) -> str:
        """Display marked household members relative to all actual members."""
        if not getattr(obj, "_result_available", False):
            return "-"

        value = f"{obj._duplicate_member_count}/{obj._member_count}"
        if not obj._duplicate_member_count:
            return value

        url = reverse("workspace:workspaces_countryindividual_changelist")
        params = {"household__exact": obj.pk, "duplicates": "with"}
        return format_html('<a href="{}?{}">{}</a>', url, urlencode(params), value)

    @display(description="Image issue members")
    def image_issue_members(self, obj: CountryHousehold) -> str:
        """Display members with biometric image issues relative to all actual members."""
        if not getattr(obj, "_result_available", False):
            return "-"
        return f"{obj._image_issue_member_count}/{obj._member_count}"

    @link(change_list=False, html_attrs={"title": "Shows related members."})
    def members(self, btn: LinkButton) -> None:
        obj = btn.context["original"]
        if obj:
            params = {"household__exact": obj.pk}
            if rdp := get_rdp_context(btn.request):
                params["rdp_id"] = rdp.pk
            btn.href = reverse("workspace:workspaces_countryindividual_changelist", query=params)
        btn.label = self.title_member_plural
