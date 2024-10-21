from typing import Any

from django import forms
from django.contrib.admin import register
from django.db.models import QuerySet
from django.db.transaction import atomic
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from admin_extra_buttons.api import button, link
from admin_extra_buttons.buttons import LinkButton
from hope_flex_fields.models import DataChecker
from hope_smart_import.readers import open_xls_multi

from country_workspace.state import state

from ...contrib.aurora.client import AuroraClient
from ...contrib.aurora.forms import ImportAuroraForm
from ...models import AsyncJob, Batch, Individual
from ...sync.office import sync_programs
from ..models import CountryProgram
from ..options import WorkspaceModelAdmin
from ..sites import workspace
from .forms import ImportFileForm


class SelectColumnsForm(forms.Form):
    columns = forms.MultipleChoiceField(choices=(), widget=forms.CheckboxSelectMultiple)
    model_core_fields = [("name", "name"), ("id", "id")]

    def __init__(self, *args: Any, **kwargs: Any):
        self.checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        columns: list[tuple[str, str]] = []
        for k, f in self.checker.get_form().declared_fields.items():
            columns.append((f"flex_fields__{k}", f.label))
        self.fields["columns"].choices = self.model_core_fields + sorted(columns)


class SelectIndividualColumnsForm(SelectColumnsForm):
    model_core_fields = [("name", "name"), ("id", "id"), ("household", "household")]


class ProgramForm(forms.ModelForm):
    class Meta:
        model = CountryProgram
        exclude = ("country_office",)


class BulkUpdateImportForm(forms.Form):
    file = forms.FileField()


def clean_field_name(v: str) -> str:
    return v.replace("_h_c", "").replace("_h_f", "").replace("_i_c", "").replace("_i_f", "").lower()


