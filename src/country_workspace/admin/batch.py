from django.contrib import admin
from django.urls import reverse

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link

from ..models import Batch
from .base import BaseModelAdmin


@admin.register(Batch)
class BatchAdmin(BaseModelAdmin):
    list_display = ("name", "import_date", "imported_by", "program")
    list_filter = (
        "country_office",
        "program",
        # ("country_office", LinkedAutoCompleteFilter.factory(parent=None)),
        # ("program", LinkedAutoCompleteFilter.factory(parent="country_office")),
    )
    readonly_fields = ("country_office", "program")
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
            base = reverse("workspace:workspaces_countrybatch_changelist")
            btn.href = f"{base}?%s" % req.META["QUERY_STRING"]
