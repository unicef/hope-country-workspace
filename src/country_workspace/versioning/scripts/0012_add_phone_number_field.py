from concurrency.utils import fqn
from hope_flex_fields.models import FieldDefinition
from hope_flex_fields.registry import field_registry
from hope_flex_fields.utils import get_kwargs_from_field_class, get_common_attrs
from packaging.version import Version

from country_workspace.contrib.hope.phone_numbers import PhoneNumberField

_script_for_version = Version("0.1.0")

PHONE_NUMBER_FIELD = "phone_number"


def forward() -> None:
    field_registry.register(PhoneNumberField)
    FieldDefinition.objects.get_or_create(
        name=PhoneNumberField.__name__,
        field_type=fqn(PhoneNumberField),
        defaults={"attrs": get_kwargs_from_field_class(PhoneNumberField, get_common_attrs())},
    )


def backward() -> None:
    FieldDefinition.objects.filter(
        name=PhoneNumberField.__name__,
        field_type=fqn(PhoneNumberField),
    ).delete()


class Scripts:
    requires = []
    operations = [(forward, backward)]
