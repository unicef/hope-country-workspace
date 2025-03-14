from admin_extra_buttons.api import button
from django.contrib import admin, messages
from django.http import HttpRequest
from django.utils.translation import gettext as _
from strategy_field.utils import fqn

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.contrib.aurora.models import Project
from country_workspace.models import AsyncJob


@admin.register(Project)
class ProjectAdmin(BaseModelAdmin):
    list_display = ("name", "program", "last_synced")
    search_fields = ("name",)
    ordering = ("name",)
    autocomplete_fields = ("program",)

    @admin.display(ordering="last_modified")
    def last_synced(self, obj: Project) -> str:
        return obj.last_modified

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def get_readonly_fields(self, request: HttpRequest, obj: Project | None = None) -> tuple[str, ...]:
        return tuple(f.name for f in self.model._meta.fields if f.name != "program")

    @button()
    def sync(self, request: HttpRequest) -> None:
        job = AsyncJob.objects.create(
            description="Sync with Aurora projects and registrations",
            program=None,
            owner=request.user,
            type=AsyncJob.JobType.TASK,
            action=fqn("country_workspace.contrib.aurora.sync.sync_all"),
            batch=None,
            file=None,
            config={},
        )
        job.queue()
        self.message_user(request, _("Synchronization is scheduled."), messages.SUCCESS)
