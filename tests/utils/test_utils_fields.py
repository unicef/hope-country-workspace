from unittest.mock import Mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from pytest_mock import MockerFixture

from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT
from country_workspace.utils.fields import (
    clean_field_name,
    TO_REMOVE_VALUES,
    clean_field_names,
    map_fields,
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

    assert Base64ImageField.clean(instance, False) is None


def test_base64_image_field_content_is_encoded(mocker: MockerFixture) -> None:
    super_clean_mock = mocker.patch("country_workspace.utils.flex_fields.forms.ImageField.clean")
    b64encode_mock = mocker.patch("country_workspace.utils.flex_fields.b64encode")
    b64encode_mock.return_value.decode.return_value = (data := "decoded")
    file = SimpleUploadedFile("test.txt", b"test", content_type=(content_type := "text/plain"))
    super_clean_mock.return_value = file
    instance = Mock(spec=Base64ImageField)

    assert Base64ImageField.clean(instance, file) == VALUE_FORMAT.format(mimetype=content_type, content=data)
