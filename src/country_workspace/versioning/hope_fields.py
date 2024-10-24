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
        attrs={"choices": [["FEMALE", "FEMALE"], ["MALE", "MALE"], ["UNKNOWN", "UNKNOWN"]]},
        field_type=forms.ChoiceField,
    )
    FieldDefinition.objects.get_or_create(
        name="HOPE IND Disability",
        slug=slugify("HOPE IND Disability"),
        field_type=forms.ChoiceField,
        attrs={"choices": [["not disabled", "not disabled"], ["disabled", "disabled"]]},
    )

    SyncLog.objects.create_lookups()


def removes_hope_field_definitions() -> None:
    FieldDefinition.objects.filter(name__startswith="HOPE ").delete()
