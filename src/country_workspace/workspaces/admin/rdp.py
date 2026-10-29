import json
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from typing import Any
from uuid import UUID
from urllib.parse import urlencode

import sentry_sdk
from admin_extra_buttons.api import button, link
from admin_extra_buttons.buttons import LinkButton, StandardButton
from django.contrib import messages
from django.contrib.admin import display, register
from django.core.exceptions import PermissionDenied
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, URLPattern, URLResolver, path, reverse
from django.utils import timezone
from django.utils.dateformat import format as date_format
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_lazy as _

from country_workspace.compat.admin_extra_buttons import confirm_action
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Rdp, RdpOperation
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.rdp import (
    RDP_OPERATION_DEFINITIONS,
    RdpActionPolicy,
    RdpWorkflowError,
    cancel_rdp,
    claim_review_rdp_push,
    create_clean_rdp as create_clean_rdp_workflow,
    get_push_policy,
    get_rdp_policy,
    has_retryable_rdp_operations,
    is_biometric_threshold_exceeded,
    ocr_affected_individuals_count,
    qs_biometric_affected_individuals,
    retry_rdp_operations,
    retry_rdp_push,
)
from country_workspace.state import state
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryRdp
from country_workspace.workspaces.options import WorkspaceModelAdmin
from country_workspace.workspaces.sites import workspace

from .filters import ChoiceFilter
from .forms import RdpFindingsFilterForm
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


def _has_retryable_operations(btn: StandardButton) -> bool:
    return bool(
        (rdp := btn.original) and rdp.status == Rdp.PushStatus.PENDING and has_retryable_rdp_operations(rdp_id=rdp.pk)
    )


