from typing import TYPE_CHECKING

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from django.contrib.admin import register
from django.http import HttpRequest
from django.urls import reverse

from country_workspace.state import state
from country_workspace.workspaces.models import CountryHousehold
from country_workspace.workspaces.sites import workspace

from .filters import (
    CWLinkedAutoCompleteFilter,
    MultiValueFilter,
    WIsValidFilter,
    WJsonFieldFilter,
    get_rdp_context,
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
        return (
            super()
            .get_queryset(request)
            .select_related("batch__program", "batch__program__household_checker", "batch__country_office")
            .filter(batch__country_office=state.tenant, batch__program=state.program)
        )

    @link(change_list=False, html_attrs={"title": "Shows related members."})
    def members(self, btn: LinkButton) -> None:
        obj = btn.context["original"]
        if obj:
            params = {"household__exact": obj.pk}
            if rdp := get_rdp_context(btn.request):
                params["rdp_id"] = rdp.pk
            btn.href = reverse("workspace:workspaces_countryindividual_changelist", query=params)
        btn.label = self.title_member_plural
