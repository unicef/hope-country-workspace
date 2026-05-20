from typing import Any

from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import button, link
from django import forms
from django.contrib import messages
from django.contrib.admin import register
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from strategy_field.utils import fqn

from country_workspace.models import AsyncJob, MappingImporter, Program, Transformer
from ....state import state
from ...models import CountryBatch
from ...options import WorkspaceModelAdmin
from ...permissions import can_reprocess_batch
from ...sites import workspace
from ..filters import CWLinkedAutoCompleteFilter, ChoiceFilter, UserAutoCompleteFilter
from ..hh_ind import SelectedProgramMixin
from .reprocessing import reprocess_batch as reprocess_batch_task


class ProgramBatchFilter(CWLinkedAutoCompleteFilter):
    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.lookup_val:
            p = state.tenant.programs.get(pk=self.lookup_val)
            queryset = super().queryset(request, queryset).filter(program=p)
        return queryset


class BatchReprocessForm(forms.Form):
    household_transformer = forms.ModelChoiceField(
        queryset=Transformer.objects.none(),
        required=False,
        label=_("Household Transformer (optional)"),
        empty_label=_("No transformer"),
        help_text=_("Optional: Transform values at the end of reprocessing."),
    )
    household_mapping = forms.ModelChoiceField(
        queryset=MappingImporter.objects.none(),
        required=False,
        label=_("Household Mapping (optional)"),
        empty_label=_("No mapping (validation only)"),
        help_text=_("Optional: Select a mapping to apply to household data before validation"),
    )
    individual_transformer = forms.ModelChoiceField(
        queryset=Transformer.objects.none(),
        required=False,
        label=_("Individual Transformer (optional)"),
        empty_label=_("No transformer"),
        help_text=_("Optional: Transform values at the end of reprocessing."),
    )
    individual_mapping = forms.ModelChoiceField(
        queryset=MappingImporter.objects.none(),
        required=False,
        label=_("Individual Mapping (optional)"),
        empty_label=_("No mapping (validation only)"),
        help_text=_("Optional: Select a mapping to apply to individual data before validation"),
    )

    def __init__(self, *args: Any, program: Program | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        if program:
            transformer_queryset = Transformer.objects.filter(office=program.country_office)
            self.fields["household_transformer"].queryset = transformer_queryset
            self.fields["individual_transformer"].queryset = transformer_queryset

            if program.is_master_detail:
                if program.household_checker:
                    self.fields["household_mapping"].queryset = MappingImporter.objects.filter(
                        office=program.country_office,
                        data_checker=program.household_checker,
                    )
                else:
                    self.fields.pop("household_mapping", None)
            else:
                self.fields.pop("household_mapping", None)
                self.fields.pop("household_transformer", None)

            if program.individual_checker:
                self.fields["individual_mapping"].queryset = MappingImporter.objects.filter(
                    office=program.country_office,
                    data_checker=program.individual_checker,
                )
            else:
                self.fields.pop("individual_mapping", None)


@register(CountryBatch, site=workspace)
class CountryBatchAdmin(SelectedProgramMixin, WorkspaceModelAdmin):
    list_display = ["name", "import_date", "imported_by", "source", "status"]
    search_fields = ("name",)
    change_list_template = ["workspace/change_list.html"]
    change_form_template = ["workspace/change_form.html"]
    ordering = ("-import_date",)
    list_filter = (("source", ChoiceFilter), ("imported_by", UserAutoCompleteFilter))
    readonly_fields = fields = ("name", "source", "status")

    def get_common_context(self, request: HttpRequest, pk: str | None = None, **kwargs: Any) -> dict[str, Any]:
        kwargs["modeladmin"] = self
        kwargs["modeladmin_name"] = self.__class__.__name__
        return super().get_common_context(request, pk, **kwargs)

    def get_queryset(self, request: HttpRequest) -> "QuerySet[CountryBatch]":
        return (
            super()
            .get_queryset(request)
            .select_related("program", "country_office")
            .filter(country_office=state.tenant, program=state.program)
        )

    def has_add_permission(self, request: HttpRequest, obj: CountryBatch | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: CountryBatch | None = None) -> bool:
        return False

    @link(change_list=False, html_attrs={"title": "Shows related Household records."})
    def imported_records(self, btn: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryhousehold_changelist")
        obj = btn.context["original"]
        btn.href = f"{base}?batch__exact={obj.pk}"
        if obj.program.beneficiary_group:
            btn.label = obj.program.beneficiary_group.group_label
            if not obj.program.beneficiary_group.master_detail:
                btn.visible = False

    @link(change_list=False, html_attrs={"title": "Shows related Individual records."})
    def imported_individuals(self, btn: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryindividual_changelist")
        obj = btn.context["original"]
        btn.href = f"{base}?batch__exact={obj.pk}"
        if obj.program.beneficiary_group:
            btn.label = obj.program.beneficiary_group.member_label

    @button(
        change_list=False,
        permission=can_reprocess_batch,
        html_attrs={"title": "Re-validate all records in this batch (excludes records already pushed to HOPE)"},
    )
    def reprocess_batch(self, request: HttpRequest, pk: str) -> "HttpResponse":
        obj: CountryBatch | None = self.get_object(request, pk)
        if not obj:
            return HttpResponse("Batch not found", status=404)

        # Handle form submission
        if request.method == "POST" and "apply" in request.POST:
            form = BatchReprocessForm(request.POST, program=obj.program)
            if form.is_valid():
                config = {"batch_id": obj.pk}

                if form.cleaned_data.get("household_transformer"):
                    config["household_transformer_id"] = form.cleaned_data["household_transformer"].pk
                if form.cleaned_data.get("household_mapping"):
                    config["household_mapping_id"] = form.cleaned_data["household_mapping"].pk
                if form.cleaned_data.get("individual_transformer"):
                    config["individual_transformer_id"] = form.cleaned_data["individual_transformer"].pk
                if form.cleaned_data.get("individual_mapping"):
                    config["individual_mapping_id"] = form.cleaned_data["individual_mapping"].pk

                job = AsyncJob.objects.create(
                    description=f"Reprocess batch: {obj.name}",
                    type=AsyncJob.JobType.TASK,
                    owner=request.user,
                    action=fqn(reprocess_batch_task),
                    program=obj.program,
                    batch=obj,
                    config=config,
                )
                job.queue()

                self.message_user(request, "Batch reprocessing has been scheduled.", messages.SUCCESS)

                # Redirect to changelist
                namespace = self.admin_site.name
                opts = self.model._meta
                url_name = f"{namespace}:{opts.app_label}_{opts.model_name}_changelist"
                return HttpResponseRedirect(reverse(url_name))

            self.message_user(request, "Please correct the errors below.", messages.ERROR)
        else:
            form = BatchReprocessForm(program=obj.program)

        context = self.get_common_context(
            request,
            pk=pk,
            title="Reprocess Batch",
            form=form,
            batch=obj,
        )

        return render(request, "workspace/admin_extra_buttons/reprocess_batch_form.html", context)
