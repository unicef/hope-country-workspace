from django.contrib import admin
from django.http import HttpRequest

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.contrib.aurora.models import Project
from country_workspace.admin.sync import SyncAdminMixin, SyncAdminConfig, TargetConfig, Target


@admin.register(Project)
class ProjectAdmin(SyncAdminMixin, BaseModelAdmin):
    list_display = ("name", "program", "last_synced")
    search_fields = ("name",)
    ordering = ("name",)
    autocomplete_fields = ("program",)

    sync_config = SyncAdminConfig(
        targets=[
            TargetConfig(target=Target.PROJECTS),
            TargetConfig(target=Target.REGISTRATIONS),
        ]
    )

    @admin.display(ordering="last_modified")
    def last_synced(self, obj: Project) -> str:
        return obj.last_modified

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def get_readonly_fields(self, request: HttpRequest, obj: Project | None = None) -> tuple[str, ...]:
        return tuple(f.name for f in self.model._meta.fields if f.name != "program")
