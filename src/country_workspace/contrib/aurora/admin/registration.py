from adminfilters.autocomplete import AutoCompleteFilter
from django.contrib import admin, messages
from django.http import HttpRequest
from admin_extra_buttons.api import button
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext as _
from strategy_field.utils import fqn

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.contrib.aurora.models import Registration
from country_workspace.models import AsyncJob
from country_workspace.contrib.aurora.context_aurora import SyncStep


@admin.register(Registration)
class RegistrationAdmin(BaseModelAdmin):
    list_display = ("name", "project", "active", "last_synced")
    list_filter = (
        ("project", AutoCompleteFilter),
        "active",
    )
    search_fields = ("name",)
    ordering = ("name",)
    autocomplete_fields = ("project",)

    @admin.display(ordering="last_modified")
    def last_synced(self, obj: Registration) -> str:
        return obj.last_modified

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Registration | None = None) -> bool:
        return False

    @button()
    def sync(self, request: HttpRequest) -> None:
        AsyncJob.objects.create(
            description=_("Sync with Aurora projects and registrations"),
            program=None,
            owner=request.user,
            type=AsyncJob.JobType.TASK,
            action=fqn("country_workspace.contrib.aurora.tasks.sync_from_aurora"),
            batch=None,
            file=None,
            config={"ct_id": ContentType.objects.get_for_model(Registration).id, "step": SyncStep.REGISTRATIONS.name},
        ).queue()
        self.message_user(request, _("Synchronization is scheduled."), level=messages.SUCCESS)
