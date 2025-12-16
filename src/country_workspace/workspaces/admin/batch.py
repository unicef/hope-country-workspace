from typing import Any

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import button, link
from django.contrib.admin import register
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from strategy_field.utils import fqn

from country_workspace.compat.admin_extra_buttons import confirm_action
from country_workspace.models import AsyncJob
from ...state import state
from ..models import CountryBatch
from ..options import WorkspaceModelAdmin
from ..permissions import can_reprocess_batch
from ..sites import workspace
from .filters import CWLinkedAutoCompleteFilter, ChoiceFilter, UserAutoCompleteFilter
from .hh_ind import SelectedProgramMixin


class ProgramBatchFilter(CWLinkedAutoCompleteFilter):
    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.lookup_val:
            p = state.tenant.programs.get(pk=self.lookup_val)
            queryset = super().queryset(request, queryset).filter(program=p)
        return queryset


@register(CountryBatch, site=workspace)
class CountryBatchAdmin(SelectedProgramMixin, WorkspaceModelAdmin):
    list_display = ["name", "import_date", "imported_by", "source"]
    search_fields = ("name",)
    change_list_template = ["workspace/change_list.html"]
    change_form_template = ["workspace/change_form.html"]
    ordering = ("-import_date",)
    list_filter = (("source", ChoiceFilter), ("imported_by", UserAutoCompleteFilter))
    readonly_fields = fields = ("name", "source")

    def get_common_context(self, request: HttpRequest, pk: str | None = None, **kwargs: Any) -> dict[str, Any]:
        kwargs["modeladmin"] = self
        kwargs["modeladmin_name"] = self.__class__.__name__
        return super().get_common_context(request, pk, **kwargs)

    def get_queryset(self, request: HttpRequest) -> "QuerySet[CountryBatch]":
        return (
            super()
            .get_queryset(request)
            .select_related("program", "country_office")
            .filter(country_office=state.tenant, program=state.program)
        )

    def has_add_permission(self, request: HttpRequest, obj: CountryBatch | None = None) -> bool:
        return False

    @link(change_list=False, html_attrs={"title": "Shows related Household records."})
    def imported_records(self, btn: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryhousehold_changelist")
        obj = btn.context["original"]
        btn.href = f"{base}?batch__exact={obj.pk}"

    @button(
        change_list=False,
        permission=lambda r, o, handler: can_reprocess_batch(r, o, handler),
        html_attrs={"title": "Reprocess all records in this batch"},
    )
    def reprocess_batch(self, request: HttpRequest, pk: str) -> "HttpResponse":
        obj: CountryBatch | None = self.get_object(request, pk)
        if not obj:
            return HttpResponse("Batch not found", status=404)

        def execute_reprocess(req: HttpRequest) -> None:
            job = AsyncJob.objects.create(
                description=f"Reprocess batch: {obj.name}",
                type=AsyncJob.JobType.TASK,
                owner=req.user,
                action=fqn("country_workspace.workspaces.admin.batch_reprocessing.reprocess_batch"),
                program=obj.program,
                batch=obj,
                config={"batch_id": obj.pk},
            )
            job.queue()

        return confirm_action(
            self,
            request,
            execute_reprocess,
            message=f"Are you sure you want to reprocess batch '{obj.name}'?",
            description="This will re-validate all households and individuals in this batch.",
            success_message="Batch reprocessing has been scheduled.",
            pk=pk,
            title="Reprocess Batch",
        )
