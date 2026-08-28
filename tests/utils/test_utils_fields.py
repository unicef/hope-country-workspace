import json
from types import SimpleNamespace
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
    describe_flex_file_value,
    encode_flex_files_blob,
    get_checker_fields,
    split_flex_payload,
    split_flex_storage,
    merge_flex_payload,
    split_options,
    summarize_flex_payload,
    to_storage_flex_file_value,
    to_public_flex_file_value,
    get_obj_checksum,
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


def test_base64_image_field_is_registered_on_startup() -> None:
    from hope_flex_fields.registry import field_registry

    assert field_registry.get_class(Base64ImageField) is Base64ImageField


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
    assert set(files) == {"photo"}
    assert to_public_flex_file_value(files["photo"]) == "data:image/png;base64,BBB"

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


def test_split_flex_payload_without_checker_returns_payload_as_text() -> None:
    payload = {"name": "John", "photo": "data:image/png;base64,AAA"}
    text, files = split_flex_payload(None, payload)
    assert text == payload
    assert files == {}


def test_split_flex_storage_reports_explicitly_emptied_files() -> None:
    checker = Mock(spec=["split_data"])
    checker.split_data.return_value = {
        "fields": {"name": "John"},
        "files": {"photo": "", "signature": "data:image/png;base64,QUJD"},
    }

    split = split_flex_storage(checker, {}, {"photo", "signature"})

    assert split.text_fields == {"name": "John"}
    assert set(split.file_values) == {"signature"}
    assert split.cleared_files == {"photo"}
    checker.split_data.assert_called_once_with({}, file_field_names={"photo", "signature"})


def test_describe_flex_file_value_replaces_payload_with_a_label() -> None:
    stored = to_storage_flex_file_value("data:image/png;base64,QUJD")

    described = describe_flex_file_value(stored)

    assert "QUJD" not in described
    assert described.startswith("image/png (")
    assert described == describe_flex_file_value("data:image/png;base64,QUJD")
    assert described != describe_flex_file_value("data:image/png;base64,WFla")


def test_summarize_flex_payload_describes_files_from_both_storages() -> None:
    legacy = {"name": "John", "photo": "data:image/png;base64,QUJD"}
    blob = encode_flex_files_blob({"signature": to_storage_flex_file_value("data:image/png;base64,WFla")})

    summary = summarize_flex_payload(legacy, blob, {"photo", "signature"})

    assert summary["name"] == "John"
    assert summary["photo"].startswith("image/png (")
    assert summary["signature"].startswith("image/png (")
    assert "QUJD" not in summary["photo"]


def test_get_checker_fields_skips_file_fields_and_applies_placeholder_prefix() -> None:
    checker = _checker_with_fields("national_id_%s", ["photo", "number"], file_field_names={"national_id_photo"})

    assert list(get_checker_fields(checker, with_fs_prefix=True)) == [
        ("national_id_photo", "national_id_Photo"),
        ("national_id_number", "national_id_Number"),
    ]
    assert list(get_checker_fields(checker, with_fs_prefix=True, skip_file_fields=True)) == [
        ("national_id_number", "national_id_Number"),
    ]


def _checker_with_fields(prefix: str, names: list[str], file_field_names: set[str]) -> SimpleNamespace:
    class _Members(list):
        def select_related(self, *args: str) -> "_Members":
            return self

        def order_by(self, *args: str) -> "_Members":
            return self

        def all(self) -> "_Members":
            return self

    fields = [SimpleNamespace(name=name, attrs={"label": name.capitalize()}) for name in names]
    member = SimpleNamespace(prefix=prefix, fieldset=SimpleNamespace(get_fields=lambda: fields))
    return SimpleNamespace(members=_Members([member]), get_file_field_names=lambda: file_field_names)


def test_split_flex_payload_with_checker_split() -> None:
    payload = {"name": "John", "photo": "data:image/png;base64,QUJD"}
    checker = Mock(spec=["split_data"])
    checker.split_data.return_value = {
        "fields": {"name": "John"},
        "files": {"photo": payload["photo"]},
    }
    text, files = split_flex_payload(checker, payload)
    assert text == {"name": "John"}
    assert set(files) == {"photo"}
    assert to_public_flex_file_value(files["photo"]) == payload["photo"]


@pytest.mark.parametrize("value", [b"bytes", 123, None, {"k": "v"}])
def test_to_storage_flex_file_value_non_string_passthrough(value) -> None:
    assert to_storage_flex_file_value(value) is value


def test_to_storage_flex_file_value_invalid_data_uri_passthrough() -> None:
    value = "not-a-data-uri"
    assert to_storage_flex_file_value(value) == value


def test_to_storage_flex_file_value_invalid_base64_passthrough() -> None:
    value = "data:image/png;base64,!!invalid!!"
    assert to_storage_flex_file_value(value) == value


def test_to_storage_and_to_public_roundtrip_for_data_uri() -> None:
    original = "data:image/png;base64,QUJD"
    stored = to_storage_flex_file_value(original)
    assert isinstance(stored, dict)
    assert stored.get("__bin_value__") is True
    assert stored.get("mimetype") == "image/png"
    assert stored.get("content") == b"ABC"
    assert to_public_flex_file_value(stored) == original


def test_to_public_flex_file_value_passthrough_for_invalid_shape() -> None:
    value = {"__bin_value__": True, "mimetype": "image/png", "content": "not-bytes"}
    assert to_public_flex_file_value(value) == value


def test_get_obj_checksum_uses_full_flex_files_content() -> None:
    common_prefix = b"A" * 10000
    obj1 = SimpleNamespace(flex_fields={"x": 1}, flex_files=common_prefix + b"1", removed=False)
    obj2 = SimpleNamespace(flex_fields={"x": 1}, flex_files=common_prefix + b"2", removed=False)
    assert get_obj_checksum(obj1) != get_obj_checksum(obj2)
