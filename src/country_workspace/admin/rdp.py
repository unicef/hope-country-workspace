from uuid import UUID

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import button, link
from adminfilters.autocomplete import AutoCompleteFilter, LinkedAutoCompleteFilter
from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from country_workspace.compat.admin_extra_buttons import confirm_action
from country_workspace.rdp import fail_stuck_rdp_push, get_rdp_policy, reset_rdp
from country_workspace.models import Rdp
from .base import BaseModelAdmin


@admin.register(Rdp)
class RdpAdmin(BaseModelAdmin):
    list_display = ("name", "program", "status", "pushed_by", "push_date")
    list_filter = (
        ("country_office", LinkedAutoCompleteFilter.factory(parent=None)),
        ("program", LinkedAutoCompleteFilter.factory(parent="country_office")),
        ("pushed_by", AutoCompleteFilter),
        ("status"),
    )
    fields = (
        "name",
        "country_office",
        "program",
        "pushed_by",
        "push_date",
        "status",
        "hope_rdi_id",
        "deduplication_set_id",
        "operation_log",
        "related_job",
    )
    readonly_fields = ("country_office", "program", "related_job", "push_date", "hope_rdi_id")
    search_fields = ("name",)
    ordering = ("-push_date",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def related_job(self, obj: Rdp) -> str:
        if job := obj.jobs.first():
            url = reverse("admin:country_workspace_asyncjob_change", args=[job.pk])
            return format_html('<a href="{}">{}</a>', url, str(job))
        return "-"

    def get_queryset(self, request: HttpRequest) -> QuerySet[Rdp]:
        return super().get_queryset(request).select_related("program__beneficiary_group", "country_office")

    @link(change_list=False, html_attrs={"title": "Shows related beneficiary records."})
    def records(self, button: LinkButton) -> None:
        obj = button.context["original"]
        item = (
            obj.households if obj.program.beneficiary_group.master_detail else obj.individuals
        ).model._meta.model_name
        base = reverse(f"admin:country_workspace_{item}_changelist")
        button.href = f"{base}?rdp__exact={obj.pk}"

    @link(change_list=True, change_form=False)
    def view_in_workspace(self, btn: LinkButton) -> None:
        if "request" in btn.context:
            req = btn.context["request"]
            base = reverse("workspace:workspaces_countryrdp_changelist")
            btn.href = f"{base}?%s" % req.META["QUERY_STRING"]

    @button(
        permission="country_workspace.reset_rdp",
        change_form=True,
        change_list=False,
        label="Reset",
        html_attrs={"class": "btn-warning"},
        enabled=lambda btn: get_rdp_policy(btn.context["original"]).reset_check().allowed,
    )
    def reset(self, request: HttpRequest, pk: int) -> HttpResponse:
        obj: Rdp = self.get_object(request, str(pk))
        check = get_rdp_policy(obj).reset_check()
        if not check.allowed:
            self.message_user(request, check.reason or "Reset is not allowed.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:country_workspace_rdp_change", args=[pk]))

        def _action(_: HttpRequest) -> HttpResponseRedirect:
            check = reset_rdp(rdp_id=pk)
            if check.allowed:
                self.message_user(
                    request,
                    "RDP reset successfully. Related beneficiaries marked as not removed.",
                    level=messages.SUCCESS,
                )
            else:
                self.message_user(request, check.reason or "Reset is not allowed.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:country_workspace_rdp_change", args=[pk]))

        return confirm_action(
            self,
            request,
            _action,
            "Are you sure you want to reset this RDP?",
            description=(
                "This will set all related households and individuals to removed=False "
                "and mark the RDP status as CANCELLED. This action cannot be undone."
            ),
            error_message="RDP reset failed.",
            pk=str(pk),
        )

    # TODO(Vitali): Remove this button and fail_stuck_rdp_push after Bitcaster recovery is implemented.
    @button(
        permission="country_workspace.reset_rdp",
        change_form=True,
        change_list=False,
        label="Fail stuck push",
        html_attrs={"class": "btn-warning"},
        visible=lambda btn: btn.context["original"].status == Rdp.PushStatus.PUSH_PENDING,
    )
    def fail_stuck_push(self, request: HttpRequest, pk: int) -> HttpResponse:  # pragma: no cover
        change_url = reverse("admin:country_workspace_rdp_change", args=[pk])

        if not (raw_attempt_id := request.GET.get("push_attempt_id")):
            if not (attempt_id := self.get_object(request, str(pk)).push_attempt_id):
                self.message_user(request, "RDP: no active push attempt was found.", level=messages.ERROR)
                return HttpResponseRedirect(change_url)
            return HttpResponseRedirect(f"{request.path}?push_attempt_id={attempt_id}")

        try:
            push_attempt_id = UUID(raw_attempt_id)
        except ValueError:
            self.message_user(request, "Invalid push attempt ID.", level=messages.ERROR)
            return HttpResponseRedirect(change_url)

        def _action(_: HttpRequest) -> HttpResponseRedirect:
            check = fail_stuck_rdp_push(rdp_id=pk, push_attempt_id=push_attempt_id)
            self.message_user(
                request,
                "Recovery completed. The RDP can now be retried."
                if check.allowed
                else check.reason or "Recovery is not allowed.",
                level=messages.SUCCESS if check.allowed else messages.ERROR,
            )
            return HttpResponseRedirect(change_url)

        return confirm_action(
            self,
            request,
            _action,
            "Fail this stuck push?",
            description=(
                "Use this action only after confirming that the push preparation job is not running. "
                "For a retry, also confirm that the HOPE callback is no longer expected. "
                "The selected push attempt will be marked as FAILURE and can then be retried. "
                "This action will be removed after Bitcaster recovery is implemented."
            ),
            error_message="Stuck-push recovery failed.",
            pk=str(pk),
        )
