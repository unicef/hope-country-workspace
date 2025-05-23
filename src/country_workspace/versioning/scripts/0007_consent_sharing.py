from django import forms

from hope_flex_fields.models import Fieldset, FieldDefinition, FlexField
from packaging.version import Version

from country_workspace.contrib.hope.constants import HOUSEHOLD_CHECKER_NAME

_script_for_version = Version("0.1.0")

CONSENT_SHARING = "consent_sharing"


def forward() -> None:
    household_fieldset = Fieldset.objects.get(name=HOUSEHOLD_CHECKER_NAME)
    household_fieldset.fields.create(
        name=CONSENT_SHARING,
        definition=FieldDefinition.objects.get(field_type=forms.CharField),
        attrs={},
    )


def backward() -> None:
    FlexField.objects.filter(name=CONSENT_SHARING).delete()


class Scripts:
    requires = []
    operations = [(forward, backward)]
