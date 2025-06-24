import io
from base64 import b64encode
from collections import defaultdict
from collections.abc import Iterable, Generator
from typing import Any, Mapping, cast

import openpyxl
from PIL import Image
from django.db.transaction import atomic
from hope_smart_import.readers import open_xls_multi
from openpyxl.drawing.image import Image as RDIImage

from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT
from country_workspace.models import AsyncJob, Batch, Household
from country_workspace.utils.config import BatchNameConfig, FailIfAlienConfig
from country_workspace.utils.fields import Record, clean_field_names
from country_workspace.utils.functional import compose
from country_workspace.validators.beneficiaries import validate_beneficiaries
from country_workspace.datasources.utils import datetime_to_date, date_to_iso_string


RDI = str | io.BytesIO
Sheet = Iterable[Record]
MultiSheet = Iterable[tuple[int, Sheet]]


INDIVIDUAL = "individual"
HOUSEHOLD = "household"


class Config(BatchNameConfig, FailIfAlienConfig):
    household_pk_col: str
    master_column_label: str
    detail_column_label: str


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

        try:
            mapping[household_key] = cast(
                "Household",
                job.program.households.create(
                    batch=batch,
                    name=label,
                    flex_fields=clean_field_names(row),
                ),
            )
        except Exception as e:
            raise SheetProcessingError(HOUSEHOLD, i) from e

    return mapping


def full_name_column(row: Record) -> str | None:
    for key in row:
        if key.startswith("full") and "name" in key:
            return key
    return None


def process_individuals(
    sheet: Sheet, household_mapping: Mapping[int, Household], job: AsyncJob, batch: Batch, config: Config
) -> int:
    processed = 0

    for i, row in enumerate(sheet, 1):
        name_column = full_name_column(row)
        name = get_value(row, name_column) if name_column else None
        household_key = get_value(row, config["master_column_label"])
        household = household_mapping.get(household_key)

        try:
            job.program.individuals.create(
                batch=batch,
                name=name,
                household_id=household.pk,
                flex_fields=clean_field_names(row),
            )
        except Exception as e:
            raise SheetProcessingError(INDIVIDUAL, i) from e

        processed += 1

    return processed


def image_location(image: RDIImage) -> tuple[int, int]:
    return image.anchor._from.row, image.anchor._from.col


def image_content(rdi_image: RDIImage) -> tuple[str | None, str]:
    image = Image.open(rdi_image.ref)
    content_type = Image.MIME.get(image.format)
    rdi_image.ref.seek(0)
    content = b64encode(rdi_image.ref.read()).decode()
    return content_type, content


def extract_images(filepath: str, *sheet_indices: int) -> Generator[Mapping[int, Mapping[int, str]], None, None]:
    workbook = openpyxl.load_workbook(filepath)
    for i in sheet_indices:
        worksheet = workbook.worksheets[i]
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


def read_sheets(config: Config, filepath: str, *sheet_indices: int) -> Generator[Sheet, None, None]:
    cell_mapper = compose(datetime_to_date, date_to_iso_string)
    sheets = open_xls_multi(filepath, sheets=list(sheet_indices), value_mapper=cell_mapper)
    sheet_images = extract_images(filepath, *sheet_indices)
    for (_, sheet), images in zip(sheets, sheet_images, strict=False):
        sheet_with_images = merge_images(sheet, images)
        yield filter_rows_with_household_pk(config, sheet_with_images)


def import_from_rdi(job: AsyncJob) -> dict[str, int]:
    with atomic():
        config: Config = job.config
        rdi = job.file
        batch = Batch.objects.create(
            name=config["batch_name"],
            program=job.program,
            country_office=job.program.country_office,
            imported_by=job.owner,
            source=Batch.BatchSource.RDI,
        )

        household_sheet, individual_sheet = read_sheets(config, rdi, 0, 1)

        household_mapping = process_households(household_sheet, job, batch, config)
        individuals_number = process_individuals(individual_sheet, household_mapping, job, batch, config)

        validate_beneficiaries(config, household_mapping)

        return {
            "household": len(household_mapping),
            "individual": individuals_number,
        }
