from admin_extra_buttons.decorators import button
from django.contrib import admin
from django.http import HttpRequest, HttpResponse

from hope_country_workspace.workspaces.models import CountryHousehold
from hope_country_workspace.workspaces.options import CWModelAdmin
from hope_country_workspace.workspaces.sites import workspace


class CountryHouseholddAdmin(CWModelAdmin):
    change_list_template = "workspace/change_list.html"

    @button()
    def import_file(self, request: HttpRequest):
        return HttpResponse("Ok")
