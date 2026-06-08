import io
import tempfile
import zipfile
from pathlib import Path

import pytest
from strategy_field.utils import fqn
from django import forms
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory

from country_workspace.models import AsyncJob
from country_workspace.workspaces.admin.batch import BatchPictureImportForm, BatchReprocessForm
from country_workspace.workspaces.admin.batch.admin import (
    BATCH_PICTURE_IMPORT_SESSION_KEY,
    ProgramBatchFilter,
)
from country_workspace.workspaces.admin.batch.picture_import import BatchPictureImportService
from country_workspace.workspaces.admin.batch.reprocessing import reprocess_batch as reprocess_batch_task
from country_workspace.workspaces.models import CountryBatch
from country_workspace.utils.flex_fields import Base64ImageField


pytestmark = pytest.mark.django_db


def _add_middleware_to_request(request, user) -> None:
    middleware = SessionMiddleware(lambda _: HttpResponse())
    middleware.process_request(request)
    request.session.save()
    request._messages = FallbackStorage(request)  # type: ignore[attr-defined]
    request.user = user


def _make_zip_upload(files: dict[str, bytes]) -> SimpleUploadedFile:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    return SimpleUploadedFile("pictures.zip", payload.getvalue(), content_type="application/zip")


def test_reprocess_form_hides_household_fields_for_people_program(people_program) -> None:
    form = BatchReprocessForm(program=people_program)

    assert "household_mapping" not in form.fields
    assert "household_transformer" not in form.fields
    assert "individual_mapping" in form.fields
    assert "individual_transformer" in form.fields


def test_reprocess_form_hides_missing_checker_mapping_fields(program) -> None:
    program.household_checker = None
    program.individual_checker = None
    program.save(update_fields=["household_checker", "individual_checker"])

    form = BatchReprocessForm(program=program)

    assert "household_mapping" not in form.fields
    assert "individual_mapping" not in form.fields
    assert "household_transformer" in form.fields
    assert "individual_transformer" in form.fields


def test_reprocess_form_filters_mappings_and_transformers_by_program(program) -> None:
    from testutils.factories import MappingImporterFactory, OfficeFactory, TransformerFactory

    other_office = OfficeFactory()
    household_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.household_checker,
        rules="a=b",
    )
    individual_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.individual_checker,
        rules="c=d",
    )
    transformer = TransformerFactory(office=program.country_office)
    other_transformer = TransformerFactory(office=other_office)

    form = BatchReprocessForm(program=program)

    assert form.fields["household_mapping"].queryset.filter(pk=household_mapping.pk).exists()
    assert form.fields["individual_mapping"].queryset.filter(pk=individual_mapping.pk).exists()
    assert form.fields["household_transformer"].queryset.filter(pk=transformer.pk).exists()
    assert not form.fields["household_transformer"].queryset.filter(pk=other_transformer.pk).exists()


def test_reprocess_button_creates_task_job(
    batch_admin,
    batch: CountryBatch,
    user,
    rf: RequestFactory,
    mocker,
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin, "message_user")
    mocker.patch.object(batch_admin, "get_common_context")
    mocker.patch.object(AsyncJob, "queue")
    mocker.patch.object(batch_admin_module, "reverse", return_value="/batches/")

    request = rf.post("/", data={"apply": "1"})
    request.user = user

    response = batch_admin.reprocess_batch.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302

    job = AsyncJob.objects.latest("pk")
    assert job.batch == batch
    assert job.description.startswith("Reprocess batch: ")
    assert job.type == AsyncJob.JobType.TASK
    assert job.owner == user
    assert job.program == batch.program
    assert job.config == {"batch_id": batch.pk}
    assert job.action == fqn(reprocess_batch_task)


