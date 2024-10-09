from typing import TYPE_CHECKING

from django.contrib.admin.utils import unquote
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _

from admin_extra_buttons.decorators import button
from adminfilters.autocomplete import AutoCompleteFilter
from rest_framework.exceptions import PermissionDenied

from country_workspace.state import state

from ..filters import ProgramFilter
from ..models import CountryIndividual
from ..options import WorkspaceModelAdmin

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker

    from ..models import CountryProgram


class CountryIndividualAdmin(WorkspaceModelAdmin):
    list_display = ("full_name", "program", "household", "country_office")
    search_fields = ("full_name",)
    list_filter = (
        ("program", ProgramFilter),
        ("household", AutoCompleteFilter),
    )
    exclude = [
        "household",
        "country_office",
        "program",
        "user_fields",
    ]
    change_list_template = "workspace/individual/change_list.html"
    change_form_template = "workspace/individual/change_form.html"

    def get_queryset(self, request):
        return CountryIndividual.objects.filter(country_office=state.tenant)

    def get_list_display(self, request):
        if program := self.get_selected_program(request):
            return [c.strip() for c in program.individual_columns.split("\n")]
        else:
            return self.list_display

    def get_selected_program(self, request) -> "CountryProgram | None":
        # if not self._selected_program:
        from country_workspace.models import Program

        if "program__exact" in request.GET:
            self._selected_program = Program.objects.get(
                pk=request.GET["program__exact"]
            )
        return self._selected_program

    @button()
    def import_file(self, request: HttpRequest):
        return HttpResponse("Ok")

    #
    # def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
    #     extra_context = extra_context or {}
    #     if object_id:
    #         if obj := self.get_object(request, object_id):
    #             dc: "DataChecker" = obj.program.individual_checker
    #             extra_context['checker_form'] = dc.get_form()(initial=obj.flex_fields, prefix="flex_field")
    #     return super().changeform_view(request, object_id, form_url, extra_context)

    def _changeform_view(self, request, object_id, form_url, extra_context):
        context = self.get_common_context(request, object_id, **extra_context)
        add = object_id is None
        obj = self.get_object(request, unquote(object_id))
        dc: "DataChecker" = obj.program.individual_checker
        form_class = dc.get_form()
        if request.method == "POST":
            if not self.has_change_permission(request, obj):
                raise PermissionDenied
        else:
            if not self.has_view_or_change_permission(request, obj):
                raise PermissionDenied
        if request.method == "POST":
            if obj:
                form = form_class(request.POST, prefix="flex_field")
                if form.is_valid():
                    obj.flex_fields = form.cleaned_data
                    obj.save()
                    return HttpResponseRedirect(request.META["HTTP_REFERER"])
                else:
                    self.message_user(request, "Please fixes the errors below")
        else:
            form = form_class(prefix="flex_field")
        if add:
            title = _("Add %s")
        elif self.has_change_permission(request, obj):
            title = _("Change %s")
        else:
            title = _("View %s")
        context["title"] = title % obj._meta.verbose_name
        context["checker_form"] = form
        context["has_change_permission"] = self.has_change_permission(request)

        return TemplateResponse(
            request, "workspace/individual/change_form.html", context
        )
