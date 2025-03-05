from typing import Any

from django.contrib import admin

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.models import KoboAsset


@admin.register(KoboAsset)
class KoboAssetAdmin(BaseModelAdmin):
    list_display = ("uid", "name")
    exclude = ("programs",)

    def has_add_permission(self, *args: Any, **kwargs: Any) -> bool:
        return False

    def has_change_permission(self, *args: Any, **kwargs: Any) -> bool:
        return False

    def has_delete_permission(self, *args: Any, **kwargs: Any) -> bool:
        return False