def test_reprocess_button_includes_selected_mapping_and_transformer_ids(
    batch_admin,
    batch: CountryBatch,
    user,
    rf: RequestFactory,
    mocker,
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module
    from testutils.factories import MappingImporterFactory, TransformerFactory

    household_mapping = MappingImporterFactory(
        office=batch.country_office,
        data_checker=batch.program.household_checker,
        rules="hh_external=hh_internal",
    )
    individual_mapping = MappingImporterFactory(
        office=batch.country_office,
        data_checker=batch.program.individual_checker,
        rules="ind_external=ind_internal",
    )
    household_transformer = TransformerFactory(office=batch.country_office)
    individual_transformer = TransformerFactory(office=batch.country_office)

    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin, "message_user")
    mocker.patch.object(AsyncJob, "queue")
    mocker.patch.object(batch_admin_module, "reverse", return_value="/batches/")

    request = rf.post(
        "/",
        data={
            "apply": "1",
            "household_mapping": str(household_mapping.pk),
            "individual_mapping": str(individual_mapping.pk),
            "household_transformer": str(household_transformer.pk),
            "individual_transformer": str(individual_transformer.pk),
        },
    )
    request.user = user

    response = batch_admin.reprocess_batch.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302

    job = AsyncJob.objects.latest("pk")
    assert job.config == {
        "batch_id": batch.pk,
        "household_mapping_id": household_mapping.pk,
        "individual_mapping_id": individual_mapping.pk,
        "household_transformer_id": household_transformer.pk,
        "individual_transformer_id": individual_transformer.pk,
    }


def test_reprocess_button_returns_404_for_missing_batch(batch_admin, rf: RequestFactory, user, mocker) -> None:
    mocker.patch.object(batch_admin, "get_object", return_value=None)

    request = rf.get("/")
    request.user = user

    response = batch_admin.reprocess_batch.func(batch_admin, request, "999999")

    assert response.status_code == 404
    assert response.content == b"Batch not found"


