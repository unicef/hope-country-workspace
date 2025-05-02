from typing import Any
from packaging.version import Version
from django import forms
from django.db import transaction
from django.utils.text import slugify

from hope_flex_fields.models import FieldDefinition, Fieldset
from country_workspace.contrib.hope.constants import INDIVIDUAL_CHECKER_NAME

_script_for_version = Version("0.1.0")

FIELD_DEFS: dict[str, dict[str, Any]] = {
    "HOPE IND Disability": {
        "choices": [("NOT DISABLED", "not disabled"), ("DISABLED", "disabled")],
        "field_name": "disability",
        "label": "Disability",
    },
    "HOPE IND Gender": {
        "choices": [("FEMALE", "female"), ("MALE", "male"), ("UNKNOWN", "unknown")],
        "field_name": "gender",
        "label": "Gender",
    },
}


def forward() -> None:
    with transaction.atomic():
        field_defs = {}
        for name, config in FIELD_DEFS.items():
            field_def, __ = FieldDefinition.objects.get_or_create(
                name=name,
                defaults={
                    "slug": slugify(name),
                    "field_type": forms.ChoiceField,
                    "attrs": {"choices": config["choices"]},
                },
            )
            field_defs[config["field_name"]] = field_def

        fs, __ = Fieldset.objects.get_or_create(name=INDIVIDUAL_CHECKER_NAME)
        for field_name, field_def in field_defs.items():
            fs.fields.get_or_create(
                name=field_name,
                definition=field_def,
                defaults={"attrs": {"label": FIELD_DEFS[field_def.name]["label"]}},
            )


def backward() -> None:
    FieldDefinition.objects.filter(name__in=FIELD_DEFS.keys()).delete()


class Scripts:
    requires = []
    operations = [(forward, backward)]
