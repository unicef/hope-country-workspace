from typing import Any

from django import forms
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from admin_extra_buttons.api import button, link
from admin_extra_buttons.buttons import LinkButton
from hope_flex_fields.models import DataChecker
from hope_smart_import.readers import open_xls_multi

from country_workspace.state import state

from ...sync.office import sync_programs
from ..models import CountryProgram
from ..options import WorkspaceModelAdmin
from .forms import ImportFileForm


class SelectColumnsForm(forms.Form):
    columns = forms.MultipleChoiceField(choices=(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args: Any, **kwargs: Any):
        self.checker: "DataChecker" = kwargs.pop("checker")
        self.checker_fields = {}
        super().__init__(*args, **kwargs)
        columns: list[tuple[str, str]] = [("name", "name"), ("id", "id")]
        for k, f in self.checker.get_form().declared_fields.items():
            columns.append((k, f.label))
            self.checker_fields[k] = f
        self.fields["columns"].choices = columns
        # columns = [(k, f.label) for k, f in self.checker.get_form().declared_fields.items()]
        # self.fields["columns"].choices = columns
        # self.checker_fields = {k:v for k, v in self.checker.get_fields()}


class ProgramForm(forms.ModelForm):
    class Meta:
        model = CountryProgram
        exclude = ("country_office",)


def clean_field_name(v):
    return v.replace("_h_c", "").replace("_h_f", "").replace("_i_c", "").replace("_i_f", "").lower()


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

    def get_queryset(self, request: HttpResponse) -> QuerySet[CountryProgram]:
        return CountryProgram.objects.filter(country_office=state.tenant)

    def has_add_permission(self, request: HttpResponse) -> bool:
        return False

    @link(
        change_list=False,
        html_attrs={"class": "superuser-only"},
        visible=lambda o: o.context["request"].user.is_superuser,
    )
    def view_in_admin(self, btn: LinkButton) -> None:
        obj = btn.context["original"]
        base = reverse("admin:country_workspace_program_change", args=[obj.pk])
        btn.href = base

    @link(change_list=False)
    def population(self, btn: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryhousehold_changelist")
        obj = btn.context["original"]
        btn.href = f"{base}?program__exact={obj.pk}"

    @button()
    def sync(self, request: HttpResponse) -> None:
        sync_programs(state.tenant)

    def _configure_columns(self, request: HttpResponse, context: dict[str, Any]) -> "HttpResponse":

        program: "CountryProgram" = context["original"]
        checker: DataChecker = context["checker"]

        initials = [s.replace("flex_fields__", "") for s in getattr(program, context["storage_field"]).split("\n")]

        if request.method == "POST":
            form = SelectColumnsForm(
                request.POST,
                checker=checker,
                initial={"columns": initials},
            )
            if form.is_valid():
                columns = []
                for s in form.cleaned_data["columns"]:
                    if s in ["name", "id"]:
                        columns.append(s)
                    else:
                        columns.append("flex_fields__%s" % s)
                setattr(program, context["storage_field"], "\n".join(columns))
                program.save()
                return HttpResponseRedirect(reverse("workspace:workspaces_countryprogram_change", args=[program.pk]))
        else:
            form = SelectColumnsForm(checker=checker, initial={"columns": initials})
        context["form"] = form
        return render(request, "workspace/program/configure_columns.html", context)

    @button()
    def household_columns(self, request: HttpResponse, pk: str) -> "HttpResponse | HttpResponseRedirect":
        context = self.get_common_context(request, pk, title="Configure default Household columns")
        program: "CountryProgram" = context["original"]
        context["checker"]: "DataChecker" = program.household_checker
        context["storage_field"] = "household_columns"
        return self._configure_columns(request, context)

    @button()
    def individual_columns(self, request: HttpResponse, pk: str) -> "HttpResponse | HttpResponseRedirect":
        context = self.get_common_context(request, pk, title="Configure default Individual columns")
        program: "CountryProgram" = context["original"]
        context["checker"]: "DataChecker" = program.individual_checker
        context["storage_field"] = "individual_columns"
        return self._configure_columns(request, context)

    @button(label=_("Import File"))
    def import_rdi(self, request: HttpRequest, pk: str) -> "HttpResponse":
        context = self.get_common_context(request, pk)
        program: "CountryProgram" = context["original"]
        hh_ids = {}
        if request.method == "POST":
            form = ImportFileForm(request.POST, request.FILES)
            if form.is_valid():
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
                                    hh = program.households.create(
                                        country_office=program.country_office, flex_fields=record
                                    )
                                    hh_ids[record[hh_id_col]] = hh.pk
                                    total_hh += 1
                                elif sheet_index == 1:
                                    program.individuals.create(
                                        country_office=program.country_office,
                                        household_id=hh_ids[record[hh_id_col]],
                                        flex_fields=record,
                                    )
                                    total_ind += 1
                            except Exception as e:
                                raise Exception("Error processing sheet %s line %s: %s" % (1 + sheet_index, line, e))
                hh_msg = ngettext("%(c)d Household", "%(c)d Households", total_hh) % {"c": total_hh}
                ind_msg = ngettext("%(c)d Individual", "%(c)d Individuals", total_ind) % {"c": total_ind}
                self.message_user(request, _("Imported {0} and {1}").format(hh_msg, ind_msg))
                context["form"] = form

        else:
            form = ImportFileForm()
        context["form"] = form
        return render(request, "workspace/program/import_rdi.html", context)
