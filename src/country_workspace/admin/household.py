from django.contrib import admin
from django.urls import reverse

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link

from ..models import Household
from .base import BaseModelAdmin


@admin.register(Household)
class HouseholdAdmin(BaseModelAdmin):
    list_display = ("name", "batch")
    # list_filter = (
    #     ("batch__country_office", LinkedAutoCompleteFilter.factory(parent=None)),
    #     ("batch__program", LinkedAutoCompleteFilter.factory(parent="batch__country_office")),
    # )
    # readonly_fields = ("country_office", "program")
    search_fields = ("name",)

    @link(change_list=False)
    def members(self, button: LinkButton) -> None:
        base = reverse("admin:country_workspace_individual_changelist")
        obj = button.context["original"]
        button.href = f"{base}?household__exact={obj.pk}"
