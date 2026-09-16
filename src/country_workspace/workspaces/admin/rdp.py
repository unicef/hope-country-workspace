import json
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from typing import Any

import sentry_sdk
from admin_extra_buttons.api import button, link
from admin_extra_buttons.buttons import LinkButton, StandardButton
from django.contrib import messages
from django.contrib.admin import display, register
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.dateformat import format as date_format
from django.utils.dateparse import parse_datetime
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from country_workspace.compat.admin_extra_buttons import confirm_action
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Rdp, RdpOperation
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.contrib.hope.ocr import claim_rdp_ocr, get_ocr_policy, run_ocr_core
from country_workspace.rdp import (
    RdpActionPolicy,
    RdpWorkflowError,
    cancel_rdp,
    create_clean_rdp as create_clean_rdp_workflow,
    claim_review_rdp_push,
    failed_rdp_operations,
    get_push_policy,
    get_rdp_policy,
    qs_biometric_affected_individuals,
    retry_failed_rdp_operations,
    retry_rdp_push,
)
from country_workspace.state import state
from country_workspace.workspaces.models import CountryRdp
from country_workspace.workspaces.options import WorkspaceModelAdmin
from country_workspace.workspaces.sites import workspace

from .filters import ChoiceFilter
from .hh_ind import SelectedProgramMixin


type PolicyGetter = Callable[[CountryRdp], RdpActionPolicy]


def _is_visible(btn: StandardButton, policy_getter: PolicyGetter, action: str) -> bool:
    return bool((obj := btn.original) and getattr(policy_getter(obj), action)())


def _is_allowed(btn: StandardButton, policy_getter: PolicyGetter, action: str) -> bool:
    if (obj := btn.original) is None:
        return False
    try:
        return getattr(policy_getter(obj), action)().allowed
    except RemoteUnavailableError as exc:
        sentry_sdk.capture_exception(exc)
        return False
    except RemoteError:
        return False


def _has_failed_operations(btn: StandardButton) -> bool:
    return bool(
        (obj := btn.original) and obj.status == Rdp.PushStatus.PENDING and failed_rdp_operations(rdp_id=obj.pk).exists()
    )


