from adminfilters.autocomplete import AutoCompleteFilter
from django.contrib import admin

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.models import UserRole


@admin.register(UserRole)
class UserRoleAdmin(BaseModelAdmin):
    list_display = ("user", "country_office", "program", "group")
    list_filter = (
        ("user", AutoCompleteFilter),
        ("country_office", AutoCompleteFilter),
        ("program", AutoCompleteFilter),
        ("group", AutoCompleteFilter),
    )
