from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import button, link
from adminfilters.autocomplete import AutoCompleteFilter, LinkedAutoCompleteFilter
from django.contrib import admin
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from ..compat.admin_extra_buttons import confirm_action
from ..models import Rdp
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
        "deduplication_snapshots",
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
        enabled=lambda btn: btn.context["original"].status == Rdp.PushStatus.SUCCESS,
    )
    def reset(self, request: HttpRequest, pk: int) -> HttpResponse:
        obj: Rdp = self.get_object(request, str(pk))

        if obj.status != Rdp.PushStatus.SUCCESS:
            self.message_user(request, "Reset is only allowed for SUCCESS status.", level="error")
            return HttpResponseRedirect(reverse("admin:country_workspace_rdp_change", args=[pk]))

        def _action(_: HttpRequest) -> HttpResponseRedirect:
            with transaction.atomic():
                obj.households.all().update(removed=False)
                obj.individuals.all().update(removed=False)
                obj.status = Rdp.PushStatus.CANCELLED
                obj.save()
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
            success_message="RDP reset successfully. Related beneficiaries marked as not removed.",
            pk=str(pk),
        )
