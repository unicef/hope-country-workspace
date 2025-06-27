from dataclasses import dataclass
from packaging.version import Version
from django.db import transaction

from hope_flex_fields.models import FieldDefinition, FlexField

_script_for_version = Version("0.1.0")


@dataclass(frozen=True)
class FieldRename:
    old_definition: str
    new_definition: str
    old_field: str
    new_field: str

    def reverse(self) -> "FieldRename":
        return FieldRename(self.new_definition, self.old_definition, self.new_field, self.old_field)


RENAME = FieldRename("HOPE IND Gender", "HOPE IND Sex", "gender", "sex")


def _rename_field(rename: FieldRename) -> None:
    with transaction.atomic():
        field_def_qs = FieldDefinition.objects.filter(name=rename.old_definition)
        if field_def_qs.exists():
            FlexField.objects.filter(definition__in=field_def_qs).update(name=rename.new_field)
            field_def_qs.update(name=rename.new_definition)


def forward() -> None:
    _rename_field(RENAME)


def backward() -> None:
    _rename_field(RENAME.reverse())


class Scripts:
    requires = []
    operations = [(forward, backward)]
