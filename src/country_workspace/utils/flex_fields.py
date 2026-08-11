from base64 import b64decode, b64encode
import binascii
import hashlib
import json
import re
from typing import TYPE_CHECKING, Any, Generator, Literal

from django import forms
from django.core.files.uploadedfile import UploadedFile
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
    """Fallback decoder for blobs stored by the previous JSON-based format."""
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def decode_flex_files_blob(value: bytes | memoryview | bytearray | None) -> dict[str, Any]:
    """Decode ``flex_files`` blob into ``{field_name: content}``.

    Primary format is msgpack. Legacy json blobs are still readable.
    """
    if not value:
        return {}
    raw = bytes(value) if isinstance(value, memoryview | bytearray) else value
    try:
        parsed = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    except (msgpack.ExtraData, msgpack.FormatError, msgpack.StackError, ValueError, TypeError):
        parsed = _decode_legacy_json_blob(raw)
    return parsed if isinstance(parsed, dict) else {}


def encode_flex_files_blob(value: dict[str, Any]) -> bytes | None:
    """Encode a ``{field_name: content}`` mapping to msgpack bytes."""
    if not value:
        return None
    return msgpack.packb(dict(sorted(value.items())), use_bin_type=True)


def to_storage_flex_file_value(value: Any) -> Any:
    """Convert external file value to compact binary storage representation."""
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
    """Convert internal storage representation to external/public value."""
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
    """Overlay stored file values on top of the text fields.

    The blob only ever holds file-typed keys, so no field-name filtering (and
    therefore no checker lookup) is needed here.
    """
    merged = dict(flex_fields or {})
    merged.update(
        {
            field_name: public_value
            for field_name, value in decode_flex_files_blob(flex_files).items()
            if (public_value := to_public_flex_file_value(value))
        }
    )
    return merged


def split_flex_payload(
    checker: DataChecker | None,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if checker is None:
        return dict(payload), {}
    split = checker.split_data(payload)
    text_fields = dict(split.get("fields", {}))
    raw_file_values = dict(split.get("files", {}))

    file_values = {
        key: to_storage_flex_file_value(value)
        for key, value in raw_file_values.items()
        if value not in (None, "") and not (isinstance(value, str) and not value.strip())
    }
    return text_fields, file_values


def get_checker_fields(checker: DataChecker, with_fs_prefix: bool = False) -> Generator[tuple[str, str], None, None]:
    for fs in checker.members.select_related("fieldset").order_by("fieldset_id", "prefix").all():
        for field in fs.fieldset.get_fields():
            yield (
                f"{fs.prefix if with_fs_prefix else ''}{field.name}",
                f"{fs.prefix if with_fs_prefix else ''}{(field.attrs.get('label', field.name) or field.name)}",
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
