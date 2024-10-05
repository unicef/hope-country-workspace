from django.contrib import admin

from country_workspace.models import Household


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("name", "country_office")
    list_filter = ("country_office",)
    readonly_fields = ("country_office",)
    search_fields = ("name",)
