from unittest.mock import Mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from pytest_mock import MockerFixture
from base64 import b64encode
from uuid import uuid4, UUID

from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT
from country_workspace.utils.fields import (
    clean_field_name,
    TO_REMOVE_VALUES,
    clean_field_names,
    map_fields,
    extract_uuid,
)
from country_workspace.utils.flex_fields import Base64ImageInput, Base64ImageField


@pytest.mark.parametrize(
    ("input_value", "expected_output"),
    [(f"field{substr}_foo", "field_foo") for substr in TO_REMOVE_VALUES]
    + [(f"FIELD{substr.upper()}_foo", "field_foo") for substr in TO_REMOVE_VALUES]
    + [
        ("field_foo", "field_foo"),
    ],
)
def test_clean_field_name(input_value, expected_output):
    assert clean_field_name(input_value) == expected_output


def test_clean_field_names(mocker: MockerFixture) -> None:
    clean_field_name_mock = mocker.patch("country_workspace.utils.fields.clean_field_name")

    cleaned = clean_field_names({(key := "foo"): "bar"})

    assert cleaned == {clean_field_name_mock.return_value: "bar"}
    clean_field_name_mock.assert_called_once_with(key)


@pytest.mark.parametrize(
    ("input_fields", "expected_output"),
    [
        ({"gender": "male"}, {"sex": "male"}),
        ({"name": "John"}, {"name": "John"}),
        ({}, {}),
        ({"gender": "female", "age": "30"}, {"sex": "female", "age": "30"}),
    ],
)
def test_map_fields(input_fields, expected_output):
    result = map_fields(input_fields)
    assert result == expected_output


@pytest.mark.parametrize("value", [None, "", "test"])
def test_base64_image_input(value: str | None) -> None:
    input_ = Base64ImageInput()
    assert input_.is_initial(value) == bool(value)


def test_base64_image_field_file_was_cleared(mocker: MockerFixture) -> None:
    super_clean_mock = mocker.patch("country_workspace.utils.flex_fields.forms.ImageField.clean")
    super_clean_mock.return_value = False
    instance = Mock(spec=Base64ImageField)
    initial_data = None

    assert Base64ImageField.clean(instance, False, initial_data) is None
    super_clean_mock.assert_called_once_with(False, initial_data)


def test_base64_image_field_content_is_encoded(mocker: MockerFixture) -> None:
    super_clean_mock = mocker.patch("country_workspace.utils.flex_fields.forms.ImageField.clean")
    b64encode_mock = mocker.patch("country_workspace.utils.flex_fields.b64encode")
    b64encode_mock.return_value.decode.return_value = (data := "decoded")
    file = SimpleUploadedFile("test.txt", content := b"test", content_type=(content_type := "text/plain"))
    super_clean_mock.return_value = file
    instance = Mock(spec=Base64ImageField)
    initial_data = None

    assert Base64ImageField.clean(instance, file, initial_data) == VALUE_FORMAT.format(
        mimetype=content_type, content=data
    )
    super_clean_mock.assert_called_once_with(file, initial_data)
    b64encode_mock.assert_called_once_with(content)


def test_base64_image_field_content_is_unchanged(mocker: MockerFixture) -> None:
    super_clean_mock = mocker.patch("country_workspace.utils.flex_fields.forms.ImageField.clean")
    super_clean_mock.return_value = (initial_data := "initial_data")
    instance = Mock(spec=Base64ImageField)
    data = None

    assert Base64ImageField.clean(instance, data, initial_data) == initial_data
    super_clean_mock.assert_called_once_with(data, initial_data)


FAKE_UUID = uuid4()
FAKE_PREFIX = "Area:"
ENC_B64_PREF = b64encode(f"{FAKE_PREFIX}{FAKE_UUID}".encode()).decode()
ENC_B64 = b64encode(str(FAKE_UUID).encode()).decode()
ENC_B64_BAD = b64encode("hello-world".encode()).decode()


@pytest.mark.parametrize(
    ("value", "prefix", "expected"),
    [
        (str(FAKE_UUID), None, FAKE_UUID),
        (ENC_B64_PREF, FAKE_PREFIX, FAKE_UUID),
        (ENC_B64, None, FAKE_UUID),
    ],
    ids=["raw-uuid", "b64-with-prefix", "b64-no-prefix"],
)
def test_extract_uuid_success(value: str, prefix: str | None, expected: UUID) -> None:
    assert extract_uuid(value, prefix) == expected


@pytest.mark.parametrize(
    ("value", "prefix", "exc_type"),
    [
        ("not-a-uuid-or-base64", None, ValueError),
        (ENC_B64_BAD, None, ValueError),
        (123, None, TypeError),
        (str(FAKE_UUID), 123, TypeError),
    ],
    ids=["invalid-string", "b64-not-uuid", "value-not-str", "prefix-not-str"],
)
def test_extract_uuid_errors(value: str | int, prefix: str | int | None, exc_type: type[Exception]) -> None:
    with pytest.raises(exc_type):
        extract_uuid(value, prefix)
