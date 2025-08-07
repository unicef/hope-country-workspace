from base64 import b64encode
from collections import defaultdict
from collections.abc import Generator
from copy import deepcopy
from functools import partial
from typing import Any, cast, Mapping

from hope_smart_import.readers import open_xls_multi
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as RDIImage
from PIL import Image

from django.db.transaction import atomic

from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT
from country_workspace.models import AsyncJob, Batch, Household, Individual
from country_workspace.utils.fields import clean_field_names, Record
from country_workspace.utils.functional import compose
from country_workspace.utils.types import ValidateBeneficiaries
from country_workspace.validators.beneficiaries import validate_beneficiaries
from .config import Config, SheetName, Sheet
from .exceptions import ColumnConfigurationError, SheetProcessingError, SheetNotFoundError
from .utils import date_to_iso_string, datetime_to_date, validation_errors_handler


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
    except IndexError as e:
        raise SheetNotFoundError(sheet_names) from e


def process_households(sheet: Sheet, job: AsyncJob, batch: Batch, config: Config) -> Mapping[int, Household]:
    mapping = {}

    for row in sheet:
        household_key = get_value(row, config["household_id_column"])
        if household_key in mapping:
            raise SheetProcessingError(SheetName.HOUSEHOLDS, household_key)

        label = get_value(row, config["household_label"])
        raw_data = clean_field_names(row)
        flex_fields = job.program.apply_mapping_importer(Household, deepcopy(raw_data))

        try:
            mapping[household_key] = cast(
                "Household",
                Household.objects.create(
                    batch_id=batch.pk,
                    name=str(label),
                    flex_fields=flex_fields,
                    raw_data=raw_data,
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

    for row in sheet:
        beneficiary_key = get_value(row, config["beneficiary_id_column"])
        if beneficiary_key in mapping:
            raise SheetProcessingError(sheet_name, beneficiary_key)

        cleaned_row, name_column = normalize_row_structure(row, people_prefix)
        name = cleaned_row.get(name_column) if name_column else ""
        household = get_hh_for_ind(cleaned_row, household_id_column, household_mapping)
        raw_data = clean_field_names(cleaned_row)
        flex_fields = job.program.apply_mapping_importer(Individual, deepcopy(raw_data))

        try:
            mapping[beneficiary_key] = cast(
                "Individual",
                Individual.objects.create(
                    batch_id=batch.pk,
                    name=name,
                    household=household,
                    flex_fields=flex_fields,
                    raw_data=raw_data,
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
        validate = partial(validate_beneficiaries, config=config, office=job.program.country_office)
        if config["master_detail"]:
            return _import_master_detail(job, batch, config, validate)
        return _import_people_only(job, batch, config, validate)


def _import_master_detail(
    job: AsyncJob, batch: Batch, config: Config, validate: ValidateBeneficiaries
) -> dict[str, int]:
    household_sheet, individual_sheet = read_sheets(config, job.file, SheetName.HOUSEHOLDS, SheetName.INDIVIDUALS)
    household_mapping = process_households(household_sheet, job, batch, config)
    individuals_mapping = process_beneficiaries(individual_sheet, job, batch, config, household_mapping)
    _sync_ind_pks(household_mapping, individuals_mapping)
    with validation_errors_handler(job, config, households=household_mapping, individuals=individuals_mapping):
        validate(household_mapping)
    return {"household": len(household_mapping), "individual": len(individuals_mapping)}


def _import_people_only(job: AsyncJob, batch: Batch, config: Config, validate: ValidateBeneficiaries) -> dict[str, int]:
    (people_sheet,) = read_sheets(config, job.file, SheetName.PEOPLE)
    people_mapping = process_beneficiaries(people_sheet, job, batch, config)
    with validation_errors_handler(job, config, people=people_mapping):
        validate(people_mapping)
    return {"people": len(people_mapping)}


def _sync_ind_pks(households_mapping: dict, individuals_mapping: dict) -> None:
    pk_mapping = {v.flex_fields.get("individual_id"): v.pk for _, v in individuals_mapping.items()}

    for v in households_mapping.values():
        hh_flex_fields = v.flex_fields
        hh_flex_fields["head_of_household_id"] = pk_mapping.get(v.flex_fields.get("head_of_household_id"))
        hh_flex_fields["primary_collector_id"] = pk_mapping.get(v.flex_fields.get("primary_collector_id"))
        if alt_id := v.flex_fields.get("alternate_collector_id"):  # is optional
            hh_flex_fields["alternate_collector_id"] = pk_mapping.get(alt_id)

        v.flex_fields = hh_flex_fields
        v.save(update_fields=["flex_fields"])
