from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from django.contrib import admin
from django.urls import reverse

from country_workspace.models import Office
from country_workspace.admin.base import BaseModelAdmin
from country_workspace.admin.sync import SyncAdminMixin, SyncAdminConfig, TargetConfig, Target


@admin.register(Office)
class OfficeAdmin(SyncAdminMixin, BaseModelAdmin):
    list_display = ("name", "long_name", "slug", "code", "active", "enabled", "kobo_country_code")
    filter_horizontal = ("countries",)
    search_fields = ("name", "slug", "code")
    list_filter = ("active", "enabled")
    readonly_fields = ("hope_id", "slug")
    ordering = ("name",)
    sync_config = SyncAdminConfig(
        targets=[
            TargetConfig(target=Target.OFFICES),
            TargetConfig(target=Target.BENEFICIARY_GROUPS),
            TargetConfig(target=Target.PROGRAMS),
        ],
    )

    @link(change_list=False)
    def programmes(self, btn: LinkButton) -> None:
        url = reverse("admin:country_workspace_program_changelist")
        pk = btn.context.get("original").pk
        btn.href = f"{url}?country_office__exact={pk}"
