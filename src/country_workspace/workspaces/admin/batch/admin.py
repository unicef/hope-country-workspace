import logging
import uuid
import zipfile
from time import time
from datetime import UTC
from typing import Any

from admin_extra_buttons.buttons import ChoiceButton, LinkButton
from admin_extra_buttons.decorators import button, choice, link
from constance import config as constance_config
from django import forms
from django.contrib import messages
from django.contrib.admin import register
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
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
from ...permissions import can_import_program_data, can_reprocess_batch
from ...sites import workspace
from ..filters import CWLinkedAutoCompleteFilter, ChoiceFilter, UserAutoCompleteFilter
from ..hh_ind import SelectedProgramMixin
from .picture_import import BatchPictureImportService, PictureImportLimitError
from .reprocessing import reprocess_batch as reprocess_batch_task

logger = logging.getLogger(__name__)


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


PICTURE_IMPORT_SESSION_TTL_SECONDS = 3600


class BatchPictureImportForm(forms.Form):
    zip_file = forms.FileField(
        label=_("Pictures ZIP file"),
        help_text=_(
            "Upload a .zip archive containing picture files. The filename (without extension) is used for matching."
        ),
    )
    match_field = forms.ChoiceField(
        label=_("Record key field (from raw data)"),
        choices=(),
        help_text=_("Field used to match each picture filename to individuals in this batch."),
    )
    target_field = forms.ChoiceField(
        label=_("Target image field"),
        choices=(),
        help_text=_("Image field to update on matched individuals (photo/document image field)."),
    )

    def __init__(
        self,
        *args: Any,
        match_field_choices: list[tuple[str, str]] | None = None,
        target_field_choices: list[tuple[str, str]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["match_field"].choices = match_field_choices or []
        self.fields["target_field"].choices = target_field_choices or []

    def clean_zip_file(self) -> UploadedFile:
        zip_file: UploadedFile = self.cleaned_data["zip_file"]
        if not zipfile.is_zipfile(zip_file):
            raise forms.ValidationError(_("Please upload a valid zip archive."))
        max_zip_upload_mb = int(constance_config.PICTURE_IMPORT_MAX_ZIP_UPLOAD_MB)
        max_zip_upload_bytes = max_zip_upload_mb * 1024 * 1024
        if zip_file.size and zip_file.size > max_zip_upload_bytes:
            raise forms.ValidationError(
                _("ZIP archive is too large (max %(max_mb)d MB).") % {"max_mb": max_zip_upload_mb}
            )
        zip_file.seek(0)
        return zip_file


@register(CountryBatch, site=workspace)
class CountryBatchAdmin(SelectedProgramMixin, WorkspaceModelAdmin):
    list_display = ["name", "import_date", "imported_by", "source", "status"]
    search_fields = ("name",)
    change_list_template = ["workspace/change_list.html"]
    change_form_template = ["workspace/batch/change_form.html", "workspace/change_form.html"]
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

    @staticmethod
    def _picture_import_payloads(batch: CountryBatch) -> dict[str, dict[str, Any]]:
        payloads = batch.get_picture_import_state()
        now = int(time())
        cleaned_payloads: dict[str, dict[str, Any]] = {}
        changed = False
        for token, payload in payloads.items():
            if not isinstance(payload, dict):
                changed = True
                continue
            created_at = payload.get("created_at")
            if isinstance(created_at, int) and now - created_at > PICTURE_IMPORT_SESSION_TTL_SECONDS:
                CountryBatchAdmin._delete_uploaded_zip(payload.get("zip_file_name"))
                changed = True
                continue
            cleaned_payloads[token] = payload
        if changed:
            batch.picture_import_state = cleaned_payloads
            batch.save(update_fields=["picture_import_state"])
        return cleaned_payloads

    @staticmethod
    def _delete_uploaded_zip(file_name: str | None) -> None:
        if file_name:
            default_storage.delete(file_name)

    @staticmethod
    def _cleanup_stale_stored_zips() -> None:
        now = int(time())
        try:
            _, files = default_storage.listdir("batch-picture-import")
        except (OSError, NotImplementedError):
            logger.exception("Could not list picture import storage directory")
            return
        for filename in files:
            file_name = f"batch-picture-import/{filename}"
            try:
                modified_at = int(default_storage.get_modified_time(file_name).astimezone(UTC).timestamp())
            except (OSError, NotImplementedError):
                logger.exception("Could not get modified time for %s", file_name)
                continue
            if now - modified_at > PICTURE_IMPORT_SESSION_TTL_SECONDS:
                default_storage.delete(file_name)

    @staticmethod
    def _store_uploaded_zip(uploaded: UploadedFile) -> str:
        CountryBatchAdmin._cleanup_stale_stored_zips()
        file_name = f"batch-picture-import/{uuid.uuid4()}.zip"
        stored_name = default_storage.save(file_name, uploaded)
        uploaded.seek(0)
        return stored_name

    @staticmethod
    def _acquire_batch_action_lock(batch_id: int) -> Any | None:
        lock = cache.lock(f"lock:batch:{batch_id}", 60, auto_renewal=True)
        if lock.acquire(blocking=False):
            return lock
        return None

    def _get_picture_import_payload(self, request: HttpRequest, batch: CountryBatch, token: str) -> dict[str, Any] | None:
        payloads = self._picture_import_payloads(batch)
        payload = payloads.get(token)
        if not payload:
            return None
        if payload.get("batch_id") != batch.pk:
            return None
        if payload.get("created_by_id") != request.user.pk:
            return None
        return payload

    def _save_picture_import_payload(
        self, request: HttpRequest, batch: CountryBatch, token: str, payload: dict[str, Any]
    ) -> None:
        payload_to_store = {
            **payload,
            "created_at": int(time()),
            "created_by_id": request.user.pk,
        }
        old_payload = batch.start_picture_import(token=token, payload=payload_to_store, user=request.user)
        if old_payload:
            self._delete_uploaded_zip(old_payload.get("zip_file_name"))

    def _clear_picture_import_payload(self, request: HttpRequest, batch: CountryBatch, token: str) -> None:
        payload = batch.finish_picture_import(token=token, user=request.user)
        if payload:
            self._delete_uploaded_zip(payload.get("zip_file_name"))

    @button(
        visible=False,
        change_list=False,
        permission=can_import_program_data,
        html_attrs={"title": "Import pictures from zip and assign by matching key."},
    )
    def import_pictures(self, request: HttpRequest, pk: str) -> HttpResponse:  # noqa: C901, PLR0912, PLR0915
        obj: CountryBatch | None = self.get_object(request, pk)
        if not obj:
            return HttpResponse("Batch not found", status=404)

        def redirect_to_change() -> HttpResponseRedirect:
            return HttpResponseRedirect(obj.get_change_url(namespace=self.admin_site.name))

        service = BatchPictureImportService(obj)
        match_field_choices = service.get_match_field_choices()
        target_field_choices = service.get_target_field_choices()
        response: HttpResponse | None = None
        report: dict[str, Any] | None = None
        step = "1"
        token = request.POST.get("token") or request.GET.get("token")
        form = BatchPictureImportForm(
            match_field_choices=match_field_choices,
            target_field_choices=target_field_choices,
        )

        if not match_field_choices:
            self.message_user(
                request,
                _("Cannot import pictures: no raw data keys were found in this batch."),
                messages.ERROR,
            )
            response = redirect_to_change()
        elif not target_field_choices:
            self.message_user(
                request,
                _("Cannot import pictures: no image/document fields are available in the individual checker."),
                messages.ERROR,
            )
            response = redirect_to_change()
        elif request.method == "POST" and "preview" in request.POST:
            form = BatchPictureImportForm(
                request.POST,
                request.FILES,
                match_field_choices=match_field_choices,
                target_field_choices=target_field_choices,
            )
            if form.is_valid():
                zip_file_name = self._store_uploaded_zip(form.cleaned_data["zip_file"])
                try:
                    with default_storage.open(zip_file_name, "rb") as zip_stream:
                        preview = service.build_preview(form.cleaned_data["match_field"], zip_stream)
                except PictureImportLimitError as exc:
                    self._delete_uploaded_zip(zip_file_name)
                    form.add_error("zip_file", str(exc))
                else:
                    token = str(uuid.uuid4())
                    self._save_picture_import_payload(
                        request,
                        obj,
                        token,
                        {
                            "batch_id": obj.pk,
                            "match_field": form.cleaned_data["match_field"],
                            "target_field": form.cleaned_data["target_field"],
                            "zip_file_name": zip_file_name,
                            **preview,
                        },
                    )
                    response = HttpResponseRedirect(f"{request.path}?step=2&token={token}")
        elif request.method == "POST" and "confirm" in request.POST:
            step = "3"
            if not token:
                self.message_user(request, _("Picture import confirmation is missing."), messages.ERROR)
                response = HttpResponseRedirect(request.path)
            else:
                payload = self._get_picture_import_payload(request, obj, token)
                if not payload:
                    self.message_user(
                        request,
                        _("Picture import session has expired. Please run the matching step again."),
                        messages.ERROR,
                    )
                    response = HttpResponseRedirect(request.path)
                else:
                    zip_file_name = payload.get("zip_file_name")
                    if not zip_file_name or not default_storage.exists(zip_file_name):
                        self._clear_picture_import_payload(request, obj, token)
                        self.message_user(
                            request,
                            _("Picture import session has expired. Please run the matching step again."),
                            messages.ERROR,
                        )
                        response = HttpResponseRedirect(request.path)
                    else:
                        batch_lock = self._acquire_batch_action_lock(obj.pk)
                        if not batch_lock:
                            self.message_user(
                                request,
                                _("Another action is currently running for this batch. Please try again later."),
                                messages.ERROR,
                            )
                            response = HttpResponseRedirect(request.path)
                        else:
                            try:
                                with default_storage.open(zip_file_name, "rb") as zip_stream:
                                    assignments = service.enrich_assignments_with_zip_data(
                                        payload.get("assignments", []),
                                        zip_stream,
                                    )
                            except PictureImportLimitError as exc:
                                self._clear_picture_import_payload(request, obj, token)
                                self.message_user(request, str(exc), messages.ERROR)
                                response = HttpResponseRedirect(request.path)
                            else:
                                updated = service.apply_assignments(payload["target_field"], assignments)
                                self._clear_picture_import_payload(request, obj, token)
                                self.message_user(
                                    request,
                                    _("Picture import completed: %(updated)d records updated.") % {"updated": updated},
                                    messages.SUCCESS,
                                )
                                response = redirect_to_change()
                            finally:
                                batch_lock.release()
        elif request.method == "GET" and request.GET.get("step") == "2" and token:
            payload = self._get_picture_import_payload(request, obj, token)
            if not payload:
                self.message_user(
                    request,
                    _("Picture import session has expired. Please upload the zip again."),
                    messages.ERROR,
                )
                response = HttpResponseRedirect(request.path)
            else:
                report = payload
                step = "2"

        if not response:
            context = self.get_common_context(
                request,
                pk=pk,
                title="Import Pictures",
                form=form,
                batch=obj,
                step=step,
                report=report,
                token=token,
            )
            response = render(request, "workspace/admin_extra_buttons/import_pictures_form.html", context)
        return response

    @choice(
        label=_("Batch actions"),
        change_form=True,
        change_list=False,
        visible=lambda btn: bool(
            btn.request.user.has_perm("country_workspace.import_program_data", btn.original)
            or btn.request.user.has_perm("country_workspace.reprocess_batch", btn.original)
        ),
    )
    def batch_actions(self, button: ChoiceButton) -> None:
        model_admin = self or button.handler.model_admin
        if not model_admin:
            button.choices = []
            return
        button.choices = [model_admin.import_pictures, model_admin.reprocess_batch]

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
        visible=False,
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
