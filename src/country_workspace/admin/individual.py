from typing import TYPE_CHECKING

from admin_extra_buttons.decorators import link
from adminfilters.autocomplete import LinkedAutoCompleteFilter
from django.contrib import admin
from django.urls import reverse

from ..models import Individual
from .base import BaseModelAdmin
from .filters import IsValidFilter

if TYPE_CHECKING:
    from admin_extra_buttons.buttons import LinkButton


@admin.register(Individual)
class IndividualAdmin(BaseModelAdmin):
    list_display = ("name", "household", "country_office", "program", "batch", "removed")
    search_fields = ("name",)
    list_filter = (
        ("batch__country_office", LinkedAutoCompleteFilter.factory(parent=None)),
        ("batch__program", LinkedAutoCompleteFilter.factory(parent="batch__country_office")),
        ("batch", LinkedAutoCompleteFilter.factory(parent="batch__program")),
        IsValidFilter,
        "removed",
    )
    autocomplete_fields = (
        "batch",
        "household",
    )

    @link(change_list=True, change_form=False)
    def view_in_workspace(self, btn: "LinkButton") -> None:
        if "request" in btn.context:
            req = btn.context["request"]
            base = reverse("workspace:workspaces_countryindividual_changelist")
            btn.href = f"{base}?%s" % req.META["QUERY_STRING"]
