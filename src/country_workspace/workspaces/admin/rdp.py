import json
from collections.abc import Callable
from contextlib import suppress
from decimal import Decimal
from enum import StrEnum, auto
from typing import Any

import sentry_sdk
from admin_extra_buttons.api import button, link
from admin_extra_buttons.buttons import LinkButton, StandardButton
from django.contrib import messages
from django.contrib.admin import display, register
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.dateformat import format as date_format
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_lazy as _
from strategy_field.utils import fqn

from country_workspace.compat.admin_extra_buttons import confirm_action
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob, Rdp
from country_workspace.models.rdp import NON_TERMINAL_RDP_STATUSES, RdpOperationAction
from country_workspace.rdp import (
    DedupEngineState,
    PushThresholdType,
    RdpActionPolicy,
    RdpWorkflowError,
    get_dedup_callback_base_url,
    get_deduplication_policy,
    get_push_policy,
    claim_rdp_cancel,
    claim_rdp_deduplication,
    claim_rdp_push,
    claim_rdp_push_clean,
    claim_review_rdp_push,
    dedup_existing_rdp_core,
    qs_individuals_for_rdp,
    sync_deduplication_result,
)
from country_workspace.state import state
from country_workspace.workspaces.models import CountryRdp
from country_workspace.workspaces.options import WorkspaceModelAdmin
from country_workspace.workspaces.sites import workspace


from .filters import ChoiceFilter
from .forms import PushThresholdForm
from .hh_ind import SelectedProgramMixin


type PolicyGetter = Callable[[CountryRdp], RdpActionPolicy]


class PushDecision(StrEnum):
    CHECK = auto()
    PUSH = auto()


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


