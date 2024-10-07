from django.contrib import admin

from ..models import Program


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    list_filter = ("country_office",)
