from django import forms
from django.conf import settings
from django.utils.text import slugify
from hope_flex_fields.models import FieldDefinition

from country_workspace.models import SyncLog


def create_hope_field_definitions() -> None:
    for m in settings.HH_LOOKUPS:
        n = f"HOPE HH {m}"
        FieldDefinition.objects.get_or_create(name=n, slug=slugify(n), field_type=forms.ChoiceField)
    for m in settings.IND_LOOKUPS:
        n = f"HOPE IND {m}"
        FieldDefinition.objects.get_or_create(name=n, slug=slugify(n), field_type=forms.ChoiceField)
    FieldDefinition.objects.get_or_create(
        name="HOPE IND Gender",
        slug=slugify("HOPE IND Gender"),
        attrs={"choices": [["FEMALE", "female"], ["MALE", "male"], ["UNKNOWN", "unknown"]]},
        field_type=forms.ChoiceField,
    )
    FieldDefinition.objects.get_or_create(
        name="HOPE IND Disability",
        slug=slugify("HOPE IND Disability"),
        field_type=forms.ChoiceField,
        attrs={"choices": [["NOT DISABLED", "not disabled"], ["DISABLED", "disabled"]]},
    )
    FieldDefinition.objects.get_or_create(
        name="HOPE People Type",
        slug=slugify("HOPE People Type"),
        field_type=forms.ChoiceField,
        attrs={
            "choices": [
                ["", ""],
                ["NON_BENEFICIARY", "Non Beneficiary"],
            ]
        },
    )

    SyncLog.objects.create_lookups()


def removes_hope_field_definitions() -> None:
    FieldDefinition.objects.filter(name__startswith="HOPE ").delete()
