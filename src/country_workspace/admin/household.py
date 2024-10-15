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

    @link(change_list=True, change_form=False)
    def view_in_workspace(self, btn: "LinkButton") -> None:
        if "request" in btn.context:
            req = btn.context["request"]
            base = reverse("workspace:workspaces_countryhousehold_changelist")
            btn.href = f"{base}?%s" % req.META["QUERY_STRING"]
