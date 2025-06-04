from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from django.contrib import admin
from django.urls import reverse

from country_workspace.models import Office
from country_workspace.admin.base import BaseModelAdmin
from country_workspace.admin.sync import SyncAdminMixin, SyncAdminConfig, StepConfig


@admin.register(Office)
class OfficeAdmin(SyncAdminMixin, BaseModelAdmin):
    list_display = ("name", "long_name", "slug", "code", "active", "enabled", "kobo_country_code")
    search_fields = ("name", "slug", "code")
    list_filter = ("active", "enabled")
    readonly_fields = ("hope_id", "slug")
    ordering = ("name",)
    sync_config = SyncAdminConfig(
        step_handler=StepConfig(path="country_workspace.contrib.hope.sync.context_programs.SyncStep", name="OFFICES"),
        sync_handler="country_workspace.contrib.hope.sync.context_programs.sync_context_programs",
    )

    @link(change_list=False)
    def programmes(self, btn: LinkButton) -> None:
        url = reverse("admin:country_workspace_program_changelist")
        pk = btn.context.get("original").pk
        btn.href = f"{url}?country_office__exact={pk}"
