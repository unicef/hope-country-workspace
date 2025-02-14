from typing import TYPE_CHECKING, Any

from admin_extra_buttons.api import button
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.admin import register
from django.db.models import QuerySet
from django.forms import Media
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from strategy_field.utils import fqn

from ...contrib.aurora.forms import ImportAuroraForm
from ...datasources.rdi import import_from_rdi
from ...models import AsyncJob
from ...utils.flex_fields import get_checker_fields
from ..models import CountryProgram
from ..options import WorkspaceModelAdmin
from ..sites import workspace
from .cleaners.bulk_update import bulk_update_household, bulk_update_individual
from .forms import ImportFileForm
from country_workspace.constants import BATCH_NAME_DEFAULT
from country_workspace.contrib.aurora.pipeline import import_from_aurora
from country_workspace.state import state

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker


class SelectColumnsForm(forms.Form):
    columns = forms.MultipleChoiceField(choices=(), widget=forms.CheckboxSelectMultiple)
    model_core_fields = [("name", "name"), ("id", "id")]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        columns: list[tuple[str, str]] = []

        for name, label in get_checker_fields(self.checker):
            columns.append((f"flex_fields__{name}", label))

        self.fields["columns"].choices = self.model_core_fields + sorted(columns)


class SelectIndividualColumnsForm(SelectColumnsForm):
    model_core_fields = [("name", "name"), ("id", "id"), ("household", "household")]


class ProgramForm(forms.ModelForm):
    class Meta:
        model = CountryProgram
        fields = (
            "name",
            "code",
            "status",
            "sector",
            "active",
            "beneficiary_validator",
            "household_checker",
            "individual_checker",
            "household_search",
            "individual_search",
            "household_columns",
            "individual_columns",
            "extra_fields",
        )


