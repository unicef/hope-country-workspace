from base64 import b64decode, b64encode
import binascii
from contextlib import suppress
import hashlib
import json
import re
from typing import TYPE_CHECKING, Any, Generator, Literal, NamedTuple

from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.template.defaultfilters import filesizeformat
import msgpack

from hope_flex_fields.models import DataChecker

from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT

if TYPE_CHECKING:
    from country_workspace.models.base import Validable

_DATA_URI_PATTERN = re.compile(r"^data:(?P<mimetype>[^;]+);base64,(?P<content>.+)$")
_BIN_VALUE_KEY = "__bin_value__"
_BIN_MIMETYPE_KEY = "mimetype"
_BIN_CONTENT_KEY = "content"


def _decode_legacy_json_blob(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def decode_flex_files_blob(value: bytes | memoryview | bytearray | None) -> dict[str, Any]:
    if not value:
        return {}
    raw = bytes(value) if isinstance(value, memoryview | bytearray) else value
    try:
        parsed = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    except (msgpack.ExtraData, msgpack.FormatError, msgpack.StackError, ValueError, TypeError):
        parsed = _decode_legacy_json_blob(raw)
    return parsed if isinstance(parsed, dict) else {}


def encode_flex_files_blob(value: dict[str, Any]) -> bytes | None:
    if not value:
        return None
    return msgpack.packb(dict(sorted(value.items())), use_bin_type=True)


def to_storage_flex_file_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    match = _DATA_URI_PATTERN.fullmatch(value.strip())
    if not match:
        return value
    try:
        binary = b64decode(match.group("content"), validate=True)
    except (binascii.Error, ValueError):
        return value
    return {
        _BIN_VALUE_KEY: True,
        _BIN_MIMETYPE_KEY: match.group("mimetype"),
        _BIN_CONTENT_KEY: binary,
    }


def to_public_flex_file_value(value: Any) -> Any:
    if not isinstance(value, dict) or not value.get(_BIN_VALUE_KEY):
        return value
    mimetype = value.get(_BIN_MIMETYPE_KEY)
    content = value.get(_BIN_CONTENT_KEY)
    if not isinstance(mimetype, str) or not isinstance(content, (bytes | bytearray | memoryview)):
        return value
    encoded = b64encode(bytes(content)).decode()
    return VALUE_FORMAT.format(mimetype=mimetype, content=encoded)


def merge_flex_payload(
    flex_fields: dict[str, Any] | None,
    flex_files: bytes | memoryview | bytearray | None,
) -> dict[str, Any]:
    merged = dict(flex_fields or {})
    for field_name, value in decode_flex_files_blob(flex_files).items():
        if field_name in merged:
            continue
        if public_value := to_public_flex_file_value(value):
            merged[field_name] = public_value
    return merged


def is_blank_flex_file_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str | bytes | bytearray):
        return not value.strip()
    return False


class FlexStorageSplit(NamedTuple):
    text_fields: dict[str, Any]
    file_values: dict[str, Any]
    cleared_files: set[str]


def split_flex_storage(
    checker: DataChecker | None,
    payload: dict[str, Any],
    file_field_names: set[str] | None = None,
) -> FlexStorageSplit:
    if checker is None:
        return FlexStorageSplit(dict(payload), {}, set())

    split = checker.split_data(payload, file_field_names=file_field_names)
    file_values: dict[str, Any] = {}
    cleared_files: set[str] = set()
    for key, value in split.get("files", {}).items():
        if is_blank_flex_file_value(value):
            cleared_files.add(key)
        else:
            file_values[key] = to_storage_flex_file_value(value)
    return FlexStorageSplit(dict(split.get("fields", {})), file_values, cleared_files)


