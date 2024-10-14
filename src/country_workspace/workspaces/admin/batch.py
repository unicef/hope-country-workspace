from typing import TYPE_CHECKING

from django.db.models import QuerySet
from django.http import HttpRequest

from ...state import state
from ..options import WorkspaceModelAdmin

if TYPE_CHECKING:
    from ..models import CountryBatch


class CountryBatchAdmin(WorkspaceModelAdmin):
    list_display = ["name", "program", "country_office"]
    search_fields = ("label",)

    change_list_template = "workspace/household/change_list.html"
    change_form_template = "workspace/household/change_form.html"
    ordering = ("name",)

    def get_queryset(self, request: HttpRequest) -> "QuerySet[CountryBatch]":
        return super().get_queryset(request).filter(country_office=state.tenant)

    def has_add_permission(self, request, obj=None):
        return False
