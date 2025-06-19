from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from adminfilters.autocomplete import AutoCompleteFilter, LinkedAutoCompleteFilter
from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from ..models import Rdp
from .base import BaseModelAdmin


@admin.register(Rdp)
class RdpAdmin(BaseModelAdmin):
    list_display = ("name", "program", "pushed_by", "push_date", "status")
    list_filter = (
        ("country_office", LinkedAutoCompleteFilter.factory(parent=None)),
        ("program", LinkedAutoCompleteFilter.factory(parent="country_office")),
        ("pushed_by", AutoCompleteFilter),
        ("status"),
    )
    fields = ("name", "country_office", "program", "pushed_by", "push_date", "status", "related_job")
    readonly_fields = ("country_office", "program", "related_job", "push_date")
    search_fields = ("name",)

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
