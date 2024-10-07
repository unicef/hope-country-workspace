from django.contrib import admin

from ..models import Office


@admin.register(Office)
class CountryOfficeAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
