from typing import Self
from dataclasses import dataclass
from contextlib import suppress
from packaging.version import Version
from django.db import transaction

from hope_flex_fields.models import FieldDefinition, FlexField, DataChecker
from country_workspace.models import MappingImporter
from country_workspace.contrib.hope.constants import INDIVIDUAL_CHECKER_NAME, PEOPLE_CHECKER_NAME

_script_for_version = Version("0.1.0")


@dataclass(frozen=True)
class FieldRename:
    old_definition: str
    new_definition: str
    old_field: str
    new_field: str

    def reverse(self) -> Self:
        return FieldRename(self.new_definition, self.old_definition, self.new_field, self.old_field)


RENAME = FieldRename("HOPE IND Gender", "HOPE IND Sex", "gender", "sex")
CHECKERS = (INDIVIDUAL_CHECKER_NAME, PEOPLE_CHECKER_NAME)
MI_NAME = "gender_to_sex"


def _rename_field(rename: FieldRename) -> None:
    field_def_qs = FieldDefinition.objects.filter(name=rename.old_definition)
    if field_def_qs.exists():
        FlexField.objects.filter(definition__in=field_def_qs).update(name=rename.new_field)
        field_def_qs.update(name=rename.new_definition)


def _create_mapping_rules(rename: FieldRename) -> None:
    for checker_name in CHECKERS:
        with suppress(DataChecker.DoesNotExist):
            dc = DataChecker.objects.get(name=checker_name)
            MappingImporter.objects.get_or_create(
                name=MI_NAME,
                data_checker=dc,
                defaults={
                    "rules": f"{rename.old_field}={rename.new_field}",
                },
            )


def _remove_mapping_rules(rename: FieldRename) -> None:
    MappingImporter.objects.filter(name=MI_NAME).delete()


def forward() -> None:
    with transaction.atomic():
        _rename_field(RENAME)
        _create_mapping_rules(RENAME)


def backward() -> None:
    with transaction.atomic():
        _remove_mapping_rules(RENAME)
        _rename_field(RENAME.reverse())


class Scripts:
    requires = []
    operations = [(forward, backward)]
