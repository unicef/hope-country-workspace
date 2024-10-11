from django import forms
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from admin_extra_buttons.api import button, link
from admin_extra_buttons.buttons import LinkButton
from hope_flex_fields.models import DataChecker

from country_workspace.state import state

from ...sync.office import sync_programs
from ..models import CountryProgram
from ..options import WorkspaceModelAdmin


class SelectColumnsForm(forms.Form):
    columns = forms.MultipleChoiceField(choices=(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
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
    form = ProgramForm
    ordering = ("name",)

    def get_queryset(self, request):
        return CountryProgram.objects.filter(country_office=state.tenant)

    def has_add_permission(self, request):
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
    def sync(self, request) -> None:
        sync_programs(state.tenant)

    def _configure_columns(self, request, context) -> "HttpResponse":

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
    def household_columns(self, request, pk) -> "HttpResponse | HttpResponseRedirect":
        context = self.get_common_context(request, pk, title="Configure default Household columns")
        program: "CountryProgram" = context["original"]
        context["checker"]: "DataChecker" = program.household_checker
        context["storage_field"] = "household_columns"
        return self._configure_columns(request, context)

    @button()
    def individual_columns(self, request, pk) -> "HttpResponse | HttpResponseRedirect":
        context = self.get_common_context(request, pk, title="Configure default Individual columns")
        program: "CountryProgram" = context["original"]
        context["checker"]: "DataChecker" = program.individual_checker
        context["storage_field"] = "individual_columns"
        return self._configure_columns(request, context)
