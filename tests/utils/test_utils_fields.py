import json
from unittest.mock import Mock, call

import msgpack
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from pytest_mock import MockerFixture


from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT
from country_workspace.utils.fields import clean_field_name, TO_REMOVE_VALUES, clean_field_names, to_reference_key
from country_workspace.utils.flex_fields import (
    Base64ImageInput,
    Base64ImageField,
    ConsentSharingChoice,
    decode_flex_files_blob,
    encode_flex_files_blob,
    split_flex_payload,
    merge_flex_payload,
    split_options,
)


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


@pytest.mark.parametrize("value", [None, "", "test"])
def test_base64_image_input(value: str | None) -> None:
    input_ = Base64ImageInput()
    assert input_.is_initial(value) == bool(value)


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


def test_encode_and_decode_flex_files_blob_roundtrip() -> None:
    value = {"photo": "data:image/png;base64,AAA"}
    encoded = encode_flex_files_blob(value)
    assert decode_flex_files_blob(encoded) == value


def test_split_and_merge_flex_payload_with_file_fields() -> None:
    payload = {"name": "John", "photo": "data:image/png;base64,BBB"}
    checker = Mock(spec=["split_data"])
    checker.split_data.return_value = {
        "fields": {"name": "John"},
        "files": {"photo": "data:image/png;base64,BBB"},
    }
    text, files = split_flex_payload(checker, payload)

    assert text == {"name": "John"}
    assert files == {"photo": "data:image/png;base64,BBB"}

    merged = merge_flex_payload(text, encode_flex_files_blob(files))
    assert merged == payload


def test_encode_flex_files_blob_uses_binary_not_json() -> None:
    value = {"photo": b"\x89PNG\r\n", "doc": "data:application/pdf;base64,AAA"}
    encoded = encode_flex_files_blob(value)
    assert decode_flex_files_blob(encoded) == value
    with pytest.raises((json.JSONDecodeError, UnicodeDecodeError)):
        json.loads(encoded.decode("utf-8"))


def test_encode_flex_files_blob_empty_returns_none() -> None:
    assert encode_flex_files_blob({}) is None


@pytest.mark.parametrize("value", [None, b"", bytearray(), memoryview(b"")])
def test_decode_flex_files_blob_empty_returns_empty(value) -> None:
    assert decode_flex_files_blob(value) == {}


def test_decode_flex_files_blob_accepts_bytearray_and_memoryview() -> None:
    encoded = encode_flex_files_blob({"photo": "data:image/png;base64,AAA"})
    assert decode_flex_files_blob(bytearray(encoded)) == {"photo": "data:image/png;base64,AAA"}
    assert decode_flex_files_blob(memoryview(encoded)) == {"photo": "data:image/png;base64,AAA"}


def test_decode_flex_files_blob_invalid_data_returns_empty() -> None:
    assert decode_flex_files_blob(b"not-a-msgpack-or-json") == {}


def test_decode_flex_files_blob_non_dict_msgpack_returns_empty() -> None:
    assert decode_flex_files_blob(msgpack.packb([1, 2, 3], use_bin_type=True)) == {}


def test_decode_flex_files_blob_reads_legacy_json_format() -> None:
    legacy = json.dumps({"photo": "data:image/png;base64,AAA"}).encode("utf-8")
    assert decode_flex_files_blob(legacy) == {"photo": "data:image/png;base64,AAA"}


def test_decode_flex_files_blob_legacy_json_non_dict_returns_empty() -> None:
    legacy_list = json.dumps([1, 2, 3]).encode("utf-8")
    assert decode_flex_files_blob(legacy_list) == {}


def test_merge_flex_payload_skips_empty_stored_values() -> None:
    blob = encode_flex_files_blob({"photo": ""})
    assert merge_flex_payload({"name": "John"}, blob) == {"name": "John"}


def test_split_flex_payload_ignores_empty_file_values() -> None:
    checker = Mock(spec=["split_data"])
    payload = {"photo": "   ", "name": "John", "empty": "", "missing": None}
    checker.split_data.return_value = {
        "fields": {"name": "John"},
        "files": {"photo": "   ", "empty": "", "missing": None},
    }
    text, files = split_flex_payload(checker, payload)
    assert text == {"name": "John"}
    assert files == {}
