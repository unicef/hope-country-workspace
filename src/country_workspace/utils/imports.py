from country_workspace.models import Household
from country_workspace.models import Individual

def validate_alien_fields(instance: Household | Individual) -> None:
    if isinstance(instance, Household):
        dc = instance.batch.program.household_checker
        fields_to_ignore = instance.batch.program.hh_alien_columns_to_ignore
    elif isinstance(instance, Individual):
        dc = instance.batch.program.individual_checker
        fields_to_ignore = instance.batch.program.ind_alien_columns_to_ignore
    else:
        dc = fields_to_ignore =None

    if dc is None:
        return

    fields = instance.flex_fields.keys()
    if mapping_importers := dc.mapping_importers.all():
        fields = {mapping_importer.rules_as_dict.get(f, f) for f in fields for mapping_importer in mapping_importers}

    dc_fields = {f"{fieldset.prefix}{field.name}" for fieldset, field in list(dc.get_fields())}

    alien_fields = fields - dc_fields

    if fields_to_ignore:
        ignored = {f.strip() for f in fields_to_ignore.split("\n") if f.strip()}
        alien_fields = alien_fields - ignored

    if alien_fields:
        raise ValueError(f"Alien values found for: {alien_fields}")
