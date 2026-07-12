from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.forms import Media
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from strategy_field.utils import fqn

from country_workspace.contrib.aurora.forms import ImportAuroraForm
from country_workspace.contrib.aurora.import_processing import (
    Config as AuroraConfig,
    import_data as import_from_aurora,
)

from country_workspace.contrib.ona.forms import ImportOnaForm
from country_workspace.contrib.ona.import_processing import (
    Config as OnaConfig,
    import_data as import_from_ona,
)
from country_workspace.contrib.kobo.forms import ImportKoboForm
from country_workspace.contrib.kobo.sync import (
    Config as KoboConfig,
    import_data as import_from_kobo,
)
from country_workspace.datasources.rdi import (
    Config as RDIConfig,
    import_from_rdi,
)
from country_workspace.models import AsyncJob
from country_workspace.utils.fields import batch_name_default
from .forms import ImportFileForm

if TYPE_CHECKING:
    from ..models import CountryProgram


KOBO_IMPORT_JOB_DESCRIPTION = "Kobo import: {program_name}"


class ImportDataMixin:
    """Provide the shared *Import Data* view.

    Subclasses inherit ``_render_import_data`` and call it from any
    ``@button`` (change-form or change-list) that has access to the active
    :class:`CountryProgram`. Override ``_get_import_success_url`` to control
    where the user is redirected after a successful import has been queued.
    """

    import_data_template = "workspace/program/import.html"

    def _get_import_success_url(
        self,
        request: HttpRequest,
        program: "CountryProgram",
    ) -> str:
        """Where to send the user after a successful import scheduling.

        Default: the program change page (legacy behaviour).
        """
        return reverse("workspace:workspaces_countryprogram_change", args=[program.pk])

    def _render_import_data(
        self,
        request: HttpRequest,
        program: "CountryProgram",
        pk: str | None = None,
        title: str | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        """Render the Import Data page (RDI/Aurora/Kobo tabs).

        ``pk`` is forwarded to ``get_common_context`` so admins that key
        their context off an object id keep working. ``program`` is the
        :class:`CountryProgram` the import will be queued against.
        """
        context = self.get_common_context(request, pk, title=title or _("Import Data"))
        context["selected_program"] = program
        context["original"] = program
        context["media"] = Media(
            js=["admin/js/vendor/jquery/jquery.js", "workspace/js/import_data.js"],
            css={},
        )

        form_rdi = ImportFileForm(prefix="rdi", beneficiary_group=program.beneficiary_group, program=program)
        form_aurora = ImportAuroraForm(prefix="aurora", program=program)
        form_kobo = ImportKoboForm(
            prefix="kobo",
            kobo_country_code=program.country_office.kobo_country_code,
            program=program,
        )
        form_ona = ImportOnaForm(prefix="ona", program=program)

        if request.method == "POST":
            success_url = self._get_import_success_url(request, program)
            match request.POST.get("_selected_tab"):
                case "rdi":
                    if not (form_rdi := self.import_rdi(request, program)):
                        return HttpResponseRedirect(success_url)
                case "aurora":
                    if not (form_aurora := self.import_aurora(request, program)):
                        return HttpResponseRedirect(success_url)
                case "kobo":
                    if not (form_kobo := self.import_kobo(request, program)):
                        return HttpResponseRedirect(success_url)
                case "ona":
                    if not (form_ona := self.import_ona(request, program)):
                        return HttpResponseRedirect(success_url)

        context["form_rdi"] = form_rdi
        context["form_aurora"] = form_aurora
        context["form_kobo"] = form_kobo
        context["form_ona"] = form_ona
        if extra_context:
            context.update(extra_context)

        return render(request, self.import_data_template, context)

    def import_rdi(self, request: HttpRequest, program: "CountryProgram") -> "ImportFileForm | None":
        form = ImportFileForm(
            request.POST,
            request.FILES,
            prefix="rdi",
            beneficiary_group=program.beneficiary_group,
            program=program,
        )
        if form.is_valid():
            master_detail = program.beneficiary_group.master_detail if program.beneficiary_group else False
            config: RDIConfig = {
                "master_detail": master_detail,
                "batch_name": form.cleaned_data["batch_name"] or batch_name_default(),
                "validate_after_import": bool(form.cleaned_data.get("validate_after_import")),
                "fail_if_alien": bool(form.cleaned_data.get("fail_if_alien")),
                "beneficiary_id_column": form.cleaned_data.get("beneficiary_id_column"),
                **(
                    {
                        "household_id_column": form.cleaned_data.get("household_id_column"),
                        "household_label": form.cleaned_data.get("household_label"),
                    }
                    if master_detail
                    else {
                        "people_prefix": form.cleaned_data.get("people_prefix"),
                    }
                ),
                "first_line": form.cleaned_data["first_line"],
                "send_to": request.user.email,
                "household_mapping_id": household_mapping.id
                if (household_mapping := form.cleaned_data.get("household_mapping"))
                else None,
                "individual_mapping_id": individual_mapping.id
                if (individual_mapping := form.cleaned_data.get("individual_mapping"))
                else None,
                "household_transformer_id": (
                    form.cleaned_data.get("household_transformer").id
                    if form.cleaned_data.get("household_transformer")
                    else None
                ),
                "individual_transformer_id": (
                    form.cleaned_data.get("individual_transformer").id
                    if form.cleaned_data.get("individual_transformer")
                    else None
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

    def import_aurora(self, request: HttpRequest, program: "CountryProgram") -> "ImportAuroraForm | None":
        form = ImportAuroraForm(request.POST, prefix="aurora", program=program)
        if form.is_valid():
            config: AuroraConfig = {
                "batch_name": form.cleaned_data["batch_name"] or batch_name_default(),
                "validate_after_import": form.cleaned_data.get("validate_after_import"),
                "fail_if_alien": form.cleaned_data.get("fail_if_alien"),
                "registration_reference_pk": getattr(form.cleaned_data.get("registration"), "reference_pk", None),
                "master_detail": program.beneficiary_group.master_detail if program.beneficiary_group else False,
                "household_mapping_id": form.cleaned_data.get("household_mapping").id
                if form.cleaned_data.get("household_mapping")
                else None,
                "individual_mapping_id": form.cleaned_data.get("individual_mapping").id
                if form.cleaned_data.get("individual_mapping")
                else None,
                "household_transformer_id": (
                    form.cleaned_data.get("household_transformer").id
                    if form.cleaned_data.get("household_transformer")
                    else None
                ),
                "individual_transformer_id": (
                    form.cleaned_data.get("individual_transformer").id
                    if form.cleaned_data.get("individual_transformer")
                    else None
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

    def import_kobo(self, request: HttpRequest, program: "CountryProgram") -> "ImportKoboForm | None":
        form = ImportKoboForm(
            request.POST,
            prefix="kobo",
            kobo_country_code=program.country_office.kobo_country_code,
            program=program,
        )
        if form.is_valid():
            config: KoboConfig = {
                "batch_name": form.cleaned_data["batch_name"] or batch_name_default(),
                "validate_after_import": bool(form.cleaned_data.get("validate_after_import")),
                "fail_if_alien": bool(form.cleaned_data.get("fail_if_alien")),
                "project_id": form.cleaned_data["project_id"],
                "individual_records_field": form.cleaned_data["individual_records_field"],
                "household_mapping_id": (
                    household_mapping.id if (household_mapping := form.cleaned_data.get("household_mapping")) else None
                ),
                "individual_mapping_id": (
                    individual_mapping.id
                    if (individual_mapping := form.cleaned_data.get("individual_mapping"))
                    else None
                ),
                "household_transformer_id": (
                    form.cleaned_data.get("household_transformer").id
                    if form.cleaned_data.get("household_transformer")
                    else None
                ),
                "individual_transformer_id": (
                    form.cleaned_data.get("individual_transformer").id
                    if form.cleaned_data.get("individual_transformer")
                    else None
                ),
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

    def import_ona(self, request: HttpRequest, program: "CountryProgram") -> "ImportOnaForm | None":
        form = ImportOnaForm(request.POST, prefix="ona", program=program)
        if form.is_valid():
            config: OnaConfig = {
                "batch_name": form.cleaned_data["batch_name"] or batch_name_default(),
                "validate_after_import": bool(form.cleaned_data.get("validate_after_import")),
                "form_id": form.cleaned_data["form_id"],
                "master_detail": program.beneficiary_group.master_detail if program.beneficiary_group else False,
                "individuals_key": form.cleaned_data.get("individuals_key") or "individuals",
                "household_field_mapping": form.cleaned_data.get("household_field_mapping") or {},
                "individual_field_mapping": form.cleaned_data.get("individual_field_mapping") or {},
                "household_mapping_id": (
                    household_mapping.id if (household_mapping := form.cleaned_data.get("household_mapping")) else None
                ),
                "individual_mapping_id": (
                    individual_mapping.id
                    if (individual_mapping := form.cleaned_data.get("individual_mapping"))
                    else None
                ),
                "household_transformer_id": (
                    form.cleaned_data.get("household_transformer").id
                    if form.cleaned_data.get("household_transformer")
                    else None
                ),
                "individual_transformer_id": (
                    form.cleaned_data.get("individual_transformer").id
                    if form.cleaned_data.get("individual_transformer")
                    else None
                ),
            }

            job: AsyncJob = AsyncJob.objects.create(
                description=f"ONA / INFORM import: {program.name}",
                type=AsyncJob.JobType.TASK,
                action=fqn(import_from_ona),
                file=None,
                program=program,
                owner=request.user,
                config=config,
            )
            job.queue()
            self.message_user(
                request,
                _("The ONA / INFORM data import task has been successfully queued. Job #{0}.").format(job.id),
                level=messages.SUCCESS,
            )
            return None

        return form
