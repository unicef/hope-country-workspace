from django.contrib import admin

from ..models import Office


@admin.register(Office)
class OfficeAdmin(admin.ModelAdmin):
    list_display = ("name", "long_name", "active")
    search_fields = ("name",)
    list_filter = ("active",)
    readonly_fields = ("hope_id", "slug")