@register(CountryProgram, site=workspace)
class CountryProgramAdmin(WorkspaceModelAdmin):
    list_display = (
        "name",
        "sector",
        "status",
        "active",
    )
    search_fields = ("name",)
    list_filter = ("status", "active", "sector")
    exclude = ("country_office",)
    default_url_filters = {"status__exact": CountryProgram.ACTIVE}
    readonly_fields = (
        "individual_columns",
        "household_columns",
    )
    # form = ProgramForm
    ordering = ("name",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("name", "programme_code"),
                    ("status", "sector", "active"),
                )
            },
        ),
        (_("Validators"), {"fields": ("beneficiary_validator", ("household_checker", "individual_checker"))}),
        (
            _("Columns"),
            {
                "fields": (
                    "household_columns",
                    "individual_columns",
                ),
            },
        ),
        # (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    change_form_template = "workspace/program/change_form.html"

    def get_queryset(self, request: HttpResponse) -> QuerySet[CountryProgram]:
        return CountryProgram.objects.filter(country_office=state.tenant)

    def has_add_permission(self, request: HttpResponse) -> bool:
        return False

    @link(change_list=False)
    def population(self, btn: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryhousehold_changelist")
        obj = btn.context["original"]
        btn.href = f"{base}?batch__program__exact={obj.pk}"

    @button()
    def sync(self, request: HttpResponse) -> None:
        sync_programs(state.tenant)

    def _configure_columns(
        self,
        request: HttpResponse,
        form_class: "type[SelectColumnsForm|SelectIndividualColumnsForm]",
        context: dict[str, Any],
    ) -> "HttpResponse":

        program: "CountryProgram" = context["original"]
        checker: DataChecker = context["checker"]

        # initials = [s.replace("flex_fields__", "") for s in getattr(program, context["storage_field"]).split("\n")]
        initials = [s for s in getattr(program, context["storage_field"]).split("\n")]

        if request.method == "POST":
            form = form_class(
                request.POST,
                checker=checker,
                initial={"columns": initials},
            )
            if form.is_valid():
                columns = []
                for s in form.cleaned_data["columns"]:
                    columns.append(s)
                setattr(program, context["storage_field"], "\n".join(columns))
                program.save()
                return HttpResponseRedirect(reverse("workspace:workspaces_countryprogram_change", args=[program.pk]))
        else:
            form = form_class(checker=checker, initial={"columns": initials})
        context["form"] = form

        return render(request, "workspace/program/configure_columns.html", context)

    @button()
    def household_columns(self, request: HttpResponse, pk: str) -> "HttpResponse | HttpResponseRedirect":
        context = self.get_common_context(request, pk, title="Configure default Household columns")
        program: "CountryProgram" = context["original"]
        context["checker"]: "DataChecker" = program.household_checker
        context["storage_field"] = "household_columns"
        return self._configure_columns(request, SelectColumnsForm, context)

    @button()
    def individual_columns(self, request: HttpResponse, pk: str) -> "HttpResponse | HttpResponseRedirect":
        context = self.get_common_context(request, pk, title="Configure default Individual columns")
        program: "CountryProgram" = context["original"]
        context["checker"]: "DataChecker" = program.individual_checker
        context["storage_field"] = "individual_columns"
        return self._configure_columns(request, SelectIndividualColumnsForm, context)

    @button(label=_("Import File"))
    def import_rdi(self, request: HttpRequest, pk: str) -> "HttpResponse":
        context = self.get_common_context(request, pk, title="Import RDI file")
        program: "CountryProgram" = context["original"]
        context["selected_program"] = context["original"]
        hh_ids = {}
        if request.method == "POST":
            form = ImportFileForm(request.POST, request.FILES)
            if form.is_valid():
                with atomic():
                    batch_name = form.cleaned_data["batch_name"]
                    batch, __ = Batch.objects.get_or_create(
                        name=batch_name or ("Batch %s" % timezone.now()),
                        program=program,
                        country_office=program.country_office,
                        imported_by=request.user,
                    )
                    hh_id_col = form.cleaned_data["pk_column_name"]
                    total_hh = total_ind = 0
                    for sheet_index, sheet_generator in open_xls_multi(form.cleaned_data["file"], sheets=[0, 1]):
                        for line, raw_record in enumerate(sheet_generator, 1):
                            record = {}
                            for k, v in raw_record.items():
                                record[clean_field_name(k)] = v
                            if record[hh_id_col]:
                                try:
                                    if sheet_index == 0:
                                        hh = program.households.create(batch=batch, flex_fields=record)
                                        hh_ids[record[hh_id_col]] = hh.pk
                                        total_hh += 1
                                    elif sheet_index == 1:
                                        program.individuals.create(
                                            batch=batch,
                                            household_id=hh_ids[record[hh_id_col]],
                                            flex_fields=record,
                                        )
                                        total_ind += 1
                                except Exception as e:
                                    raise Exception(
                                        "Error processing sheet %s line %s: %s" % (1 + sheet_index, line, e)
                                    )
                hh_msg = ngettext("%(c)d Household", "%(c)d Households", total_hh) % {"c": total_hh}
                ind_msg = ngettext("%(c)d Individual", "%(c)d Individuals", total_ind) % {"c": total_ind}
                self.message_user(request, _("Imported {0} and {1}").format(hh_msg, ind_msg))
                context["form"] = form

        else:
            form = ImportFileForm()
        context["form"] = form
        return render(request, "workspace/program/import_rdi.html", context)

    @button(label=_("Import File Updates"))
    def import_file_updates(self, request: HttpRequest, pk: str) -> "HttpResponse":
        context = self.get_common_context(request, pk, title="Import updates from file")
        program: "CountryProgram" = context["original"]
        context["selected_program"] = context["original"]
        updated = 0
        if request.method == "POST":
            form = BulkUpdateImportForm(request.POST, request.FILES)

            if form.is_valid():
                AsyncJob.objects.create(
                    program=program, type=AsyncJob.JobType.BULK_UPDATE_IND, batch=None, file=request.FILES["file"]
                )
                self.message_user(request, _("Imported. {0} records updated").format(updated))
                return HttpResponseRedirect(self.get_changelist_url())

        else:
            form = BulkUpdateImportForm()
        context["form"] = form
        return render(request, "workspace/actions/bulk_update_import.html", context)

    @button(label=_("Import from Aurora"))
    def import_aurora(self, request: HttpRequest, pk: str) -> "HttpResponse":
        context = self.get_common_context(request, pk, title="Import from Aurora")
        program: "CountryProgram" = context["original"]
        context["selected_program"] = context["original"]
        client = AuroraClient()
        if request.method == "POST":
            form = ImportAuroraForm(request.POST)
            if form.is_valid():
                total_hh = total_ind = 0
                with atomic():
                    batch_name = form.cleaned_data["batch_name"]
                    batch, __ = Batch.objects.get_or_create(
                        name=batch_name or ("Batch %s" % timezone.now()),
                        program=program,
                        country_office=program.country_office,
                        imported_by=request.user,
                    )
                    total_hh = total_ind = 0

                    for i, record in enumerate(client.get("record")):
                        for f_name, f_value in record["fields"].items():
                            try:
                                individuals = []
                                if f_name == "household":
                                    hh = program.households.create(
                                        batch=batch, flex_fields={clean_field_name(k): v for k, v in f_value[0].items()}
                                    )
                                    total_hh += 1
                                elif f_name == "individuals":
                                    for individual in f_value:
                                        relationship = next(
                                            (
                                                k
                                                for k in individual
                                                # TODO: use a constant for the relationship instead of hardcoding it
                                                if k.startswith("relationship") and individual[k] == "head"
                                            ),
                                            None,
                                        )
                                        # TODO: define rule to populate the fullname
                                        fullname = next((k for k in individual if k.startswith("given_name")), None)
                                        for k, v in individual.items():
                                            if (
                                                relationship
                                                and clean_field_name(k) == form.cleaned_data["household_name_column"]
                                            ):
                                                program.households.filter(pk=hh.pk).update(name=v)
                                        individuals.append(
                                            Individual(
                                                batch=batch,
                                                household_id=hh.pk,
                                                name=individual.get(fullname, ""),
                                                flex_fields={clean_field_name(k): v for k, v in individual.items()},
                                            )
                                        )
                                        total_ind += 1
                                program.individuals.bulk_create(individuals)
                            except Exception as e:
                                raise Exception("Error processing record %s: %s" % (i, e))

                hh_msg = ngettext("%(c)d Household", "%(c)d Households", total_hh) % {"c": total_hh}
                ind_msg = ngettext("%(c)d Individual", "%(c)d Individuals", total_ind) % {"c": total_ind}
                self.message_user(request, _("Imported {0} and {1}").format(hh_msg, ind_msg))
                context["form"] = form

        else:
            form = ImportAuroraForm()
        context["form"] = form
        return render(request, "workspace/program/import_rdi.html", context)
        # return render(request, "workspace/program/import_aurora.html", context)
