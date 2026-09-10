import base64

import pytest
from django import forms
from hope_flex_fields.registry import field_registry

from country_workspace.exceptions import BlobStorageError
from country_workspace.services.hope_blob import (
    decode_data_uri,
    image_field_names,
    is_data_uri,
    sync_record_blobs,
)
from country_workspace.storages import HOPE_STORAGE
from country_workspace.utils.flex_fields import Base64ImageField

pytestmark = pytest.mark.django_db

RAW_BYTES = b"fake-png-bytes"
DATA_URI = f"data:image/png;base64,{base64.b64encode(RAW_BYTES).decode()}"


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture
def individual_checker():
    from testutils.factories import DataCheckerFactory, DataCheckerFieldsetFactory, FieldsetFactory, FlexFieldFactory

    field_registry.register(Base64ImageField)
    checker = DataCheckerFactory()
    fieldset = FieldsetFactory()
    FlexFieldFactory(fieldset=fieldset, name="photo", definition__field_type=Base64ImageField)
    FlexFieldFactory(fieldset=fieldset, name="notes", definition__field_type=forms.CharField)
    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix="")
    return checker


@pytest.fixture
def program(office, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(country_office=office, individual_checker=individual_checker)


@pytest.fixture
def batch(program):
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory(program=program, country_office=program.country_office)


@pytest.fixture
def individual(batch):
    from testutils.factories import IndividualFactory

    return IndividualFactory(household=None, batch=batch, flex_fields={"photo": DATA_URI, "notes": "hello"})


def test_is_data_uri():
    assert is_data_uri(DATA_URI) is True
    assert is_data_uri("not-a-data-uri") is False
    assert is_data_uri(None) is False
    assert is_data_uri(123) is False


def test_decode_data_uri():
    assert decode_data_uri(DATA_URI) == RAW_BYTES


def test_image_field_names_returns_only_image_fields(individual_checker):
    assert image_field_names(individual_checker) == ["photo"]


def test_sync_record_blobs_uploads_new_image(individual):
    result = sync_record_blobs(individual, ["photo"])

    key = individual.hope_blob_key("photo")
    assert result == {"photo": key}
    assert HOPE_STORAGE.exists(key)

    individual.refresh_from_db()
    assert "photo" in individual.blob_hashes


def test_sync_record_blobs_skips_unchanged_image(individual, mocker):
    sync_record_blobs(individual, ["photo"])
    individual.refresh_from_db()

    save = mocker.patch.object(HOPE_STORAGE, "save")
    result = sync_record_blobs(individual, ["photo"])

    save.assert_not_called()
    assert result == {"photo": individual.hope_blob_key("photo")}


def test_sync_record_blobs_reuploads_changed_image(individual, mocker):
    sync_record_blobs(individual, ["photo"])
    individual.refresh_from_db()

    new_bytes = b"other-bytes"
    individual.flex_fields["photo"] = f"data:image/png;base64,{base64.b64encode(new_bytes).decode()}"
    individual.save(update_fields=["flex_fields"])

    save = mocker.patch.object(HOPE_STORAGE, "save", wraps=HOPE_STORAGE.save)
    sync_record_blobs(individual, ["photo"])

    save.assert_called_once()


def test_sync_record_blobs_removes_deleted_image(individual):
    sync_record_blobs(individual, ["photo"])
    individual.refresh_from_db()
    key = individual.hope_blob_key("photo")
    assert HOPE_STORAGE.exists(key)

    individual.flex_fields["photo"] = ""
    individual.save(update_fields=["flex_fields"])

    result = sync_record_blobs(individual, ["photo"])

    assert result == {}
    assert not HOPE_STORAGE.exists(key)
    individual.refresh_from_db()
    assert "photo" not in individual.blob_hashes


def test_sync_record_blobs_only_filter_restricts_fields(individual):
    individual.flex_fields["other_photo"] = DATA_URI
    individual.save(update_fields=["flex_fields"])

    result = sync_record_blobs(individual, ["photo", "other_photo"], only={"photo"})

    assert result == {"photo": individual.hope_blob_key("photo")}


def test_sync_record_blobs_raises_blob_storage_error_on_backend_failure(individual, mocker):
    mocker.patch.object(HOPE_STORAGE, "save", side_effect=OSError("boom"))

    with pytest.raises(BlobStorageError):
        sync_record_blobs(individual, ["photo"])
