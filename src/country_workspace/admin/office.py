from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from django.contrib import admin
from django.urls import reverse

from ..contrib.hope.sync.context_programs import SyncStep
from ..models import Office
from .base import BaseModelAdmin
from .sync import SyncAdminMixin, SyncConfig, ContextProgramsSyncHandler


@admin.register(Office)
class OfficeAdmin(SyncAdminMixin, BaseModelAdmin):
    list_display = ("name", "long_name", "slug", "code", "active", "enabled", "kobo_country_code")
    search_fields = ("name", "slug", "code")
    list_filter = ("active", "enabled")
    readonly_fields = ("hope_id", "slug")
    ordering = ("name",)
    sync_config = SyncConfig(model=Office, step=SyncStep.OFFICES, sync_handler=ContextProgramsSyncHandler())

    @link(change_list=False)
    def programmes(self, btn: LinkButton) -> None:
        url = reverse("admin:country_workspace_program_changelist")
        pk = btn.context.get("original").pk
        btn.href = f"{url}?country_office__exact={pk}"
