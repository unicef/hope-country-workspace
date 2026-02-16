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

    RegexRule = tuple[str, str]
    RegexRules = list[RegexRule]


class RegexFormField(forms.CharField):
    def clean(self, value: Any) -> Any:
        super().clean(value)
        try:
            re.compile(value)
        except (ValueError, TypeError, re.error):
            raise forms.ValidationError("Invalid regex")
        else:
            return value


class RegexUpdateForm(BaseActionForm):
    field = forms.ChoiceField(choices=[])
    regex = RegexFormField()
    subst = forms.CharField()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        choices = list(get_checker_fields(checker, with_fs_prefix=True))
        self.fields["field"].choices = choices


class UpdateResult(NamedTuple):
    original: Any
    updated: Any
    data_type: str

def update_json(json: dict[str, Any], key: str, pattern: re.Pattern[str], replacement: str) -> UpdateResult:
    original_value = json.get(key)
    if isinstance(original_value, int):
        data_type = "int"
    elif isinstance(original_value, float):
        data_type = "float"
    else:
        data_type = "str"

    updated_value = pattern.sub(replacement, str(original_value), 1)
    json[key] = updated_value

    return UpdateResult(original_value, updated_value, data_type)


def update_checksum(records: "QuerySet[Beneficiary]", initial_fields: set[str]) -> Iterable[str]:
    """Update checksum for all records in the queryset."""
    fields = initial_fields.copy()
    for record in records:
        if update_fields := record.update_checksum(initial_fields):
            fields.update(update_fields)
    return fields


def regex_update_impl(
    records: "QuerySet[Beneficiary]",
    config: dict[str, Any],
    save: bool = True,
) -> list[tuple[str, str, str]]:
    if isinstance(config["regex"], str):
        config["regex"] = re.compile(config["regex"])

    field_name = config["field"]
    ret = []
    with transaction.atomic():
        for record in records:
            result = update_json(record.flex_fields, field_name, config["regex"], config["subst"])
            ret.append((record.id, result.original, result.updated))

        if save:
            fields = update_checksum(records, {"flex_fields"})
            records.bulk_update(records, fields, batch_size=1000)

    return ret
