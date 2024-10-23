from django.contrib import admin

from country_workspace.versioning.models import Script


@admin.register(Script)
class ScriptAdmin(admin.ModelAdmin):
    list_display = ("num", "label", "version", "applied")
    ordering = ("name",)
