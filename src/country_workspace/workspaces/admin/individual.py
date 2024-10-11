from typing import TYPE_CHECKING

from django.http import HttpRequest, HttpResponse

from admin_extra_buttons.decorators import button

from country_workspace.state import state

from ..filters import HouseholdFilter, ProgramFilter
from .hh_ind import CountryHouseholdIndividualBaseAdmin

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker


class CountryIndividualAdmin(CountryHouseholdIndividualBaseAdmin):
    list_display = ("name", "program", "household", "country_office")
    search_fields = ("name",)
    list_filter = (
        ("program", ProgramFilter),
        ("household", HouseholdFilter),
    )
    exclude = [
        "household",
        "country_office",
        "program",
        "user_fields",
    ]
    change_list_template = "workspace/individual/change_list.html"
    change_form_template = "workspace/individual/change_form.html"
    ordering = ("name",)

    def get_list_display(self, request):
        if program := self.get_selected_program(request):
            return [c.strip() for c in program.individual_columns.split("\n")]
        else:
            return self.list_display

    @button()
    def import_file(self, request: HttpRequest):
        return HttpResponse("Ok")

    def get_checker(self, request, obj=None) -> "DataChecker":
        if obj:
            return obj.program.individual_checker
        return state.program.individual_checker

    #
    # def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
    #     extra_context = extra_context or {}
    #     if object_id:
    #         if obj := self.get_object(request, object_id):
    #             dc: "DataChecker" = obj.program.individual_checker
    #             extra_context['checker_form'] = dc.get_form()(initial=obj.flex_fields, prefix="flex_field")
    #     return super().changeform_view(request, object_id, form_url, extra_context)
