from typing import TYPE_CHECKING

from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _

from adminfilters.mixin import AdminAutoCompleteSearchMixin
from hope_flex_fields.models import DataChecker

from country_workspace.workspaces.filters import ProgramFilter
from country_workspace.workspaces.options import WorkspaceModelAdmin

if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryProgram


class CountryHouseholdIndividualBaseAdmin(AdminAutoCompleteSearchMixin, WorkspaceModelAdmin):
    list_filter = (("program", ProgramFilter),)

    def get_changelist(self, request, **kwargs):
        from ..changelist import FlexFieldsChangeList

        if program := self.get_selected_program(request):
            return type("FlexFieldsChangeList", (FlexFieldsChangeList,), {"checker": program.household_checker})
        return FlexFieldsChangeList

    def has_add_permission(self, request):
        return False

    def get_selected_program(self, request) -> "CountryProgram | None":
        from country_workspace.workspaces.models import CountryProgram

        self._selected_program = None
        if "program__exact" in request.GET:
            self._selected_program = CountryProgram.objects.get(pk=request.GET["program__exact"])
        return self._selected_program

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["selected_program"] = self.get_selected_program(request)
        extra_context["title"] = ""
        return super().changelist_view(request, extra_context)

    def get_checker(self, request, obj=None) -> "DataChecker":
        raise NotImplementedError

    def get_common_context(self, request, pk=None, **kwargs):
        kwargs["selected_program"] = self.get_selected_program(request)
        return super().get_common_context(request, pk, **kwargs)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        if object_id:
            if obj := self.get_object(request, object_id):
                dc: "DataChecker" = self.get_checker(request, obj)
                extra_context["checker_form"] = dc.get_form()(initial=obj.flex_fields, prefix="flex_field")
        return super().changeform_view(request, object_id, form_url, extra_context)

    def _changeform_view(self, request, object_id, form_url, extra_context):
        context = self.get_common_context(request, object_id, **extra_context)
        add = object_id is None
        obj = self.get_object(request, unquote(object_id))
        dc: "DataChecker" = self.get_checker(request, obj)
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

        return TemplateResponse(request, self.change_form_template, context)
