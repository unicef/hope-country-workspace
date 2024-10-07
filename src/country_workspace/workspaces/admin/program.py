from django.urls import reverse

from admin_extra_buttons.api import link
from admin_extra_buttons.buttons import LinkButton

from country_workspace.state import state

from ..models import CountryProgram
from ..options import WorkspaceModelAdmin


class CountryProgramAdmin(WorkspaceModelAdmin):
    list_display = ("name", "sector", "status")
    search_fields = ("name",)
    list_filter = ("status", "sector")
    exclude = ("country_office",)

    def get_queryset(self, request):
        return CountryProgram.objects.filter(country_office=state.tenant)

    @link(change_list=False)
    def data_checker(self, button: LinkButton) -> None:
        base = reverse("workspace:country_workspace_countryhousehold_changelist")
        obj = button.context["original"]
        button.href = f"{base}?program={obj.pk}"

    @link(change_list=False)
    def population1(self, button: LinkButton) -> None:
        base = reverse("workspace:country_workspace_countryhousehold_changelist")
        obj = button.context["original"]
        button.href = f"{base}?program={obj.pk}"
