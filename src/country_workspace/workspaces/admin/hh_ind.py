from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import parse_qs

from django.contrib import admin, messages
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import button, link
from adminfilters.autocomplete import LinkedAutoCompleteFilter
from adminfilters.mixin import AdminAutoCompleteSearchMixin
from hope_flex_fields.models import DataChecker

from ..options import WorkspaceModelAdmin
from . import actions

if TYPE_CHECKING:
    from ...models.base import Validable
    from .program import CountryProgram


class SelectedProgramMixin(WorkspaceModelAdmin):

    def get_selected_program(self, request: HttpRequest, obj: "Optional[Validable]" = None) -> "CountryProgram | None":
        from country_workspace.workspaces.models import CountryProgram

        self._selected_program = None
        if obj:
            self._selected_program = obj.batch.program
        elif "program__exact" in request.GET:
            self._selected_program = CountryProgram.objects.get(pk=request.GET["program__exact"])
        elif "batch__program__exact" in request.GET:
            self._selected_program = CountryProgram.objects.get(pk=request.GET["batch__program__exact"])
        return self._selected_program

    def get_common_context(self, request: HttpRequest, pk: Optional[str] = None, **kwargs: Any) -> dict[str, Any]:
        ret = super().get_common_context(request, pk, **kwargs)

        ret["selected_program"] = self.get_selected_program(request, ret.get("original"))
        ret["preserved_filters"] = request.GET.get("_changelist_filters", "")
        return ret

    def changelist_view(self, request: HttpRequest, extra_context: Optional[dict[str, Any]] = None) -> HttpResponse:
        context = self.get_common_context(request, title="")
        context.update(extra_context or {})
        return super().changelist_view(request, context)

    @link()
    def import_rdi(self, btn: LinkButton) -> None:
        btn.visible = False
        if prg := self.get_selected_program(btn.context["request"]):
            btn.href = reverse("workspace:workspaces_countryprogram_import_rdi", args=[prg.pk])
            btn.visible = True


class CountryHouseholdIndividualBaseAdmin(AdminAutoCompleteSearchMixin, SelectedProgramMixin, WorkspaceModelAdmin):
    list_filter = (
        ("batch__program", LinkedAutoCompleteFilter.factory(parent=None)),
        ("batch", LinkedAutoCompleteFilter.factory(parent="batch__program")),
        # ("batch", BatchFilter),
    )
    actions = ["validate_queryset", actions.mass_update]

    @button(label=_("Validate"))
    def validate_single(self, request: HttpRequest, pk: str) -> "HttpResponse":
        obj: "Validable" = self.get_object(request, pk)
        if obj.validate_with_checker():
            self.message_user(request, _("Validation successful!"))
        else:
            self.message_user(request, _("Validation failed!"), messages.ERROR)

    @button(label=_("Validate Programme"), visible=lambda b: "batch__program__exact" in b.context["request"].GET)
    def validate_program(self, request: HttpRequest) -> "HttpResponse":
        from .program import CountryProgram

        if cl_flt := request.GET.get("_changelist_filters", ""):
            if prg := parse_qs(cl_flt).get("batch__program__exact"):
                self._selected_program = CountryProgram.objects.get(pk=prg[0])
                qs = self.get_queryset(request).filter(batch__program=self._selected_program)
                self.validate_queryset(request, qs)

    @admin.action(description="Validate selected")
    def validate_queryset(self, request: HttpRequest, queryset: QuerySet) -> HttpResponseRedirect | None:
        try:
            num = valid = invalid = 0
            for num, entry in enumerate(queryset.all(), 1):
                entry.validate_with_checker()
                if entry.validate_with_checker():
                    valid += 1
                else:
                    invalid += 1
            self.message_user(request, _("%s validated. Found:  %s valid - %s invalid." % (num, valid, invalid)))
        except AttributeError:
            self.message_user(
                request, _("Required datachecker not found. Please check your Program configuration."), messages.ERROR
            )
            return HttpResponseRedirect(request.META["HTTP_REFERER"])

    @button()
    def view_raw_data(self, request: HttpRequest, pk: str) -> "HttpResponse":
        context = self.get_common_context(request, pk, title="Raw Data")
        return render(request, "workspace/raw_data.html", context)

    def is_valid(self, obj: "Validable") -> bool | None:
        if not obj.last_checked:
            return None
        return not bool(obj.errors)

    is_valid.boolean = True

    def get_changelist(self, request: HttpRequest, **kwargs: Any) -> type:
        from ..changelist import FlexFieldsChangeList

        if program := self.get_selected_program(request):
            return type(
                "FlexFieldsChangeList",
                (FlexFieldsChangeList,),
                {"checker": program.household_checker, "selected_program": self.get_selected_program(request)},
            )
        return FlexFieldsChangeList

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def get_checker(self, request: HttpRequest, obj: Optional[str] = None) -> "DataChecker":
        if obj:
            return obj.program.get_checker_for(obj)
        elif p := self.get_selected_program(request):
            return p.household_checker
        raise Http404("No Household checkers available")

    def _changeform_view(
        self, request: HttpRequest, object_id: str, form_url: str, extra_context: dict[str, Any]
    ) -> HttpResponse:
        context = self.get_common_context(request, object_id, **extra_context)
        add = object_id is None
        obj = self.get_object(request, unquote(object_id))
        dc: "DataChecker" = self.get_checker(request, obj)
        try:
            form_class = dc.get_form()
        except AttributeError:
            self.message_user(
                request, _("Required datachecker not found. Please check your Program configuration."), messages.ERROR
            )
            return HttpResponseRedirect(request.META["HTTP_REFERER"])

        if request.method == "POST":
            if not self.has_change_permission(request, obj):
                raise PermissionDenied
        else:
            if not self.has_view_or_change_permission(request, obj):
                raise PermissionDenied
        initials = {k.replace("flex_fields__", ""): v for k, v in obj.flex_fields.items()}

        if request.method == "POST":
            if obj:
                form = form_class(request.POST, prefix="flex_field", initial=initials)
                if form.is_valid():
                    obj.flex_fields = form.cleaned_data
                    obj.save()
                    return HttpResponseRedirect(request.META["HTTP_REFERER"])
                else:
                    self.message_user(request, "Please fixes the errors below", messages.ERROR)
        else:
            form = form_class(prefix="flex_field", initial=initials)
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
