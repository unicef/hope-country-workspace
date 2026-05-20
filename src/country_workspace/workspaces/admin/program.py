from typing import TYPE_CHECKING, Any

from admin_extra_buttons.api import button, choice, view
from admin_extra_buttons.buttons import ChoiceButton
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.admin import display, register
from django.db.models import Field, QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.html import format_html_join
from strategy_field.utils import fqn

from country_workspace.contrib.dedup_engine import make_dedup_client
from country_workspace.contrib.hope.push import get_program_dedup_settings_policy
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Household, Individual
from country_workspace.models.base import Validable
from country_workspace.state import state
from ._import_data import ImportDataMixin
from .cleaners.bulk_update import import_household_updates, import_individual_updates
from .forms import BulkUpdateImportForm, MassDefaultsForm, DedupSettingsForm
from ..permissions import can_change_country_program, can_import_program_data
from ..models import CountryProgram
from ..options import WorkspaceModelAdmin
from ..sites import workspace
from ...models import AsyncJob


if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker


class SelectColumnsForm(forms.Form):
    columns = forms.MultipleChoiceField(choices=(), widget=forms.CheckboxSelectMultiple)
    model_core_fields = [("name", "name"), ("id", "id")]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        columns: list[tuple[str, str]] = []
        checker_form_class = self.checker.get_form_class()
        for name, field in checker_form_class.base_fields.items():
            label = getattr(field, "label", "") or name
            columns.append((f"flex_fields__{name}", f"{label} ({name})"))
        self.fields["columns"].choices = self.model_core_fields + columns


class AlienColumnsForm(forms.Form):
    new_columns = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(),
    )

    def __init__(self, data: list[str] | None = None, existing_columns: list | None = None, **kwargs: Any) -> None:
        super().__init__(data=data, **kwargs)

        if data and "new_columns" in data:
            choices = [(v, v) for v in data.get("new_columns")]
            self.fields["new_columns"].choices = choices
        elif existing_columns:
            choices = [(v, v) for v in existing_columns]
            self.fields["new_columns"].choices = choices
            self.initial["new_columns"] = existing_columns


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
            "alien_validation_enabled",
            "household_checker",
            "individual_checker",
            "household_search",
            "individual_search",
            "household_columns",
            "individual_columns",
            "extra_fields",
            "serializer",
        )


