import io
from collections.abc import Iterable, Callable
from typing import Mapping, Any, TypedDict, cast

from django.db.transaction import atomic
from hope_smart_import.readers import open_xls_multi

from country_workspace.models import AsyncJob, Batch, Household
from country_workspace.utils.fields import clean_field_name

RDI = str | io.BytesIO
Row = Mapping[str, Any]
Sheet = Iterable[Row]

INDIVIDUAL = "individual"
HOUSEHOLD = "household"


class Config(TypedDict):
    batch_name: str
    household_pk_col: str
    master_column_label: str
    detail_column_label: str
    check_before: bool


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


class HouseholdValidationError(Exception):
    def __init__(self, household_key: str) -> None:
        super().__init__(household_key)
        self.household_key = household_key

    def __str__(self) -> str:
        return f"Failed to validate household {self.household_key}."


def normalize_row(row: Row) -> Mapping[str, Any]:
    return {clean_field_name(k): v for k, v in row.items()}


def get_value(row: Row, column_name: str) -> Any:
    if column_name in row:
        return row[column_name]

    raise ColumnConfigurationError(column_name)


def create_has_household_pk_predicate(config: Config) -> Callable[[Row], bool]:
    household_pk_col = config["household_pk_col"]

    def has_household_pk(row: Row) -> bool:
        return bool(get_value(row, household_pk_col))

    return has_household_pk


def process_households(sheet: Sheet, job: AsyncJob, batch: Batch, config: Config) -> Mapping[str, Household]:
    mapping = {}
    has_household_pk = create_has_household_pk_predicate(config)

    for i, row in enumerate(sheet, 1):
        if not has_household_pk(row):
            continue

        name = get_value(row, config["master_column_label"])
        household_key = get_value(row, config["household_pk_col"])

        try:
            mapping[household_key] = cast(
                Household,
                job.program.households.create(
                    batch=batch,
                    name=name,
                    flex_fields=normalize_row(row),
                ),
            )
        except Exception as e:
            raise SheetProcessingError(HOUSEHOLD, i) from e

    return mapping


def process_individuals(
    sheet: Sheet, household_mapping: Mapping[str, Household], job: AsyncJob, batch: Batch, config: Config
) -> int:
    processed = 0
    has_household_pk = create_has_household_pk_predicate(config)

    for i, row in enumerate(sheet, 1):
        if not has_household_pk(row):
            continue

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
                flex_fields=normalize_row(row),
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
        household_mapping = process_households(household_sheet, job, batch, config)
        individuals_number = process_individuals(individual_sheet, household_mapping, job, batch, config)

        if config["check_before"]:
            for household_key, household in household_mapping.items():
                if not household.validate_with_checker():
                    raise HouseholdValidationError(household_key)

        return {
            "household": len(household_mapping),
            "individual": individuals_number,
        }
