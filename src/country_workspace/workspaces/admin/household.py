from django.http import HttpRequest, HttpResponse

from admin_extra_buttons.decorators import button

from country_workspace.state import state

from ..filters import ProgramFilter
from ..models import CountryHousehold, CountryProgram
from ..options import WorkspaceModelAdmin


class CountryHouseholdAdmin(WorkspaceModelAdmin):
    list_display = ("name", "program")
    search_fields = ("name",)
    list_filter = (("program", ProgramFilter),)
    # readonly_fields = ["program"]
    exclude = [
        "country_office",
        "program",
    ]
    change_list_template = "workspace/household/change_list.html"
    change_form_template = "workspace/household/change_form.html"

    @button()
    def import_file(self, request: HttpRequest):
        return HttpResponse("Ok")

    def get_selected_program(self, request) -> "CountryProgram | None":
        # if not self._selected_program:
        from country_workspace.models import Program

        if "program__exact" in request.GET:
            self._selected_program = Program.objects.get(
                pk=request.GET["program__exact"]
            )
        return self._selected_program

    def get_common_context(self, request, pk=None, **kwargs):
        kwargs["selected_program"] = self.get_selected_program(request)
        return super().get_common_context(request, pk, **kwargs)

    def get_queryset(self, request):
        return CountryHousehold.objects.filter(country_office=state.tenant)

    def get_list_display(self, request):
        if program := self.get_selected_program(request):
            return [c.strip() for c in program.changelist_columns.split("\n")]
        else:
            return self.list_display
