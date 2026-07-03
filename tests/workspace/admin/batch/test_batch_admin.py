import io
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from strategy_field.utils import fqn
from django import forms
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory
from PIL import Image

from country_workspace.models import AsyncJob
from country_workspace.workspaces.admin.batch import BatchPictureImportForm, BatchReprocessForm
from country_workspace.workspaces.admin.batch.admin import (
    ProgramBatchFilter,
)
from country_workspace.workspaces.admin.batch.picture_import import BatchPictureImportService, PictureImportLimitError
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
            suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if suffix in {"jpg", "jpeg", "png"}:
                content = _make_image_bytes("PNG" if suffix == "png" else "JPEG")  # noqa: PLW2901
            archive.writestr(filename, content)
    return SimpleUploadedFile("pictures.zip", payload.getvalue(), content_type="application/zip")


def _make_image_bytes(image_format: str = "JPEG") -> bytes:
    image = Image.new("RGB", (2, 2), color=(255, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def _mock_picture_import_service(mocker, batch_admin_module, service) -> None:
    mocker.patch.object(batch_admin_module, "BatchPictureImportService", return_value=service)


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


def test_batch_picture_import_form_clean_zip_file_rejects_oversized_archive(mocker) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    upload = _make_zip_upload({"A-1.jpg": b"jpg"})
    mocker.patch.object(
        batch_admin_module,
        "constance_config",
        SimpleNamespace(PICTURE_IMPORT_MAX_ZIP_UPLOAD_MB=0),
    )
    form = BatchPictureImportForm(
        data={"match_field": "id", "target_field": "photo"},
        files={"zip_file": upload},
        match_field_choices=[("id", "id")],
        target_field_choices=[("photo", "photo")],
    )

    assert not form.is_valid()
    assert "zip_file" in form.errors


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


def test_batch_admin_picture_payload_helpers(batch_admin, batch: CountryBatch, rf: RequestFactory, user) -> None:
    request = rf.get("/")
    _add_middleware_to_request(request, user)

    assert batch_admin._picture_import_payloads(batch) == {}

    batch.picture_import_state = "not-a-dict"
    batch.save(update_fields=["picture_import_state"])
    assert batch_admin._picture_import_payloads(batch) == {}

    batch_admin._save_picture_import_payload(request, batch, "tok", {"batch_id": batch.pk})
    batch.refresh_from_db()
    assert batch.picture_import_state["tok"]["batch_id"] == batch.pk
    assert batch.picture_import_state["tok"]["created_by_id"] == user.pk
    assert batch.picture_import_state_updated_by_id == user.pk
    assert batch.picture_import_state_updated_at is not None

    assert batch_admin._get_picture_import_payload(request, batch, "missing") is None
    assert batch_admin._get_picture_import_payload(request, batch, "tok")["batch_id"] == batch.pk

    batch_admin._clear_picture_import_payload(request, batch, "tok")
    batch.refresh_from_db()
    assert batch.picture_import_state == {}


def test_batch_admin_get_picture_import_payload_is_user_scoped(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user
) -> None:
    from testutils.factories import UserFactory

    other_user = UserFactory()
    request = rf.get("/")
    _add_middleware_to_request(request, user)
    batch.picture_import_state = {"tok": {"batch_id": batch.pk, "created_by_id": other_user.pk}}
    batch.save(update_fields=["picture_import_state"])

    assert batch_admin._get_picture_import_payload(request, batch, "tok") is None


def test_batch_admin_get_picture_import_payload_rejects_wrong_batch(batch_admin, batch: CountryBatch, rf, user) -> None:
    request = rf.get("/")
    _add_middleware_to_request(request, user)
    batch.picture_import_state = {"tok": {"batch_id": batch.pk + 1, "created_by_id": user.pk}}
    batch.save(update_fields=["picture_import_state"])

    assert batch_admin._get_picture_import_payload(request, batch, "tok") is None


def test_batch_admin_delete_uploaded_zip_removes_existing_file(batch_admin) -> None:
    storage_name = default_storage.save("batch-picture-import/test-delete.zip", ContentFile(b"zip"))
    assert default_storage.exists(storage_name)
    batch_admin._delete_uploaded_zip(storage_name)
    assert not default_storage.exists(storage_name)


def test_batch_admin_store_uploaded_zip_saves_file_and_resets_pointer(batch_admin) -> None:
    upload = _make_zip_upload({"A-1.jpg": b"jpg"})
    storage_name = batch_admin._store_uploaded_zip(upload)
    assert default_storage.exists(storage_name)
    assert upload.tell() == 0
    default_storage.delete(storage_name)


def test_batch_admin_save_payload_replaces_old_and_deletes_old_file(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user
) -> None:
    request = rf.get("/")
    _add_middleware_to_request(request, user)
    old_storage_name = default_storage.save("batch-picture-import/old.zip", ContentFile(b"old"))
    batch.picture_import_state = {
        "tok": {"batch_id": batch.pk, "zip_file_name": old_storage_name, "created_by_id": user.pk}
    }
    batch.save(update_fields=["picture_import_state"])
    batch_admin._save_picture_import_payload(request, batch, "tok", {"batch_id": batch.pk, "zip_file_name": "new.zip"})
    batch.refresh_from_db()
    assert not default_storage.exists(old_storage_name)
    assert batch.picture_import_state["tok"]["zip_file_name"] == "new.zip"


def test_batch_admin_picture_import_payloads_prune_expired_entries(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    request = rf.get("/")
    _add_middleware_to_request(request, user)
    now = 1000
    batch.picture_import_state = {
        "ok": {"batch_id": 1, "created_at": now},
        "expired-storage": {"batch_id": 1, "created_at": now - 999, "zip_file_name": "old-storage.zip"},
        "broken": "not-a-dict",
    }
    batch.save(update_fields=["picture_import_state"])
    mocker.patch.object(batch_admin_module, "time", return_value=now)
    mocker.patch.object(batch_admin_module, "PICTURE_IMPORT_SESSION_TTL_SECONDS", 10)
    delete_uploaded_zip = mocker.patch.object(batch_admin_module.CountryBatchAdmin, "_delete_uploaded_zip")

    payloads = batch_admin._picture_import_payloads(batch)
    batch.refresh_from_db()

    assert payloads == {"ok": {"batch_id": 1, "created_at": now}}
    assert batch.picture_import_state == payloads
    delete_uploaded_zip.assert_any_call("old-storage.zip")


def test_batch_admin_picture_import_payloads_handles_non_dict_values(batch_admin, batch: CountryBatch, mocker) -> None:
    mocker.patch.object(batch, "get_picture_import_state", return_value={"bad": "value", "ok": {"batch_id": 1}})

    payloads = batch_admin._picture_import_payloads(batch)

    assert payloads == {"ok": {"batch_id": 1}}


def test_batch_admin_cleanup_stale_stored_zips_ignores_storage_errors(batch_admin, mocker) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    mocker.patch.object(batch_admin_module.default_storage, "listdir", side_effect=OSError("storage unavailable"))

    batch_admin._cleanup_stale_stored_zips()


def test_batch_admin_cleanup_stale_stored_zips_deletes_expired_files(batch_admin, mocker) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    mocker.patch.object(batch_admin_module, "PICTURE_IMPORT_SESSION_TTL_SECONDS", 10)
    mocker.patch.object(batch_admin_module, "time", return_value=1000)
    mocker.patch.object(
        batch_admin_module.default_storage,
        "listdir",
        return_value=([], ["old.zip", "new.zip", "broken.zip"]),
    )

    def _modified_time(path: str) -> datetime:
        if path.endswith("old.zip"):
            return datetime.fromtimestamp(980, UTC)
        if path.endswith("new.zip"):
            return datetime.fromtimestamp(995, UTC)
        raise OSError("stat failed")

    mocker.patch.object(batch_admin_module.default_storage, "get_modified_time", side_effect=_modified_time)
    delete = mocker.patch.object(batch_admin_module.default_storage, "delete")

    batch_admin._cleanup_stale_stored_zips()

    delete.assert_called_once_with("batch-picture-import/old.zip")


def test_batch_admin_acquire_batch_action_lock_returns_lock_when_available(batch_admin, mocker) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    lock = mocker.MagicMock()
    lock.acquire.return_value = True
    mocker.patch.object(batch_admin_module.cache, "lock", return_value=lock)

    assert batch_admin._acquire_batch_action_lock(5) is lock


def test_batch_admin_acquire_batch_action_lock_returns_none_when_unavailable(batch_admin, mocker) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    lock = mocker.MagicMock()
    lock.acquire.return_value = False
    mocker.patch.object(batch_admin_module.cache, "lock", return_value=lock)

    assert batch_admin._acquire_batch_action_lock(5) is None


def test_batch_admin_clear_payload_handles_missing_token(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user
) -> None:
    request = rf.get("/")
    _add_middleware_to_request(request, user)
    batch.picture_import_state = {}
    batch.save(update_fields=["picture_import_state"])

    batch_admin._clear_picture_import_payload(request, batch, "missing-token")
    batch.refresh_from_db()

    assert batch.picture_import_state == {}


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
    _mock_picture_import_service(mocker, batch_admin_module, service)
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
    _mock_picture_import_service(mocker, batch_admin_module, service)
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
    _mock_picture_import_service(mocker, batch_admin_module, service)
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
    batch.refresh_from_db()
    payload = batch.picture_import_state["token-123"]
    assert payload["batch_id"] == batch.pk
    assert payload["match_field"] == "beneficiary_id"
    assert payload["target_field"] == "photo"
    storage_name = payload["zip_file_name"]
    assert default_storage.exists(storage_name)
    default_storage.delete(storage_name)


def test_import_pictures_post_preview_with_invalid_form_renders_form(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    _mock_picture_import_service(mocker, batch_admin_module, service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin_module, "render", return_value=HttpResponse("rendered"))
    get_common_context = mocker.patch.object(batch_admin, "get_common_context", return_value={"step": "1"})

    request = rf.post(
        "/admin/import-pictures/",
        data={"preview": "1", "match_field": "beneficiary_id", "target_field": "photo"},
    )
    _add_middleware_to_request(request, user)

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 200
    form = get_common_context.call_args.kwargs["form"]
    assert "zip_file" in form.errors


def test_import_pictures_post_preview_handles_limit_error_and_cleans_temp_file(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    service.build_preview.side_effect = PictureImportLimitError("too many files")
    _mock_picture_import_service(mocker, batch_admin_module, service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin_module, "render", return_value=HttpResponse("rendered"))
    get_common_context = mocker.patch.object(batch_admin, "get_common_context", return_value={"step": "1"})

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

    assert response.status_code == 200
    form = get_common_context.call_args.kwargs["form"]
    assert "zip_file" in form.errors
    batch.refresh_from_db()
    assert batch.picture_import_state == {}


def test_import_pictures_post_confirm_without_token_redirects_with_error(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    _mock_picture_import_service(mocker, batch_admin_module, service)
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
    _mock_picture_import_service(mocker, batch_admin_module, service)
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
    service.enrich_assignments_with_zip_data.return_value = [
        {"record_id": 1, "data_uri": "data:image/jpeg;base64,Zm9v"}
    ]
    service.apply_assignments.return_value = 2
    _mock_picture_import_service(mocker, batch_admin_module, service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin, "message_user")
    mocker.patch.object(batch, "get_change_url", return_value="/workspace/batch/1/change/")
    batch_lock = mocker.MagicMock()
    mocker.patch.object(batch_admin, "_acquire_batch_action_lock", return_value=batch_lock)

    request = rf.post("/admin/import-pictures/", data={"confirm": "1", "token": "tok"})
    _add_middleware_to_request(request, user)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        archive.writestr("A-1.jpg", b"content")
    storage_name = default_storage.save("batch-picture-import/confirm.zip", ContentFile(payload.getvalue()))
    batch.picture_import_state = {
        "tok": {
            "batch_id": batch.pk,
            "match_field": "beneficiary_id",
            "target_field": "photo",
            "zip_file_name": storage_name,
            "created_by_id": user.pk,
            "assignments": [{"record_id": 1, "filename": "A-1.jpg"}],
        }
    }
    batch.save(update_fields=["picture_import_state"])

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302
    assert response.url == "/workspace/batch/1/change/"
    batch.refresh_from_db()
    assert batch.picture_import_state == {}
    service.enrich_assignments_with_zip_data.assert_called_once()
    service.apply_assignments.assert_called_once_with(
        "photo", [{"record_id": 1, "data_uri": "data:image/jpeg;base64,Zm9v"}]
    )
    batch_lock.release.assert_called_once()


def test_import_pictures_post_confirm_with_running_batch_action_redirects(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    _mock_picture_import_service(mocker, batch_admin_module, service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    message_user = mocker.patch.object(batch_admin, "message_user")
    mocker.patch.object(batch_admin, "_acquire_batch_action_lock", return_value=None)

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        archive.writestr("A-1.jpg", b"content")
    storage_name = default_storage.save("batch-picture-import/confirm-running.zip", ContentFile(payload.getvalue()))
    request = rf.post("/admin/import-pictures/", data={"confirm": "1", "token": "tok"})
    _add_middleware_to_request(request, user)
    batch.picture_import_state = {
        "tok": {
            "batch_id": batch.pk,
            "match_field": "beneficiary_id",
            "target_field": "photo",
            "zip_file_name": storage_name,
            "created_by_id": user.pk,
            "assignments": [{"record_id": 1, "filename": "A-1.jpg"}],
        }
    }
    batch.save(update_fields=["picture_import_state"])

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302
    assert response.url == "/admin/import-pictures/"
    service.enrich_assignments_with_zip_data.assert_not_called()
    service.apply_assignments.assert_not_called()
    batch.refresh_from_db()
    assert batch.picture_import_state["tok"]["zip_file_name"] == storage_name
    message_user.assert_called()
    default_storage.delete(storage_name)


def test_import_pictures_post_confirm_with_missing_zip_path_clears_payload(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    _mock_picture_import_service(mocker, batch_admin_module, service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    message_user = mocker.patch.object(batch_admin, "message_user")

    request = rf.post("/admin/import-pictures/", data={"confirm": "1", "token": "tok"})
    _add_middleware_to_request(request, user)
    batch.picture_import_state = {
        "tok": {
            "batch_id": batch.pk,
            "match_field": "beneficiary_id",
            "target_field": "photo",
            "created_by_id": user.pk,
        }
    }
    batch.save(update_fields=["picture_import_state"])

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302
    assert response.url == "/admin/import-pictures/"
    batch.refresh_from_db()
    assert batch.picture_import_state == {}
    message_user.assert_called()


def test_import_pictures_post_confirm_handles_limit_error(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    service.enrich_assignments_with_zip_data.side_effect = PictureImportLimitError("zip too large")
    _mock_picture_import_service(mocker, batch_admin_module, service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    message_user = mocker.patch.object(batch_admin, "message_user")
    batch_lock = mocker.MagicMock()
    mocker.patch.object(batch_admin, "_acquire_batch_action_lock", return_value=batch_lock)

    storage_name = default_storage.save("batch-picture-import/confirm-limit.zip", ContentFile(b"content"))
    request = rf.post("/admin/import-pictures/", data={"confirm": "1", "token": "tok"})
    _add_middleware_to_request(request, user)
    batch.picture_import_state = {
        "tok": {
            "batch_id": batch.pk,
            "match_field": "beneficiary_id",
            "target_field": "photo",
            "zip_file_name": storage_name,
            "created_by_id": user.pk,
            "assignments": [],
        }
    }
    batch.save(update_fields=["picture_import_state"])

    response = batch_admin.import_pictures.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302
    assert response.url == "/admin/import-pictures/"
    batch.refresh_from_db()
    assert batch.picture_import_state == {}
    assert not default_storage.exists(storage_name)
    message_user.assert_called()
    batch_lock.release.assert_called_once()


def test_import_pictures_get_step_two_with_expired_token_redirects(
    batch_admin, batch: CountryBatch, rf: RequestFactory, user, mocker
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    service = mocker.MagicMock()
    service.get_match_field_choices.return_value = [("beneficiary_id", "beneficiary_id")]
    service.get_target_field_choices.return_value = [("photo", "Photo")]
    _mock_picture_import_service(mocker, batch_admin_module, service)
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
    _mock_picture_import_service(mocker, batch_admin_module, service)
    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin_module, "render", return_value=HttpResponse("rendered"))
    get_common_context = mocker.patch.object(batch_admin, "get_common_context", return_value={"step": "2"})

    request = rf.get("/admin/import-pictures/?step=2&token=tok", data={"step": "2", "token": "tok"})
    _add_middleware_to_request(request, user)
    batch.picture_import_state = {
        "tok": {"batch_id": batch.pk, "created_by_id": user.pk, "matched_files_count": 1, "assignments": []}
    }
    batch.save(update_fields=["picture_import_state"])

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
    _mock_picture_import_service(mocker, batch_admin_module, service)
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
        archive.writestr("ABC.jpg", _make_image_bytes("JPEG"))
        archive.writestr("abc.png", _make_image_bytes("PNG"))
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
        archive.writestr("A-001.jpg", _make_image_bytes("JPEG"))
        archive.writestr("MISSING.jpg", _make_image_bytes("JPEG"))
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

    updated = BatchPictureImportService(batch).apply_assignments(
        "photo",
        [{"record_id": individual.pk, "data_uri": "data:image/jpeg;base64,Zm9v"}],
    )

    individual.refresh_from_db()
    assert updated == 1
    assert individual.flex_fields["photo"] == "data:image/jpeg;base64,Zm9v"


def test_picture_import_service_helpers() -> None:
    assert BatchPictureImportService._normalize_match_key(None) == ""
    assert BatchPictureImportService._normalize_match_key("  AbC ") == "abc"
    assert BatchPictureImportService._guess_image_mimetype("unknown.ext", b"not-an-image") == "application/octet-stream"


def test_picture_import_service_guess_image_mimetype_prefers_pillow_result() -> None:
    assert BatchPictureImportService._guess_image_mimetype("photo.bin", _make_image_bytes("PNG")) == "image/png"


def test_picture_import_service_guess_image_mimetype_falls_back_to_extension(mocker) -> None:
    from country_workspace.workspaces.admin.batch import picture_import as picture_import_module

    image_stub = mocker.MagicMock()
    image_stub.verify.return_value = None
    image_stub.format = None
    cm = mocker.MagicMock()
    cm.__enter__.return_value = image_stub
    cm.__exit__.return_value = False
    mocker.patch.object(picture_import_module.Image, "open", return_value=cm)

    assert BatchPictureImportService._guess_image_mimetype("photo.jpg", b"x") == "image/jpeg"


def test_extract_zip_images_ignores_non_images_and_blank_keys() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        archive.writestr("images/", b"")
        archive.writestr("notes.txt", b"ignored")
        archive.writestr(" .png", _make_image_bytes("PNG"))
        archive.writestr("valid.jpeg", _make_image_bytes("JPEG"))
    upload = SimpleUploadedFile("pictures.zip", payload.getvalue(), content_type="application/zip")

    entries, duplicate_keys = BatchPictureImportService.extract_zip_images(upload)

    assert [item["filename"] for item in entries] == ["valid.jpeg"]
    assert duplicate_keys == set()
    assert upload.tell() == 0


def test_extract_zip_images_ignores_invalid_image_content() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        archive.writestr("looks-like-image.jpg", b"not-really-an-image")
    upload = SimpleUploadedFile("pictures.zip", payload.getvalue(), content_type="application/zip")

    entries, duplicate_keys = BatchPictureImportService.extract_zip_images(upload)

    assert entries == []
    assert duplicate_keys == set()


def test_extract_zip_images_skips_empty_filename_entries(mocker) -> None:
    from country_workspace.workspaces.admin.batch import picture_import as picture_import_module

    upload = _make_zip_upload({"A-1.jpg": b"ok"})
    fake_path_obj = mocker.MagicMock()
    fake_path_obj.name = ""
    fake_path_obj.stem = ""
    mocker.patch.object(picture_import_module, "Path", return_value=fake_path_obj)

    entries, duplicate_keys = BatchPictureImportService.extract_zip_images(upload)

    assert entries == []
    assert duplicate_keys == set()


def test_extract_zip_images_raises_when_zip_has_too_many_files(mocker) -> None:
    from country_workspace.workspaces.admin.batch import picture_import as picture_import_module

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        archive.writestr("first.jpg", b"1")
        archive.writestr("second.jpg", b"2")
    upload = SimpleUploadedFile("pictures.zip", payload.getvalue(), content_type="application/zip")
    mocker.patch.object(
        picture_import_module,
        "constance_config",
        SimpleNamespace(PICTURE_IMPORT_MAX_ZIP_FILE_COUNT=1),
    )

    with pytest.raises(PictureImportLimitError, match="too many files"):
        BatchPictureImportService.extract_zip_images(upload)


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


def test_get_match_field_choices_ignores_non_dict_raw_data(batch: CountryBatch) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    CountryIndividualFactory(batch=batch, household=hh, raw_data=["a"])
    CountryIndividualFactory(batch=batch, household=hh, raw_data={"a_key": "1"})

    assert BatchPictureImportService(batch).get_match_field_choices() == [("a_key", "a_key")]


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


def test_build_preview_skips_records_with_empty_or_missing_match_values(batch: CountryBatch) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    CountryIndividualFactory(batch=batch, household=hh, raw_data={"beneficiary_id": None})
    CountryIndividualFactory(batch=batch, household=hh, raw_data={})

    report = BatchPictureImportService(batch).build_preview("beneficiary_id", _make_zip_upload({"A.jpg": b"x"}))

    assert report["matched_files_count"] == 0


def test_build_preview_include_data_uri_adds_data_uri_to_assignments(batch: CountryBatch) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    CountryIndividualFactory(batch=batch, household=hh, raw_data={"beneficiary_id": "A-1"})

    report = BatchPictureImportService(batch).build_preview(
        "beneficiary_id",
        _make_zip_upload({"A-1.jpg": b"x"}),
        include_data_uri=True,
    )

    assert report["assignments"]
    assert "data_uri" in report["assignments"][0]


def test_apply_picture_assignments_returns_zero_without_assignments(batch: CountryBatch) -> None:
    assert BatchPictureImportService(batch).apply_assignments("photo", []) == 0


def test_apply_picture_assignments_skips_missing_and_unchanged_records(batch: CountryBatch) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(batch=batch, household=hh, flex_fields={"photo": "same"})

    updated = BatchPictureImportService(batch).apply_assignments(
        "photo",
        [
            {"record_id": individual.pk, "data_uri": "same"},
            {"record_id": 999999999, "data_uri": "new"},
        ],
    )

    assert updated == 0


def test_apply_picture_assignments_enforces_batch_and_not_removed(batch: CountryBatch) -> None:
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    removable = CountryIndividualFactory(batch=batch, household=hh, removed=True, flex_fields={"photo": ""})

    other_batch = CountryBatchFactory(program=batch.program, country_office=batch.country_office)
    other_hh = CountryHouseholdFactory(batch=other_batch, individuals=0)
    outsider = CountryIndividualFactory(batch=other_batch, household=other_hh, flex_fields={"photo": ""})

    updated = BatchPictureImportService(batch).apply_assignments(
        "photo",
        [
            {"record_id": removable.pk, "data_uri": "data:image/jpeg;base64,Zm9v"},
            {"record_id": outsider.pk, "data_uri": "data:image/jpeg;base64,YmFy"},
        ],
    )

    removable.refresh_from_db()
    outsider.refresh_from_db()
    assert updated == 0
    assert removable.flex_fields.get("photo") == ""
    assert outsider.flex_fields.get("photo") == ""


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


def test_batch_actions_choice_contains_import_and_reprocess(batch_admin, batch: CountryBatch, mocker) -> None:
    request = mocker.MagicMock()
    request.user.has_perm.return_value = True
    button = batch_admin.batch_actions.get_button({"original": batch, "request": request})

    batch_admin.batch_actions.func(batch_admin, button)

    assert button.choices == [batch_admin.import_pictures, batch_admin.reprocess_batch]


def test_batch_actions_visible_with_any_permission(batch_admin, batch: CountryBatch, mocker) -> None:
    request = mocker.MagicMock()
    request.user.has_perm.side_effect = [False, True]
    button = batch_admin.batch_actions.get_button({"original": batch, "request": request})
    assert button.visible is True


def test_picture_import_service_reads_file_count_limit_from_constance(mocker) -> None:
    from country_workspace.workspaces.admin.batch import picture_import as picture_import_module

    mocker.patch.object(
        picture_import_module,
        "constance_config",
        SimpleNamespace(PICTURE_IMPORT_MAX_ZIP_FILE_COUNT=1),
    )

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w") as archive:
        archive.writestr("1.jpg", b"x")
        archive.writestr("2.jpg", b"y")
    upload = SimpleUploadedFile("pictures.zip", payload.getvalue(), content_type="application/zip")

    with pytest.raises(PictureImportLimitError, match="max 1"):
        BatchPictureImportService.extract_zip_images(upload)


def test_enrich_assignments_with_zip_data_skips_missing_items() -> None:
    upload = _make_zip_upload({"A-1.jpg": b"content"})
    assignments = [
        {"record_id": 1, "filename": "A-1.jpg"},
        {"record_id": 2},
        {"record_id": 3, "filename": "MISSING.jpg"},
    ]

    enriched = BatchPictureImportService.enrich_assignments_with_zip_data(assignments, upload)

    assert len(enriched) == 1
    assert enriched[0]["record_id"] == 1
    assert enriched[0]["filename"] == "A-1.jpg"
    assert "data_uri" in enriched[0]


def test_enrich_assignments_with_zip_data_returns_empty_for_empty_input() -> None:
    upload = _make_zip_upload({"A-1.jpg": b"content"})

    assert BatchPictureImportService.enrich_assignments_with_zip_data([], upload) == []
