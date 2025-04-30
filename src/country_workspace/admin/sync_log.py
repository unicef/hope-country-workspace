from admin_extra_buttons.decorators import button
from django.contrib import admin
from django.http import HttpRequest, HttpResponse

from ..models import SyncLog
from .base import BaseModelAdmin


@admin.register(SyncLog)
class SyncLogAdmin(BaseModelAdmin):
    list_display = ("content_type", "content_object", "last_update_date", "last_id")

    @button()
    def sync_all(self, request: HttpRequest) -> "HttpResponse":
        SyncLog.objects.refresh()
