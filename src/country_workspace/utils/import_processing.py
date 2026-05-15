import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from constance import config as constance_config
from django.db.models import QuerySet

from country_workspace.models import Batch, Household, Individual, Program, Transformer
from country_workspace.utils.document_columns import expand_document_columns
from country_workspace.utils.fields import TO_UPPERCASE_FIELDS, clean_field_names

Processor = Callable[[dict[str, Any]], dict[str, Any]]
type Transformable = Household | Individual


def _split_ignored_fields(value: str | None) -> set[str]:
    if not value or not isinstance(value, str):
        return set()
    return {part.strip() for part in re.split(r"[,\n]", value) if part.strip()}


def _normalize_source(source: str | None) -> str | None:
    if not source:
        return None

    if source in (Batch.BatchSource.RDI, "RDI"):
        return "XLS"
    if source in (Batch.BatchSource.KOBO, "KOBO"):
        return "KOBO"
    if source in (Batch.BatchSource.AURORA, "AURORA"):
        return "AURORA"
    return source


def get_ignored_fields(
    program: Program,
    model: type[Household | Individual],
    source: str | None = None,
) -> set[str]:
    if issubclass(model, Household):
        entity = "HH"
        program_fields = program.hh_alien_columns_to_ignore
    else:
        entity = "IND"
        program_fields = program.ind_alien_columns_to_ignore

    ignored = _split_ignored_fields(program_fields)

    source_key = _normalize_source(source)
    if source_key:
        ignored |= _split_ignored_fields(getattr(constance_config, f"{source_key}_{entity}_FIELDS_TO_IGNORE", ""))
        if source_key == "KOBO":
            ignored |= _split_ignored_fields(getattr(constance_config, "KOBO_FIELDS_TO_IGNORE", ""))

    return ignored


def process_import_record(  # noqa: PLR0913
    raw: Mapping[str, Any],
    *,
    program: Program,
    model: type[Household | Individual],
    mapping_id: int | None = None,
    fields_to_uppercase: Iterable[str] | None = None,
    pre_processors: Iterable[Processor] | None = None,
    post_processors: Iterable[Processor] | None = None,
    apply_defaults: bool = True,
    apply_mapping: bool = True,
    source: str | None = None,
    ignored_fields: Iterable[str] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = dict(raw)

    for processor in pre_processors or ():
        data = processor(data)

    data = dict(clean_field_names(data, fields_to_uppercase=fields_to_uppercase or TO_UPPERCASE_FIELDS))
    if apply_mapping:
        data = program.apply_mapping_importer(model, data, mapping_id=mapping_id)

    data = expand_document_columns(data)

    for processor in post_processors or ():
        data = processor(data)

    if apply_defaults:
        data = program.apply_default_fields(model, data)

    ignore_set = set(ignored_fields) if ignored_fields is not None else get_ignored_fields(program, model, source)
    if ignore_set:
        data = {key: value for key, value in data.items() if key not in ignore_set}

    return data


def build_import_processor(  # noqa: PLR0913
    *,
    program: Program,
    model: type[Household | Individual],
    mapping_id: int | None = None,
    fields_to_uppercase: Iterable[str] | None = None,
    pre_processors: Iterable[Processor] | None = None,
    post_processors: Iterable[Processor] | None = None,
    apply_defaults: bool = True,
    apply_mapping: bool = True,
    source: str | None = None,
    ignored_fields: Iterable[str] | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    def processor(raw: Mapping[str, Any]) -> dict[str, Any]:
        return process_import_record(
            raw,
            program=program,
            model=model,
            mapping_id=mapping_id,
            fields_to_uppercase=fields_to_uppercase,
            pre_processors=pre_processors,
            post_processors=post_processors,
            apply_defaults=apply_defaults,
            apply_mapping=apply_mapping,
            source=source,
            ignored_fields=ignored_fields,
        )

    return processor


def _apply_transformer(
    qs: QuerySet[Transformable],
    *,
    batch: Batch,
    transformer_id: int | None,
) -> int:
    if not transformer_id:
        return 0

    transformer = Transformer.objects.filter(pk=transformer_id, office=batch.country_office).first()
    if not transformer:
        return 0

    count = 0
    for record in qs.only("pk", "flex_fields").iterator():
        record.flex_fields = transformer.apply(dict(record.flex_fields or {}))
        record.last_checked = None
        record.errors = {}
        record.save(update_fields=["flex_fields", "last_checked", "errors"])
        count += 1

    return count


def apply_transformers(
    batch: Batch,
    *,
    household_transformer_id: int | None = None,
    individual_transformer_id: int | None = None,
) -> dict[str, int]:
    transformed_households = 0

    if batch.program.is_master_detail:
        transformed_households = _apply_transformer(
            batch.household_set.filter(removed=False),
            batch=batch,
            transformer_id=household_transformer_id,
        )

    transformed_individuals = _apply_transformer(
        batch.individual_set.filter(removed=False),
        batch=batch,
        transformer_id=individual_transformer_id,
    )

    return {
        "transformed_households": transformed_households,
        "transformed_individuals": transformed_individuals,
    }
