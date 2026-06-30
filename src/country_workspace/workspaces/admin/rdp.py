from typing import Any

import sentry_sdk
from admin_extra_buttons.api import button, link
from admin_extra_buttons.buttons import LinkButton, StandardButton
from django.contrib import messages
from django.contrib.admin import register
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html_join
from strategy_field.utils import fqn


from country_workspace.contrib.hope.push import (
    DedupEngineState,
    PushExistingRdpConfig,
    claim_rdp_deduplication,
    get_rdp_policy,
    dedup_existing_rdp_core,
    push_existing_rdp_core,
    reject_deduplication_set_existing_rdp_core,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob


from ...state import state
from ..models import CountryRdp
from ..options import WorkspaceModelAdmin
from ..sites import workspace
from .filters import ChoiceFilter
from .hh_ind import SelectedProgramMixin


def _is_visible(btn: StandardButton, action: str) -> bool:
    return bool((obj := btn.original) and getattr(get_rdp_policy(obj), action)())


def _is_allowed(btn: StandardButton, action: str) -> bool:
    if (obj := btn.original) is None:
        return False
    try:
        return getattr(get_rdp_policy(obj), action)().allowed
    except RemoteUnavailableError as exc:
        sentry_sdk.capture_exception(exc)
        return False
    except RemoteError:
        return False


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
            "push_date",
            "status",
        ]
        if obj and obj.program.biometric_deduplication_enabled:
            fields.extend(("dedup_engine_state", "deduplication_set_id", "deduplication_snapshots"))
        fields.append("related_jobs")
        return fields

    def get_readonly_fields(self, request: HttpRequest, obj: CountryRdp | None = None) -> list[str]:
        return self.get_fields(request, obj)

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
        try:
            return str(get_rdp_policy(obj).dedup_engine_state())
        except RemoteUnavailableError:
            return str(DedupEngineState.unavailable())
        except RemoteError as exc:
            return str(exc)

    def _change_url(self, obj: CountryRdp) -> str:
        try:
            return reverse("workspace:workspaces_countryrdp_change", args=[obj.pk])
        except NoReverseMatch:
            return reverse("workspace:workspaces_countryrdp_changelist")

    def _deny_if_not_allowed(self, request: HttpRequest, obj: CountryRdp, action: str) -> HttpResponse | None:
        def deny(message: str) -> HttpResponse:
            messages.error(request, message)
            return redirect(self._change_url(obj))

        try:
            check = getattr(get_rdp_policy(obj), action)()
        except RemoteUnavailableError as exc:
            sentry_sdk.capture_exception(exc)
            return deny(str(exc))
        except RemoteError as exc:
            return deny(str(exc))

        return None if check.allowed else deny(check.reason or "Action is not allowed.")

    @button(
        label="Deduplicate",
        change_form=True,
        change_list=False,
        permission="country_workspace.deduplicate_rdp",
        visible=lambda btn: _is_visible(btn, "is_deduplicate_visible"),
        enabled=lambda btn: _is_allowed(btn, "claim_deduplication_check"),
        html_attrs={"title": "Run Deduplication process on DedupEngine."},
    )
    def deduplicate(self, request: HttpRequest, pk: str) -> HttpResponse:
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        try:
            with transaction.atomic():
                check, locked = claim_rdp_deduplication(rdp_id=obj.pk)
                if not check.allowed or locked is None:
                    messages.error(request, check.reason or "Action is not allowed.")
                    return redirect(self._change_url(obj))
                job = AsyncJob.objects.create(
                    description="Run Deduplication process on DedupEngine",
                    type=AsyncJob.JobType.TASK,
                    owner=request.user,
                    action=fqn(dedup_existing_rdp_core),
                    program=locked.program,
                    rdp=locked,
                    config={"rdp_id": locked.pk},
                )
                transaction.on_commit(job.queue)
        except RemoteUnavailableError as exc:
            sentry_sdk.capture_exception(exc)
            messages.error(request, str(exc))
            return redirect(self._change_url(obj))
        except RemoteError as exc:
            messages.error(request, str(exc))
            return redirect(self._change_url(obj))

        messages.success(request, "Dedup task scheduled")
        return redirect(self._change_url(obj))

    @button(
        label="Reject",
        change_form=True,
        change_list=False,
        permission="country_workspace.reject_deduplication_set",
        visible=lambda btn: _is_visible(btn, "is_reject_ds_visible"),
        enabled=lambda btn: _is_allowed(btn, "reject_ds_check"),
        html_attrs={"title": "Reject this RDP by rejecting its active DE deduplication set."},
    )
    def reject_ds(self, request: HttpRequest, pk: str) -> HttpResponse:
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")
        if response := self._deny_if_not_allowed(request, obj, "reject_ds_check"):
            return response

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
        label="Push to HOPE",
        change_form=True,
        change_list=False,
        permission="country_workspace.push_rdp_to_hope",
        visible=lambda btn: _is_visible(btn, "is_push_visible"),
        enabled=lambda btn: _is_allowed(btn, "push_check"),
        html_attrs={"title": "Push beneficiaries to HOPE."},
    )
    def push(self, request: HttpRequest, pk: str) -> HttpResponse:
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")
        if response := self._deny_if_not_allowed(request, obj, "push_check"):
            return response

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
        btn.href = f"{base}?rdp__exact={obj.pk}"
