from typing import Any

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.api import button, link
import sentry_sdk

from django.contrib import messages
from django.contrib.admin import register
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html_join
from strategy_field.utils import fqn

from country_workspace.contrib.dedup_engine import DeduplicationSetState, get_deduplication_status, make_dedup_client
from country_workspace.contrib.dedup_engine.deduplication_status import (
    CLONEABLE_DEDUPLICATION_SET_STATES,
    DedupResponseStatus,
)
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.contrib.hope.forms import CreateRDPForm
from country_workspace.contrib.hope.push import (
    PushExistingRdpConfig,
    clone_rdp_core,
    dedup_existing_rdp_core,
    push_existing_rdp_core,
    reject_deduplication_set_existing_rdp_core,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob
from country_workspace.utils.fields import rdi_name_default


from ...state import state
from ..models import CountryRdp
from ..options import WorkspaceModelAdmin
from ..sites import workspace
from .filters import ChoiceFilter
from .hh_ind import SelectedProgramMixin


from admin_extra_buttons.buttons import ButtonWidget


def visible_clone_rdp(btn: ButtonWidget) -> bool:
    return bool((obj := btn.original) and obj.program.biometric_deduplication_enabled)


def enabled_clone_rdp(btn: ButtonWidget) -> bool:
    obj = btn.original
    if obj is None:
        return False

    owner = obj.parent or obj

    pending_qs = CountryRdp.objects.filter(
        program_id=owner.program_id,
        status=obj.PushStatus.PENDING,
    )
    if obj.status == obj.PushStatus.PENDING:
        pending_qs = pending_qs.exclude(pk=obj.pk)
    if pending_qs.exists():
        return False

    if not owner.deduplication_set_id:
        return False

    status = get_deduplication_status(
        owner.program.unicef_id,
        str(owner.deduplication_set_id),
    )
    if status.response_status != DedupResponseStatus.OK:
        return False

    return status.deduplication_set_status in CLONEABLE_DEDUPLICATION_SET_STATES


def visible_workflow(btn: ButtonWidget) -> bool:
    if (obj := btn.original) is None:
        return False
    return obj.status == obj.PushStatus.PENDING


def visible_deduplicate(btn: ButtonWidget) -> bool:
    if (obj := btn.original) is None:
        return False
    return bool(obj.status == obj.PushStatus.PENDING and obj.program.biometric_deduplication_enabled)


def enabled_deduplicate(btn: ButtonWidget) -> bool:
    obj = btn.original
    is_available = bool(obj and obj.status == obj.PushStatus.PENDING and obj.program.biometric_deduplication_enabled)
    if not is_available:
        return False

    try:
        if obj.deduplication_set_id:
            with make_dedup_client(
                obj.program.unicef_id,
                deduplication_set_id=str(obj.deduplication_set_id),
            ) as client:
                payload = client.retrieve_deduplication_set()
            is_available = payload.get("state") != DeduplicationSetState.DEDUPLICATED
        else:
            with make_dedup_client(obj.program.unicef_id) as client:
                is_available = client.can_create_deduplication_set()
    except RemoteUnavailableError as exc:
        sentry_sdk.capture_exception(exc)
        is_available = False
    except RemoteError:
        is_available = False

    return is_available


def visible_reject_ds(btn: ButtonWidget) -> bool:
    if (obj := btn.original) is None:
        return False
    return bool(
        obj.status == obj.PushStatus.PENDING
        and obj.program.biometric_deduplication_enabled
        and obj.deduplication_set_id
    )


def enabled_reject_ds(btn: ButtonWidget) -> bool:
    obj = btn.original
    if obj is None:
        return False

    if not (
        obj.status == obj.PushStatus.PENDING
        and obj.program.biometric_deduplication_enabled
        and obj.deduplication_set_id
    ):
        return False

    try:
        with make_dedup_client(
            obj.program.unicef_id,
            deduplication_set_id=str(obj.deduplication_set_id),
        ) as client:
            payload = client.retrieve_deduplication_set()
    except RemoteUnavailableError as exc:
        sentry_sdk.capture_exception(exc)
        return False
    except RemoteError:
        return False

    return payload.get("state") == DeduplicationSetState.DEDUPLICATED


def enabled_push(btn: ButtonWidget) -> bool:
    obj = btn.original
    can_push = bool(obj is not None and obj.status == obj.PushStatus.PENDING)
    if can_push and obj.program.biometric_deduplication_enabled and obj.deduplication_set_id:
        try:
            with make_dedup_client(
                obj.program.unicef_id,
                deduplication_set_id=str(obj.deduplication_set_id),
            ) as client:
                can_push = client.can_create_deduplication_set()
                if not can_push:
                    payload = client.retrieve_deduplication_set()
                    can_push = payload.get("state") == DeduplicationSetState.DEDUPLICATED
        except RemoteUnavailableError as exc:
            sentry_sdk.capture_exception(exc)
            can_push = False
        except RemoteError:
            can_push = False

    return can_push


@register(CountryRdp, site=workspace)
class CountryRdpAdmin(SelectedProgramMixin, WorkspaceModelAdmin):
    list_display = ("name", "push_date", "status", "deduplication_set_id")
    list_filter = (("status", ChoiceFilter),)
    search_fields = ("name", "deduplication_set_id")
    change_list_template = ["workspace/change_list.html"]
    change_form_template = ["workspace/change_form.html"]
    ordering = ("-push_date",)

    def get_fields(self, request: HttpRequest, obj: CountryRdp | None = None) -> list[str]:
        fields = [
            "name",
            "parent",
            "push_date",
            "status",
            "biometric_deduplication_enabled",
        ]
        if obj and obj.program.biometric_deduplication_enabled:
            fields.extend(("dedup_engine_state", "deduplication_set_id"))
        fields.append("related_jobs")
        return fields

    def get_readonly_fields(self, request: HttpRequest, obj: CountryRdp | None = None) -> list[str]:
        return self.get_fields(request, obj)

    def biometric_deduplication_enabled(self, obj: CountryRdp) -> bool:
        return obj.program.biometric_deduplication_enabled

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

    def related_jobs(self, obj: CountryRdp) -> str:
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
        result = "-"
        response_status = DedupResponseStatus.OK
        deduplication_set_status: str | None = None
        findings_count = -1

        if obj.status == obj.PushStatus.PENDING:
            try:
                if obj.deduplication_set_id:
                    resp = get_deduplication_status(
                        obj.program.unicef_id,
                        str(obj.deduplication_set_id),
                    )
                    response_status = resp.response_status
                    deduplication_set_status = resp.deduplication_set_status
                    findings_count = resp.findings_count
                else:
                    with make_dedup_client(obj.program.unicef_id) as client:
                        deduplication_set_status = (
                            "Ready to start"
                            if client.can_create_deduplication_set()
                            else "Blocked / another active deduplication set"
                        )
            except RemoteUnavailableError:
                response_status = DedupResponseStatus.STATUS_UNAVAILABLE
            except RemoteError:
                response_status = None

            if response_status == DedupResponseStatus.STATUS_UNAVAILABLE:
                result = DedupResponseStatus.STATUS_UNAVAILABLE.value
            elif response_status != DedupResponseStatus.OK:
                result = "Remote error"
            elif deduplication_set_status is None:
                result = "Created / waiting for status"
            elif obj.deduplication_set_id and findings_count >= 0:
                result = f"{deduplication_set_status} / {findings_count} findings"
            else:
                result = deduplication_set_status

        return result

    def _change_url(self, obj: CountryRdp) -> str:
        try:
            return reverse("workspace:workspaces_countryrdp_change", args=[obj.pk])
        except NoReverseMatch:
            return reverse("workspace:workspaces_countryrdp_changelist")

    @button(
        label="Deduplicate",
        change_form=True,
        change_list=False,
        permission="country_workspace.deduplicate_rdp",
        enabled=enabled_deduplicate,
        visible=visible_deduplicate,
        html_attrs={"title": "Run Deduplication process on DedupEngine."},
    )
    def deduplicate(self, request: HttpRequest, pk: str) -> HttpResponse:
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        job = AsyncJob.objects.create(
            description="Run Deduplication process on DedupEngine",
            type=AsyncJob.JobType.TASK,
            owner=request.user,
            action=fqn(dedup_existing_rdp_core),
            program=obj.program,
            rdp=obj,
            config={"rdp_id": obj.pk},
        )
        job.queue()

        messages.success(request, "Dedup task scheduled")
        return redirect(self._change_url(obj))

    @button(
        label="Reject",
        change_form=True,
        change_list=False,
        permission="country_workspace.reject_deduplication_set",
        enabled=enabled_reject_ds,
        visible=visible_reject_ds,
        html_attrs={"title": "Reject this RDP by rejecting its active DE deduplication set."},
    )
    def reject_ds(self, request: HttpRequest, pk: str) -> HttpResponse:
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        job = AsyncJob.objects.create(
            description="Reject RDP by rejecting its active DE deduplication set",
            type=AsyncJob.JobType.TASK,
            owner=request.user,
            action=fqn(reject_deduplication_set_existing_rdp_core),
            program=obj.program,
            rdp=obj,
            config={"rdp_id": obj.pk},
        )
        job.queue()

        messages.success(request, "Reject task scheduled")
        return redirect(self._change_url(obj))

    @button(
        label="Clone RDP",
        change_form=True,
        change_list=False,
        permission="country_workspace.create_rdp",
        visible=visible_clone_rdp,
        enabled=enabled_clone_rdp,
        html_attrs={"title": "Create a child RDP that reuses the parent selection."},
    )
    def clone_rdp(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Create a child RDP without copying beneficiary M2M links."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        if request.method == "POST" and "_clone" in request.POST:
            if (form := CreateRDPForm(request.POST)).is_valid():
                try:
                    cloned = clone_rdp_core(
                        source=obj,
                        batch_name=form.cleaned_data["batch_name"] or rdi_name_default(),
                        pushed_by_id=request.user.id,
                    )
                except HopePushError as e:
                    messages.error(request, str(e))
                else:
                    messages.success(request, "RDP cloned")
                    return redirect(self._change_url(cloned))
        else:
            form = CreateRDPForm(
                initial={
                    "action": "clone_rdp",
                    "select_across": False,
                    "_selected_action": [str(obj.pk)],
                },
            )
        ctx = self.get_common_context(
            request,
            title="Clone RDP",
            form=form,
            original=obj,
            changelist_url=reverse("workspace:workspaces_countryrdp_changelist"),
            original_change_url=self._change_url(obj),
            intro_text="A new RDP will be created using the parent RDP beneficiary selection.",
            submit_label="Clone RDP",
            submit_name="_clone",
        )
        return render(request, "workspace/actions/create_rdp.html", ctx)

    @button(
        label="Push to HOPE",
        change_form=True,
        change_list=False,
        permission="country_workspace.push_rdp_to_hope",
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
            description="Push beneficiaries to HOPE",
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
        owner = obj.parent if obj.parent_id else obj
        btn.href = f"{base}?rdp__exact={owner.pk}"
