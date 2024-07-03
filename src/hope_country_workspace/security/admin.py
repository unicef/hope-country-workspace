from django.contrib import admin

# from unicef_security.admin import UserAdminPlus
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from hope_country_workspace.security.models import CountryOffice, User, UserRole


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    pass


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "country_office", "group")


@admin.register(CountryOffice)
class CountryOfficeAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
