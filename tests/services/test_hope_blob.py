import base64

import pytest
from hope_flex_fields.registry import field_registry
from pytest_mock import MockerFixture

from country_workspace.services.hope_blob import (
    decode_data_uri,
    image_field_names,
    is_data_uri,
    substitute_row_images,
    sync_record_blobs,
)
from country_workspace.storages import HOPE_STORAGE
from country_workspace.utils.flex_fields import Base64ImageField
from testutils.factories import (
    CountryIndividualFactory,
    DataCheckerFactory,
    DataCheckerFieldsetFactory,
    FieldDefinitionFactory,
    FieldsetFactory,
    FlexFieldFactory,
)

PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
DATA_URI = f"data:image/png;base64,{PNG_B64}"
OTHER_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
OTHER_DATA_URI = f"data:image/png;base64,{OTHER_PNG_B64}"


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
    assert image_field_names(checker_with_image_field) == ["national_id_photo"]


# ----------------------------- sync_record_blobs -------------------------


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


# --------------------------- substitute_row_images -----------------------


def test_substitute_row_images_replaces_top_level_data_uri(individual) -> None:
    row = {"photo": DATA_URI, "full_name": "John Doe"}
    paths = {"photo": "AFG/0001/CW_ind_1_photo.png"}

    result = substitute_row_images(individual, row, paths)

    assert result == {"photo": paths["photo"], "full_name": "John Doe"}


def test_substitute_row_images_leaves_non_data_uri_values_untouched(individual) -> None:
    row = {"photo": "", "full_name": "John Doe"}

    result = substitute_row_images(individual, row, paths={})

    assert result == row


def test_substitute_row_images_replaces_nested_document_images(individual) -> None:
    row = {
        "documents": [
            {"type": "national_id", "document_number": "NI123", "photo": DATA_URI},
            {"type": "national_passport", "document_number": "NP123", "photo": ""},
        ],
    }
    paths = {"national_id_photo": "AFG/0001/CW_ind_1_national_id_photo.png"}

    result = substitute_row_images(individual, row, paths)

    assert result == {
        "documents": [
            {"type": "national_id", "document_number": "NI123", "photo": paths["national_id_photo"]},
            {"type": "national_passport", "document_number": "NP123", "photo": ""},
        ],
    }
