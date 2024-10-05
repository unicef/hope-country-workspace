from django.contrib import admin

from country_workspace.models import Individual


@admin.register(Individual)
class IndividualAdmin(admin.ModelAdmin):
    list_display = ("full_name", "country_office")
    list_filter = ("country_office",)
    readonly_fields = ("country_office",)
    search_fields = ("full_name",)
