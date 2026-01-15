from typing import Any

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.api import button, link

from django.contrib import messages
from django.contrib.admin import register
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html
from strategy_field.utils import fqn

from country_workspace.contrib.dedup_engine import dedup, dedup_was_successful
from country_workspace.contrib.hope.push import PushExistingRdpConfig, push_existing_rdp_core
from country_workspace.models import AsyncJob

from ...state import state
from ..models import CountryRdp
from ..options import WorkspaceModelAdmin
from ..sites import workspace
from .filters import ChoiceFilter
from .hh_ind import SelectedProgramMixin


@register(CountryRdp, site=workspace)
class CountryRdpAdmin(SelectedProgramMixin, WorkspaceModelAdmin):
    list_display = ("name", "push_date", "status", "dedup_state")
    list_filter = (("status", ChoiceFilter),)
    readonly_fields = fields = ("name", "push_date", "status", "hope_rdi_id", "dedup_state", "related_job")
    search_fields = ("name",)
    change_list_template = ["workspace/change_list.html"]
    change_form_template = ["workspace/change_form.html"]
    ordering = ("-push_date",)

    def has_change_permission(self, request: HttpRequest, obj: CountryRdp | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: CountryRdp | None = None) -> bool:
        return False

    def has_add_permission(self, request: HttpRequest, obj: CountryRdp | None = None) -> bool:
        return False

    def get_common_context(self, request: HttpRequest, pk: str | None = None, **kwargs: Any) -> dict[str, Any]:
        kwargs["modeladmin"] = self
        kwargs["modeladmin_name"] = self.__class__.__name__
        return super().get_common_context(request, pk, **kwargs)

    def get_queryset(self, request: HttpRequest) -> QuerySet[CountryRdp]:
        return super().get_queryset(request).select_related("program__beneficiary_group").filter(program=state.program)

    def related_job(self, obj: CountryRdp) -> str:
        if job := obj.jobs.first():
            url = reverse("workspace:workspaces_countryasyncjob_change", args=[job.pk])
            return format_html('<a href="{}" style="color: var(--link-fg)">{}</a>', url, str(job))
        return "-"

    def dedup_state(self, obj: CountryRdp) -> str:
        return "<STATUS>. Findings: <num>"

    def _change_url(self, obj: CountryRdp) -> str:
        try:
            return reverse("workspace:workspaces_countryrdp_change", args=[obj.pk])
        except NoReverseMatch:
            return reverse("workspace:workspaces_countryrdp_changelist")

    @button(
        label="Deduplicate",
        change_form=True,
        change_list=False,
        permission="country_workspace.push_beneficiary_to_hope",
        html_attrs={"title": "Run Dedup on DedupEngine."},
    )
    def deduplicate(self, request: HttpRequest, pk: str) -> HttpResponse:
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        job = AsyncJob.objects.create(
            description="Dedup",
            type=AsyncJob.JobType.TASK,
            owner=request.user,
            action=fqn(dedup),
            program=obj.program,
            rdp=obj,
            config={"rdp_id": obj.pk},
        )
        job.queue()

        messages.success(request, "Dedup task scheduled")
        return redirect(self._change_url(obj))

    @button(
        label="Push to HOPE",
        change_form=True,
        change_list=False,
        permission="country_workspace.push_beneficiary_to_hope",
        enabled=dedup_was_successful,
        html_attrs={"title": "Push beneficiaries to HOPE."},
    )
    def push(self, request: HttpRequest, pk: str) -> HttpResponse:
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        config: PushExistingRdpConfig = {"rdp_id": obj.pk}
        job = AsyncJob.objects.create(
            description="Push to HOPE",
            type=AsyncJob.JobType.TASK,
            owner=request.user,
            action=fqn(push_existing_rdp_core),
            program=obj.program,
            rdp=obj,
            config=config,
        )
        job.queue()

        messages.success(request, "Push to HOPE task scheduled")
        return redirect(self._change_url(obj))

    @link(change_list=False, html_attrs={"title": "Shows related beneficiary records."})
    def records(self, btn: LinkButton) -> None:
        obj = btn.context["original"]
        if obj.status == CountryRdp.PushStatus.SUCCESS:
            btn.visible = False
            return
        item = "countryhousehold" if obj.program.beneficiary_group.master_detail else "countryindividual"
        base = reverse(f"workspace:workspaces_{item}_changelist")
        btn.href = f"{base}?rdp__exact={obj.pk}"
