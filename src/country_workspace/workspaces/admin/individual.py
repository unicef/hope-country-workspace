from django.http import HttpRequest, HttpResponse

from admin_extra_buttons.decorators import button

from country_workspace.state import state

from ..models import CountryIndividual
from ..options import WorkspaceModelAdmin


class CountryIndividualAdmin(WorkspaceModelAdmin):

    @button()
    def import_file(self, request: HttpRequest):
        return HttpResponse("Ok")

    def get_queryset(self, request):
        return CountryIndividual.objects.filter(country_office=state.tenant)
