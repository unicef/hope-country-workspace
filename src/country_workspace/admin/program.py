from django.contrib import admin
from django.urls import reverse

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from adminfilters.autocomplete import AutoCompleteFilter

from ..models import Program
from .base import BaseModelAdmin


@admin.register(Program)
class ProgramAdmin(BaseModelAdmin):
    list_display = ("name", "active", "sector")
    search_fields = ("name",)
    list_filter = (
        "active",
        ("country_office", AutoCompleteFilter),
    )

    @link(change_list=False, html_attrs={"target": "_workspace"})
    def view_in_workspace(self, button: LinkButton) -> None:
        obj = button.context["original"]
        base = reverse("workspace:workspaces_countryprogram_change", args=[obj.pk])
        button.href = base

    @link(change_list=False)
    def population(self, button: LinkButton) -> None:
        base = reverse("admin:country_workspace_individual_changelist")
        obj = button.context["original"]
        button.href = f"{base}?household__exact={obj.pk}"