@register(CountryRdp, site=workspace)
class CountryRdpAdmin(SelectedProgramMixin, WorkspaceModelAdmin):
    list_display = ("name", "push_date", "status")
    list_filter = (("status", ChoiceFilter),)
    search_fields = ("name",)
    ordering = ("-push_date",)
    readonly_fields = (
        "name",
        "status",
        "push_date",
        "hope_rdi_id",
        "operations_display",
        "processing_history",
        "rdp_log_display",
        "ocr_run_display",
    )

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        """Format an admin datetime."""
        return date_format(timezone.localtime(value), "Y-m-d H:i:s") if value else "-"

    @staticmethod
    def _format_log_entry(entry: dict[str, Any], *, action: str | None = None) -> dict[str, str]:
        """Format a log entry for display."""
        timestamp = entry.get("timestamp", "-")
        if isinstance(timestamp, str) and (dt := parse_datetime(timestamp)):
            timestamp = date_format(timezone.localtime(dt), "Y-m-d H:i:s")

        result = entry.get("result")
        return {
            "action": action if action is not None else str(entry.get("action", "-")),
            "timestamp": str(timestamp),
            "result": json.dumps(result, indent=2, ensure_ascii=False) if result else "",
        }

    def get_fieldsets(
        self,
        request: HttpRequest,
        obj: CountryRdp | None = None,
    ) -> list[tuple[str | None, dict[str, Any]]]:
        fieldsets = [
            (_("RDP details"), {"fields": ("name", "status", "push_date", "hope_rdi_id")}),
        ]

        if obj and obj.operations.exists():
            fieldsets.append((_("Operations"), {"fields": ("operations_display",), "classes": ("content-only",)}))

        if obj and hasattr(obj, "ocr_run"):
            fieldsets.append((_("OCR"), {"fields": ("ocr_run_display",), "classes": ("content-only",)}))

        fieldsets.extend(
            [
                (_("Processing history"), {"fields": ("processing_history",), "classes": ("content-only",)}),
                (_("RDP log"), {"fields": ("rdp_log_display",), "classes": ("content-only",)}),
            ]
        )
        return fieldsets

    def has_change_permission(self, request: HttpRequest, obj: CountryRdp | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: CountryRdp | None = None) -> bool:
        return False

    def has_add_permission(self, request: HttpRequest, obj: CountryRdp | None = None) -> bool:
        return False

    def get_queryset(self, request: HttpRequest) -> QuerySet[CountryRdp]:
        return super().get_queryset(request).select_related("program__beneficiary_group").filter(program=state.program)

    @display(description="")
    def operations_display(self, obj: CountryRdp) -> str:
        """Return RDP operation execution details."""
        operations = list(obj.operations.order_by("operation_type"))
        if not operations:
            return "-"
        rows = []
        for operation in operations:
            successful = operation.status == RdpOperation.Status.SUCCESS
            biometric = operation.operation_type == RdpOperation.Type.BIOMETRIC_DEDUPLICATION
            rows.append(
                {
                    "id": str(operation.id),
                    "type": operation.get_operation_type_display(),
                    "status": operation.get_status_display(),
                    "attempts": operation.attempt,
                    "started_at": self._format_datetime(operation.started_at),
                    "finished_at": self._format_datetime(operation.finished_at),
                    "config": json.dumps(operation.config, indent=2, ensure_ascii=False) if operation.config else "",
                    "error": json.dumps(operation.error, indent=2, ensure_ascii=False) if operation.error else "",
                    "log": [self._format_log_entry(entry) for entry in operation.log],
                    "findings": operation.findings.count() if biometric and successful else None,
                    "affected_individuals": (
                        qs_biometric_affected_individuals(operation=operation).count()
                        if biometric and successful
                        else None
                    ),
                }
            )
        return render_to_string("workspace/rdp/_operations.html", {"rows": rows})

    @display(description="")
    def processing_history(self, obj: CountryRdp) -> str:
        jobs = list(obj.jobs.order_by("datetime_created"))
        if not jobs:
            return "-"

        rows = [
            {
                "url": reverse("workspace:workspaces_countryasyncjob_change", args=[job.pk]),
                "step": job.description or _("Background job"),
                "scheduled_at": self._format_datetime(job.datetime_queued),
                "status": job.task_status or "-",
            }
            for job in jobs
        ]

        return render_to_string("workspace/rdp/_processing_history.html", {"rows": rows})

    @display(description="")
    def rdp_log_display(self, obj: CountryRdp) -> str:
        """Return the formatted RDP log."""
        rows = []
        for entry in obj.operation_log:
            action = entry.get("action", "-")
            with suppress(TypeError, ValueError):
                action = RdpLogEntryType(action).label
            rows.append(self._format_log_entry(entry, action=str(action)))

            result = entry.get("result")
            rows.append(
                {
                    "action": action,
                    "timestamp": timestamp,
                    "result": json.dumps(result, indent=2, ensure_ascii=False) if result else "",
                }
            )

        return render_to_string("workspace/rdp/_log.html", {"rows": rows}) if rows else "-"

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

    def _deny_if_not_allowed(
        self,
        request: HttpRequest,
        obj: CountryRdp,
        policy_getter: PolicyGetter,
        action: str,
    ) -> HttpResponse | None:
        def deny(message: str) -> HttpResponse:
            messages.error(request, message)
            return redirect(self._change_url(obj))

        try:
            check = getattr(policy_getter(obj), action)()
        except RemoteUnavailableError as exc:
            sentry_sdk.capture_exception(exc)
            return deny(str(exc))
        except RemoteError as exc:
            return deny(str(exc))

        return None if check.allowed else deny(check.reason or "Action is not allowed.")

    @button(
        label="Cancel RDP",
        change_form=True,
        change_list=False,
        permission="country_workspace.cancel_rdp",
        visible=lambda btn: _is_visible(btn, get_rdp_policy, "is_cancel_visible"),
        enabled=lambda btn: _is_allowed(btn, get_rdp_policy, "cancel_check"),
        html_attrs={"title": "Cancel this RDP."},
    )
    def cancel(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Cancel an RDP and schedule DedupEngine cleanup when required."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        if response := self._deny_if_not_allowed(request, obj, get_rdp_policy, "cancel_check"):
            return response

        def apply_cancel(_: HttpRequest) -> HttpResponse:
            try:
                check, rejection_scheduled = cancel_rdp(rdp_id=obj.pk, user_id=request.user.pk)
            except RemoteUnavailableError as exc:
                sentry_sdk.capture_exception(exc)
                messages.error(request, str(exc))
            except RemoteError as exc:
                messages.error(request, str(exc))
            else:
                if not check.allowed:
                    messages.error(request, check.reason or "Action is not allowed.")
                elif rejection_scheduled:
                    messages.success(request, "RDP cancelled. DedupEngine rejection task scheduled.")
                else:
                    messages.success(request, "RDP cancelled.")

            return redirect(self._change_url(obj))

        if obj.hope_rdi_id not in {None, "N/A"}:
            return confirm_action(
                self,
                request,
                apply_cancel,
                message=(
                    f"This RDP is linked to HOPE RDI {obj.hope_rdi_id}. "
                    "Confirm that it has been deleted manually in HOPE before continuing."
                ),
                template="workspace/admin_extra_buttons/confirm.html",
            )

        return apply_cancel(request)

    @button(
        label="Retry failed operations",
        change_form=True,
        change_list=False,
        permission="country_workspace.create_rdp",
        visible=_has_failed_operations,
        html_attrs={"title": "Retry failed RDP operations."},
    )
    def retry_failed_operations(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Retry failed RDP operations."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        count = retry_failed_rdp_operations(rdp_id=obj.pk, owner_id=request.user.pk)
        if count:
            messages.success(request, f"{count} failed operation(s) scheduled for retry.")
        else:
            messages.warning(request, "No failed operations available for retry.")

        return redirect(self._change_url(obj))

    @button(
        label="Push all to HOPE",
        change_form=True,
        change_list=False,
        permission="country_workspace.push_rdp_to_hope",
        visible=lambda btn: bool((obj := btn.original) and obj.status == Rdp.PushStatus.REVIEW_PENDING),
        enabled=lambda btn: _is_allowed(btn, get_push_policy, "review_push_check"),
        html_attrs={"title": "Push all RDP beneficiaries despite exceeding the threshold."},
    )
    def push_review(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Push all RDP beneficiaries after review approval."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        if response := self._deny_if_not_allowed(request, obj, get_push_policy, "review_push_check"):
            return response

        def schedule_push(_: HttpRequest) -> HttpResponse:
            check, rdp = claim_review_rdp_push(rdp_id=obj.pk, user_id=request.user.pk)

            if check.allowed and rdp is not None:
                messages.success(request, "Push to HOPE task scheduled")
            else:
                messages.error(request, check.reason or "Action is not allowed.")

            return redirect(self._change_url(obj))

        return confirm_action(
            self,
            request,
            schedule_push,
            message="The configured threshold was exceeded. Confirm that you want to push all RDP beneficiaries.",
            template="workspace/admin_extra_buttons/confirm.html",
        )

    @button(
        label="Retry push to HOPE",
        change_form=True,
        change_list=False,
        permission="country_workspace.push_rdp_to_hope",
        visible=lambda btn: bool((obj := btn.original) and obj.status == Rdp.PushStatus.FAILURE),
        enabled=lambda btn: _is_allowed(btn, get_push_policy, "retry_push_check"),
        html_attrs={"title": "Retry the failed push to HOPE."},
    )
    def retry_push(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Retry a failed RDP push to HOPE."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        check, rdp = retry_rdp_push(rdp_id=obj.pk, user_id=request.user.pk)
        if check.allowed and rdp is not None:
            messages.success(request, "Push to HOPE retry scheduled.")
        else:
            messages.error(request, check.reason or "Action is not allowed.")

        return redirect(self._change_url(obj))

    @button(
        label="Create clean RDP",
        change_form=True,
        change_list=False,
        permission="country_workspace.push_rdp_to_hope",
        visible=lambda btn: bool((obj := btn.original) and obj.status == Rdp.PushStatus.REVIEW_PENDING),
        html_attrs={"title": "Create a new RDP excluding beneficiaries affected by biometric findings."},
    )
    def create_clean_rdp(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Cancel this RDP and create a new one without beneficiaries affected by biometric findings."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        def apply(_: HttpRequest) -> HttpResponse:
            try:
                check, clean_rdp = create_clean_rdp_workflow(rdp_id=obj.pk, user_id=request.user.pk)
            except RemoteUnavailableError as exc:
                sentry_sdk.capture_exception(exc)
                messages.error(request, str(exc))
            except RemoteError as exc:
                messages.error(request, str(exc))
            except RdpWorkflowError as exc:
                messages.error(request, "; ".join(exc.args[0]["errors"]))
            else:
                if check.allowed and clean_rdp is not None:
                    messages.success(request, "Clean RDP created. DedupEngine rejection task scheduled.")
                    return redirect(self._change_url(clean_rdp))
                messages.error(request, check.reason or "Action is not allowed.")
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

        message = "Cancel this RDP and create a new one excluding beneficiaries affected by biometric findings? "
        if obj.hope_rdi_id not in {None, "N/A"}:
            message += f"Confirm HOPE RDI {obj.hope_rdi_id} has been deleted manually. "
        message += "The old DedupEngine set will be scheduled for rejection."
        return confirm_action(
            self, request, apply, message=message, template="workspace/admin_extra_buttons/confirm.html"
        )

    @link(change_list=False, html_attrs={"title": "Shows related beneficiary records."})
    def records(self, btn: LinkButton) -> None:
        obj = btn.context["original"]
        item = "countryhousehold" if obj.program.beneficiary_group.master_detail else "countryindividual"
        base = reverse(f"workspace:workspaces_{item}_changelist")
        btn.href = f"{base}?rdp_id={obj.pk}"
