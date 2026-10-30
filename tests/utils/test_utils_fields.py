from base64 import b64decode
from io import BytesIO
from unittest.mock import Mock, call
from uuid import UUID

import pytest
from django import forms
from PIL import Image
from concurrency.utils import fqn
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from hope_flex_fields.fields import FlexImageField
from pytest_mock import MockerFixture


from country_workspace.utils.fields import clean_field_name, TO_REMOVE_VALUES, clean_field_names, to_reference_key
from country_workspace.utils.flex_fields import (
    Base64ImageField,
    CaseInsensitiveChoiceField,
    CaseInsensitiveChoiceFieldWithEmptyDisplay,
    ConsentSharingChoice,
    ObservedDisabilityChoice,
    split_options,
)

SEVERITY_CHOICES = [("", "None"), ("LOT_DIFFICULTY", "A lot"), ("CANNOT_DO", "Cannot"), ("SOME_DIFFICULTY", "Some")]
DISABILITY_CHOICES = [("disabled", "disabled"), ("not disabled", "not disabled")]
OBSERVED_DISABILITY_CHOICES = [("NONE", "None"), ("SEEING", "Seeing"), ("HEARING", "Hearing")]

FILE_ID = UUID("0f3b6a1e-2d0d-4a1e-9a4a-3f5a2d1c8b70")
REFERENCE = "flexfile:%s" % FILE_ID


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


def test_flex_image_widget_links_to_the_workspace_file_view() -> None:
    context = FlexImageField().widget.get_context("photo", REFERENCE, None)

    assert context["widget"]["image_src"] == reverse("workspace:flex_file", args=[FILE_ID])


def test_base64_image_field_keeps_its_stored_import_path() -> None:
    """Field definitions saved before the library took the field over still name this path."""
    assert fqn(Base64ImageField) == "country_workspace.utils.flex_fields.Base64ImageField"


def test_base64_image_field_still_encodes_the_upload_inline(png_upload: SimpleUploadedFile) -> None:
    content = png_upload.read()
    png_upload.seek(0)

    cleaned = Base64ImageField(required=False).clean(png_upload, None)

    assert cleaned.startswith("data:image/png;base64,")
    assert b64decode(cleaned.split(",", 1)[1]) == content


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
        pytest.param("SOME_DIFFICULTY", "SOME_DIFFICULTY", id="exact"),
        pytest.param("some_difficulty", "SOME_DIFFICULTY", id="lowercase"),
        pytest.param("Cannot_Do", "CANNOT_DO", id="mixed-case"),
        pytest.param("", "", id="empty"),
        pytest.param(None, "", id="none"),
    ],
)
def test_case_insensitive_choice_field_returns_choice_key(value: str | None, expected: str) -> None:
    field = CaseInsensitiveChoiceField(choices=SEVERITY_CHOICES, required=False)

    assert field.clean(value) == expected


def test_case_insensitive_choice_field_rejects_unknown_value() -> None:
    field = CaseInsensitiveChoiceField(choices=SEVERITY_CHOICES, required=False)

    with pytest.raises(forms.ValidationError):
        field.clean("some difficulty")


def test_case_insensitive_choice_field_keeps_lowercase_choice_keys() -> None:
    field = CaseInsensitiveChoiceFieldWithEmptyDisplay(choices=DISABILITY_CHOICES, required=False)

    assert field.clean("DISABLED") == "disabled"
    assert field.clean("Not Disabled") == "not disabled"


def test_case_insensitive_choice_field_with_empty_display_still_requires_value() -> None:
    field = CaseInsensitiveChoiceFieldWithEmptyDisplay(choices=DISABILITY_CHOICES, required=True)

    with pytest.raises(forms.ValidationError):
        field.clean("")


def test_case_insensitive_choice_field_matches_grouped_choices() -> None:
    field = CaseInsensitiveChoiceField(choices=[("Group", [("MARRIED", "Married"), ("SINGLE", "Single")])])

    assert field.clean("single") == "SINGLE"


def test_case_insensitive_choice_field_selects_stored_lowercase_value() -> None:
    class TestForm(forms.Form):
        seeing_disability = CaseInsensitiveChoiceField(choices=SEVERITY_CHOICES, required=False)

    html = str(TestForm(initial={"seeing_disability": "some_difficulty"})["seeing_disability"])

    assert '<option value="SOME_DIFFICULTY" selected>' in html


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("seeing, Hearing", ["SEEING", "HEARING"], id="string"),
        pytest.param(["none"], ["NONE"], id="list"),
        pytest.param("", [], id="empty"),
    ],
)
def test_observed_disability_choice_returns_choice_keys(value: str | list[str], expected: list[str]) -> None:
    field = ObservedDisabilityChoice(choices=OBSERVED_DISABILITY_CHOICES, required=False)

    assert field.clean(value) == expected


def test_consent_sharing_choice_returns_choice_keys() -> None:
    field = ConsentSharingChoice(choices=[("UNICEF", "UNICEF"), ("PRIVATE_PARTNER", "Private")], required=False)

    assert field.clean("unicef private_partner") == ["UNICEF", "PRIVATE_PARTNER"]


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
