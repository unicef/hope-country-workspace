from typing import TYPE_CHECKING, Any

from admin_extra_buttons.decorators import button
from adminfilters.mixin import AdminAutoCompleteSearchMixin
from concurrency.utils import fqn
from django.contrib import messages
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.db.models import Model, QuerySet
from django.forms import Form
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _

from ...models import AsyncJob
from ...state import state
from ..options import WorkspaceModelAdmin
from .cleaners import actions
from .cleaners.validate import validate_program

if TYPE_CHECKING:
    from hope_flex_fields.forms import FlexForm
    from hope_flex_fields.models import DataChecker

    from ...models.base import Validable
    from ...types import Beneficiary
    from .program import CountryProgram


class SelectedProgramMixin(WorkspaceModelAdmin):
    def get_selected_program(
        self,
        request: HttpRequest,
        obj: "Validable | None" = None,
    ) -> "tuple[str|None, CountryProgram | None]":
        return state.program

    def get_checker(self, request: HttpRequest, obj: "Beneficiary | None" = None) -> "DataChecker":
        if p := state.program:
            checker = p.get_checker_for(self.model)
        else:
            checker = None
        return checker

    def delete_queryset(self, request: HttpRequest, queryset: "QuerySet[Beneficiary]") -> None:
        queryset.filter().delete()

    def delete_model(self, request: HttpRequest, obj: "Beneficiary") -> None:
        super().delete_model(request, obj)


class BeneficiaryBaseAdmin(AdminAutoCompleteSearchMixin, SelectedProgramMixin, WorkspaceModelAdmin):
    actions = [
        actions.validate_records,
        actions.mass_update,
        actions.regex_update,
        actions.bulk_update_export,
        actions.calculate_checksum,
    ]
    title = None
    title_plural = None
    list_per_page = 20

    def has_validate_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("country_workspace.validate_beneficiary")

    def has_export_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("country_workspace.export_beneficiary")

    def has_mass_update_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("country_workspace.mass_update_beneficiary")

    def has_regex_update_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("country_workspace.regex_update_beneficiary")

    def get_queryset(self, request: HttpRequest) -> "QuerySet[Beneficiary]":
        qs = super().get_queryset(request)
        if prg := self.get_selected_program(request):
            return qs.filter(batch__program=prg)
        return qs

    def get_common_context(self, request: HttpRequest, pk: str | None = None, **kwargs: Any) -> dict[str, Any]:
        ret = super().get_common_context(request, pk, **kwargs)
        ret["datachecker"] = self.get_checker(request, ret.get("original"))
        ret["modeladmin"] = self
        ret["title_plural"] = self.title_plural
        ret.update(**kwargs)
        return ret

    @button(
        label=_("Validate"),
        enabled=lambda btn: btn.context["original"].checker,
        html_attrs={"title": "Validate single Entity and related Children"},
    )
    def validate_single(self, request: HttpRequest, pk: str) -> "HttpResponse":
        obj: "Beneficiary" = self.get_object(request, pk)
        if obj.validate_with_checker():
            self.message_user(request, _("Validation successful!"), messages.SUCCESS)
        else:
            self.message_user(request, _("Validation failed!"), messages.ERROR)

    @button(
        label=_("Validate Programme"),
        html_attrs={"title": "Validate Entire Programme: Beneficiaries, Households and Individuals"},
    )
    def validate_program(self, request: HttpRequest) -> "HttpResponse":
        opts = self.model._meta
        job = AsyncJob.objects.create(
            description="Validate Program %s" % opts.proxy_for_model._meta.verbose_name_plural,
            type=AsyncJob.JobType.TASK,
            owner=state.request.user,
            action=fqn(validate_program),
            program=state.program,
            config={},
        )
        job.queue()
        self.message_user(request, "Task scheduled", messages.SUCCESS)

    @button(html_attrs={"title": "Shows raw data as stored, ready to be sent to HOPE"})
    def view_raw_data(self, request: HttpRequest, pk: str) -> "HttpResponse":
        context = self.get_common_context(request, pk, title="Raw Data")
        return render(request, f"workspace/{self.model._meta.proxy_for_model._meta.model_name}/raw_data.html", context)

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
                {
                    "checker": self.get_checker(request),
                    "selected_program": program,
                },
            )
        return FlexFieldsChangeList

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False

    def _changeform_view(  # noqa: PLR0912
        self,
        request: HttpRequest,
        object_id: str,
        form_url: str,
        extra_context: dict[str, Any],
    ) -> HttpResponse:
        context = self.get_common_context(request, object_id, **extra_context)
        obj = self.get_object(request, unquote(object_id))
        dc: "DataChecker" = self.get_checker(request, obj)
        try:
            form_class = dc.get_form()
        except AttributeError:
            self.message_user(
                request,
                _("Required datachecker not found. Please check your Program configuration."),
                messages.ERROR,
            )
            return HttpResponseRedirect(
                reverse("workspace:workspaces_%s_view_raw_data" % self.model._meta.model_name, args=[object_id]),
            )

        if request.method == "POST":
            if not self.has_change_permission(request, obj):
                raise PermissionDenied
        elif not self.has_view_or_change_permission(request, obj):
            raise PermissionDenied

        if obj.flex_fields:
            initials = {k.replace("flex_fields__", ""): v for k, v in obj.flex_fields.items()}
        else:
            initials = {}
        if request.method == "POST":
            if obj:
                form: "FlexForm" = form_class(request.POST, prefix="flex_field", initial=initials)
                form_valid = form.is_valid()
                if form_valid or "_save_invalid" in request.POST:
                    obj.flex_fields = form.cleaned_data
                    self.save_model(request, obj, form, True)
                    if form_valid:
                        self.message_user(request, _("Record saved!"), messages.SUCCESS)
                    else:
                        self.message_user(request, _("Record saved but not validated"), messages.WARNING)
                    return HttpResponseRedirect(request.META["HTTP_REFERER"])
                self.message_user(request, "Please fixes the errors below", messages.ERROR)
        else:
            form = form_class(prefix="flex_field", initial=initials)

        context["show_save_invalid"] = True
        context["title"] = self.title
        context["checker_form"] = form
        context["has_change_permission"] = self.has_change_permission(request)

        return TemplateResponse(request, self.change_form_template, context)

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
        context = self.get_common_context(request, title="----")
        context.update(extra_context or {})
        return super().changelist_view(request, context)

    def change_view(
        self,
        request: HttpRequest,
        object_id: str,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        context = self.get_common_context(request, object_id, title="")
        context.update(extra_context or {})
        return super().change_view(request, object_id, form_url, context)

    def save_model(self, request: HttpRequest, obj: "Validable", form: Form, change: bool) -> None:
        super().save_model(request, obj, form, change)
        obj.validate_with_checker()
