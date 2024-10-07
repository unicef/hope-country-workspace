from django.http import HttpRequest, HttpResponse

from admin_extra_buttons.decorators import button

from country_workspace.state import state

from ..filters import ProgramFilter
from ..models import CountryHousehold
from ..options import WorkspaceModelAdmin


class CountryHouseholdAdmin(WorkspaceModelAdmin):
    list_display = ("name", "program")
    search_fields = ("name",)
    list_filter = (("program", ProgramFilter),)
    readonly_fields = ["program"]
    exclude = [
        "country_office",
    ]

    @button()
    def import_file(self, request: HttpRequest):
        return HttpResponse("Ok")

    def get_queryset(self, request):
        return CountryHousehold.objects.filter(country_office=state.tenant)
