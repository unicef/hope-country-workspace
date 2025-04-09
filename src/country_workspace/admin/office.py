from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import button, link
from django.contrib import admin, messages
from django.http import HttpRequest
from django.urls import reverse

from ..models import Office
from .base import BaseModelAdmin


@admin.register(Office)
class OfficeAdmin(BaseModelAdmin):
    list_display = ("name", "long_name", "slug", "code", "active", "kobo_country_code")
    search_fields = ("name", "slug", "code")
    list_filter = ("active",)
    readonly_fields = ("hope_id", "slug")
    ordering = ("name",)

    @link(change_list=False)
    def programmes(self, btn: LinkButton) -> None:
        url = reverse("admin:country_workspace_program_changelist")
        pk = btn.context.get("original").pk
        btn.href = f"{url}?country_office__exact={pk}"

    @button()
    def sync(self, request: HttpRequest) -> None:
        from country_workspace.contrib.hope.sync.context_programs import SyncStep, sync_context_programs

        totals = sync_context_programs(step=SyncStep.OFFICES)

        if errors := totals.get("errors"):
            self.message_user(request, "; ".join(errors), level=messages.ERROR)
        else:
            info = totals[Office._meta.model_name]
            self.message_user(request, f"{info['add']} created - {info['upd']} updated", level=messages.SUCCESS)
