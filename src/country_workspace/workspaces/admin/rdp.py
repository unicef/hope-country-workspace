import json
from contextlib import suppress
from typing import Any

import sentry_sdk
from admin_extra_buttons.api import button, link
from admin_extra_buttons.buttons import LinkButton, StandardButton
from django.contrib import messages
from django.contrib.admin import display, register
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.dateformat import format as date_format
from django.utils.dateparse import parse_datetime
from django.utils.html import format_html, format_html_join
from strategy_field.utils import fqn

from country_workspace.contrib.hope.ocr import claim_rdp_ocr, get_ocr_policy, run_ocr_core
from country_workspace.compat.admin_extra_buttons import confirm_action
from country_workspace.rdp import (
    DedupEngineState,
    cancel_existing_rdp_core,
    claim_rdp_deduplication,
    claim_rdp_push,
    dedup_existing_rdp_core,
    get_rdp_policy,
    push_existing_rdp_core,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.state import state

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
            fields.extend(("dedup_engine_state", "deduplication_set_id"))
        if obj and hasattr(obj, "ocr_run"):
            fields.append("ocr_run_display")
        fields.extend(("related_jobs", "operation_log_display"))
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

    @display(description="Operation log")
    def operation_log_display(self, obj: CountryRdp) -> str:
        """Return formatted RDP operation log."""
        if not obj.operation_log:
            return "—"

        rows = []
        for entry in obj.operation_log:
            action = entry.get("action", "—")
            with suppress(TypeError, ValueError):
                action = RdpOperationAction(action).label
            timestamp = entry.get("timestamp", "—")
            if isinstance(timestamp, str) and (dt := parse_datetime(timestamp)):
                timestamp = date_format(timezone.localtime(dt), "Y-m-d H:i:s")
            result = entry.get("result")
            rows.append(
                (
                    action,
                    timestamp,
                    format_html("<pre>{}</pre>", json.dumps(result, indent=2, ensure_ascii=False)) if result else "",
                )
            )

        return format_html_join(
            "",
            "<div><strong>{}</strong> · {}{}</div>",
            rows,
        )

    @display(description="OCR run")
    def ocr_run_display(self, obj: CountryRdp) -> str:
        """Return a compact summary of this RDP's OCR run, if any."""
        try:
            run = obj.ocr_run
        except ObjectDoesNotExist:
            return "-"

        progress = f"{len(run.received_batch_ids)}/{run.batch_total}" if run.batch_total else "-"
        summary = f"{run.get_status_display()} ({progress}) · correlation_id={run.correlation_id}"
        if not run.results:
            return summary

        return format_html(
            "{}<pre>{}</pre>",
            summary,
            json.dumps(run.results, indent=2, ensure_ascii=False),
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
        label="Cancel",
        change_form=True,
        change_list=False,
        permission="country_workspace.cancel_rdp",
        visible=lambda btn: _is_visible(btn, "is_cancel_visible"),
        enabled=lambda btn: _is_allowed(btn, "cancel_check"),
        html_attrs={"title": "Cancel this RDP."},
    )
    def cancel(self, request: HttpRequest, pk: str) -> HttpResponse:
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")
        if response := self._deny_if_not_allowed(request, obj, "cancel_check"):
            return response

        def schedule_cancel(_: HttpRequest) -> HttpResponse:
            AsyncJob.objects.create(
                description="Cancel RDP",
                type=AsyncJob.JobType.TASK,
                owner=request.user,
                action=fqn(cancel_existing_rdp_core),
                program=obj.program,
                rdp=obj,
                config={"rdp_id": obj.pk},
            ).queue()
            messages.success(request, "Cancel task scheduled")
            return redirect(self._change_url(obj))

        if obj.hope_rdi_id not in {None, "N/A"}:
            return confirm_action(
                self,
                request,
                schedule_cancel,
                message=(
                    f"This RDP is linked to HOPE RDI {obj.hope_rdi_id}. "
                    "Confirm that it has been deleted manually in HOPE before continuing."
                ),
            )

        return schedule_cancel(request)

    @button(
        label="Push to HOPE",
        change_form=True,
        change_list=False,
        permission="country_workspace.push_rdp_to_hope",
        visible=lambda btn: _is_visible(btn, "is_push_visible"),
        enabled=lambda btn: _is_allowed(btn, "start_push_check"),
        html_attrs={"title": "Push beneficiaries to HOPE."},
    )
    def push(self, request: HttpRequest, pk: str) -> HttpResponse:
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        try:
            with transaction.atomic():
                check, locked = claim_rdp_push(rdp_id=obj.pk)
                if not check.allowed or locked is None:
                    messages.error(request, check.reason or "Action is not allowed.")
                    return redirect(self._change_url(obj))
                if locked.push_attempt_id is None:
                    raise RuntimeError("RDP push attempt was not initialized.")
                job = AsyncJob.objects.create(
                    description="Prepare RDP for HOPE push",
                    type=AsyncJob.JobType.TASK,
                    owner=request.user,
                    action=fqn(push_existing_rdp_core),
                    program=locked.program,
                    rdp=locked,
                    config={
                        "rdp_id": locked.pk,
                        "push_attempt_id": str(locked.push_attempt_id),
                        "rdi_id_to_reset": None if locked.hope_rdi_id == "N/A" else locked.hope_rdi_id,
                    },
                )
                transaction.on_commit(job.queue)
        except RemoteUnavailableError as exc:
            sentry_sdk.capture_exception(exc)
            messages.error(request, str(exc))
            return redirect(self._change_url(obj))
        except RemoteError as exc:
            messages.error(request, str(exc))
            return redirect(self._change_url(obj))

        messages.success(request, "Push to HOPE task scheduled")
        return redirect(self._change_url(obj))

    @button(
        label="Run OCR",
        change_form=True,
        change_list=False,
        permission="country_workspace.run_ocr_rdp",
        visible=lambda btn: bool((obj := btn.original) and get_ocr_policy(obj).is_ocr_visible()),
        enabled=lambda btn: bool((obj := btn.original) and get_ocr_policy(obj).ocr_check().allowed),
        html_attrs={"title": "Send identity-document images to Hope Documents for OCR."},
    )
    def run_ocr(self, request: HttpRequest, pk: str) -> HttpResponse:
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        check, locked = claim_rdp_ocr(rdp_id=obj.pk)
        if not check.allowed or locked is None:
            messages.error(request, check.reason or "Action is not allowed.")
            return redirect(self._change_url(obj))

        with transaction.atomic():
            job = AsyncJob.objects.create(
                description="Run OCR on RDP identity documents",
                type=AsyncJob.JobType.TASK,
                owner=request.user,
                action=fqn(run_ocr_core),
                program=locked.program,
                rdp=locked,
                config={"rdp_id": locked.pk},
            )
            transaction.on_commit(job.queue)

        messages.success(request, "OCR task scheduled")
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
