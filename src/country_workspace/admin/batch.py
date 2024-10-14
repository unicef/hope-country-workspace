from django.contrib import admin
from django.urls import reverse

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link

from ..models import Batch
from .base import BaseModelAdmin


@admin.register(Batch)
class BatchAdmin(BaseModelAdmin):
    list_display = ("name", "import_date", "imported_by")

    readonly_fields = ("country_office", "program")
    search_fields = ("name",)

    @link(change_list=False)
    def members(self, button: LinkButton) -> None:
        base = reverse("admin:country_workspace_individual_changelist")
        obj = button.context["original"]
        button.href = f"{base}?household__exact={obj.pk}"
