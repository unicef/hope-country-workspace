from typing import TYPE_CHECKING

from django.http import HttpResponseRedirect
from django.urls import reverse

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import link
from hope_flex_fields.models import DataChecker

from country_workspace.state import state

from ..filters import ProgramFilter
from ..models import CountryHousehold
from ..options import WorkspaceModelAdmin

if TYPE_CHECKING:
    from ..models import CountryProgram


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

    def get_queryset(self, request):
        return CountryHousehold.objects.filter(country_office=state.tenant)

    def get_list_display(self, request):
        if program := self.get_selected_program(request):
            return [c.strip() for c in program.household_columns.split("\n")]
        else:
            return self.list_display

    def get_selected_program(self, request) -> "CountryProgram | None":
        from country_workspace.models import Program

        if "program__exact" in request.GET:
            self._selected_program = Program.objects.get(
                pk=request.GET["program__exact"]
            )
        return self._selected_program

    @link(change_list=False)
    def members(self, button: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryindividual_changelist")
        obj = button.context["original"]
        button.href = f"{base}?household__exact={obj.pk}"

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        if object_id:
            if obj := self.get_object(request, object_id):
                dc: "DataChecker" = obj.program.household_checker
                extra_context["checker_form"] = dc.get_form()(
                    initial=obj.flex_fields, prefix="flex_field"
                )
        return super().changeform_view(request, object_id, form_url, extra_context)

    def _changeform_view(self, request, object_id, form_url, extra_context):
        if request.method == "POST":
            if obj := self.get_object(request, object_id):
                dc: "DataChecker" = obj.program.household_checker
                form_class = dc.get_form()
                form = form_class(request.POST, prefix="flex_field")
                if form.is_valid():
                    obj.flex_fields = form.cleaned_data
                    obj.save()
                    return HttpResponseRedirect(request.META["HTTP_REFERER"])
        return super()._changeform_view(request, object_id, form_url, extra_context)

    def get_common_context(self, request, pk=None, **kwargs):
        kwargs["selected_program"] = self.get_selected_program(request)
        return super().get_common_context(request, pk, **kwargs)