def split_flex_payload(
    checker: DataChecker | None,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    text_fields, file_values, __ = split_flex_storage(checker, payload)
    return text_fields, file_values


def describe_flex_file_value(value: Any) -> str:
    mimetype: str | None = None
    content: bytes | None = None
    if isinstance(value, dict) and value.get(_BIN_VALUE_KEY):
        mimetype = value.get(_BIN_MIMETYPE_KEY)
        raw = value.get(_BIN_CONTENT_KEY)
        if isinstance(raw, bytes | bytearray | memoryview):
            content = bytes(raw)
    elif isinstance(value, str) and (match := _DATA_URI_PATTERN.fullmatch(value.strip())):
        mimetype = match.group("mimetype")
        with suppress(binascii.Error, ValueError):
            content = b64decode(match.group("content"), validate=True)

    if content is None:
        return str(value)
    digest = hashlib.md5(content).hexdigest()[:8]  # noqa: S324
    return f"{mimetype or 'file'} ({filesizeformat(len(content))}, {digest})"


def summarize_flex_payload(
    flex_fields: dict[str, Any] | None,
    flex_files: bytes | memoryview | bytearray | None,
    file_field_names: set[str],
) -> dict[str, Any]:
    merged = dict(flex_fields or {})
    for field_name, value in decode_flex_files_blob(flex_files).items():
        merged.setdefault(field_name, value)
    return {
        field_name: describe_flex_file_value(value) if field_name in file_field_names and value else value
        for field_name, value in merged.items()
    }


def apply_field_prefix(prefix: str, name: str) -> str:
    if not prefix:
        return name
    return prefix % name if "%s" in prefix else f"{prefix}{name}"


def get_checker_fields(
    checker: DataChecker,
    with_fs_prefix: bool = False,
    skip_file_fields: bool = False,
) -> Generator[tuple[str, str], None, None]:
    file_field_names = checker.get_file_field_names() if skip_file_fields else set()
    for fs in checker.members.select_related("fieldset").order_by("fieldset_id", "prefix").all():
        prefix = fs.prefix or ""
        for field in fs.fieldset.get_fields():
            if skip_file_fields and apply_field_prefix(prefix, field.name) in file_field_names:
                continue
            label = field.attrs.get("label", field.name) or field.name
            yield (
                apply_field_prefix(prefix if with_fs_prefix else "", field.name),
                apply_field_prefix(prefix if with_fs_prefix else "", label),
            )


def get_obj_checksum(obj: "Validable") -> str:
    h = hashlib.md5()  # noqa: S324
    h.update(json.dumps(obj.flex_fields, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if obj.flex_files:
        h.update(memoryview(obj.flex_files))
    h.update(bytes([1 if getattr(obj, "removed", False) else 0]))
    return h.hexdigest()


class Base64ImageInput(forms.ClearableFileInput):
    template_name = "workspace/base64_image_widget.html"

    def is_initial(self, value: str | None) -> bool:
        # we need to override this as base method looks for url
        return bool(value)


class Base64ImageField(forms.ImageField):
    widget = Base64ImageInput

    def clean(self, data: UploadedFile | Literal[False] | None, initial: str | None = None) -> str | None:
        if cleaned_data := super().clean(data, initial):
            if hasattr(cleaned_data, "read"):
                content = b64encode(cleaned_data.read()).decode()
                return VALUE_FORMAT.format(mimetype=data.content_type, content=content)
            return cleaned_data

        return ""


def split_options(value: str) -> list[str]:
    stripped = value.strip()

    if not stripped:
        return []

    # If there's a comma we split by comma, otherwise space is used as a separator
    for separator in (",", " "):
        if separator in stripped:
            return [s for part in value.split(separator) if (s := part.strip())]

    return [stripped]


class CustomMultipleChoiceField(forms.MultipleChoiceField):
    def to_python(self, value: str | list[str] | None) -> list[str]:
        if isinstance(value, str):
            return split_options(value)

        return super().to_python(value)

    def prepare_value(self, value: str | list[str] | None) -> list[str]:
        if isinstance(value, str):
            return split_options(value)

        return super().prepare_value(value)


class ConsentSharingChoice(CustomMultipleChoiceField):
    """Consent sharing multiple choice field."""


class ObservedDisabilityChoice(CustomMultipleChoiceField):
    """Observed Disability multiple choice field."""
