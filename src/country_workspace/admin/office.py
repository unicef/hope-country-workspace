from django.contrib import admin
from django.urls import reverse

from admin_extra_buttons.decorators import button, link

from ..models import Office
from ..sync.office import sync_offices
from .base import BaseModelAdmin


@admin.register(Office)
class OfficeAdmin(BaseModelAdmin):
    list_display = ("name", "long_name", "active")
    search_fields = ("name",)
    list_filter = ("active",)
    readonly_fields = ("hope_id", "slug")

    @link(change_list=False)
    def programmes(self, btn):
        url = reverse("admin:country_workspace_program_changelist")
        pk = btn.context.get("original").pk
        btn.href = f"{url}?country_office__exact={pk}"

    @button()
    def sync(self, request) -> None:
        sync_offices()
