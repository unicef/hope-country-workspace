from typing import Any
from django.db import transaction
from django import forms
from django.utils.text import slugify
from packaging.version import Version

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


_script_for_version = Version("0.1.0")

type FieldSpec = tuple[str, FieldDefinition, dict[str, Any] | None]

field_registry.register(ConsentSharingChoice)
field_registry.register(Base64ImageField)

attrs_default = lambda cls: get_kwargs_from_field_class(cls, get_common_attrs())

DEFS = {
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
    "field_relationship": {
        "name": "HOPE IND Relationship",
        "defaults": {
            "slug": slugify("HOPE IND Relationship"),
            "field_type": fqn(forms.ChoiceField),
            "attrs": {
                **attrs_default(forms.ChoiceField),
                "choices": [
                    ["RELATIONSHIP_UNKNOWN", "Unknown"],
                    ["AUNT_UNCLE", "Aunt / Uncle"],
                    ["BROTHER_SISTER", "Brother / Sister"],
                    ["COUSIN", "Cousin"],
                    ["DAUGHTERINLAW_SONINLAW", "Daughter-in-law / Son-in-law"],
                    ["GRANDDAUGHER_GRANDSON", "Granddaughter / Grandson"],
                    ["GRANDMOTHER_GRANDFATHER", "Grandmother / Grandfather"],
                    ["HEAD", "Head of household (self)"],
                    ["MOTHER_FATHER", "Mother / Father"],
                    ["MOTHERINLAW_FATHERINLAW", "Mother-in-law / Father-in-law"],
                    ["NEPHEW_NIECE", "Nephew / Niece"],
                    ["NON_BENEFICIARY", "Not a Family Member. Can only act as a recipient."],
                    ["RELATIONSHIP_OTHER", "Other"],
                    ["SISTERINLAW_BROTHERINLAW", "Sister-in-law / Brother-in-law"],
                    ["SON_DAUGHTER", "Son / Daughter"],
                    ["WIFE_HUSBAND", "Wife / Husband"],
                    ["FOSTER_CHILD", "Foster child"],
                    ["FREE_UNION", "Free union"],
                ],
            },
        },
    },
    "field_collector_role": {
        "name": "HOPE IND Collector Role",
        "defaults": {
            "slug": slugify("HOPE IND Collector Role"),
            "field_type": fqn(forms.ChoiceField),
            "attrs": {
                **attrs_default(forms.ChoiceField),
                "choices": [
                    ["NO_ROLE", "None"],
                    ["PRIMARY", "Primary collector"],
                    ["ALTERNATE", "Alternate collector"],
                ],
            },
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
    "field_photo_base64": {
        "name": Base64ImageField.__name__,
        "defaults": {
            "field_type": fqn(Base64ImageField),
            "attrs": attrs_default(Base64ImageField),
        },
    },
}


HOPE_SPECS = {
    INDIVIDUAL_CHECKER_NAME: [
        ("disability", "field_disability"),
        ("relationship", "field_relationship"),
        ("role", "field_collector_role"),
        ("photo", "field_photo_base64"),
        ("national_id_photo", "field_photo_base64"),
    ],
    HOUSEHOLD_CHECKER_NAME: [
        ("consent_sharing", "field_consent_sharing"),
    ],
    PEOPLE_CHECKER_NAME: [
        ("disability", "field_disability"),
        ("photo", "field_photo_base64"),
        ("national_id_photo", "field_photo_base64"),
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


class Scripts:
    requires = []
    operations = [(forward, backward)]
