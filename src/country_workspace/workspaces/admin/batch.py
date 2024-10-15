from typing import TYPE_CHECKING

from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link

from ..filters import ProgramFilter
from ..options import WorkspaceModelAdmin
from .hh_ind import SelectedProgramMixin

if TYPE_CHECKING:
    from ..models import CountryBatch


class CountryBatchAdmin(SelectedProgramMixin, WorkspaceModelAdmin):
    list_display = ["name", "program", "country_office"]
    search_fields = ("label",)
    list_filter = (("program", ProgramFilter),)
    change_list_template = "workspace/change_list.html"
    change_form_template = "workspace/change_form.html"
    ordering = ("name",)
    readonly_fields = ("program", "country_office", "imported_by")

    def get_queryset(self, request: HttpRequest) -> "QuerySet[CountryBatch]":
        return super().get_queryset(request).all()
        # return super().get_queryset(request).filter(country_office=state.tenant)

    def has_add_permission(self, request, obj=None):
        return False

    @link(change_list=False)
    def imported_records(self, btn: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryhousehold_changelist")
        obj = btn.context["original"]
        btn.href = f"{base}?batch__exact={obj.pk}&batch__program__exact={obj.program.pk}"
