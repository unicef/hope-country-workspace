import hashlib
import json
from typing import TYPE_CHECKING, Any, Generator

from django import forms
from django.utils.choices import flatten_choices

import hope_flex_fields.fields
from hope_flex_fields.models import DataChecker

from country_workspace.contrib.hope.required_choice_field import ChoiceFieldWithEmptyDisplay

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


class Base64ImageField(hope_flex_fields.fields.Base64ImageField):
    """Deprecated: superseded by `hope_flex_fields.fields.FlexImageField`, kept for one release.

    Stored field definitions reference this class by its import path, so it stays
    defined here rather than being an alias of the library class.
    """


def split_options(value: str) -> list[str]:
    stripped = value.strip()

    if not stripped:
        return []

    # If there's a comma we split by comma, otherwise space is used as a separator
    for separator in (",", " "):
        if separator in stripped:
            return [s for part in value.split(separator) if (s := part.strip())]

    return [stripped]


class CaseInsensitiveChoiceMixin(forms.Field):
    """Match values against the choice keys ignoring letter case and return the key as defined."""

    choices: Any

    def _match_choice(self, value: Any) -> Any:
        if not isinstance(value, str) or not value:
            return value
        keys = [str(key) for key, __ in flatten_choices(self.choices)]
        if value in keys:
            return value
        folded = value.casefold()
        return next((key for key in keys if key.casefold() == folded), value)

    def _match_choices(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._match_choice(item) for item in value]
        return self._match_choice(value)

    def to_python(self, value: Any) -> Any:
        return self._match_choices(super().to_python(value))

    def prepare_value(self, value: Any) -> Any:
        return self._match_choices(super().prepare_value(value))


class CaseInsensitiveChoiceField(CaseInsensitiveChoiceMixin, forms.ChoiceField):
    """Choice field that accepts values in any letter case."""


class CaseInsensitiveChoiceFieldWithEmptyDisplay(CaseInsensitiveChoiceMixin, ChoiceFieldWithEmptyDisplay):
    """Choice field with an explicit empty option that accepts values in any letter case."""


class CustomMultipleChoiceField(forms.MultipleChoiceField):
    def to_python(self, value: str | list[str] | None) -> list[str]:
        if isinstance(value, str):
            return split_options(value)

        return super().to_python(value)

    def prepare_value(self, value: str | list[str] | None) -> list[str]:
        if isinstance(value, str):
            return split_options(value)

        return super().prepare_value(value)


class ConsentSharingChoice(CaseInsensitiveChoiceMixin, CustomMultipleChoiceField):
    """Consent sharing multiple choice field."""


class ObservedDisabilityChoice(CaseInsensitiveChoiceMixin, CustomMultipleChoiceField):
    """Observed Disability multiple choice field."""
