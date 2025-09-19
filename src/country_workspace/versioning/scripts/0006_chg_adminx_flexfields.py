from typing import Any
from packaging.version import Version
from django import forms
from django.db import transaction

from hope_flex_fields.models import FieldDefinition, Fieldset
from country_workspace.contrib.hope.constants import HOUSEHOLD_CHECKER_NAME

_script_for_version = Version("0.1.0")


field_defs: dict[str, dict[str, Any]] = {
    "admin1": {"name": "Admin1Choice"},
    "admin2": {"name": "Admin2Choice"},
    "admin3": {"name": "Admin3Choice"},
    "admin4": {"name": "Admin4Choice"},
}


def forward() -> None:
    with transaction.atomic():
        for key, lookup_kwargs in field_defs.items():
            field_defs[key] = FieldDefinition.objects.get(**lookup_kwargs)
        specs = [(name, field_defs[name], {}) for name in field_defs]
        fs, __ = Fieldset.objects.get_or_create(name=HOUSEHOLD_CHECKER_NAME)
        for f_name, f_def, f_attrs in specs:
            fs.fields.update_or_create(
                name=f_name,
                defaults={
                    "definition": f_def,
                    "attrs": f_attrs or {},
                },
            )


def backward() -> None:
    with transaction.atomic():
        if not Fieldset.objects.filter(name=HOUSEHOLD_CHECKER_NAME).exists():
            return
        fs = Fieldset.objects.get(name=HOUSEHOLD_CHECKER_NAME)
        for f_name in field_defs:
            fs.fields.update_or_create(
                name=f_name,
                defaults={
                    "definition": FieldDefinition.objects.get_or_create(name=f_name, field_type=forms.CharField)[0],
                    "attrs": {},
                },
            )


class Scripts:
    requires = []
    operations = [(forward, backward)]
