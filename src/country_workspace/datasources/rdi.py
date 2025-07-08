import io
from base64 import b64encode
from collections import defaultdict
from collections.abc import Iterable, Generator
from enum import StrEnum
from typing import Any, Mapping, cast, NotRequired
from functools import partial

import openpyxl
from PIL import Image
from django.db.transaction import atomic
from hope_smart_import.readers import open_xls_multi
from openpyxl.drawing.image import Image as RDIImage

from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT
from country_workspace.datasources.utils import datetime_to_date, date_to_iso_string
from country_workspace.models import AsyncJob, Batch, Household, Individual
from country_workspace.utils.config import BatchNameConfig, ValidateModeConfig
from country_workspace.utils.fields import Record, clean_field_names
from country_workspace.utils.functional import compose
from country_workspace.utils.types import ValidateBeneficiaries
from country_workspace.validators.beneficiaries import validate_beneficiaries

RDI = str | io.BytesIO
Sheet = Iterable[Record]
MultiSheet = Iterable[tuple[int, Sheet]]


INDIVIDUAL = "individual"
HOUSEHOLD = "household"
PEOPLE = "people"


class Config(BatchNameConfig, ValidateModeConfig):
    master_detail: bool
    household_pk_col: NotRequired[str]
    master_column_label: NotRequired[str]
    detail_column_label: NotRequired[str]
    people_column_prefix: NotRequired[str]
    first_line: int


class SheetName(StrEnum):
    HOUSEHOLDS = "Households"
    INDIVIDUALS = "Individuals"
    PEOPLE = "People"


class ColumnConfigurationError(Exception):
    def __init__(self, column_name: str) -> None:
        super().__init__(column_name)
        self.column_name = column_name

    def __str__(self) -> str:
        return f"Column {self.column_name} not found."


class SheetProcessingError(Exception):
    def __init__(self, sheet_name: str, row_index: int) -> None:
        super().__init__(sheet_name, row_index)
        self.sheet_name = sheet_name
        self.row_index = row_index

    def __str__(self) -> str:
        return f"Failed to process {self.sheet_name} sheet at row {self.row_index}"


class SheetNotFoundError(Exception):
    def __init__(self, sheet_names: str | tuple[str, ...]) -> None:
        if isinstance(sheet_names, str):
            sheet_names = (sheet_names,)
        super().__init__(sheet_names)
        self.sheet_names = sheet_names

    def __str__(self) -> str:
        if len(self.sheet_names) == 1:
            return f"Sheet with index {self.sheet_names[0]} was not found in the provided file."
        indices_str = ", ".join(map(str, self.sheet_names))
        return f"Sheets with indices {indices_str} were not found in the provided file."


def get_value(row: Record, column_name: str) -> Any:
    if column_name in row:
        return row[column_name]

    raise ColumnConfigurationError(column_name)


def filter_rows_with_household_pk(config: Config, sheet: Sheet) -> Sheet:
    household_pk_col = config["household_pk_col"]

    def has_household_pk(row: Record) -> bool:
        return bool(get_value(row, household_pk_col))

    return filter(has_household_pk, sheet)


def process_households(sheet: Sheet, job: AsyncJob, batch: Batch, config: Config) -> Mapping[int, Household]:
    mapping = {}

    for i, row in enumerate(sheet, 1):
        household_key = get_value(row, config["household_pk_col"])
        label = get_value(row, config["detail_column_label"])
        flex_fields = job.program.apply_mapping_importer(Household, clean_field_names(row))

        try:
            mapping[household_key] = cast(
                "Household",
                job.program.households.create(
                    batch=batch,
                    name=label,
                    flex_fields=flex_fields,
                ),
            )
        except Exception as e:
            raise SheetProcessingError(HOUSEHOLD, i) from e

    return mapping


def normalize_row_structure(row: Record, people_column_prefix: str | None = None) -> tuple[Record, str | None]:
    if people_column_prefix:
        row = {k.removeprefix(people_column_prefix): v for k, v in row.items()}
    name_column = next((key for key in row if key.startswith("full") and "name" in key), None)
    return row, name_column


def get_hh_for_ind(
    cleaned_row: dict, master_column_label: str, household_mapping: Mapping[int, Household] | None
) -> Household | None:
    if not household_mapping or not master_column_label:
        return None
    household_key = get_value(cleaned_row, master_column_label)
    return household_mapping.get(household_key)


def process_beneficiaries(
    sheet: Sheet, job: AsyncJob, batch: Batch, config: Config, household_mapping: Mapping[int, Household] | None = None
) -> Mapping[int, Individual]:
    mapping = {}
    people_column_prefix = config.get("people_column_prefix") if household_mapping is None else None
    master_column_label = config.get("master_column_label") if household_mapping is not None else None
    sheet_name = PEOPLE if household_mapping is None else INDIVIDUAL

    for i, row in enumerate(sheet, 1):
        cleaned_row, name_column = normalize_row_structure(row, people_column_prefix)
        name = cleaned_row.get(name_column) if name_column else ""
        household = get_hh_for_ind(cleaned_row, master_column_label, household_mapping)
        flex_fields = job.program.apply_mapping_importer(Individual, clean_field_names(cleaned_row))

        try:
            mapping[i] = cast(
                "Individual",
                job.program.individuals.create(
                    batch=batch,
                    name=name,
                    household=household,
                    flex_fields=flex_fields,
                ),
            )
        except Exception as e:
            raise SheetProcessingError(sheet_name, i) from e

    return mapping


def image_location(image: RDIImage) -> tuple[int, int]:
    return image.anchor._from.row, image.anchor._from.col


def image_content(rdi_image: RDIImage) -> tuple[str | None, str]:
    image = Image.open(rdi_image.ref)
    content_type = Image.MIME.get(image.format)
    rdi_image.ref.seek(0)
    content = b64encode(rdi_image.ref.read()).decode()
    return content_type, content


def extract_images(filepath: str, *sheet_names: str) -> Generator[Mapping[int, Mapping[int, str]], None, None]:
    workbook = openpyxl.load_workbook(filepath)
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


def read_sheets(config: Config, filepath: str, *sheet_names: str) -> Generator[Sheet, None, None]:
    cell_mapper = compose(datetime_to_date, date_to_iso_string)
    try:
        sheets = open_xls_multi(filepath, indices_or_names=list(sheet_names), value_mapper=cell_mapper)
        sheet_images = extract_images(filepath, *sheet_names)
        for (_, sheet), images in zip(sheets, sheet_images, strict=False):
            sheet_with_images = merge_images(sheet, images)
            if config["master_detail"]:
                yield filter_rows_with_household_pk(config, sheet_with_images)
            else:
                yield sheet_with_images
    except IndexError as e:
        raise SheetNotFoundError(sheet_names) from e


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
    household_sheet, individual_sheet = read_sheets(
        config, job.file, SheetName.HOUSEHOLDS.value, SheetName.INDIVIDUALS.value
    )
    household_mapping = process_households(household_sheet, job, batch, config)
    individuals_mapping = process_beneficiaries(individual_sheet, job, batch, config, household_mapping)
    validate(household_mapping)
    return {"household": len(household_mapping), "individual": len(individuals_mapping)}


def _import_people_only(job: AsyncJob, batch: Batch, config: Config, validate: ValidateBeneficiaries) -> dict[str, int]:
    (people_sheet,) = read_sheets(config, job.file, SheetName.PEOPLE.value)
    people_mapping = process_beneficiaries(people_sheet, job, batch, config)
    validate(people_mapping)
    return {"people": len(people_mapping)}
