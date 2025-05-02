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
        name="HOPE HH ResidenceStatus",
        slug=slugify("HOPE HH ResidenceStatus"),
        field_type=forms.ChoiceField,
        attrs={
            "choices": [
                ["", ""],
                ["IDP", "Displaced  |  Internally Displaced People"],
                ["REFUGEE", "Displaced  |  Refugee / Asylum Seeker"],
                ["OTHERS_OF_CONCERN", "Displaced  |  Others of Concern"],
                ["HOST", "Non-displaced  |   Host"],
                ["NON_HOST", "Non-displaced  |   Non-host"],
                ["RETURNEE", "Displaced  |   Returnee"],
            ]
        },
    )
    FieldDefinition.objects.get_or_create(
        name="HOPE IND Relationship",
        slug=slugify("HOPE IND Relationship"),
        field_type=forms.ChoiceField,
        attrs={
            "choices": [
                ["RELATIONSHIP_UNKNOWN", "Unknown"],
                ["AUNT_UNCLE", "Aunt / Uncle"],
                ["BROTHER_SISTER", "Brother / Sister"],
                ["COUSIN", "Cousin"],
                ["DAUGHTERINLAW_SONINLAW", "Daughter-in-law / Son-in-law"],
                ["GRANDDAUGHTER_GRANDSON", "Granddaughter / Grandson"],
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
