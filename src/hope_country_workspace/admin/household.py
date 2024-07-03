from django.contrib import admin, messages

from hope_country_workspace.models import Household


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    pass
