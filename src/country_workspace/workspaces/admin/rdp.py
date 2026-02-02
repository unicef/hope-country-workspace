from typing import Any

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.api import button, link
from requests.exceptions import RequestException
import sentry_sdk

from django.contrib import messages
from django.contrib.admin import register
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html_join
from strategy_field.utils import fqn

from country_workspace.contrib.dedup_engine.client import Status as DedupClientStatus, make_client
from country_workspace.contrib.dedup_engine.response import Status as DedupResponseStatus
from country_workspace.contrib.hope.push import PushExistingRdpConfig, dedup_existing_rdp_core, push_existing_rdp_core
from country_workspace.models import AsyncJob


from ...state import state
from ..models import CountryRdp
from ..options import WorkspaceModelAdmin
from ..sites import workspace
from .filters import ChoiceFilter
from .hh_ind import SelectedProgramMixin


from admin_extra_buttons.buttons import ButtonWidget


def _dedup_status_safe(program_code: str) -> DedupClientStatus:
    """Fetch DedupEngine status for admin UI; capture request failures in Sentry and degrade to UNKNOWN."""
    try:
        with make_client(program_code) as client:
            return client.status()
    except RequestException as e:
        sentry_sdk.capture_exception(e)
        return DedupClientStatus(DedupResponseStatus.UNKNOWN, -1)


def visible_workflow(btn: ButtonWidget) -> bool:
    if (obj := btn.original) is None:
        return False
    return obj.status == obj.PushStatus.PENDING


def enabled_deduplicate(btn: ButtonWidget) -> bool:
    obj = btn.original
    if obj is None or obj.status != obj.PushStatus.PENDING:
        return False

    if not obj.program.biometric_deduplication_enabled:
        return False

    match obj.dedup_run_state:
        case obj.DedupRunState.NOT_RUN:
            return True
        case obj.DedupRunState.IN_PROGRESS:
            return _dedup_status_safe(obj.program.code).status in {
                DedupResponseStatus.FAILURE,
                DedupResponseStatus.REVOKED,
                DedupResponseStatus.UNKNOWN,
                DedupResponseStatus.NOT_SCHEDULED,
            }
        case _:
            return False


def enabled_push(btn: ButtonWidget) -> bool:
    obj = btn.original
    if obj is None or obj.status != obj.PushStatus.PENDING:
        return False

    if not obj.program.biometric_deduplication_enabled:
        return True

    match obj.dedup_run_state:
        case obj.DedupRunState.IN_PROGRESS:
            return _dedup_status_safe(obj.program.code).status == DedupResponseStatus.SUCCESS
        case _:
            return False


@register(CountryRdp, site=workspace)
class CountryRdpAdmin(SelectedProgramMixin, WorkspaceModelAdmin):
    list_display = ("name", "push_date", "status", "dedup_run_state", "deduplication_set_id")
    list_filter = (("status", ChoiceFilter),)
    readonly_fields = fields = (
        "name",
        "push_date",
        "status",
        "biometric_deduplication_enabled",
        "dedup_run_state",
        "dedup_engine_state",
        "deduplication_set_id",
        "related_job",
    )
    search_fields = ("name", "deduplication_set_id")
    change_list_template = ["workspace/change_list.html"]
    change_form_template = ["workspace/change_form.html"]
    ordering = ("-push_date",)

    def biometric_deduplication_enabled(self, obj: CountryRdp) -> bool:
        return bool(obj.program.biometric_deduplication_enabled)

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
        if not (jobs := obj.jobs.order_by("datetime_created")).exists():
            return "-"
        return format_html_join(
            "\n",
            "<div style='display:grid; grid-template-columns:max-content 1fr; column-gap:10px'>"
            "<a href='{}' style='color: var(--link-fg)'>{}</a>"
            "<span style='white-space:nowrap'>{}</span>"
            "</div>",
            (
                (
                    reverse("workspace:workspaces_countryasyncjob_change", args=[job.pk]),
                    str(job),
                    str(job.task_status) if getattr(job, "task_status", None) is not None else "—",
                )
                for job in jobs
            ),
        )

    def dedup_engine_state(self, obj: CountryRdp) -> str:
        if obj.status != obj.PushStatus.PENDING:
            return "N/A"

        match obj.dedup_run_state:
            case obj.DedupRunState.IN_PROGRESS:
                resp = _dedup_status_safe(obj.program.code)
                if resp.status == DedupResponseStatus.SUCCESS:
                    return f"{resp.status.value} with findings={resp.duplicates_found}"
                return resp.status.value
            case _:
                return "N/A"

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
        enabled=enabled_deduplicate,
        visible=visible_workflow,
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
            action=fqn(dedup_existing_rdp_core),
            program=obj.program,
            rdp=obj,
            config={"rdp_id": obj.pk},
        )
        job.queue()

        obj._meta.model.objects.filter(pk=obj.pk).update(dedup_run_state=obj.DedupRunState.IN_PROGRESS)
        messages.success(request, "Dedup task scheduled")
        return redirect(self._change_url(obj))

    @button(
        label="Push to HOPE",
        change_form=True,
        change_list=False,
        permission="country_workspace.push_beneficiary_to_hope",
        enabled=enabled_push,
        visible=visible_workflow,
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