@register(CountryRdp, site=workspace)
class CountryRdpAdmin(SelectedProgramMixin, WorkspaceModelAdmin):
    list_display = ("name", "push_date", "status", "deduplication_set_id")
    list_filter = (("status", ChoiceFilter),)
    search_fields = ("name", "deduplication_set_id")
    ordering = ("-push_date",)
    readonly_fields = (
        "name",
        "status",
        "push_date",
        "hope_rdi_id",
        "dedup_engine_state",
        "deduplication_set_id",
        "processing_history",
        "operation_log_display",
    )

    def get_fieldsets(
        self,
        request: HttpRequest,
        obj: CountryRdp | None = None,
    ) -> list[tuple[str | None, dict[str, Any]]]:
        fieldsets = [
            (_("RDP details"), {"fields": ("name", "status", "push_date", "hope_rdi_id")}),
        ]

        if obj and obj.program.biometric_deduplication_enabled:
            fields = ["deduplication_set_id"]
            if obj.status in NON_TERMINAL_RDP_STATUSES:
                fields.insert(0, "dedup_engine_state")
            fieldsets.append((_("Deduplication"), {"fields": fields}))

        fieldsets.extend(
            [
                (_("Processing history"), {"fields": ("processing_history",), "classes": ("content-only",)}),
                (_("Operation log"), {"fields": ("operation_log_display",), "classes": ("content-only",)}),
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

    def change_view(
        self,
        request: HttpRequest,
        object_id: str,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        extra_context = {
            **(extra_context or {}),
            "dynamic_field_help_texts": {
                "dedup_engine_state": _("Current deduplication state reported by DedupEngine for this RDP."),
            },
        }
        return super().change_view(request, object_id, form_url, extra_context)

    @display(description="")
    def processing_history(self, obj: CountryRdp) -> str:
        jobs = list(obj.jobs.order_by("datetime_created"))
        if not jobs:
            return "—"

        rows = [
            {
                "url": reverse("workspace:workspaces_countryasyncjob_change", args=[job.pk]),
                "step": job.description or _("Background job"),
                "scheduled_at": (
                    date_format(timezone.localtime(job.datetime_queued), "Y-m-d H:i:s") if job.datetime_queued else "—"
                ),
                "status": job.task_status or "—",
            }
            for job in jobs
        ]

        return render_to_string("workspace/rdp/_processing_history.html", {"rows": rows})

    @display(description="")
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
                {
                    "action": action,
                    "timestamp": timestamp,
                    "result": json.dumps(result, indent=2, ensure_ascii=False) if result else "",
                }
            )

        return render_to_string("workspace/rdp/_operation_log.html", {"rows": rows})

    def dedup_engine_state(self, obj: CountryRdp) -> str:
        try:
            return str(get_deduplication_policy(obj).dedup_engine_state())
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

    def _render_push_threshold(
        self,
        request: HttpRequest,
        obj: CountryRdp,
        form: PushThresholdForm,
        *,
        exceeded: bool = False,
    ) -> HttpResponse:
        """Render the push threshold form or confirmation."""
        title = _("Push threshold exceeded") if exceeded else _("Push to HOPE")
        marked_count = obj.duplicate_individuals.count()
        total_count = qs_individuals_for_rdp(rdp=obj).count()
        marked_percentage = Decimal(marked_count) * 100 / total_count if total_count else Decimal(0)
        context = self.get_common_context(request, str(obj.pk), title=title)
        context.update(
            {
                "form": form,
                "rdp": obj,
                "change_url": self._change_url(obj),
                "exceeded": exceeded,
                "marked_count": marked_count,
                "total_count": total_count,
                "marked_percentage": marked_percentage,
                "decision_check": PushDecision.CHECK.value,
                "decision_push": PushDecision.PUSH.value,
            }
        )
        return render(request, "workspace/rdp/push_threshold.html", context)

    def _push_with_threshold(self, request: HttpRequest, obj: CountryRdp) -> HttpResponse:
        """Validate the threshold and handle the initial push request."""
        if response := self._deny_if_not_allowed(request, obj, get_push_policy, "start_push_check"):
            return response

        form = PushThresholdForm(
            request.POST if request.method == "POST" else None,
            total_count=qs_individuals_for_rdp(rdp=obj).count(),
        )

        if request.method != "POST" or not form.is_valid():
            return self._render_push_threshold(request, obj, form)

        if request.POST.get("decision") != PushDecision.CHECK:
            messages.error(request, "Invalid push decision.")
            return redirect(self._change_url(obj))

        return self._schedule_push(request, obj, form=form)

    def _schedule_push(
        self,
        request: HttpRequest,
        obj: CountryRdp,
        *,
        form: PushThresholdForm | None = None,
    ) -> HttpResponse:
        """Check the threshold and schedule an allowed push."""
        change_url = self._change_url(obj)
        threshold = (
            (
                PushThresholdType(form.cleaned_data["threshold_type"]),
                form.cleaned_data["threshold_value"],
            )
            if form is not None
            else None
        )

        try:
            check, locked = claim_rdp_push(rdp_id=obj.pk, user_id=request.user.pk, threshold=threshold)
        except RemoteUnavailableError as exc:
            sentry_sdk.capture_exception(exc)
            messages.error(request, str(exc))
            return redirect(change_url)
        except RemoteError as exc:
            messages.error(request, str(exc))
            return redirect(change_url)

        if not check.allowed or locked is None:
            messages.error(request, check.reason or "Action is not allowed.")
        elif locked.status == Rdp.PushStatus.REVIEW_PENDING:
            messages.warning(request, "The selected threshold was exceeded. Review this RDP before pushing.")
        else:
            messages.success(request, "Push to HOPE task scheduled")

        return redirect(change_url)

    @button(
        label="Start deduplication",
        change_form=True,
        change_list=False,
        permission="country_workspace.deduplicate_rdp",
        visible=lambda btn: _is_visible(btn, get_deduplication_policy, "is_deduplicate_visible"),
        enabled=lambda btn: _is_allowed(btn, get_deduplication_policy, "claim_deduplication_check"),
        html_attrs={"title": "Queue RDP for deduplication in DedupEngine."},
    )
    def deduplicate(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Queue this RDP for deduplication in DedupEngine."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        try:
            get_dedup_callback_base_url()
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect(self._change_url(obj))

        try:
            policy = get_deduplication_policy(obj)
            check = policy.claim_deduplication_check()
            if not check.allowed:
                messages.error(request, check.reason or "Action is not allowed.")
                return redirect(self._change_url(obj))
            can_create_deduplication_set = policy.can_create_deduplication_set
            with transaction.atomic():
                check, locked = claim_rdp_deduplication(
                    rdp_id=obj.pk,
                    can_create_deduplication_set=can_create_deduplication_set,
                    expected_deduplication_set_id=obj.deduplication_set_id,
                )
                if not check.allowed or locked is None:
                    messages.error(request, check.reason or "Action is not allowed.")
                    return redirect(self._change_url(obj))
                if (deduplication_set_id := locked.deduplication_set_id) is None:
                    raise RuntimeError("RDP deduplication set was not initialized.")
                job = AsyncJob.objects.create(
                    description="Queue RDP for deduplication in DedupEngine",
                    type=AsyncJob.JobType.TASK,
                    owner=request.user,
                    action=fqn(dedup_existing_rdp_core),
                    program=locked.program,
                    rdp=locked,
                    config={
                        "rdp_id": locked.pk,
                        "deduplication_set_id": str(deduplication_set_id),
                    },
                )
                transaction.on_commit(job.queue)
        except RemoteUnavailableError as exc:
            sentry_sdk.capture_exception(exc)
            messages.error(request, str(exc))
        except RemoteError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Dedup task scheduled")

        return redirect(self._change_url(obj))

    @button(
        label="Check deduplication result",
        change_form=True,
        change_list=False,
        permission="country_workspace.deduplicate_rdp",
        visible=lambda btn: bool(
            (obj := btn.original) and obj.status == Rdp.PushStatus.DEDUP_PENDING and obj.deduplication_set_id
        ),
        html_attrs={"title": "Fetch the current deduplication result from DedupEngine."},
    )
    def sync_deduplication(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Fetch the current DedupEngine state and synchronize the result."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        if obj.status != Rdp.PushStatus.DEDUP_PENDING or (deduplication_set_id := obj.deduplication_set_id) is None:
            messages.warning(request, "RDP is not awaiting deduplication.")
            return redirect(self._change_url(obj))

        try:
            synchronized = sync_deduplication_result(rdp_id=obj.pk, deduplication_set_id=deduplication_set_id)
        except RemoteUnavailableError as exc:
            sentry_sdk.capture_exception(exc)
            messages.error(request, str(exc))
        except RemoteError as exc:
            messages.error(request, str(exc))
        else:
            obj.refresh_from_db(fields=["status", "deduplication_set_id"])

            if synchronized:
                if obj.status == Rdp.PushStatus.FAILURE:
                    messages.error(request, "Deduplication failed in DedupEngine. RDP marked as failed.")
                else:
                    messages.success(request, "Deduplication result synchronized.")
            elif obj.status != Rdp.PushStatus.DEDUP_PENDING or obj.deduplication_set_id != deduplication_set_id:
                messages.info(request, "RDP deduplication state has already changed.")
            else:
                messages.info(request, "Deduplication is still in progress.")

        return redirect(self._change_url(obj))

    @button(
        label="Cancel RDP",
        change_form=True,
        change_list=False,
        permission="country_workspace.cancel_rdp",
        visible=lambda btn: _is_visible(btn, get_deduplication_policy, "is_cancel_visible"),
        enabled=lambda btn: _is_allowed(btn, get_deduplication_policy, "cancel_check"),
        html_attrs={"title": "Cancel this RDP."},
    )
    def cancel(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Cancel an RDP and schedule DedupEngine cleanup when required."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        if response := self._deny_if_not_allowed(request, obj, get_deduplication_policy, "cancel_check"):
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
            )

        return apply_cancel(request)

    @button(
        label="Push to HOPE",
        change_form=True,
        change_list=False,
        permission="country_workspace.push_rdp_to_hope",
        visible=lambda btn: _is_visible(btn, get_push_policy, "is_push_visible"),
        enabled=lambda btn: _is_allowed(btn, get_push_policy, "start_push_check"),
        html_attrs={"title": "Push beneficiaries to HOPE."},
    )
    def push(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Start a push to HOPE, checking the threshold when required."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        if obj.program.biometric_deduplication_enabled:
            return self._push_with_threshold(request, obj)

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
            try:
                check, locked = claim_review_rdp_push(rdp_id=obj.pk, user_id=request.user.pk)
            except RemoteUnavailableError as exc:
                sentry_sdk.capture_exception(exc)
                messages.error(request, str(exc))
            except RemoteError as exc:
                messages.error(request, str(exc))
            else:
                if check.allowed and locked is not None:
                    messages.success(request, "Push to HOPE task scheduled")
                else:
                    messages.error(request, check.reason or "Action is not allowed.")

            return redirect(self._change_url(obj))

        return confirm_action(
            self,
            request,
            schedule_push,
            message="The selected threshold was exceeded. Confirm that you want to push all RDP beneficiaries.",
            template="workspace/admin_extra_buttons/confirm.html",
        )

    @button(
        label="Create clean RDP",
        change_form=True,
        change_list=False,
        permission="country_workspace.push_rdp_to_hope",
        visible=lambda btn: bool((obj := btn.original) and obj.status == Rdp.PushStatus.REVIEW_PENDING),
        html_attrs={"title": "Create a new RDP excluding duplicate beneficiaries."},
    )
    def create_clean_rdp(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Cancel this RDP and create a new one without marked duplicates."""
        if (obj := self.get_object(request, pk)) is None:
            messages.error(request, "RDP not found")
            return redirect("workspace:workspaces_countryrdp_changelist")

        def apply(_: HttpRequest) -> HttpResponse:
            try:
                check, clean_rdp = claim_rdp_push_clean(rdp_id=obj.pk, user_id=request.user.pk)
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

        message = "Cancel this RDP and create a new one without duplicates? "
        if obj.hope_rdi_id not in {None, "N/A"}:
            message += f"Confirm HOPE RDI {obj.hope_rdi_id} has been deleted manually. "
        message += "The old DedupEngine set will be queued for rejection."
        return confirm_action(
            self, request, apply, message=message, template="workspace/admin_extra_buttons/confirm.html"
        )

    @link(change_list=False, html_attrs={"title": "Shows related beneficiary records."})
    def records(self, btn: LinkButton) -> None:
        obj = btn.context["original"]
        if obj.status == CountryRdp.PushStatus.SUCCESS:
            btn.visible = False
            return
        item = "countryhousehold" if obj.program.beneficiary_group.master_detail else "countryindividual"
        base = reverse(f"workspace:workspaces_{item}_changelist")
        btn.href = f"{base}?rdp__exact={obj.pk}"