def _is_clean_rdp_visible(btn: StandardButton) -> bool:
    """Return whether the biometric threshold contributed to the pending review."""
    if (rdp := btn.original) is None or rdp.status != Rdp.PushStatus.REVIEW_PENDING:
        return False
    with suppress(RdpWorkflowError):
        return is_biometric_threshold_exceeded(rdp=rdp)
    return False


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

    def get_urls(self) -> list[URLPattern | URLResolver]:
        return [
            path(
                "<int:rdp_id>/operations/<uuid:operation_id>/findings/",
                self.admin_site.admin_view(self.findings_view, cacheable=False),
                name="workspaces_countryrdp_findings",
            ),
        ] + super().get_urls()

    def findings_view(self, request: HttpRequest, rdp_id: int, operation_id: UUID) -> HttpResponse:
        """Display saved findings for an operation in the selected workspace context."""
        rdp = get_object_or_404(self.get_queryset(request), pk=rdp_id, country_office=state.tenant)
        individual_admin = self.admin_site.get_model_admin(CountryIndividual)
        if not self.has_view_permission(request, rdp) or not individual_admin.has_view_permission(request):
            raise PermissionDenied

        operation = get_object_or_404(rdp.operations, pk=operation_id)
        definition = RDP_OPERATION_DEFINITIONS.get(operation.operation_type)
        labels = {value: str(label) for value, label in definition.finding_types.choices} if definition else {}

        household_admin = self.admin_site.get_model_admin(CountryHousehold)
        can_view_households = rdp.program.is_master_detail and household_admin.has_view_permission(request)
        filter_form = RdpFindingsFilterForm(
            request.GET,
            finding_types=list(labels.items()),
            include_household=can_view_households,
        )

        findings = operation.findings.order_by("pk")
        if filter_form.is_valid():
            if finding_type := filter_form.cleaned_data["finding_type"]:
                findings = findings.filter(finding_type=finding_type)
            if individual_id := filter_form.cleaned_data["individual_id"]:
                findings = findings.filter(Q(individual_id=individual_id) | Q(related_individual_id=individual_id))
            if household_id := filter_form.cleaned_data.get("household_id"):
                findings = findings.filter(
                    Q(individual__household_id=household_id) | Q(related_individual__household_id=household_id)
                )
        else:
            findings = findings.none()

        rows = findings.values(
            "individual_id",
            "individual__name",
            "individual__household_id",
            "finding_type",
            "field_name",
            "related_individual_id",
            "related_individual__name",
            "related_individual__household_id",
            "details",
        )
        page = self.get_paginator(request, rows, self.list_per_page).get_page(request.GET.get("page"))
        query = {"_changelist_filters": urlencode({"rdp_id": rdp.pk})}

        for finding in page:
            finding["label"] = labels.get(finding["finding_type"], finding["finding_type"])
            finding["individual_url"] = reverse(
                "workspace:workspaces_countryindividual_change", args=[finding["individual_id"]], query=query
            )
            if related_id := finding["related_individual_id"]:
                finding["related_individual_url"] = reverse(
                    "workspace:workspaces_countryindividual_change", args=[related_id], query=query
                )
            if can_view_households and (household_id := finding["individual__household_id"]):
                finding["household_url"] = reverse(
                    "workspace:workspaces_countryhousehold_change", args=[household_id], query=query
                )

        context = self.get_common_context(
            request,
            str(rdp.pk),
            title=_("Findings"),
            operation=operation,
            page=page,
            filter_form=filter_form,
            results_complete=operation.status == RdpOperation.Status.SUCCESS,
            show_households=can_view_households,
        )
        context["original"] = rdp
        return TemplateResponse(request, "workspace/rdp/findings.html", context)

    @display(description="")
    def operations_display(self, obj: CountryRdp) -> str:
        """Return RDP operation execution details."""
        can_view_findings = bool(
            state.request and self.admin_site.get_model_admin(CountryIndividual).has_view_permission(state.request)
        )
        rows = []
        for operation in obj.operations.order_by("operation_type"):
            successful = operation.status == RdpOperation.Status.SUCCESS
            definition = RDP_OPERATION_DEFINITIONS.get(operation.operation_type)

            affected_individuals = None
            if successful:
                match operation.operation_type:
                    case RdpOperation.Type.BIOMETRIC_DEDUPLICATION:
                        affected_individuals = qs_biometric_affected_individuals(operation=operation).count()
                    case RdpOperation.Type.OCR:
                        affected_individuals = ocr_affected_individuals_count(operation=operation)

            rows.append(
                {
                    "operation_id": str(operation.id),
                    "operation_id_label": definition.operation_id_label if definition else _("Operation ID"),
                    "type": operation.get_operation_type_display(),
                    "status": operation.get_status_display(),
                    "attempts": operation.attempt,
                    "started_at": self._format_datetime(operation.started_at),
                    "finished_at": self._format_datetime(operation.finished_at),
                    "config": json.dumps(operation.config, indent=2, ensure_ascii=False) if operation.config else "",
                    "error": json.dumps(operation.error, indent=2, ensure_ascii=False) if operation.error else "",
                    "log": [self._format_log_entry(entry) for entry in operation.log],
                    "findings": operation.findings.count(),
                    "findings_url": reverse("workspace:workspaces_countryrdp_findings", args=[obj.pk, operation.pk])
                    if can_view_findings
                    else "",
                    "results_complete": successful,
                    "affected_individuals": affected_individuals,
                }
            )

        return render_to_string("workspace/rdp/_operations.html", {"rows": rows}) if rows else "-"

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
        return render_to_string("workspace/rdp/_log.html", {"rows": rows}) if rows else "-"

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
        label="Retry operations",
        change_form=True,
        change_list=False,
        permission="country_workspace.create_rdp",
        visible=_has_retryable_operations,
        html_attrs={"title": "Retry failed or stuck RDP operations."},
    )
    def retry_operations(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Retry RDP operations that require manual recovery."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        def apply(__: HttpRequest) -> HttpResponse:
            count = retry_rdp_operations(rdp_id=obj.pk, owner_id=request.user.pk)
            if count is None:
                messages.error(request, _("Program cleanup is in progress."))
            elif count:
                messages.success(request, f"{count} operation(s) scheduled for retry.")
            else:
                messages.warning(request, "No operations available for retry.")
            return redirect(self._change_url(obj))

        return confirm_action(
            self,
            request,
            apply,
            message="Retry available RDP operations?",
            description=(
                "Failed operations will be retried first. "
                "If no operation has failed, a running operation that supports manual retry may be restarted. "
                "Retry a running operation only when its current result is no longer expected."
            ),
            template="workspace/admin_extra_buttons/confirm.html",
        )

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
        visible=_is_clean_rdp_visible,
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
