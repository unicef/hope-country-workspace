from typing import Final, Any
from packaging.version import Version
from django.db import transaction
from django import forms

from hope_flex_fields.models import FieldDefinition, Fieldset
from hope_flex_fields.utils import get_kwargs_from_field_class, get_common_attrs

from country_workspace.contrib.hope.constants import INDIVIDUAL_CHECKER_NAME, PEOPLE_CHECKER_NAME

_script_for_version = Version("0.1.0")


attrs_default = lambda cls: get_kwargs_from_field_class(cls, get_common_attrs())

FD: Final[dict[str, Any]] = {
    "old_name": "HOPE IND Gender",
    "new_name": "HOPE IND Sex",
}

FS: Final[dict[str, Any]] = {
    "old_field_name": "gender",
    "new_field_name": "sex",
    "affected_fieldsets": [INDIVIDUAL_CHECKER_NAME, PEOPLE_CHECKER_NAME],
    "field_attrs": attrs_default(forms.ChoiceField),
}


def _update_field_definition_and_fieldsets(fd: tuple[str, str], fs: tuple[str, str]) -> None:
    old_name, new_name = fd
    old_field, new_field = fs

    with transaction.atomic():
        field_def_qs = FieldDefinition.objects.filter(name=old_name)
        if not field_def_qs.exists():
            return

        field_def_qs.update(name=new_name)
        field_def = FieldDefinition.objects.get(name=new_name)

        for checker_name in FS["affected_fieldsets"]:
            fieldset, _ = Fieldset.objects.get_or_create(name=checker_name)
            fieldset.fields.filter(name=old_field).delete()
            fieldset.fields.update_or_create(
                name=new_field,
                defaults={
                    "definition": field_def,
                    "attrs": FS["field_attrs"],
                },
            )


def forward() -> None:
    _update_field_definition_and_fieldsets(
        fd=(FD["old_name"], FD["new_name"]), fs=(FS["old_field_name"], FS["new_field_name"])
    )


def backward() -> None:
    _update_field_definition_and_fieldsets(
        fd=(FD["new_name"], FD["old_name"]), fs=(FS["new_field_name"], FS["old_field_name"])
    )


class Scripts:
    requires = []
    operations = [(forward, backward)]
