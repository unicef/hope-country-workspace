from typing import TYPE_CHECKING

from django.db.models import QuerySet
from hope_flex_fields.models import DataChecker
from strategy_field.utils import fqn

from country_workspace.models import AsyncJob, Program
from country_workspace.utils.fields import clean_field_names
from country_workspace.workspaces.admin.cleaners.validate import validate_queryset

if TYPE_CHECKING:
    from country_workspace.datasources.rdi.config import Sheet


def generate_validation_job(description: str, owner: str, program: Program, queryset: QuerySet) -> AsyncJob:
    opts = queryset.model._meta
    return AsyncJob.objects.create(
        description=description,
        type=AsyncJob.JobType.ACTION,
        owner=owner,
        action=fqn(validate_queryset),
        program=program,
        config={"pks": list(queryset.values_list("pk", flat=True)), "model_name": opts.label},
    )


def validate_alien_fields(sheet: "Sheet", datachecker: DataChecker) -> None:
    row = next(sheet)
    raw_data = clean_field_names(row)
    fields = set(raw_data.keys())
    if mapping_importer := datachecker.mappingimporter:
        fields = {mapping_importer.rules_as_dict.get(f, f) for f in fields}

    if datachecker is None:
        return

    dc_fields = {f"{fieldset.prefix}{field.name}" for fieldset, field in list(datachecker.get_fields())}
    if not fields.issubset(dc_fields):
        raise ValueError(f"Alien values found for: {fields - dc_fields}")
