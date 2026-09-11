from base64 import b64encode
import hashlib
import json
from typing import TYPE_CHECKING, Any, Generator, Literal

from django import forms
from django.core.files.uploadedfile import UploadedFile

from hope_flex_fields.models import DataChecker

from country_workspace.utils.flex_files import DATA_URI_FORMAT, flex_file_src

if TYPE_CHECKING:
    from country_workspace.models.base import Validable


FLEX_FILES_PREFIX = 8192  # bytes


def get_checker_fields(
    checker: DataChecker,
    with_fs_prefix: bool = False,
    include_files: bool = True,
) -> Generator[tuple[str, str], None, None]:
    for fs in checker.members.select_related("fieldset").order_by("fieldset_id", "prefix").all():
        for field in fs.fieldset.get_fields():
            if not include_files and field.is_file:
                continue
            yield (
                f"{fs.prefix if with_fs_prefix else ''}{field.name}",
                f"{fs.prefix if with_fs_prefix else ''}{(field.attrs.get('label', field.name) or field.name)}",
            )


def get_file_field_names(checker: DataChecker) -> set[str]:
    """File field names, both prefixed and bare, as callers key on either form."""
    return checker.get_file_field_names() | checker.get_file_field_names(with_prefix=False)


def get_obj_checksum(obj: "Validable") -> str:
    h = hashlib.md5()  # noqa: S324
    h.update(json.dumps(obj.flex_fields, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if obj.flex_files:
        h.update(memoryview(obj.flex_files)[:FLEX_FILES_PREFIX])
    h.update(bytes([1 if getattr(obj, "removed", False) else 0]))
    return h.hexdigest()


class FlexImageInput(forms.ClearableFileInput):
    template_name = "workspace/flex_image_widget.html"

    def is_initial(self, value: str | None) -> bool:
        # we need to override this as base method looks for url
        return bool(value)

    def get_context(self, name: str, value: Any, attrs: dict[str, Any] | None) -> dict[str, Any]:
        context = super().get_context(name, value, attrs)
        context["widget"]["image_src"] = flex_file_src(value)
        return context


class FlexImageField(forms.ImageField):
    """Image flex field whose value is a `FlexFieldFile` reference.

    Uploads are validated here but written by the save layer, which is the only
    place that has both the uploaded file and the record to attach it to.
    """

    widget = FlexImageInput

    def clean(self, data: UploadedFile | Literal[False] | None, initial: str | None = None) -> str | None:
        cleaned_data = super().clean(data, initial)
        if not cleaned_data:
            return ""
        if hasattr(cleaned_data, "read"):
            return initial or ""
        return cleaned_data


class Base64ImageInput(FlexImageInput):
    """Deprecated: superseded by `FlexImageInput`, kept for one release.

    It inherits the new rendering so that the field type swap and the data
    migration can run in any order.
    """


class Base64ImageField(forms.ImageField):
    """Deprecated: superseded by `FlexImageField`, kept for one release."""

    widget = Base64ImageInput

    def clean(self, data: UploadedFile | Literal[False] | None, initial: str | None = None) -> str | None:
        if cleaned_data := super().clean(data, initial):
            if hasattr(cleaned_data, "read"):
                content = b64encode(cleaned_data.read()).decode()
                return DATA_URI_FORMAT.format(mimetype=data.content_type, content=content)
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
