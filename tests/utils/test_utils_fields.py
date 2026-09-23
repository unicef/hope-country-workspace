from io import BytesIO
from unittest.mock import Mock, call

import pytest
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from pytest_mock import MockerFixture


from country_workspace.utils.fields import clean_field_name, TO_REMOVE_VALUES, clean_field_names, to_reference_key
from country_workspace.utils.flex_fields import (
    Base64ImageInput,
    Base64ImageField,
    ConsentSharingChoice,
    FlexImageField,
    FlexImageInput,
    split_options,
)
from country_workspace.utils.flex_files import DATA_URI_FORMAT

REFERENCE = "flexfile:0f3b6a1e-2d0d-4a1e-9a4a-3f5a2d1c8b70"


@pytest.fixture
def png_upload() -> SimpleUploadedFile:
    """A real one-pixel PNG, so that image validation runs for real."""
    buffer = BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, format="PNG")
    return SimpleUploadedFile("photo.png", buffer.getvalue(), content_type="image/png")


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


@pytest.mark.parametrize("widget_class", [FlexImageInput, Base64ImageInput])
@pytest.mark.parametrize("value", [None, "", "test"])
def test_flex_image_input_treats_any_value_as_initial(value: str | None, widget_class: type) -> None:
    assert widget_class().is_initial(value) == bool(value)


def test_flex_image_input_exposes_the_image_source() -> None:
    context = FlexImageInput().get_context("photo", REFERENCE, None)

    assert context["widget"]["image_src"].endswith("%s/" % REFERENCE.removeprefix("flexfile:"))


def test_flex_image_field_keeps_the_stored_reference_when_nothing_is_uploaded() -> None:
    assert FlexImageField(required=False).clean(None, REFERENCE) == REFERENCE


def test_flex_image_field_returns_empty_when_the_field_is_cleared() -> None:
    assert FlexImageField(required=False).clean(False, REFERENCE) == ""


def test_flex_image_field_leaves_an_upload_to_the_save_layer(png_upload: SimpleUploadedFile) -> None:
    """The upload is validated here, but only the save layer can write its row."""
    assert FlexImageField(required=False).clean(png_upload, REFERENCE) == REFERENCE
    assert FlexImageField(required=False).clean(png_upload, None) == ""


def test_base64_image_field_file_was_cleared(mocker: MockerFixture) -> None:
    super_clean_mock = mocker.patch("country_workspace.utils.flex_fields.forms.ImageField.clean")
    super_clean_mock.return_value = False
    instance = Mock(spec=Base64ImageField)
    initial_data = None

    assert Base64ImageField.clean(instance, False, initial_data) == ""
    super_clean_mock.assert_called_once_with(False, initial_data)


def test_base64_image_field_content_is_encoded(mocker: MockerFixture) -> None:
    super_clean_mock = mocker.patch("country_workspace.utils.flex_fields.forms.ImageField.clean")
    b64encode_mock = mocker.patch("country_workspace.utils.flex_fields.b64encode")
    b64encode_mock.return_value.decode.return_value = (data := "decoded")
    file = SimpleUploadedFile("test.txt", content := b"test", content_type=(content_type := "text/plain"))
    super_clean_mock.return_value = file
    instance = Mock(spec=Base64ImageField)
    initial_data = None

    assert Base64ImageField.clean(instance, file, initial_data) == DATA_URI_FORMAT.format(
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("a,b,c", abc := ["a", "b", "c"], id="comma"),
        pytest.param("a b c", abc, id="space"),
        pytest.param("a, b,c ", abc, id="comma-strip"),
        pytest.param("a b c ", abc, id="space-strip"),
        pytest.param("", [], id="empty"),
        pytest.param("a", ["a"], id="single"),
    ],
)
def test_split_options(value: str, expected: list[str]) -> None:
    assert split_options(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="none"),
        pytest.param(["a", "b"], id="list"),
    ],
)
def test_consent_sharing_choice_to_python_and_prepare_value_call_super_method(
    mocker: MockerFixture, value: list[str] | None
) -> None:
    super_to_python_mock = mocker.patch("country_workspace.utils.flex_fields.forms.MultipleChoiceField.to_python")
    super_prepare_value_mock = mocker.patch(
        "country_workspace.utils.flex_fields.forms.MultipleChoiceField.prepare_value"
    )
    instance = Mock(spec=ConsentSharingChoice)

    ConsentSharingChoice.prepare_value(instance, value)
    ConsentSharingChoice.to_python(instance, value)

    super_to_python_mock.assert_called_once_with(value)
    super_prepare_value_mock.assert_called_once_with(value)


def test_consent_sharing_choice_to_python_and_prepare_value_call_split_options(
    mocker: MockerFixture,
) -> None:
    value = "test"
    split_options_mock = mocker.patch("country_workspace.utils.flex_fields.split_options")
    instance = Mock(spec=ConsentSharingChoice)

    ConsentSharingChoice.to_python(instance, value)
    ConsentSharingChoice.prepare_value(instance, value)

    split_options_mock.assert_has_calls([c := call(value), c])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, None),
        (False, None),
        (0, "0"),
        (42, "42"),
        (2.0, "2"),
        (2.5, "2.5"),
        ("  abc  ", "abc"),
        ("   ", None),
        ("0", "0"),
    ],
)
def test_normalize_reference_primitives(value, expected) -> None:
    assert to_reference_key(value) == expected


def test_normalize_reference_fallback_object_string() -> None:
    class Obj:
        def __str__(self) -> str:
            return "  x-ref  "

    assert to_reference_key(Obj()) == "x-ref"
