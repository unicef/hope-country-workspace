import base64
from uuid import uuid4

import pytest
from django.utils.functional import empty
from hope_flex_fields.registry import field_registry
from pytest_mock import MockerFixture

from country_workspace.exceptions import MissingFlexFileError
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.services.hope_blob import (
    decode_data_uri,
    image_field_names,
    is_data_uri,
    sync_record_blobs,
)
from country_workspace.storages import HOPE_STORAGE
from country_workspace.utils.flex_fields import Base64ImageField
from country_workspace.utils.flex_files import write_flex_file
from testutils.factories import (
    CountryIndividualFactory,
    DataCheckerFactory,
    DataCheckerFieldsetFactory,
    FieldDefinitionFactory,
    FieldsetFactory,
    FlexFieldFactory,
)


@pytest.fixture(autouse=True)
def _reset_hope_storage():
    """Force HOPE_STORAGE to re-resolve from the current settings.STORAGES."""
    HOPE_STORAGE._wrapped = empty
    yield
    HOPE_STORAGE._wrapped = empty


PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
DATA_URI = f"data:image/png;base64,{PNG_B64}"
OTHER_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
OTHER_DATA_URI = f"data:image/png;base64,{OTHER_PNG_B64}"
FILE_CONTENT = b"\x89PNG\r\n\x1a\nfile-content"


# ------------------------------- helpers -------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (DATA_URI, True),
        ("plain-string", False),
        ("", False),
        (None, False),
        (123, False),
    ],
    ids=["data_uri", "plain_string", "empty", "none", "non_string"],
)
def test_is_data_uri(value: object, expected: bool) -> None:
    assert is_data_uri(value) is expected


def test_decode_data_uri() -> None:
    assert decode_data_uri(DATA_URI) == base64.b64decode(PNG_B64)


# --------------------------- image_field_names --------------------------


@pytest.fixture
def checker_with_image_field():
    field_registry.register(Base64ImageField)
    checker = DataCheckerFactory()

    plain_fieldset = FieldsetFactory()
    FlexFieldFactory(fieldset=plain_fieldset, name="full_name")
    DataCheckerFieldsetFactory(checker=checker, fieldset=plain_fieldset, prefix="")

    image_fieldset = FieldsetFactory()
    FlexFieldFactory(
        fieldset=image_fieldset,
        name="photo",
        definition=FieldDefinitionFactory(field_type=Base64ImageField),
    )
    DataCheckerFieldsetFactory(checker=checker, fieldset=image_fieldset, prefix="national_id_")

    return checker


def test_image_field_names_filters_by_type_and_applies_prefix(checker_with_image_field) -> None:
    assert image_field_names(checker_with_image_field) == {"national_id_photo"}


# ----------------------------- sync_record_blobs: legacy inline data-URI ----------


@pytest.fixture
def individual():
    return CountryIndividualFactory(household=None, flex_fields={"photo": DATA_URI})


def test_sync_record_blobs_uploads_new_image(individual) -> None:
    key = individual.hope_blob_key("photo")

    paths = sync_record_blobs(individual, ["photo"])

    assert paths == {"photo": key}
    assert HOPE_STORAGE.exists(key)
    with HOPE_STORAGE.open(key) as fh:
        assert fh.read() == decode_data_uri(DATA_URI)

    individual.refresh_from_db()
    assert individual.blob_hashes.keys() == {"photo"}


def test_sync_record_blobs_reuses_unchanged_hash(individual, mocker: MockerFixture) -> None:
    sync_record_blobs(individual, ["photo"])
    individual.refresh_from_db()

    save_spy = mocker.patch.object(HOPE_STORAGE, "save")

    paths = sync_record_blobs(individual, ["photo"])

    save_spy.assert_not_called()
    assert paths == {"photo": individual.hope_blob_key("photo")}


def test_sync_record_blobs_reuploads_on_changed_content(individual) -> None:
    sync_record_blobs(individual, ["photo"])
    individual.refresh_from_db()
    key = individual.hope_blob_key("photo")
    old_hash = individual.blob_hashes["photo"]

    individual.flex_fields["photo"] = OTHER_DATA_URI
    paths = sync_record_blobs(individual, ["photo"])

    individual.refresh_from_db()
    assert individual.blob_hashes["photo"] != old_hash
    assert paths == {"photo": key}
    with HOPE_STORAGE.open(key) as fh:
        assert fh.read() == decode_data_uri(OTHER_DATA_URI)


