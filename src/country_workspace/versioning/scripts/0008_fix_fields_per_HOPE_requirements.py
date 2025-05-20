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

_script_for_version = Version("0.1.0")

type FieldSpec = tuple[str, FieldDefinition, dict[str, Any] | None]

DEFS = {
    "field_disability": {
        "name": "HOPE IND Disability",
        "defaults": {
            "slug": slugify("HOPE IND Disability"),
            "field_type": forms.ChoiceField,
            "attrs": {
                "choices": [
                    ["not disabled", "not disabled"],
                    ["disabled", "disabled"],
                ]
            },
        },
    },
    "field_relationship": {
        "name": "HOPE Relationship",
        "defaults": {
            "slug": slugify("HOPE IND Relationship"),
            "field_type": forms.ChoiceField,
            "attrs": {
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
                ]
            },
        },
    },
    "field_consent_sharing": {
        "name": "HOPE HH Consent Sharing",
        "defaults": {
            "slug": slugify("HOPE HH Consent Sharing"),
            "field_type": forms.ChoiceField,
            "attrs": {
                "choices": [
                    ["", "None"],
                    ["GOVERNMENT_PARTNER", "Government partner"],
                    ["HUMANITARIAN_PARTNER", "Humanitarian partner"],
                    ["PRIVATE_PARTNER", "Private partner"],
                    ["UNICEF", "UNICEF"],
                ]
            },
        },
    },
}

HOPE_SPECS = {
    INDIVIDUAL_CHECKER_NAME: [
        ("disability", "field_disability"),
        ("relationship", "field_relationship"),
    ],
    HOUSEHOLD_CHECKER_NAME: [
        ("consent_sharing", "field_consent_sharing"),
    ],
    PEOPLE_CHECKER_NAME: [
        ("disability", "field_disability"),
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

                field_def_name = DEFS[def_key]["name"]
                fd_qs = FieldDefinition.objects.filter(name=field_def_name)
                if fd_qs.exists():
                    still_used = FlexField.objects.filter(definition__name=field_def_name).exists()
                    if not still_used:
                        fd_qs.delete()


class Scripts:
    requires = []
    operations = [(forward, backward)]
