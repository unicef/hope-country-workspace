from typing import TYPE_CHECKING

from hope_flex_fields.models import DataChecker

from country_workspace.utils.fields import clean_field_names

if TYPE_CHECKING:
    from country_workspace.datasources.rdi.config import Sheet


def validate_alien_fields(sheet: "Sheet", datachecker: DataChecker) -> None:
    if datachecker is None:
        return

    row = next(sheet)
    raw_data = clean_field_names(row)
    fields = set(raw_data.keys())
    if mapping_importer := datachecker.mappingimporter:
        fields = {mapping_importer.rules_as_dict.get(f, f) for f in fields}

    dc_fields = {f"{fieldset.prefix}{field.name}" for fieldset, field in list(datachecker.get_fields())}
    if not fields.issubset(dc_fields):
        raise ValueError(f"Alien values found for: {fields - dc_fields}")