@register(CountryProgram, site=workspace)
class CountryProgramAdmin(ImportDataMixin, WorkspaceModelAdmin):
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
        "hh_alien_columns_to_ignore",
        "ind_alien_columns_to_ignore",
        "code",
        "status",
        "sector",
        "name",
        "dedup_settings",
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

    def get_queryset(self, request: HttpRequest) -> QuerySet[CountryProgram]:
        return CountryProgram.objects.filter(country_office=state.tenant, enabled=True)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: CountryProgram | None = None) -> bool:
        return False

    def get_fieldsets(
        self, request: HttpRequest, obj: CountryProgram | None = None
    ) -> list[tuple[str | None, dict[str, Any]]]:
        fieldsets = [
            (
                None,
                {
                    "fields": (
                        ("name", "code"),
                        ("status", "sector"),
                    ),
                },
            ),
            (
                _("Validators"),
                {
                    "fields": (
                        "beneficiary_validator",
                        "alien_validation_enabled",
                        ("household_checker", "individual_checker"),
                    )
                },
            ),
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
                _("Alien Columns to Ignore"),
                {
                    "fields": (
                        "hh_alien_columns_to_ignore",
                        "ind_alien_columns_to_ignore",
                    ),
                },
            ),
            (
                _("Serializer"),
                {
                    "fields": ("serializer",),
                },
            ),
        ]
        if obj and obj.biometric_deduplication_enabled:
            fieldsets.append(
                (
                    _("Deduplication Configuration"),
                    {"fields": ("dedup_settings",)},
                )
            )
        if obj and obj.beneficiary_group and not obj.beneficiary_group.master_detail:
            fieldsets[1][1]["fields"] = ("beneficiary_validator", "alien_validation_enabled", "individual_checker")
            fieldsets[2][1]["fields"] = ("individual_columns",)

        return fieldsets

    def _get_dedup_settings(self, program: CountryProgram) -> dict[str, Any]:
        with make_dedup_client(program_id=program.unicef_id) as client:
            return client.get_deduplication_set_group_config()

    @display(description=_("Settings"))
    def dedup_settings(self, obj: CountryProgram) -> str:
        if not obj.biometric_deduplication_enabled:
            return "-"

        try:
            settings = self._get_dedup_settings(obj)
        except (RemoteError, RemoteUnavailableError):
            return "N/A"

        if not settings:
            return "-"

        return format_html_join(
            "\n",
            "<div style='display:grid; grid-template-columns:max-content 1fr; column-gap:10px'>"
            "<span style='white-space:nowrap'>{}:</span>"
            "<span>{}</span>"
            "</div>",
            ((key, value) for key, value in settings.items()),
        )

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

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
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
                "individual_columns": f"{member_label}",
            }
            if obj.beneficiary_group.master_detail:
                dynamic_labels["household_columns"] = f"{group_label}"
            extra_context = {
                **extra_context,
                "dynamic_field_labels": dynamic_labels,
                "btnlabels": {
                    "individual_columns": f"{member_label}",
                    "household_columns": f"{group_label}",
                },
            }
        return super().changeform_view(request, object_id, form_url, extra_context=extra_context)

    @staticmethod
    def _can_configure(
        button: ChoiceButton,
        model: type[Validable],
        require_master_detail: bool = False,
    ) -> bool:
        if not (program := button.context.get("original")):
            return False
        bg = getattr(program, "beneficiary_group", None)
        if not bg or (require_master_detail and not bg.master_detail):
            return False
        return program.get_checker_for(model) is not None

    def _configure_columns(
        self,
        request: HttpRequest,
        form_class: type[SelectColumnsForm] | type[SelectIndividualColumnsForm],
        context: dict[str, Any],
    ) -> "HttpResponse":
        program: "CountryProgram" = context["original"]
        checker: DataChecker = context["checker"]
        storage_field: str = context["storage_field"]

        initials = getattr(program, storage_field).split("\n")

        if request.method == "POST":
            form = form_class(
                request.POST,
                checker=checker,
            )
            if form.is_valid():
                columns = form.cleaned_data["columns"]
                setattr(program, storage_field, "\n".join(columns))
                program.save(update_fields=[storage_field])
                return HttpResponseRedirect(reverse("workspace:workspaces_countryprogram_change", args=[program.pk]))
        else:
            form = form_class(checker=checker, initial={"columns": initials})
        context["form"] = form

        return render(request, "workspace/program/configure_columns.html", context)

    def _configure_alien_fields(
        self,
        request: HttpRequest,
        form_class: type[AlienColumnsForm],
        context: dict[str, Any],
    ) -> "HttpResponse":
        program: "CountryProgram" = context["original"]
        storage_field: str = context["storage_field"]

        if request.method == "POST":
            existing = []
            if getattr(program, storage_field):
                existing = [c.strip() for c in getattr(program, storage_field).split("\n") if c.strip()]

            remove_columns = request.POST.getlist("remove_columns")
            new_columns = [c.strip() for c in request.POST.getlist("new_columns") if c.strip()]
            existing = [c for c in existing if c not in remove_columns]

            for col in new_columns:
                if col not in existing:
                    existing.append(col)

            setattr(program, storage_field, "\n".join(existing) if existing else None)
            program.save(update_fields=[storage_field])

            return HttpResponseRedirect(reverse("workspace:workspaces_countryprogram_change", args=[program.pk]))

        existing_columns = []
        if getattr(program, storage_field):
            existing_columns = [c.strip() for c in getattr(program, storage_field).split("\n") if c.strip()]

        form = form_class(existing_columns=existing_columns)
        context["form"] = form

        return render(request, "workspace/program/alien_fields.html", context)

    def _set_defaults(
        self,
        request: HttpRequest,
        form_class: type[MassDefaultsForm],
        context: dict[str, Any],
    ) -> HttpResponse:
        program: CountryProgram = context["original"]
        checker: "DataChecker" = context["checker"]
        model_cls = context["defaults_scope_model"]
        initial_defaults: dict[str, Any] = program.get_default_fields_for(model_cls)

        if request.method == "POST":
            selected_fields = request.POST.getlist("fields")
            form = form_class(request.POST, checker=checker)

            if form.is_valid():
                new_defaults = {name: form.cleaned_data[name] for name in selected_fields if name in form.cleaned_data}

                program.save_default_fields_for(model_cls, new_defaults)

                self.message_user(
                    request,
                    _("Default values have been updated."),
                    level=messages.SUCCESS,
                )
                return HttpResponseRedirect(reverse("workspace:workspaces_countryprogram_change", args=[program.pk]))
        else:
            selected_fields = list(initial_defaults.keys())
            form = form_class(checker=checker, initial=initial_defaults)

        context["form"] = form
        context["selected_fields"] = selected_fields
        return render(request, "workspace/program/set_defaults.html", context)

    @view(
        label=_("Configure Columns"),
        permission=can_change_country_program,
        visible=lambda btn: CountryProgramAdmin._can_configure(btn, Household, require_master_detail=True),
    )
    def household_columns(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Workspace wrapper: configure highlighted/group columns via choice."""
        context = self.get_common_context(
            request,
            pk,
            title=_("Configure default Household columns"),
        )
        program: CountryProgram = context["original"]
        context["checker"] = program.household_checker
        context["storage_field"] = "household_columns"
        return self._configure_columns(request, SelectColumnsForm, context)

    @view(
        label=_("Configure Alien Fields to Ignore"),
        permission=can_change_country_program,
        visible=lambda btn: CountryProgramAdmin._can_configure(btn, Household, require_master_detail=True),
    )
    def household_alien_fields_to_ignore(self, request: HttpRequest, pk: str) -> HttpResponse:
        context = self.get_common_context(
            request,
            pk,
            title=_("Configure Alien Fields to Ignore"),
        )
        program: CountryProgram = context["original"]
        context["checker"] = program.household_checker
        context["storage_field"] = "hh_alien_columns_to_ignore"
        return self._configure_alien_fields(request, AlienColumnsForm, context)

    @view(
        label=_("Configure Alien Fields to Ignore"),
        permission=can_change_country_program,
        visible=lambda btn: CountryProgramAdmin._can_configure(btn, Individual, require_master_detail=True),
    )
    def individual_alien_fields_to_ignore(self, request: HttpRequest, pk: str) -> HttpResponse:
        context = self.get_common_context(
            request,
            pk,
            title=_("Configure Alien Fields to Ignore"),
        )
        program: CountryProgram = context["original"]
        context["checker"] = program.individual_checker
        context["storage_field"] = "ind_alien_columns_to_ignore"
        return self._configure_alien_fields(request, AlienColumnsForm, context)

    @view(
        label=_("Set Defaults"),
        permission=can_change_country_program,
        visible=lambda btn: CountryProgramAdmin._can_configure(btn, Household, require_master_detail=True),
    )
    def household_defaults(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Workspace wrapper: configure default values for group records via choice."""
        context = self.get_common_context(request, pk)
        program: CountryProgram = context["original"]
        context["checker"] = program.household_checker
        context["defaults_scope_model"] = Household
        return self._set_defaults(request, MassDefaultsForm, context)

    @choice(
        label=_("Household Columns"),
        change_form=True,
        change_list=False,
        visible=lambda btn: CountryProgramAdmin._can_configure(btn, Household, require_master_detail=True),
    )
    def household_group(self, button: ChoiceButton) -> None:
        """Group-level choice for group_label: Columns + Defaults."""
        button.choices = [
            self.household_columns,
            self.household_defaults,
            self.household_alien_fields_to_ignore,
        ]

    @view(
        label=_("Configure Columns"),
        permission=can_change_country_program,
        visible=lambda btn: CountryProgramAdmin._can_configure(btn, Individual),
    )
    def individual_columns(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Workspace wrapper: configure highlighted/member columns via choice."""
        context = self.get_common_context(
            request,
            pk,
            title=_("Configure default Individual columns"),
        )
        program: CountryProgram = context["original"]
        context["checker"] = program.individual_checker
        context["storage_field"] = "individual_columns"
        return self._configure_columns(request, SelectIndividualColumnsForm, context)

    @view(
        label=_("Set Defaults"),
        permission=can_change_country_program,
        visible=lambda btn: CountryProgramAdmin._can_configure(btn, Individual),
    )
    def individual_defaults(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Workspace wrapper: configure default values for member records via choice."""
        context = self.get_common_context(request, pk)
        program: CountryProgram = context["original"]
        context["checker"] = program.individual_checker
        context["defaults_scope_model"] = Individual
        return self._set_defaults(request, MassDefaultsForm, context)

    @choice(
        label=_("Individual Columns"),
        change_form=True,
        change_list=False,
        visible=lambda btn: CountryProgramAdmin._can_configure(btn, Individual),
    )
    def individual_group(self, button: ChoiceButton) -> None:
        """Group-level choice for member_label: Columns + Defaults."""
        button.choices = [
            self.individual_columns,
            self.individual_defaults,
            self.individual_alien_fields_to_ignore,
        ]

    @button(
        label=_("Update Records"),
        permission=can_import_program_data,
        html_attrs={"title": "Allow to updated records previously exported."},
    )
    def import_file_updates(self, request: HttpRequest, pk: str) -> "HttpResponse":
        context = self.get_common_context(request, pk, title="Bulk update records via .xlsx import")
        program: "CountryProgram" = context["original"]
        context["selected_program"] = context["original"]
        function_map = {"hh": fqn(import_household_updates), "ind": fqn(import_individual_updates)}
        if request.method == "POST":
            form = BulkUpdateImportForm(request.POST, request.FILES, beneficiary_group=program.beneficiary_group)
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
            form = BulkUpdateImportForm(beneficiary_group=program.beneficiary_group)
        context["form"] = form
        return render(request, "workspace/actions/bulk_update_import.html", context)

    @button(
        label=_("Update Dedup Settings"),
        permission=can_change_country_program,
        visible=lambda btn: bool(
            (program := btn.context.get("original"))
            and get_program_dedup_settings_policy(program).is_update_dedup_settings_visible()
        ),
        enabled=lambda btn: bool(
            (program := btn.context.get("original"))
            and get_program_dedup_settings_policy(program).update_dedup_settings_check().allowed
        ),
        html_attrs={"title": "Update Deduplication settings on DedupEngine."},
    )
    def update_dedup_settings(self, request: HttpRequest, pk: str) -> HttpResponse:
        context = self.get_common_context(request, pk, title=_("Update Deduplication Settings"))
        program: CountryProgram = context["original"]
        change_url = reverse("workspace:workspaces_countryprogram_change", args=[program.pk])

        def deny_if_not_allowed() -> HttpResponseRedirect | None:
            check = get_program_dedup_settings_policy(program).update_dedup_settings_check()
            if check.allowed:
                return None
            self.message_user(request, check.reason or _("Action is not allowed."), messages.ERROR)
            return HttpResponseRedirect(change_url)

        if response := deny_if_not_allowed():
            return response

        try:
            settings = self._get_dedup_settings(program)
        except (RemoteError, RemoteUnavailableError) as exc:
            self.message_user(
                request,
                _("Failed to fetch Deduplication settings from DedupEngine. %(error)s") % {"error": str(exc)},
                messages.ERROR,
            )
            return HttpResponseRedirect(change_url)

        form = DedupSettingsForm(request.POST or None, settings=settings)
        if request.method == "POST" and form.is_valid():
            if response := deny_if_not_allowed():
                return response

            try:
                with make_dedup_client(program_id=program.unicef_id) as client:
                    client.post_deduplication_set_group_config(payload=form.get_payload())
            except (RemoteError, RemoteUnavailableError) as exc:
                self.message_user(
                    request,
                    _("Failed to update Deduplication settings on DedupEngine. %(error)s") % {"error": str(exc)},
                    messages.ERROR,
                )
            else:
                self.message_user(request, _("Deduplication settings have been updated."), messages.SUCCESS)
                return HttpResponseRedirect(change_url)

        context["form"] = form
        return render(request, "workspace/program/dedup_settings.html", context)

    @button(
        label=_("Import Data"),
        permission=can_import_program_data,
        html_attrs={"title": "Import Data using XLS/RDI, Kobo or Aurora."},
    )
    def import_data(self, request: HttpRequest, pk: str) -> "HttpResponse":
        program: "CountryProgram" = self.get_object(request, pk)
        return self._render_import_data(request, program=program, pk=pk)
