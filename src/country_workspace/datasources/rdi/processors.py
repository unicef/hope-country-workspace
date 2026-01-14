from base64 import b64encode
from collections import defaultdict
from collections.abc import Generator
from functools import partial
from typing import Any, cast, Mapping

from PIL import Image
from django.db.transaction import atomic
from hope_smart_import.readers import open_xls_multi, SheetNotError
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as RDIImage

from country_workspace.context import batch_ctx
from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT
from country_workspace.models import AsyncJob, Batch, Household, Individual
from country_workspace.utils.fields import clean_field_names, Record
from country_workspace.utils.imports import get_xlsx_originating_id, normalize_file_name
from country_workspace.utils.functional import compose
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs

from .config import Config, SheetName, Sheet
from .exceptions import ColumnConfigurationError, SheetProcessingError, SheetNotFoundError
from .utils import date_to_iso_string, datetime_to_date


def image_location(image: RDIImage) -> tuple[int, int]:
    return image.anchor._from.row, image.anchor._from.col


def image_content(rdi_image: RDIImage) -> tuple[str | None, str]:
    image = Image.open(rdi_image.ref)
    content_type = Image.MIME.get(image.format)
    rdi_image.ref.seek(0)
    content = b64encode(rdi_image.ref.read()).decode()
    return content_type, content


def extract_images(filepath: str, *sheet_names: str) -> Generator[Mapping[int, Mapping[int, str]], None, None]:
    workbook = load_workbook(filepath)
    for n in sheet_names:
        worksheet = workbook[n]
        images: dict[int, dict[int, str]] = defaultdict(dict)
        for rdi_image in worksheet._images:
            row, column = image_location(rdi_image)
            content_type, content = image_content(rdi_image)
            images[row - 1][column] = VALUE_FORMAT.format(mimetype=content_type, content=content)
        yield images


def merge_images(sheet: Sheet, sheet_images: Mapping[int, Mapping[int, str]]) -> Sheet:
    for i, row in enumerate(sheet):
        if i in sheet_images:
            yield {key: sheet_images[i].get(j, value) for j, (key, value) in enumerate(row.items())}
        else:
            yield row


def get_value(row: Record, column_name: str) -> Any:
    if column_name in row:
        return row[column_name]
    raise ColumnConfigurationError(column_name)


def normalize_row_structure(row: Record, people_prefix: str | None = None) -> tuple[Record, str | None]:
    if people_prefix:
        row = {k.removeprefix(people_prefix): v for k, v in row.items()}
    name_column = next((key for key in row if key.startswith("full") and "name" in key), None)
    return row, name_column


def get_hh_for_ind(
    cleaned_row: dict, household_id_column: str, household_mapping: Mapping[int, Household] | None
) -> Household | None:
    if not household_mapping or not household_id_column:
        return None
    household_key = get_value(cleaned_row, household_id_column)
    return household_mapping.get(household_key)


def filter_rows_with_household_pk(config: Config, sheet: Sheet) -> Sheet:
    household_id_column = config["household_id_column"]

    def has_household_pk(row: Record) -> bool:
        return bool(get_value(row, household_id_column))

    return filter(has_household_pk, sheet)


def read_sheets(config: Config, filepath: str, *sheet_names: str) -> Generator[Sheet, None, None]:
    cell_mapper = compose(datetime_to_date, date_to_iso_string)
    try:
        first_line = config.get("first_line")
        start_at_row = first_line - 2 if first_line > 1 else 0

        sheets = open_xls_multi(
            filepath, indices_or_names=list(sheet_names), value_mapper=cell_mapper, start_at_row=start_at_row
        )
        sheet_images = extract_images(filepath, *sheet_names)
        for (_, sheet), images in zip(sheets, sheet_images, strict=False):
            sheet_with_images = merge_images(sheet, images)
            if config["master_detail"]:
                yield filter_rows_with_household_pk(config, sheet_with_images)
            else:
                yield sheet_with_images
    except (IndexError, SheetNotError) as e:
        raise SheetNotFoundError(sheet_names) from e


def process_households(sheet: Sheet, job: AsyncJob, batch: Batch, config: Config) -> Mapping[int, Household]:
    mapping = {}
    household_mapping_id = config.get("household_mapping_id")
    household_transformer_id = config.get("household_transformer_id")
    transform_row = compose(
        clean_field_names,
        partial(
            job.program.apply_mapping_importer,
            Household,
            mapping_id=household_mapping_id,
            transformer_id=household_transformer_id,
        ),
        partial(job.program.apply_default_fields, Household),
    )

    for row in sheet:
        if (household_key := get_value(row, config["household_id_column"])) in mapping:
            raise SheetProcessingError(SheetName.HOUSEHOLDS, household_key)
        originating_id = get_xlsx_originating_id(normalize_file_name(job.file.name), household_key)
        try:
            mapping[household_key] = cast(
                "Household",
                Household.objects.create(
                    batch_id=batch.pk,
                    name=str(get_value(row, config["household_label"])),
                    originating_id=originating_id,
                    flex_fields=transform_row(row),
                    raw_data=row,
                ),
            )
        except Exception as e:
            raise SheetProcessingError(SheetName.HOUSEHOLDS, household_key) from e

    return mapping


