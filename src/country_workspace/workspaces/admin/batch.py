from typing import TYPE_CHECKING, Any

from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from adminfilters.autocomplete import LinkedAutoCompleteFilter

from ...state import state
from ..models import CountryBatch
from ..options import WorkspaceModelAdmin
from .hh_ind import SelectedProgramMixin

if TYPE_CHECKING:
    pass


class ProgramBatchFilter(LinkedAutoCompleteFilter):

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.lookup_val:
            p = state.tenant.programs.get(pk=self.lookup_val)
            queryset = super().queryset(request, queryset).filter(program=p)
        return queryset


class CountryBatchAdmin(SelectedProgramMixin, WorkspaceModelAdmin):
    list_display = ["name", "program", "country_office"]
    search_fields = ("label",)
    list_filter = (("program", ProgramBatchFilter),)
    change_list_template = "workspace/batch/change_list.html"
    change_form_template = "workspace/change_form.html"
    ordering = ("name",)
    exclude = ("program", "country_office", "imported_by")

    def get_queryset(self, request: HttpRequest) -> "QuerySet[CountryBatch]":
        qs = CountryBatch.objects.filter(country_office=state.tenant)
        if prg := self.get_selected_program(request):
            return qs.filter(program=prg)
        else:
            return qs.none()

    def get_changelist(self, request: HttpRequest, **kwargs: Any) -> type:
        from ..changelist import WorkspaceChangeList

        return WorkspaceChangeList

    def has_add_permission(self, request, obj=None):
        return False

    @link(change_list=False)
    def imported_records(self, btn: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryhousehold_changelist")
        obj = btn.context["original"]
        btn.href = f"{base}?batch__exact={obj.pk}&batch__program__exact={obj.program.pk}"
