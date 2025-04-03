from django.contrib import admin
from django.http import HttpRequest

from country_workspace.models import BeneficiaryGroup

from .base import BaseModelAdmin


@admin.register(BeneficiaryGroup)
class BeneficiaryGroupAdmin(BaseModelAdmin):
    list_display = ("name", "group_label", "group_label_plural", "member_label", "member_label_plural", "master_detail")
    search_fields = (
        "name",
        "group_label",
        "group_label_plural",
        "member_label",
        "member_label_plural",
    )
    ordering = ("name",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
