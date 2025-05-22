from typing import Any
from django.db import transaction
from django import forms
from django.utils.text import slugify
from packaging.version import Version
from django.contrib.contenttypes.models import ContentType

from hope_flex_fields.models import FieldDefinition, Fieldset, DataChecker, FlexField
from country_workspace.contrib.hope.constants import (
    INDIVIDUAL_CHECKER_NAME,
    HOUSEHOLD_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)
from country_workspace.utils.flex_fields import ConsentSharingChoice, Base64ImageField

from concurrency.utils import fqn
from hope_flex_fields.registry import field_registry
from hope_flex_fields.utils import get_kwargs_from_field_class, get_common_attrs
from country_workspace.models import SyncLog


_script_for_version = Version("0.1.0")

type FieldSpec = tuple[str, FieldDefinition, dict[str, Any] | None]

field_registry.register(ConsentSharingChoice)
field_registry.register(Base64ImageField)

attrs_default = lambda cls: get_kwargs_from_field_class(cls, get_common_attrs())

DEFS = {
    "field_photo_base64": {
        "name": Base64ImageField.__name__,
        "defaults": {
            "field_type": fqn(Base64ImageField),
            "attrs": attrs_default(Base64ImageField),
        },
    },
    "field_consent_sharing": {
        "name": "HOPE HH Consent Sharing",
        "defaults": {
            "slug": slugify("HOPE HH Consent Sharing"),
            "field_type": fqn(ConsentSharingChoice),
            "attrs": {
                **attrs_default(ConsentSharingChoice),
                "choices": [
                    ["", "None"],
                    ["GOVERNMENT_PARTNER", "Government partner"],
                    ["HUMANITARIAN_PARTNER", "Humanitarian partner"],
                    ["PRIVATE_PARTNER", "Private partner"],
                    ["UNICEF", "UNICEF"],
                ],
            },
        },
    },
    "field_disability": {
        "name": "HOPE IND Disability",
        "defaults": {
            "slug": slugify("HOPE IND Disability"),
            "field_type": fqn(forms.ChoiceField),
            "attrs": {
                **attrs_default(forms.ChoiceField),
                "choices": [
                    ["not disabled", "not disabled"],
                    ["disabled", "disabled"],
                ],
            },
        },
    },
    "field_gender": {
        "name": "HOPE IND Gender",
        "defaults": {
            "slug": slugify("HOPE IND Gender"),
            "field_type": fqn(forms.ChoiceField),
            "attrs": attrs_default(forms.ChoiceField),
        },
    },
}

HOPE_SPECS = {
    INDIVIDUAL_CHECKER_NAME: [
        ("disability", "field_disability"),
        ("photo", "field_photo_base64"),
        ("gender", "field_gender"),
    ],
    HOUSEHOLD_CHECKER_NAME: [
        ("consent_sharing", "field_consent_sharing"),
    ],
    PEOPLE_CHECKER_NAME: [
        ("disability", "field_disability"),
        ("photo", "field_photo_base64"),
        ("gender", "field_gender"),
    ],
}


def forward() -> None:
    for checker_name, specs in HOPE_SPECS.items():
        with transaction.atomic():
            dc, _ = DataChecker.objects.get_or_create(name=checker_name)
            fs, _ = Fieldset.objects.get_or_create(name=checker_name)

            for field_name, def_key in specs:
                fd, _ = FieldDefinition.objects.update_or_create(**DEFS[def_key])
                fs.fields.update_or_create(
                    name=field_name,
                    defaults={
                        "definition": fd,
                        "attrs": DEFS[def_key]["defaults"].get("attrs", {}),
                    },
                )
            dc.fieldsets.set([fs])
    _create_lookup_for_gender_field()
    SyncLog.objects.create_lookups()
    SyncLog.objects.refresh()


def backward() -> None:
    for checker_name, specs in HOPE_SPECS.items():
        with transaction.atomic():
            try:
                fs = Fieldset.objects.get(name=checker_name)
            except Fieldset.DoesNotExist:
                continue

            for field_name, def_key in specs:
                fs.fields.filter(name=field_name).delete()

                name = DEFS[def_key]["name"]
                qs = FieldDefinition.objects.filter(name=name)
                if qs.exists() and not FlexField.objects.filter(definition__name=name).exists():
                    qs.delete()


def _create_lookup_for_gender_field() -> dict[str, Any]:
    SyncLog.objects.get_or_create(
        content_type=ContentType.objects.get_for_model(FieldDefinition),
        object_id=FieldDefinition.objects.get(name="HOPE IND Gender").pk,
        data={"remote_url": "lookups/sex"},
    )


class Scripts:
    requires = []
    operations = [(forward, backward)]
