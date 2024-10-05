from django.contrib import admin

from ..models import CountryOffice


@admin.register(CountryOffice)
class CountryOfficeAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
