from typing import TYPE_CHECKING, Any

from admin_extra_buttons.api import button
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.admin import register
from django.db.models import QuerySet, Field
from django.forms import Media
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from strategy_field.utils import fqn

from country_workspace.contrib.aurora.pipeline import (
    Config as AuroraConfig,
    import_from_aurora,
)
from country_workspace.state import state
from country_workspace.utils.fields import batch_name_default

from ...contrib.aurora.forms import ImportAuroraForm
from ...contrib.kobo.forms import ImportKoboForm
from ...contrib.kobo.sync import (
    Config as KoboConfig,
    import_data as import_from_kobo,
)
from ...datasources.rdi import (
    Config as RDIConfig,
    import_from_rdi,
)
from ...models import AsyncJob
from ...utils.flex_fields import get_checker_fields
from ..models import CountryProgram
from ..options import WorkspaceModelAdmin
from ..sites import workspace
from .cleaners.bulk_update import bulk_update_household, bulk_update_individual
from .forms import BulkUpdateImportForm, ImportFileForm

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker


class SelectColumnsForm(forms.Form):
    columns = forms.MultipleChoiceField(choices=(), widget=forms.CheckboxSelectMultiple)
    model_core_fields = [("name", "name"), ("id", "id")]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        columns: list[tuple[str, str]] = []

        for name, label in get_checker_fields(self.checker, with_fs_prefix=True):
            columns.append((f"flex_fields__{name}", label))

        self.fields["columns"].choices = self.model_core_fields + columns


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
            "beneficiary_validator",
            "household_checker",
            "individual_checker",
            "household_search",
            "individual_search",
            "household_columns",
            "individual_columns",
            "extra_fields",
            "serializer",
        )


KOBO_IMPORT_JOB_DESCRIPTION = "Kobo import: {program_name}"


