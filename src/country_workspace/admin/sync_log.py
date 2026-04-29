from admin_extra_buttons.decorators import button
from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext as _
from strategy_field.utils import fqn

from ..models import AsyncJob, SyncLog
from .base import BaseModelAdmin


def sync_flex_fields_task(job: AsyncJob) -> None:
    SyncLog.objects.refresh()


@admin.register(SyncLog)
class SyncLogAdmin(BaseModelAdmin):
    list_display = ("content_type", "name", "content_object", "last_update_date", "last_id")
    search_fields = ("name", "content_type__model", "content_type__app_label")

    @button(permission="country_workspace.can_synchronize")
    def sync_flex_fields(self, request: HttpRequest) -> "HttpResponse":
        AsyncJob.objects.create(
            description="Sync Flex Fields",
            program=None,
            owner=request.user,
            type=AsyncJob.JobType.TASK,
            action=fqn(sync_flex_fields_task),
            batch=None,
            file=None,
            config={},
        ).queue()
        self.message_user(request, _("Flex fields sync has been scheduled."), level=messages.SUCCESS)