def test_reprocess_button_renders_form_on_get(
    batch_admin, batch: CountryBatch, user, rf: RequestFactory, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    get_common_context = mocker.patch.object(
        batch_admin, "get_common_context", return_value={"title": "Reprocess Batch"}
    )
    render_mock = mocker.patch.object(batch_admin_module, "render", return_value=HttpResponse("rendered"))

    request = rf.get("/")
    request.user = user

    response = batch_admin.reprocess_batch.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 200
    get_common_context.assert_called_once()
    render_mock.assert_called_once()


def test_reprocess_button_shows_errors_on_invalid_post(
    batch_admin, batch: CountryBatch, user, rf: RequestFactory, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    message_user = mocker.patch.object(batch_admin, "message_user")
    mocker.patch.object(batch_admin, "get_common_context", return_value={})
    mocker.patch.object(batch_admin_module, "render", return_value=HttpResponse("rendered"))

    request = rf.post("/", data={"apply": "1", "individual_mapping": "999999"})
    request.user = user

    response = batch_admin.reprocess_batch.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 200
    message_user.assert_called()


def test_program_batch_filter_returns_same_queryset_without_lookup(mocker) -> None:
    queryset = mocker.MagicMock(name="queryset")
    filt = ProgramBatchFilter.__new__(ProgramBatchFilter)
    filt.lookup_val = None

    result = ProgramBatchFilter.queryset(filt, mocker.MagicMock(), queryset)

    assert result is queryset


def test_program_batch_filter_filters_by_selected_program(mocker) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    program = mocker.MagicMock(name="program")
    base_queryset = mocker.MagicMock(name="base_queryset")
    filtered = mocker.MagicMock(name="filtered")
    base_queryset.filter.return_value = filtered

    filt = ProgramBatchFilter.__new__(ProgramBatchFilter)
    filt.lookup_val = "11"

    tenant = mocker.MagicMock()
    tenant.programs.get.return_value = program
    mocker.patch.object(batch_admin_module.state, "tenant", tenant)
    mocker.patch(
        "country_workspace.workspaces.admin.batch.admin.CWLinkedAutoCompleteFilter.queryset",
        return_value=base_queryset,
    )

    result = ProgramBatchFilter.queryset(filt, mocker.MagicMock(), mocker.MagicMock())

    assert result is filtered
    tenant.programs.get.assert_called_once_with(pk="11")
    base_queryset.filter.assert_called_once_with(program=program)


def test_batch_picture_import_form_clean_zip_file_rejects_non_zip() -> None:
    upload = SimpleUploadedFile("pictures.txt", b"not-a-zip", content_type="text/plain")
    form = BatchPictureImportForm(
        data={"match_field": "id", "target_field": "photo"},
        files={"zip_file": upload},
        match_field_choices=[("id", "id")],
        target_field_choices=[("photo", "photo")],
    )

    assert not form.is_valid()
    assert "zip_file" in form.errors


def test_batch_picture_import_form_clean_zip_file_accepts_zip_and_rewinds() -> None:
    upload = _make_zip_upload({"A-1.jpg": b"jpg"})
    form = BatchPictureImportForm(
        data={"match_field": "id", "target_field": "photo"},
        files={"zip_file": upload},
        match_field_choices=[("id", "id")],
        target_field_choices=[("photo", "photo")],
    )

    assert form.is_valid()
    assert form.cleaned_data["zip_file"].tell() == 0


def test_batch_admin_get_common_context_sets_admin_metadata(batch_admin, rf: RequestFactory, user, mocker) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    request = rf.get("/")
    request.user = user

    super_context = {"foo": "bar"}
    parent = mocker.patch.object(
        batch_admin_module.WorkspaceModelAdmin,
        "get_common_context",
        return_value=super_context,
    )

    result = batch_admin.get_common_context(request, pk="15", another="value")

    assert result is super_context
    parent.assert_called_once()
    call_kwargs = parent.call_args.kwargs
    assert call_kwargs["modeladmin"] is batch_admin
    assert call_kwargs["modeladmin_name"] == "CountryBatchAdmin"
    assert call_kwargs["another"] == "value"


def test_batch_admin_get_queryset_filters_program_and_office(batch_admin, rf: RequestFactory, user, mocker) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    request = rf.get("/")
    request.user = user

    qs = mocker.MagicMock(name="queryset")
    related_qs = mocker.MagicMock(name="related_queryset")
    filtered_qs = mocker.MagicMock(name="filtered_queryset")
    qs.select_related.return_value = related_qs
    related_qs.filter.return_value = filtered_qs

    tenant = mocker.MagicMock(name="tenant")
    program = mocker.MagicMock(name="program")
    mocker.patch.object(batch_admin_module.state, "tenant", tenant)
    mocker.patch.object(batch_admin_module.state, "program", program)
    mocker.patch.object(batch_admin_module.WorkspaceModelAdmin, "get_queryset", return_value=qs)

    result = batch_admin.get_queryset(request)

    assert result is filtered_qs
    qs.select_related.assert_called_once_with("program", "country_office")
    related_qs.filter.assert_called_once_with(country_office=tenant, program=program)


def test_batch_admin_permissions_are_disabled(batch_admin, rf: RequestFactory, user) -> None:
    request = rf.get("/")
    request.user = user

    assert batch_admin.has_add_permission(request) is False
    assert batch_admin.has_delete_permission(request) is False


def test_batch_admin_picture_payload_helpers(batch_admin, rf: RequestFactory, user) -> None:
    request = rf.get("/")
    _add_middleware_to_request(request, user)

    assert batch_admin._session_payloads(request) == {}

    request.session[BATCH_PICTURE_IMPORT_SESSION_KEY] = "not-a-dict"
    assert batch_admin._session_payloads(request) == {}

    batch_admin._save_picture_import_payload(request, "tok", {"batch_id": 123})
    assert request.session[BATCH_PICTURE_IMPORT_SESSION_KEY]["tok"]["batch_id"] == 123
    assert request.session.modified is True

    assert batch_admin._get_picture_import_payload(request, "missing", 123) is None
    assert batch_admin._get_picture_import_payload(request, "tok", 999) is None
    assert batch_admin._get_picture_import_payload(request, "tok", 123) == {"batch_id": 123}

    batch_admin._clear_picture_import_payload(request, "tok")
    assert request.session[BATCH_PICTURE_IMPORT_SESSION_KEY] == {}
    assert request.session.modified is True


def test_import_pictures_returns_404_for_missing_batch(batch_admin, rf: RequestFactory, user, mocker) -> None:
    mocker.patch.object(batch_admin, "get_object", return_value=None)
    request = rf.get("/")
    request.user = user

    response = batch_admin.import_pictures.func(batch_admin, request, "999999")

    assert response.status_code == 404
    assert response.content == b"Batch not found"


def test_import_pictures_redirects_when_no_match_fields(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = []
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    mocker.patch.object(batch_admin_module, "BatchPictureImportService", return_value=service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin, "message_user")
    mocker.patch.object(batch, "get_change_url", return_value="/workspace/batch/1/change/")

    request = rf.get("/")
    _add_middleware_to_request(request, user)

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302
    assert response.url == "/workspace/batch/1/change/"


def test_import_pictures_redirects_when_no_target_fields(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = []
    mocker.patch.object(batch_admin_module, "BatchPictureImportService", return_value=service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin, "message_user")
    mocker.patch.object(batch, "get_change_url", return_value="/workspace/batch/1/change/")

    request = rf.get("/")
    _add_middleware_to_request(request, user)

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302
    assert response.url == "/workspace/batch/1/change/"


def test_import_pictures_post_preview_saves_payload_and_redirects(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    service.build_preview.return_value = {"assignments": [], "matched_files_count": 0}
    mocker.patch.object(batch_admin_module, "BatchPictureImportService", return_value=service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin_module.uuid, "uuid4", return_value="token-123")

    request = rf.post(
        "/admin/import-pictures/",
        data={
            "preview": "1",
            "match_field": "beneficiary_id",
            "target_field": "photo",
            "zip_file": _make_zip_upload({"A-1.jpg": b"content"}),
        },
    )
    _add_middleware_to_request(request, user)

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302
    assert "step=2&token=token-123" in response.url
    payload = request.session[BATCH_PICTURE_IMPORT_SESSION_KEY]["token-123"]
    assert payload["batch_id"] == batch.pk
    assert payload["match_field"] == "beneficiary_id"
    assert payload["target_field"] == "photo"
    temp_zip_path = Path(payload["zip_temp_path"])
    assert temp_zip_path.exists()
    temp_zip_path.unlink()


def test_import_pictures_post_confirm_without_token_redirects_with_error(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    mocker.patch.object(batch_admin_module, "BatchPictureImportService", return_value=service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin, "message_user")

    request = rf.post("/admin/import-pictures/", data={"confirm": "1"})
    _add_middleware_to_request(request, user)

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302
    assert response.url == "/admin/import-pictures/"


def test_import_pictures_post_confirm_with_expired_token_redirects(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    mocker.patch.object(batch_admin_module, "BatchPictureImportService", return_value=service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin, "message_user")

    request = rf.post("/admin/import-pictures/", data={"confirm": "1", "token": "expired"})
    _add_middleware_to_request(request, user)

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302
    assert response.url == "/admin/import-pictures/"


def test_import_pictures_post_confirm_applies_and_clears_payload(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    service.build_preview.return_value = {
        "assignments": [{"record_id": 1, "data_uri": "data:image/jpeg;base64,Zm9v"}],
        "matched_files_count": 1,
    }
    service.apply_assignments.return_value = 2
    mocker.patch.object(batch_admin_module, "BatchPictureImportService", return_value=service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin, "message_user")
    mocker.patch.object(batch, "get_change_url", return_value="/workspace/batch/1/change/")

    request = rf.post("/admin/import-pictures/", data={"confirm": "1", "token": "tok"})
    _add_middleware_to_request(request, user)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        archive.writestr("A-1.jpg", b"content")
    with tempfile.NamedTemporaryFile(prefix="batch-import-confirm-", suffix=".zip", delete=False) as stream:
        zip_path = stream.name
        stream.write(payload.getvalue())
    request.session[BATCH_PICTURE_IMPORT_SESSION_KEY] = {
        "tok": {
            "batch_id": batch.pk,
            "match_field": "beneficiary_id",
            "target_field": "photo",
            "zip_temp_path": zip_path,
        }
    }

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302
    assert response.url == "/workspace/batch/1/change/"
    assert request.session[BATCH_PICTURE_IMPORT_SESSION_KEY] == {}
    service.build_preview.assert_called_once()
    service.apply_assignments.assert_called_once_with(
        "photo", [{"record_id": 1, "data_uri": "data:image/jpeg;base64,Zm9v"}]
    )


def test_import_pictures_get_step_two_with_expired_token_redirects(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    mocker.patch.object(batch_admin_module, "BatchPictureImportService", return_value=service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin, "message_user")

    request = rf.get("/admin/import-pictures/?step=2&token=missing", data={"step": "2", "token": "missing"})
    _add_middleware_to_request(request, user)

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302
    assert response.url == "/admin/import-pictures/"


def test_import_pictures_get_step_two_renders_preview_report(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    mocker.patch.object(batch_admin_module, "BatchPictureImportService", return_value=service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin_module, "render", return_value=HttpResponse("rendered"))
    get_common_context = mocker.patch.object(batch_admin, "get_common_context", return_value={"step": "2"})

    request = rf.get("/admin/import-pictures/?step=2&token=tok", data={"step": "2", "token": "tok"})
    _add_middleware_to_request(request, user)
    request.session[BATCH_PICTURE_IMPORT_SESSION_KEY] = {
        "tok": {"batch_id": batch.pk, "matched_files_count": 1, "assignments": []}
    }

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 200
    get_common_context.assert_called_once()
    assert get_common_context.call_args.kwargs["step"] == "2"
    assert get_common_context.call_args.kwargs["report"]["matched_files_count"] == 1


def test_import_pictures_get_default_renders_form(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    mocker.patch.object(batch_admin_module, "BatchPictureImportService", return_value=service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin_module, "render", return_value=HttpResponse("rendered"))
    get_common_context = mocker.patch.object(batch_admin, "get_common_context", return_value={"step": "1"})

    request = rf.get("/admin/import-pictures/")
    _add_middleware_to_request(request, user)

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 200
    get_common_context.assert_called_once()
    assert get_common_context.call_args.kwargs["step"] == "1"


def test_extract_zip_images_skips_duplicate_picture_keys() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        archive.writestr("ABC.jpg", b"jpg-data")
        archive.writestr("abc.png", b"png-data")
        archive.writestr("notes.txt", b"ignored")
    upload = SimpleUploadedFile("pictures.zip", payload.getvalue(), content_type="application/zip")

    entries, duplicate_keys = BatchPictureImportService.extract_zip_images(upload)

    assert [item["filename"] for item in entries] == ["ABC.jpg"]
    assert duplicate_keys == {"abc"}


def test_build_picture_import_preview_matches_by_raw_data_field(batch: CountryBatch) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    john = CountryIndividualFactory(batch=batch, household=hh, raw_data={"beneficiary_id": "A-001"})
    CountryIndividualFactory(batch=batch, household=hh, raw_data={"beneficiary_id": "A-002"})

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        archive.writestr("A-001.jpg", b"john-face")
        archive.writestr("MISSING.jpg", b"missing")
    upload = SimpleUploadedFile("pictures.zip", payload.getvalue(), content_type="application/zip")

    report = BatchPictureImportService(batch).build_preview("beneficiary_id", upload)

    assert report["total_picture_files"] == 2
    assert report["total_records"] >= 2
    assert report["matched_records_count"] == 1
    assert report["matched_files_count"] == 1
    assert report["assignments"][0]["record_id"] == john.pk
    assert report["assignments"][0]["filename"] == "A-001.jpg"
    assert report["unmatched_filenames"] == ["MISSING.jpg"]


def test_apply_picture_assignments_updates_selected_field(batch: CountryBatch) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(batch=batch, household=hh, flex_fields={"photo": ""})

    updated = BatchPictureImportService.apply_assignments(
        "photo",
        [{"record_id": individual.pk, "data_uri": "data:image/jpeg;base64,Zm9v"}],
    )

    individual.refresh_from_db()
    assert updated == 1
    assert individual.flex_fields["photo"] == "data:image/jpeg;base64,Zm9v"


def test_picture_import_service_helpers() -> None:
    assert BatchPictureImportService._normalize_match_key(None) == ""
    assert BatchPictureImportService._normalize_match_key("  AbC ") == "abc"
    assert BatchPictureImportService._guess_image_mimetype("unknown.ext") == "application/octet-stream"


def test_extract_zip_images_ignores_non_images_and_blank_keys() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        archive.writestr("images/", b"")
        archive.writestr("notes.txt", b"ignored")
        archive.writestr(" .png", b"blank-stem")
        archive.writestr("valid.jpeg", b"ok")
    upload = SimpleUploadedFile("pictures.zip", payload.getvalue(), content_type="application/zip")

    entries, duplicate_keys = BatchPictureImportService.extract_zip_images(upload)

    assert [item["filename"] for item in entries] == ["valid.jpeg"]
    assert duplicate_keys == set()
    assert upload.tell() == 0


def test_get_match_field_choices_returns_empty_without_records(batch: CountryBatch) -> None:
    assert BatchPictureImportService(batch).get_match_field_choices() == []


def test_get_match_field_choices_returns_sorted_keys(batch: CountryBatch) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    CountryIndividualFactory(batch=batch, household=hh, raw_data={"z_key": "1", "a_key": "2"})

    assert BatchPictureImportService(batch).get_match_field_choices() == [("a_key", "a_key"), ("z_key", "z_key")]


def test_get_match_field_choices_includes_union_of_keys_across_records(batch: CountryBatch) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    CountryIndividualFactory(batch=batch, household=hh, raw_data={"a_key": "1"})
    CountryIndividualFactory(batch=batch, household=hh, raw_data={"b_key": "2"})

    assert BatchPictureImportService(batch).get_match_field_choices() == [("a_key", "a_key"), ("b_key", "b_key")]


def test_get_target_field_choices_without_checker(batch: CountryBatch) -> None:
    batch.program.individual_checker = None
    batch.program.save(update_fields=["individual_checker"])

    assert BatchPictureImportService(batch).get_target_field_choices() == []


def test_get_target_field_choices_returns_only_base64_image_fields(batch: CountryBatch, mocker) -> None:
    class CheckerForm(forms.Form):
        photo = Base64ImageField(required=False, label="Photo")
        notes = forms.CharField(required=False, label="Notes")

    checker = batch.program.individual_checker
    mocker.patch.object(checker, "get_form", return_value=CheckerForm)

    assert BatchPictureImportService(batch).get_target_field_choices() == [("photo", "Photo")]


def test_build_preview_marks_ambiguous_and_duplicate_keys(batch: CountryBatch) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    CountryIndividualFactory(batch=batch, household=hh, raw_data={"beneficiary_id": "DUP"})
    CountryIndividualFactory(batch=batch, household=hh, raw_data={"beneficiary_id": "DUP"})
    CountryIndividualFactory(batch=batch, household=hh, raw_data={"beneficiary_id": "UNIQUE"})

    upload = _make_zip_upload(
        {
            "DUP.jpg": b"ambiguous",
            "UNIQUE.jpg": b"unique",
            "unique.png": b"duplicate-zip-key",
            "MISSING.jpg": b"missing",
        }
    )
    report = BatchPictureImportService(batch).build_preview("beneficiary_id", upload)

    assert report["matched_records_count"] == 0
    assert report["matched_files_count"] == 0
    assert report["duplicate_zip_keys"] == ["unique"]
    assert report["ambiguous_record_keys"] == ["dup"]
    assert report["unmatched_filenames"] == ["MISSING.jpg"]


def test_apply_picture_assignments_returns_zero_without_assignments() -> None:
    assert BatchPictureImportService.apply_assignments("photo", []) == 0


def test_apply_picture_assignments_skips_missing_and_unchanged_records(batch: CountryBatch) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(batch=batch, household=hh, flex_fields={"photo": "same"})

    updated = BatchPictureImportService.apply_assignments(
        "photo",
        [
            {"record_id": individual.pk, "data_uri": "same"},
            {"record_id": 999999999, "data_uri": "new"},
        ],
    )

    assert updated == 0


@pytest.mark.parametrize(
    ("master_detail", "expected_visible"),
    [
        (True, True),
        (False, False),
    ],
)
def test_imported_records_button_visibility(
    batch_admin, batch: CountryBatch, master_detail: bool, expected_visible: bool
) -> None:
    from testutils.factories.program import BeneficiaryGroupFactory

    batch.program.beneficiary_group = BeneficiaryGroupFactory(group_label="Group", master_detail=master_detail)
    batch.program.save(update_fields=["beneficiary_group"])

    button = batch_admin.imported_records.get_button({"original": batch})
    batch_admin.imported_records.func(batch_admin, button)

    assert button.label == "Group"
    assert button.visible is expected_visible
    assert f"batch__exact={batch.pk}" in button.href


def test_imported_individuals_button_uses_member_label(batch_admin, batch: CountryBatch) -> None:
    from testutils.factories.program import BeneficiaryGroupFactory

    batch.program.beneficiary_group = BeneficiaryGroupFactory(member_label="Member")
    batch.program.save(update_fields=["beneficiary_group"])

    button = batch_admin.imported_individuals.get_button({"original": batch})
    batch_admin.imported_individuals.func(batch_admin, button)

    assert button.label == "Member"
    assert button.visible is True
    assert f"batch__exact={batch.pk}" in button.href


def test_imported_buttons_keep_defaults_without_beneficiary_group(batch_admin, batch: CountryBatch) -> None:
    batch.program.beneficiary_group = None
    batch.program.save(update_fields=["beneficiary_group"])

    records_button = batch_admin.imported_records.get_button({"original": batch})
    individuals_button = batch_admin.imported_individuals.get_button({"original": batch})

    batch_admin.imported_records.func(batch_admin, records_button)
    batch_admin.imported_individuals.func(batch_admin, individuals_button)

    assert records_button.visible is True
    assert individuals_button.visible is True
    assert f"batch__exact={batch.pk}" in records_button.href
    assert f"batch__exact={batch.pk}" in individuals_button.href
