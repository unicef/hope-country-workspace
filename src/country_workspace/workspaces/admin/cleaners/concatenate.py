import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, NamedTuple

from django import forms
from django.db import transaction

from country_workspace.utils.flex_fields import get_checker_fields

from .base import BaseActionForm

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from hope_flex_fields.models import DataChecker

    from country_workspace.types import Beneficiary


class ConcatenateFieldForm(BaseActionForm):
    destination_field = forms.ChoiceField(choices=[], help_text="Field to update with concatenated value")
    pattern = forms.CharField(
        help_text='Pattern with field placeholders, e.g., "{first_name} {middle_name} {last_name}"'
    )
    replace_only_empty = forms.BooleanField(
        required=False,
        initial=False,
        help_text="Only update the destination field if it is currently empty",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        self.fields["destination_field"].choices = list(
            get_checker_fields(checker, with_fs_prefix=True, skip_file_fields=True)
        )

    def clean_pattern(self) -> str:
        pattern = self.cleaned_data.get("pattern", "")
        # Validate that pattern contains at least one field placeholder
        if not re.search(r"\{[^}]+\}", pattern):
            raise forms.ValidationError("Pattern must contain at least one field placeholder like {field_name}")
        return pattern


class ConcatenateResult(NamedTuple):
    record_id: str
    original: Any
    updated: str


def normalize_whitespace(value: str) -> str:
    """Trim value and remove multiple spaces."""
    if not isinstance(value, str):
        return value
    # Replace multiple spaces with single space and strip
    return re.sub(r"\s+", " ", value.strip())


def extract_field_names(pattern: str) -> list[str]:
    """Extract field names from pattern like {field_name}."""
    return re.findall(r"\{([^}]+)\}", pattern)


def concatenate_value(record: "Beneficiary", pattern: str) -> str:
    """Concatenate fields based on pattern."""
    field_names = extract_field_names(pattern)
    flex_fields = record.flex_fields or {}

    # Build the result by replacing placeholders
    result = pattern
    for field_name in field_names:
        # Get value from flex_fields, default to empty string if not found
        value = flex_fields.get(field_name, "")
        if value is None:
            value = ""
        else:
            value = str(value)
        # Replace placeholder with actual value
        result = result.replace(f"{{{field_name}}}", value)

    return normalize_whitespace(result)


def update_checksum(records: "QuerySet[Beneficiary]", initial_fields: set[str]) -> Iterable[str]:
    """Update checksum for all records in the queryset."""
    fields = initial_fields.copy()
    for record in records:
        if update_fields := record.update_checksum(initial_fields):
            fields.update(update_fields)
    return fields


def concatenate_field_impl(
    records: "QuerySet[Beneficiary]",
    config: dict[str, Any],
    save: bool = True,
) -> list[ConcatenateResult]:
    destination_field = config["destination_field"]
    pattern = config["pattern"]
    replace_only_empty = config.get("replace_only_empty", False)

    ret: list[ConcatenateResult] = []
    records_to_save: list["Beneficiary"] = []
    with transaction.atomic():
        for record in records:
            flex_fields = record.flex_fields or {}
            original_value = flex_fields.get(destination_field)

            # Check if we should skip (only replace empty values)
            if replace_only_empty and original_value:
                ret.append(ConcatenateResult(record.id, original_value, str(original_value)))
                continue

            # Concatenate the value
            concatenated_value = concatenate_value(record, pattern)

            # Update the flex_fields
            if flex_fields is None:
                flex_fields = {}
            flex_fields[destination_field] = concatenated_value
            record.flex_fields = flex_fields

            ret.append(ConcatenateResult(record.id, original_value, concatenated_value))

            if save:
                records_to_save.append(record)

        if save and records_to_save:
            fields = update_checksum(records_to_save, {"flex_fields"})
            records.model.objects.bulk_update(records_to_save, list(fields), batch_size=1000)

    return ret
