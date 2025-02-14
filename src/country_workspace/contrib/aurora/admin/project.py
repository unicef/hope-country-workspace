from django.contrib import admin
from django.http import HttpRequest

from admin_extra_buttons.api import button

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.contrib.aurora.models import Project
from country_workspace.contrib.aurora.sync import sync_projects, sync_registrations


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
        totals = sync_projects()
        self.message_user(request, f"{totals['add']} created - {totals['upd']} updated")

    @button()
    def sync_registrations(self, request: HttpRequest, pk: str) -> None:
        project: Project = self.get_object(request, pk)
        totals = sync_registrations(limit_to_project=project)
        self.message_user(request, f"{totals['add']} created - {totals['upd']} updated - {totals['skip']} skipped")