def test_sync_record_blobs_deletes_blob_when_image_removed(individual) -> None:
    sync_record_blobs(individual, ["photo"])
    individual.refresh_from_db()
    key = individual.hope_blob_key("photo")
    assert HOPE_STORAGE.exists(key)

    individual.flex_fields["photo"] = ""
    paths = sync_record_blobs(individual, ["photo"])

    individual.refresh_from_db()
    assert paths == {}
    assert individual.blob_hashes == {}
    assert not HOPE_STORAGE.exists(key)


def test_sync_record_blobs_only_scopes_reconcile(individual) -> None:
    individual.flex_fields["national_id_photo"] = DATA_URI

    paths = sync_record_blobs(individual, ["photo", "national_id_photo"], only={"photo"})

    assert paths == {"photo": individual.hope_blob_key("photo")}
    assert not HOPE_STORAGE.exists(individual.hope_blob_key("national_id_photo"))


# ------------------------ sync_record_blobs: offloaded FlexFieldFile ------------------------


@pytest.fixture
def offloaded_individual():
    individual = CountryIndividualFactory(household=None, flex_fields={"photo": ""})
    reference = write_flex_file(individual, "photo", FILE_CONTENT, "image/png", "photo.png")
    individual.flex_fields = {"photo": reference}
    individual.save(update_fields=["flex_fields"])
    return individual


def test_sync_record_blobs_uploads_an_offloaded_reference(offloaded_individual) -> None:
    key = offloaded_individual.hope_blob_key("photo")

    paths = sync_record_blobs(offloaded_individual, ["photo"])

    assert paths == {"photo": key}
    with HOPE_STORAGE.open(key) as fh:
        assert fh.read() == FILE_CONTENT
    offloaded_individual.refresh_from_db()
    flex_file = FlexFieldFile.objects.get(pk=FlexFieldFile.parse_reference(offloaded_individual.flex_fields["photo"]))
    assert offloaded_individual.blob_hashes["photo"] == flex_file.checksum


def test_sync_record_blobs_reuses_unchanged_hash_for_a_reference(offloaded_individual, mocker: MockerFixture) -> None:
    sync_record_blobs(offloaded_individual, ["photo"])
    offloaded_individual.refresh_from_db()

    save_spy = mocker.patch.object(HOPE_STORAGE, "save")
    paths = sync_record_blobs(offloaded_individual, ["photo"])

    save_spy.assert_not_called()
    assert paths == {"photo": offloaded_individual.hope_blob_key("photo")}


def test_sync_record_blobs_does_not_reupload_after_migrating_to_a_reference(individual, mocker: MockerFixture) -> None:
    """The same bytes synced first as a data-URI and then as a reference keep the same hash."""
    sync_record_blobs(individual, ["photo"])
    individual.refresh_from_db()

    reference = write_flex_file(individual, "photo", decode_data_uri(DATA_URI), "image/png")
    individual.flex_fields = {"photo": reference}
    individual.save(update_fields=["flex_fields"])
    save_spy = mocker.patch.object(HOPE_STORAGE, "save")

    paths = sync_record_blobs(individual, ["photo"])

    save_spy.assert_not_called()
    assert paths == {"photo": individual.hope_blob_key("photo")}


def test_sync_record_blobs_raises_when_the_referenced_file_is_missing() -> None:
    individual = CountryIndividualFactory(household=None, flex_fields={"photo": "flexfile:%s" % uuid4()})

    with pytest.raises(MissingFlexFileError, match="field 'photo' references missing file"):
        sync_record_blobs(individual, ["photo"])


def test_sync_record_blobs_raises_for_a_reference_owned_by_someone_else(offloaded_individual) -> None:
    other = CountryIndividualFactory(household=None, flex_fields={"photo": offloaded_individual.flex_fields["photo"]})

    with pytest.raises(MissingFlexFileError, match="field 'photo' references missing file"):
        sync_record_blobs(other, ["photo"])