class BulkUpdateImportForm(forms.Form):
    description = forms.CharField(widget=forms.Textarea)
    target = forms.ChoiceField(choices=(("hh", "Household"), ("ind", "Individual")))
    file = forms.FileField()


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
        "active",
        "code",
        "status",
        "sector",
        "name",
    )
    form = ProgramForm
    ordering = ("name",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("name", "code"),
                    ("status", "sector", "active"),
                ),
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
    )

    @property
    def media(self) -> forms.Media:
        extra = "" if settings.DEBUG else ".min"
        base = super().media
        return base + forms.Media(
            js=[
                "workspace/js/program%s.js" % extra,
            ],
            css={},
        )

    def get_queryset(self, request: HttpResponse) -> QuerySet[CountryProgram]:
        return CountryProgram.objects.filter(country_office=state.tenant)

    def has_add_permission(self, request: HttpResponse) -> bool:
        return False

    def has_delete_permission(self, request: HttpResponse, obj: CountryProgram | None = None) -> bool:
        return False

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, None] | None = None) -> HttpResponse:
        url = reverse("workspace:workspaces_countryprogram_change", args=[state.program.pk])
        return HttpResponseRedirect(url)

    def _configure_columns(
        self,
        request: HttpResponse,
        form_class: "type[SelectColumnsForm|SelectIndividualColumnsForm]",
        context: dict[str, Any],
    ) -> "HttpResponse":
        program: "CountryProgram" = context["original"]
        checker: DataChecker = context["checker"]

        initials = getattr(program, context["storage_field"]).split("\n")

        if request.method == "POST":
            form = form_class(
                request.POST,
                checker=checker,
                initial={"columns": initials},
            )
            if form.is_valid():
                columns = form.cleaned_data["columns"]
                setattr(program, context["storage_field"], "\n".join(columns))
                program.save()
                return HttpResponseRedirect(reverse("workspace:workspaces_countryprogram_change", args=[program.pk]))
        else:
            form = form_class(checker=checker, initial={"columns": initials})
        context["form"] = form

        return render(request, "workspace/program/configure_columns.html", context)

    @button(permission="workspaces.change_countryprogram")
    def household_columns(self, request: HttpResponse, pk: str) -> "HttpResponse | HttpResponseRedirect":
        context = self.get_common_context(request, pk, title="Configure default Household columns")
        program: "CountryProgram" = context["original"]
        context["checker"]: "DataChecker" = program.household_checker
        context["storage_field"] = "household_columns"
        return self._configure_columns(request, SelectColumnsForm, context)

    @button(permission="workspaces.change_countryprogram")
    def individual_columns(self, request: HttpResponse, pk: str) -> "HttpResponse | HttpResponseRedirect":
        context = self.get_common_context(request, pk, title="Configure default Individual columns")
        program: "CountryProgram" = context["original"]
        context["checker"]: "DataChecker" = program.individual_checker
        context["storage_field"] = "individual_columns"
        return self._configure_columns(request, SelectIndividualColumnsForm, context)

    @button(label=_("Update Records"), permission="country_workspace.import_program_data")
    def import_file_updates(self, request: HttpRequest, pk: str) -> "HttpResponse":
        context = self.get_common_context(request, pk, title="Import updates from file")
        program: "CountryProgram" = context["original"]
        context["selected_program"] = context["original"]
        updated = 0
        function_map = {"hh": fqn(bulk_update_household), "ind": fqn(bulk_update_individual)}
        if request.method == "POST":
            form = BulkUpdateImportForm(request.POST, request.FILES)
            if form.is_valid():
                job = AsyncJob.objects.create(
                    description=form.cleaned_data["description"],
                    program=program,
                    owner=request.user,
                    type=AsyncJob.JobType.TASK,
                    action=function_map[form.cleaned_data["target"]],
                    batch=None,
                    file=request.FILES["file"],
                    config={},
                )
                job.queue()
                self.message_user(request, _("Import scheduled").format(updated))
                return HttpResponseRedirect(self.get_changelist_url())

        else:
            form = BulkUpdateImportForm()
        context["form"] = form
        return render(request, "workspace/actions/bulk_update_import.html", context)

    @button(label=_("Import Data"), permission="country_workspace.import_program_data")
    def import_data(self, request: HttpRequest, pk: str) -> "HttpResponse":
        context = self.get_common_context(request, pk, title="Import Data")
        context["selected_program"] = program = context["original"]
        context["media"] = Media(js=["admin/js/vendor/jquery/jquery.js", "workspace/js/import_data.js"], css={})
        form_rdi = ImportFileForm(prefix="rdi")
        form_aurora = ImportAuroraForm(prefix="aurora", program=program)

        if request.method == "POST":
            match request.POST.get("_selected_tab"):
                case "rdi":
                    if not (form_rdi := self.import_rdi(request, program)):
                        return HttpResponseRedirect(reverse("workspace:workspaces_countryasyncjob_changelist"))
                case "aurora":
                    if not (form_aurora := self.import_aurora(request, program)):
                        return HttpResponseRedirect(reverse("workspace:workspaces_countryasyncjob_changelist"))
                case "kobo":
                    self.message_user(request, _("Not implemented"))

        context["form_rdi"] = form_rdi
        context["form_aurora"] = form_aurora

        return render(request, "workspace/program/import.html", context)

    def import_rdi(self, request: HttpRequest, program: CountryProgram) -> "ImportFileForm | None":
        form = ImportFileForm(request.POST, request.FILES, prefix="rdi")
        if form.is_valid():
            job: AsyncJob = AsyncJob.objects.create(
                description="RDI importing",
                type=AsyncJob.JobType.TASK,
                action=fqn(import_from_rdi),
                file=request.FILES["rdi-file"],
                program=program,
                owner=request.user,
                config={
                    "batch_name": form.cleaned_data["batch_name"] or BATCH_NAME_DEFAULT,
                    "household_pk_col": form.cleaned_data["pk_column_name"],
                    "master_column_label": form.cleaned_data["master_column_label"],
                    "detail_column_label": form.cleaned_data["detail_column_label"],
                },
            )
            job.queue()
            self.message_user(request, _("Import scheduled"), messages.SUCCESS)
            return None
        return form

    def import_aurora(self, request: HttpRequest, program: "CountryProgram") -> "ImportAuroraForm|None":
        form = ImportAuroraForm(request.POST, prefix="aurora", program=program)
        if form.is_valid():
            registration_reference_pk = getattr(form.cleaned_data["registration"], "reference_pk", None)
            job: AsyncJob = AsyncJob.objects.create(
                description="Aurora importing",
                type=AsyncJob.JobType.TASK,
                action=fqn(import_from_aurora),
                file=None,
                program=program,
                owner=request.user,
                config={
                    "batch_name": form.cleaned_data["batch_name"] or BATCH_NAME_DEFAULT,
                    "registration_reference_pk": registration_reference_pk,
                    "household_name_column": form.cleaned_data["household_name_column"],
                },
            )
            job.queue()
            self.message_user(request, _("Import scheduled"), messages.SUCCESS)
            return None
        return form
