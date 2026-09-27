import json
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from typing import Any

import sentry_sdk
from admin_extra_buttons.api import button, link
from django.contrib import messages
from django.contrib.admin import display, register
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.dateformat import format as date_format
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_lazy as _

from country_workspace.compat.admin_extra_buttons import confirm_action
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Rdp, RdpOperation
from country_workspace.models.rdp import RdpLogEntryType, RdpPushStatus
from country_workspace.rdp import (
    RdpActionPolicy,
    RdpWorkflowError,
    biometric_operation_for_rdp,
    claim_rdp_cancel,
    claim_rdp_push,
    create_clean_rdp as create_clean_rdp_workflow,
    claim_review_rdp_push,
    failed_rdp_operations,
    get_push_policy,
    get_rdp_policy,
    qs_biometric_duplicate_individuals,
    retry_failed_rdp_operations,
)
from country_workspace.state import state
from country_workspace.workspaces.models import CountryRdp
from country_workspace.workspaces.options import WorkspaceModelAdmin
from country_workspace.workspaces.sites import workspace


from .filters import ChoiceFilter
from .hh_ind import SelectedProgramMixin
from django.http import HttpRequest, HttpResponse
from django.db.models import QuerySet
from admin_extra_buttons.buttons import LinkButton, StandardButton


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
        (obj := btn.original) and obj.status == RdpPushStatus.PENDING and failed_rdp_operations(rdp_id=obj.pk).exists()
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
        "biometric_findings_count",
        "marked_individuals_count",
        "processing_history",
        "operation_log_display",
    )

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        """Format an admin datetime."""
        return date_format(timezone.localtime(value), "Y-m-d H:i:s") if value else "-"

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

        if obj and biometric_operation_for_rdp(rdp=obj):
            fieldsets.append(
                (
                    _("Deduplication"),
                    {"fields": ("biometric_findings_count", "marked_individuals_count")},
                )
            )

        fieldsets.extend(
            [
                (_("Processing history"), {"fields": ("processing_history",), "classes": ("content-only",)}),
                (_("RDP log"), {"fields": ("operation_log_display",), "classes": ("content-only",)}),
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

        rows = [
            {
                "type": operation.get_operation_type_display(),
                "status": operation.get_status_display(),
                "attempts": operation.attempt,
                "started_at": self._format_datetime(operation.started_at),
                "finished_at": self._format_datetime(operation.finished_at),
                "error": str(operation.error.get("message") or "-"),
            }
            for operation in operations
        ]
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
    def operation_log_display(self, obj: CountryRdp) -> str:
        """Return formatted RDP operation log."""
        if not obj.operation_log:
            return "-"

        rows = []
        for entry in obj.operation_log:
            action = entry.get("action", "-")
            with suppress(TypeError, ValueError):
                action = RdpLogEntryType(action).label

            timestamp = entry.get("timestamp", "-")
            if isinstance(timestamp, str) and (dt := parse_datetime(timestamp)):
                timestamp = date_format(timezone.localtime(dt), "Y-m-d H:i:s")

            result = entry.get("result")
            rows.append(
                {
                    "action": action,
                    "timestamp": timestamp,
                    "result": json.dumps(result, indent=2, ensure_ascii=False) if result else "",
                }
            )

        return render_to_string("workspace/rdp/_operation_log.html", {"rows": rows})

    @display(description=_("Findings"))
    def biometric_findings_count(self, obj: CountryRdp) -> int | str:
        """Return the number of biometric findings."""
        operation = biometric_operation_for_rdp(rdp=obj)
        if operation is None or operation.status != RdpOperation.Status.SUCCESS:
            return "-"
        return operation.findings.count()

    @display(description=_("Marked individuals"))
    def marked_individuals_count(self, obj: CountryRdp) -> int | str:
        """Return the number of locally marked duplicate individuals."""
        operation = biometric_operation_for_rdp(rdp=obj)
        if operation is None or operation.status != RdpOperation.Status.SUCCESS:
            return "-"
        return qs_biometric_duplicate_individuals(operation=operation).count()

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

    def _schedule_push(self, request: HttpRequest, obj: CountryRdp) -> HttpResponse:
        """Schedule an allowed push."""
        check, locked = claim_rdp_push(rdp_id=obj.pk, user_id=request.user.pk)

        if not check.allowed or locked is None:
            messages.error(request, check.reason or "Action is not allowed.")
        elif locked.status == Rdp.PushStatus.REVIEW_PENDING:
            messages.warning(request, "The configured threshold was exceeded. Review this RDP before pushing.")
        else:
            messages.success(request, "Push to HOPE task scheduled")

        return redirect(self._change_url(obj))

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
                check, rejection_queued = claim_rdp_cancel(rdp_id=obj.pk, user_id=request.user.pk)
            except RemoteUnavailableError as exc:
                sentry_sdk.capture_exception(exc)
                messages.error(request, str(exc))
            except RemoteError as exc:
                messages.error(request, str(exc))
            else:
                if not check.allowed:
                    messages.error(request, check.reason or "Action is not allowed.")
                elif rejection_queued:
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
        label="Push to HOPE",
        change_form=True,
        change_list=False,
        permission="country_workspace.push_rdp_to_hope",
        visible=lambda btn: _is_visible(btn, get_push_policy, "is_push_visible"),
        enabled=lambda btn: _is_allowed(btn, get_push_policy, "push_check"),
        html_attrs={"title": "Push beneficiaries to HOPE."},
    )
    def push(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Start a push to HOPE."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        return self._schedule_push(request, obj)

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
            check, locked = claim_review_rdp_push(rdp_id=obj.pk, user_id=request.user.pk)

            if check.allowed and locked is not None:
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

        message = "Cancel this RDP and create a new one excluding beneficiaries affected by biometric findings? "
        if obj.hope_rdi_id not in {None, "N/A"}:
            message += f"Confirm HOPE RDI {obj.hope_rdi_id} has been deleted manually. "
        message += "The old DedupEngine set will be queued for rejection."
        return confirm_action(
            self, request, apply, message=message, template="workspace/admin_extra_buttons/confirm.html"
        )

    @link(change_list=False, html_attrs={"title": "Shows related beneficiary records."})
    def records(self, btn: LinkButton) -> None:
        obj = btn.context["original"]
        item = "countryhousehold" if obj.program.beneficiary_group.master_detail else "countryindividual"
        base = reverse(f"workspace:workspaces_{item}_changelist")
        btn.href = f"{base}?rdp_id={obj.pk}"