@register(CountryProgram, site=workspace)
class CountryProgramAdmin(WorkspaceModelAdmin):
    list_display = (
        "name",
        "sector",
        "status",
    )
    search_fields = ("name",)
    list_filter = ("status", "sector")
    exclude = ("country_office",)
    default_url_filters = {"status__exact": CountryProgram.ACTIVE}
    readonly_fields = (
        "individual_columns",
        "household_columns",
        "code",
        "status",
        "sector",
        "name",
    )
    form = ProgramForm
    ordering = ("name",)

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
        return CountryProgram.objects.filter(country_office=state.tenant, enabled=True)

    def has_add_permission(self, request: HttpResponse) -> bool:
        return False

    def has_delete_permission(self, request: HttpResponse, obj: CountryProgram | None = None) -> bool:
        return False

    def get_fieldsets(
        self, request: HttpRequest, obj: CountryProgram | None = None
    ) -> list[tuple[str | None, dict[str, Any]]]:
        fieldsets = (
            (
                None,
                {
                    "fields": (
                        ("name", "code"),
                        ("status", "sector"),
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
            (
                _("Serializer"),
                {
                    "fields": ("serializer",),
                },
            ),
        )
        if obj and obj.beneficiary_group and not obj.beneficiary_group.master_detail:
            fieldsets[1][1]["fields"] = ("beneficiary_validator", "individual_checker")
            fieldsets[2][1]["fields"] = ("individual_columns",)

        return fieldsets

    def formfield_for_dbfield(self, db_field: Field, request: HttpRequest, **kwargs: Any) -> Field | None:
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        object_id = request.resolver_match.kwargs.get("object_id")

        if not (object_id and field):
            return field
        obj = self.get_object(request, object_id)
        if not (obj and obj.beneficiary_group):
            return field

        bg = obj.beneficiary_group
        match db_field.name.split("_"):
            case ["household", suffix] if bg.master_detail:
                label_prefix = bg.group_label or _("Household")
                field.label = f"{label_prefix} {suffix}"
            case ["individual", suffix]:
                label_prefix = bg.member_label or _("Individual")
                field.label = f"{label_prefix} {suffix}"
            case _:
                ...

        return field

    def change_view(
        self, request: HttpRequest, object_id: str, form_url: str = "", extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        extra_context = {
            **(extra_context or {}),
            "modeladmin": self,
            "modeladmin_name": self.__class__.__name__,
        }
        return super().change_view(request, object_id, form_url, extra_context)

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, None] | None = None) -> HttpResponse:
        url = reverse("workspace:workspaces_countryprogram_change", args=[state.program.pk])
        return HttpResponseRedirect(url)

    def changeform_view(
        self,
        request: "HttpRequest",
        object_id: str | None = None,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        extra_context = extra_context or {}
        if (obj := self.get_object(request, object_id)) and obj.beneficiary_group:
            group_label = obj.beneficiary_group.group_label or _("Household")
            member_label = obj.beneficiary_group.member_label or _("Individual")
            dynamic_labels = {
                "individual_columns": f"{member_label} columns",
            }
            if obj.beneficiary_group.master_detail:
                dynamic_labels["household_columns"] = f"{group_label} columns"
            extra_context = {
                **extra_context,
                "dynamic_field_labels": dynamic_labels,
                "btnlabels": {
                    "individual_columns": f"{member_label} Columns",
                    "household_columns": f"{group_label} Columns",
                },
            }
        return super().changeform_view(request, object_id, form_url, extra_context=extra_context)

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

    @button(
        permission="workspaces.change_countryprogram",
        html_attrs={"title": "Allow to select columns to be highlighted in the list view."},
        visible=lambda btn: btn.context["original"].beneficiary_group.master_detail,
        enabled=lambda btn: btn.context["original"].beneficiary_group.master_detail,
    )
    def household_columns(self, request: HttpResponse, pk: str) -> "HttpResponse | HttpResponseRedirect":
        context = self.get_common_context(request, pk, title="Configure default Household columns")
        program: "CountryProgram" = context["original"]
        context["checker"]: "DataChecker" = program.household_checker
        context["storage_field"] = "household_columns"
        return self._configure_columns(request, SelectColumnsForm, context)

    @button(
        permission="workspaces.change_countryprogram",
        html_attrs={"title": "Allow to select columns to be highlighted in the list view."},
    )
    def individual_columns(self, request: HttpResponse, pk: str) -> "HttpResponse | HttpResponseRedirect":
        context = self.get_common_context(request, pk, title="Configure default Individual columns")
        program: "CountryProgram" = context["original"]
        context["checker"]: "DataChecker" = program.individual_checker
        context["storage_field"] = "individual_columns"
        return self._configure_columns(request, SelectIndividualColumnsForm, context)

    @button(
        label=_("Update Records"),
        permission="country_workspace.import_program_data",
        html_attrs={"title": "Allow to updated records previously exported."},
    )
    def import_file_updates(self, request: HttpRequest, pk: str) -> "HttpResponse":
        context = self.get_common_context(request, pk, title="Bulk update records via .xlsx import")
        program: "CountryProgram" = context["original"]
        context["selected_program"] = context["original"]
        function_map = {"hh": fqn(bulk_update_household), "ind": fqn(bulk_update_individual)}
        if request.method == "POST":
            form = BulkUpdateImportForm(request.POST, request.FILES)
            if form.is_valid():
                job = AsyncJob.objects.create(
                    description=form.cleaned_data["description"] or context["title"],
                    program=program,
                    owner=request.user,
                    type=AsyncJob.JobType.TASK,
                    action=function_map[form.cleaned_data["target"]],
                    batch=None,
                    file=request.FILES["file"],
                    config={},
                )
                job.queue()
                self.message_user(request, _("Import scheduled"), messages.SUCCESS)
                return HttpResponseRedirect(reverse("workspace:workspaces_countryasyncjob_changelist"))

        else:
            form = BulkUpdateImportForm()
        context["form"] = form
        return render(request, "workspace/actions/bulk_update_import.html", context)

    @button(
        label=_("Import Data"),
        permission="country_workspace.import_program_data",
        html_attrs={"title": "Import Data using XLS/RDI, Kobo or Aurora."},
    )
    def import_data(self, request: HttpRequest, pk: str) -> "HttpResponse":
        context = self.get_common_context(request, pk, title="Import Data")
        context["selected_program"] = program = context["original"]
        context["media"] = Media(js=["admin/js/vendor/jquery/jquery.js", "workspace/js/import_data.js"], css={})

        if request.method == "POST":
            match request.POST.get("_selected_tab"):
                case "rdi":
                    if not (form_rdi := self.import_rdi(request, program)):
                        return HttpResponseRedirect(reverse("workspace:workspaces_countryasyncjob_changelist"))
                case "aurora":
                    if not (form_aurora := self.import_aurora(request, program)):
                        return HttpResponseRedirect(reverse("workspace:workspaces_countryasyncjob_changelist"))
                case "kobo":
                    if not (form_kobo := self.import_kobo(request, program)):
                        return HttpResponseRedirect(reverse("workspace:workspaces_countryasyncjob_changelist"))
        else:
            form_rdi = ImportFileForm(prefix="rdi", beneficiary_group=program.beneficiary_group)
            form_aurora = ImportAuroraForm(prefix="aurora", program=program)
            form_kobo = ImportKoboForm(prefix="kobo", kobo_country_code=program.country_office.kobo_country_code)

            context["form_rdi"] = form_rdi
            context["form_aurora"] = form_aurora
            context["form_kobo"] = form_kobo

        return render(request, "workspace/program/import.html", context)

    def import_rdi(self, request: HttpRequest, program: CountryProgram) -> "ImportFileForm | None":
        form = ImportFileForm(request.POST, request.FILES, prefix="rdi", beneficiary_group=program.beneficiary_group)
        if form.is_valid():
            config: RDIConfig = {
                "master_detail": (
                    master_detail := (program.beneficiary_group.master_detail if program.beneficiary_group else False)
                ),
                "batch_name": form.cleaned_data["batch_name"] or batch_name_default(),
                "validate_mode": form.cleaned_data["validate_mode"],
                "first_line": form.cleaned_data["first_line"],
                **(
                    {
                        "household_pk_col": form.cleaned_data.get("pk_column_name"),
                        "master_column_label": form.cleaned_data.get("master_column_label"),
                        "detail_column_label": form.cleaned_data.get("detail_column_label"),
                    }
                    if master_detail
                    else {
                        "people_column_prefix": form.cleaned_data.get("people_column_prefix"),
                    }
                ),
            }
            job: AsyncJob = AsyncJob.objects.create(
                description="RDI import",
                type=AsyncJob.JobType.TASK,
                action=fqn(import_from_rdi),
                file=request.FILES["rdi-file"],
                program=program,
                owner=request.user,
                config=config,
            )
            job.queue()
            self.message_user(request, _("Import scheduled"), messages.SUCCESS)
            return None
        return form

    def import_aurora(self, request: HttpRequest, program: "CountryProgram") -> "ImportAuroraForm|None":
        form = ImportAuroraForm(request.POST, prefix="aurora", program=program)
        if form.is_valid():
            config: AuroraConfig = {
                "batch_name": form.cleaned_data["batch_name"] or batch_name_default(),
                "validate_mode": form.cleaned_data["validate_mode"],
                "registration_reference_pk": getattr(form.cleaned_data.get("registration"), "reference_pk", None),
                "individuals_column_prefix": form.cleaned_data["individuals_column_prefix"],
                "master_detail": (
                    master_detail := (program.beneficiary_group.master_detail if program.beneficiary_group else False)
                ),
                **(
                    {
                        "household_column_prefix": form.cleaned_data.get("household_column_prefix"),
                        "household_label_column": form.cleaned_data.get("household_label_column"),
                    }
                    if master_detail
                    else {}
                ),
            }
            job: AsyncJob = AsyncJob.objects.create(
                description="Aurora importing",
                type=AsyncJob.JobType.TASK,
                action=fqn(import_from_aurora),
                file=None,
                program=program,
                owner=request.user,
                config=config,
            )
            job.queue()
            self.message_user(request, _("Import scheduled"), messages.SUCCESS)
            return None
        return form

    def import_kobo(self, request: HttpRequest, program: "CountryProgram") -> ImportKoboForm | None:
        form = ImportKoboForm(request.POST, prefix="kobo", kobo_country_code=program.country_office.kobo_country_code)
        if form.is_valid():
            config: KoboConfig = {
                "batch_name": form.cleaned_data["batch_name"] or batch_name_default(),
                "validate_mode": form.cleaned_data["validate_mode"],
                "project_id": form.cleaned_data["project_id"],
                "individual_records_field": form.cleaned_data["individual_records_field"],
            }
            job: AsyncJob = AsyncJob.objects.create(
                description=KOBO_IMPORT_JOB_DESCRIPTION.format(program_name=program.name),
                type=AsyncJob.JobType.TASK,
                action=fqn(import_from_kobo),
                file=None,
                program=program,
                owner=request.user,
                config=config,
            )
            job.queue()
            self.message_user(
                request,
                _("The Kobo data import task has been successfully queued. Job #{0}.").format(job.id),
                level=messages.SUCCESS,
            )
            return None

        return form
