from base64 import b64encode
import hashlib
import json
from typing import TYPE_CHECKING, Generator

from django import forms
from django.core.files.uploadedfile import UploadedFile

from hope_flex_fields.models import DataChecker

from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT

if TYPE_CHECKING:
    from country_workspace.models.base import Validable


def get_checker_fields(checker: DataChecker) -> Generator[tuple[str, str], None, None]:
    for fs in checker.members.select_related("fieldset").all():
        for field in fs.fieldset.get_fields():
            yield field.name, (field.attrs.get("label", field.name) or field.name)


def get_obj_checksum(obj: "Validable") -> str:
    h = hashlib.new("md5")  # noqa: S324
    data = json.dumps(obj.flex_fields, sort_keys=True).encode("utf-8")
    h.update(data)
    if obj.flex_files:
        h.update(obj.flex_files[:8192])  # is this enough ?
    return h.hexdigest()


class Base64ImageInput(forms.ClearableFileInput):
    template_name = "workspace/base64_image_widget.html"

    def is_initial(self, value: str | None) -> bool:
        # we need to override this as base method looks for url
        return bool(value)


class Base64ImageField(forms.ImageField):
    widget = Base64ImageInput

    def clean(self, data: UploadedFile, initial: str | None = None) -> str | None:
        if cleaned_data := super().clean(data, initial):
            content = b64encode(cleaned_data.read()).decode()
            return VALUE_FORMAT.format(mimetype=data.content_type, content=content)

        # if we return cleaned_data here, False will be stored, so we return None explicitly
        return None
