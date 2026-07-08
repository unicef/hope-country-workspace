from adminfilters.autocomplete import AutoCompleteFilter
from django.contrib import admin
from django.http import HttpRequest

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.contrib.aurora.forms import RegistrationAdminForm
from country_workspace.contrib.aurora.models import Registration


@admin.register(Registration)
class RegistrationAdmin(BaseModelAdmin):
    form = RegistrationAdminForm
    list_display = ("name", "project", "active", "has_decryption_key", "last_synced")
    list_filter = (
        ("project", AutoCompleteFilter),
        "active",
    )
    search_fields = ("name",)
    ordering = ("name",)
    autocomplete_fields = ("project",)

    @admin.display(boolean=True, description="RSA key")
    def has_decryption_key(self, obj: Registration) -> bool:
        return bool((obj.rsa_private_key or "").strip())

    @admin.display(ordering="last_modified")
    def last_synced(self, obj: Registration) -> str:
        return obj.last_modified

    def get_readonly_fields(self, request: HttpRequest, obj: Registration | None = None) -> tuple[str, ...]:
        if obj is None:
            return super().get_readonly_fields(request, obj)
        return tuple(field.name for field in Registration._meta.fields if field.name not in {"id", "rsa_private_key"})

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Registration | None = None) -> bool:
        return request.user.has_perm("aurora.change_registration")
