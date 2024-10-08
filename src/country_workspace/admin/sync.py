from django.contrib import admin

from ..models import SyncLog


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = ("content_type", "last_update_date", "last_id")
