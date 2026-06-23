from base64 import b64encode
import hashlib
import json
from typing import TYPE_CHECKING, Any, Generator, Literal

from django import forms
from django.core.files.uploadedfile import UploadedFile

from hope_flex_fields.models import DataChecker

from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT

if TYPE_CHECKING:
    from country_workspace.models.base import Validable


FLEX_FILES_PREFIX = 8192  # bytes


def decode_flex_files_blob(value: bytes | memoryview | bytearray | None) -> dict[str, str]:
    if not value:
        return {}
    raw = bytes(value) if isinstance(value, memoryview | bytearray) else value
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def encode_flex_files_blob(value: dict[str, str]) -> bytes | None:
    if not value:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def get_checker_file_fields(checker: DataChecker | None) -> set[str]:
    if checker is None:
        return set()
    try:
        form = checker.get_form()()
    except Exception:  # noqa: BLE001
        return set()
    return {name for name, field in form.fields.items() if isinstance(field, forms.FileField)}


def merge_flex_payload(
    flex_fields: dict[str, Any] | None,
    flex_files: bytes | memoryview | bytearray | None,
    file_fields: set[str],
) -> dict[str, Any]:
    merged = dict(flex_fields or {})
    files_map = decode_flex_files_blob(flex_files)
    for field_name in file_fields:
        if value := files_map.get(field_name):
            merged[field_name] = value
    return merged


def split_flex_payload(payload: dict[str, Any], file_fields: set[str]) -> tuple[dict[str, Any], dict[str, str]]:
    text_fields: dict[str, Any] = {}
    file_values: dict[str, str] = {}
    for key, value in payload.items():
        if key not in file_fields:
            text_fields[key] = value
            continue
        if isinstance(value, str) and value.strip():
            file_values[key] = value
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
        h.update(memoryview(obj.flex_files)[:FLEX_FILES_PREFIX])
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
