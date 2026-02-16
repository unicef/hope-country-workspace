from admin_extra_buttons.decorators import button
from django.contrib import admin
from django.http import HttpRequest, HttpResponse

from ..models import SyncLog
from .base import BaseModelAdmin


@admin.register(SyncLog)
class SyncLogAdmin(BaseModelAdmin):
    list_display = ("content_type", "name", "content_object", "last_update_date", "last_id")
    search_fields = ("name", "content_type__model", "content_type__app_label")

    @button(permission="country_workspace.can_synchronize")
    def sync_flex_fields(self, request: HttpRequest) -> "HttpResponse":
        SyncLog.objects.refresh()
