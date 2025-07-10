from typing import Any

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from django.contrib.admin import register
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from ...state import state
from ..models import CountryRdp
from ..options import WorkspaceModelAdmin
from ..sites import workspace
from .filters import ChoiceFilter
from .hh_ind import SelectedProgramMixin


@register(CountryRdp, site=workspace)
class CountryRdpAdmin(SelectedProgramMixin, WorkspaceModelAdmin):
    list_display = ("name", "push_date", "status")
    list_filter = (("status", ChoiceFilter),)
    readonly_fields = fields = ("name", "push_date", "status", "hope_rdi_id", "related_job")
    search_fields = ("name",)
    change_list_template = ["workspace/change_list.html"]
    change_form_template = ["workspace/change_form.html"]
    ordering = ("-push_date",)

    def has_change_permission(self, request: HttpRequest, obj: CountryRdp | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: CountryRdp | None = None) -> bool:
        return False

    def get_common_context(self, request: HttpRequest, pk: str | None = None, **kwargs: Any) -> dict[str, Any]:
        kwargs["modeladmin"] = self
        kwargs["modeladmin_name"] = self.__class__.__name__
        return super().get_common_context(request, pk, **kwargs)

    def related_job(self, obj: CountryRdp) -> str:
        if job := obj.jobs.first():
            url = reverse("workspace:workspaces_countryasyncjob_change", args=[job.pk])
            return format_html('<a href="{}" style="color: var(--link-fg)">{}</a>', url, str(job))
        return "-"

    def get_queryset(self, request: HttpRequest) -> QuerySet[CountryRdp]:
        return super().get_queryset(request).select_related("program__beneficiary_group").filter(program=state.program)

    def has_add_permission(self, request: HttpRequest, obj: CountryRdp | None = None) -> bool:
        return False

    @link(change_list=False, html_attrs={"title": "Shows related beneficiary records."})
    def records(self, button: LinkButton) -> None:
        obj = button.context["original"]
        if obj.status == CountryRdp.PushStatus.SUCCESS:
            button.visible = False
            return
        item = "countryhousehold" if obj.program.beneficiary_group.master_detail else "countryindividual"
        base = reverse(f"workspace:workspaces_{item}_changelist")
        button.href = f"{base}?rdp__exact={obj.pk}"
