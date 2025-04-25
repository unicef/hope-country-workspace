import io
from collections.abc import Iterable
from typing import Any, Mapping, cast

from django.db.transaction import atomic
from hope_smart_import.readers import open_xls_multi

from country_workspace.models import AsyncJob, Batch, Household
from country_workspace.utils.config import BatchNameConfig, FailIfAlienConfig
from country_workspace.utils.fields import Record, clean_field_names
from country_workspace.validators.beneficiaries import validate_beneficiaries

RDI = str | io.BytesIO
Sheet = Iterable[Record]

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


class MissingHouseholdError(Exception):
    def __init__(self, row_index: int, household_key: str) -> None:
        super().__init__(row_index, household_key)
        self.row_index = row_index
        self.household_key = household_key

    def __str__(self) -> str:
        return f"Missing household {self.household_key} for individual at row {self.row_index}"


def get_value(row: Record, column_name: str) -> Any:
    if column_name in row:
        return row[column_name]

    raise ColumnConfigurationError(column_name)


def filter_rows_with_household_pk(config: Config, *sheets: Sheet) -> Iterable[Sheet]:
    household_pk_col = config["household_pk_col"]

    def has_household_pk(row: Record) -> bool:
        return bool(get_value(row, household_pk_col))

    return (filter(has_household_pk, sheet) for sheet in sheets)


def process_households(sheet: Sheet, job: AsyncJob, batch: Batch, config: Config) -> Mapping[int, Household]:
    mapping = {}

    for i, row in enumerate(sheet, 1):
        name = get_value(row, config["master_column_label"])
        household_key = get_value(row, config["household_pk_col"])

        try:
            mapping[household_key] = cast(
                Household,
                job.program.households.create(
                    batch=batch,
                    name=name,
                    flex_fields=clean_field_names(row),
                ),
            )
        except Exception as e:
            raise SheetProcessingError(HOUSEHOLD, i) from e

    return mapping


def process_individuals(
    sheet: Sheet, household_mapping: Mapping[int, Household], job: AsyncJob, batch: Batch, config: Config
) -> int:
    processed = 0

    for i, row in enumerate(sheet, 1):
        name = get_value(row, config["detail_column_label"])
        household_key = get_value(row, config["household_pk_col"])
        household = household_mapping.get(household_key)

        if not household:
            raise MissingHouseholdError(i, household_key)

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
        (_, household_sheet), (_, individual_sheet) = open_xls_multi(rdi, sheets=[0, 1])

        household_sheet, individual_sheet = filter_rows_with_household_pk(config, household_sheet, individual_sheet)

        household_mapping = process_households(household_sheet, job, batch, config)
        individuals_number = process_individuals(individual_sheet, household_mapping, job, batch, config)

        validate_beneficiaries(config, household_mapping)

        return {
            "household": len(household_mapping),
            "individual": individuals_number,
        }
