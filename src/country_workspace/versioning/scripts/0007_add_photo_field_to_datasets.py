from packaging.version import Version
from concurrency.utils import fqn
from hope_flex_fields.models import FieldDefinition, Fieldset
from country_workspace.utils.flex_fields import Base64ImageField

from country_workspace.contrib.hope.constants import INDIVIDUAL_CHECKER_NAME, PEOPLE_CHECKER_NAME


_script_for_version = Version("0.1.0")


def forward() -> None:
    fd = FieldDefinition.objects.get(name=Base64ImageField.__name__, field_type=fqn(Base64ImageField))
    for fs in Fieldset.objects.filter(name__in=[INDIVIDUAL_CHECKER_NAME, PEOPLE_CHECKER_NAME]):
        fs.fields.update_or_create(
            name="photo",
            defaults={"definition": fd, "attrs": {}},
        )


def backward() -> None:
    for fs in Fieldset.objects.filter(name__in=[INDIVIDUAL_CHECKER_NAME, PEOPLE_CHECKER_NAME]):
        field = fs.fields.get(name="photo")
        if not field.exists():
            continue
        field.delete()


class Scripts:
    requires = []
    operations = [(forward, backward)]