def process_beneficiaries(
    sheet: Sheet, job: AsyncJob, batch: Batch, config: Config, household_mapping: Mapping[int, Household] | None = None
) -> Mapping[int, Individual]:
    mapping = {}
    people_prefix = config.get("people_prefix") if household_mapping is None else None
    household_id_column = config.get("household_id_column") if household_mapping is not None else None
    sheet_name = SheetName.PEOPLE if household_mapping is None else SheetName.INDIVIDUALS
    individual_mapping_id = config.get("individual_mapping_id")
    individual_transformer_id = config.get("individual_transformer_id")
    transform_row = compose(
        clean_field_names,
        partial(
            job.program.apply_mapping_importer,
            Individual,
            mapping_id=individual_mapping_id,
            transformer_id=individual_transformer_id,
        ),
        partial(job.program.apply_default_fields, Individual),
    )

    for row in sheet:
        beneficiary_key = get_value(row, config["beneficiary_id_column"])
        if beneficiary_key in mapping:
            raise SheetProcessingError(sheet_name, beneficiary_key)
        originating_id = get_xlsx_originating_id(normalize_file_name(job.file.name), beneficiary_key)

        cleaned_row, name_column = normalize_row_structure(row, people_prefix)
        name = cleaned_row.get(name_column) if name_column else ""
        household = get_hh_for_ind(cleaned_row, household_id_column, household_mapping)

        try:
            mapping[beneficiary_key] = cast(
                "Individual",
                Individual.objects.create(
                    batch_id=batch.pk,
                    name=name,
                    household=household,
                    originating_id=originating_id,
                    flex_fields=transform_row(cleaned_row),
                    raw_data=row,
                ),
            )
        except Exception as e:
            raise SheetProcessingError(sheet_name, beneficiary_key) from e

    return mapping


def import_from_rdi(job: AsyncJob) -> dict[str, int]:
    with atomic():
        config: Config = job.config
        batch = Batch.objects.create(
            name=config["batch_name"],
            program=job.program,
            country_office=job.program.country_office,
            imported_by=job.owner,
            source=Batch.BatchSource.RDI,
        )
        with batch_ctx(batch.pk):
            if config["master_detail"]:
                result = _import_master_detail(job, batch, config)
            else:
                result = _import_people_only(job, batch, config)

    if not config.get("validate_after_import"):
        return result

    if job.config.get("master_detail"):
        queryset = batch.household_set.all().prefetch_related("members")
    else:
        queryset = batch.individual_set.filter(household=None)

    create_validation_jobs(
        description=f"Validate records for batch {batch.pk}",
        owner=job.owner,
        program=job.program,
        queryset=queryset,
    )
    return result


def _import_master_detail(job: AsyncJob, batch: Batch, config: Config) -> dict[str, int]:
    household_sheet, individual_sheet = read_sheets(config, job.file, SheetName.HOUSEHOLDS, SheetName.INDIVIDUALS)

    household_mapping = process_households(household_sheet, job, batch, config)
    individuals_mapping = process_beneficiaries(individual_sheet, job, batch, config, household_mapping)
    _sync_ind_pks(household_mapping, individuals_mapping)
    return {"household": len(household_mapping), "individual": len(individuals_mapping)}


def _import_people_only(job: AsyncJob, batch: Batch, config: Config) -> dict[str, int]:
    (people_sheet,) = read_sheets(config, job.file, SheetName.PEOPLE)

    people_mapping = process_beneficiaries(people_sheet, job, batch, config)
    return {"people": len(people_mapping)}


def _sync_ind_pks(households_mapping: dict, individuals_mapping: dict) -> None:
    pk_mapping = {v.flex_fields.get("individual_id"): v.pk for _, v in individuals_mapping.items()}

    for v in households_mapping.values():
        hh_flex_fields = v.flex_fields.copy()
        hh_flex_fields["head_of_household"] = pk_mapping.get(v.flex_fields.get("head_of_household"))
        hh_flex_fields["primary_collector"] = pk_mapping.get(v.flex_fields.get("primary_collector"))
        if alt_id := v.flex_fields.get("alternate_collector"):  # is optional
            hh_flex_fields["alternate_collector"] = pk_mapping.get(alt_id)

        v.flex_fields = hh_flex_fields
        v.save(update_fields=["flex_fields"])
