import re
from typing import TYPE_CHECKING, Any

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
            return value
        except (ValueError, TypeError):
            raise forms.ValidationError("Invalid regex")


class RegexUpdateForm(BaseActionForm):
    field = forms.ChoiceField(choices=[])
    regex = RegexFormField()
    subst = forms.CharField()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        choices = list(get_checker_fields(checker))
        choices.sort()
        self.fields["field"].choices = choices


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
            old_value = record.flex_fields.get(field_name, "")
            new_value = config["regex"].sub(config["subst"], old_value, 1)
            record.flex_fields[field_name] = new_value
            if save:
                record.save()
            else:
                ret.append((record.pk, old_value, new_value))
    return ret
