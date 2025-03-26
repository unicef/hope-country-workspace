from collections.abc import Mapping
from unittest.mock import Mock, call

import pytest
from pytest_mock import MockerFixture

from country_workspace.datasources.rdi import (
    normalize_row,
    get_value,
    ColumnConfigurationError,
    SheetProcessingError,
    MissingHouseholdError,
    HouseholdValidationError,
    filter_rows_with_household_pk,
    process_households,
    process_individuals,
    validate_households,
    import_from_rdi,
    Config,
    Sheet,
    Record,
)
from country_workspace.models import Household

HOUSEHOLD_1_PK = 1
HOUSEHOLD_2_PK = 2
HOUSEHOLD_1_NAME = "Household 1"
HOUSEHOLD_2_NAME = "Household 2"


@pytest.fixture
def config() -> Config:
    return {
        "batch_name": "batch_name",
        "household_pk_col": "household_pk",
        "master_column_label": "master_column",
        "detail_column_label": "detail_column",
        "check_before": False,
    }


@pytest.fixture
def household_sheet(config: Config) -> Sheet:
    return [
        {config["master_column_label"]: HOUSEHOLD_1_NAME, config["household_pk_col"]: HOUSEHOLD_1_PK},
        {config["master_column_label"]: HOUSEHOLD_1_NAME, config["household_pk_col"]: HOUSEHOLD_2_PK},
    ]


@pytest.fixture
def individual_sheet(config: Config) -> Sheet:
    return [
        {
            config["detail_column_label"]: "John Doe",
            config["household_pk_col"]: HOUSEHOLD_1_PK,
        },
        {
            config["detail_column_label"]: "Doe John",
            config["household_pk_col"]: HOUSEHOLD_2_PK,
        },
    ]


@pytest.fixture
def household_mapping() -> Mapping[int, Mock]:
    return {
        HOUSEHOLD_1_PK: Mock(name=HOUSEHOLD_1_NAME),
        HOUSEHOLD_2_PK: Mock(name=HOUSEHOLD_2_NAME),
    }


def test_column_configuration_error_format() -> None:
    error = ColumnConfigurationError(column_name := "test_column")
    assert column_name in str(error)


def test_sheet_processing_error_format() -> None:
    error = SheetProcessingError(sheet_name := "test_sheet", row_index := 42)
    assert sheet_name in str(error)
    assert str(row_index) in str(error)


def test_missing_household_error_format() -> None:
    error = MissingHouseholdError(row_index := 42, household_key := "test_household_key")
    assert str(row_index) in str(error)
    assert household_key in str(error)


def test_household_validation_error_format() -> None:
    error = HouseholdValidationError(household_key := "test_household_key")
    assert household_key in str(error)


def test_normalize_row_calls_clean_field_name(mocker: MockerFixture) -> None:
    row = {(key := "key"): (value := "value")}
    clean_field_name_mock = mocker.patch("country_workspace.datasources.rdi.clean_field_name")

    result = normalize_row(row)

    assert result == {clean_field_name_mock.return_value: value}
    clean_field_name_mock.assert_called_once_with(key)


def test_get_value_returns_value() -> None:
    row = {(column := "column"): (column_value := "value")}

    value = get_value(row, column)

    assert value == column_value


def test_get_value_raise_exception_when_key_is_missing() -> None:
    row: Record = {}

    with pytest.raises(ColumnConfigurationError):
        get_value(row, "column")


def test_filter_rows_with_household_pk(mocker: MockerFixture, config: Config, household_sheet: Sheet) -> None:
    household_sheet_list = list(household_sheet)
    get_value_mock = mocker.patch("country_workspace.datasources.rdi.get_value")
    get_value_mock.side_effect = True, False

    result = [list(s) for s in filter_rows_with_household_pk(config, household_sheet)]

    assert result == [[household_sheet_list[0]]]
    get_value_mock.assert_has_calls(
        (
            call(household_sheet_list[0], config["household_pk_col"]),
            call(household_sheet_list[1], config["household_pk_col"]),
        )
    )


def test_process_households(config: Config, household_sheet: Sheet) -> None:
    job = Mock()
    batch = Mock()

    result = process_households(household_sheet, job, batch, config)

    assert result == {
        row[config["household_pk_col"]]: job.program.households.create.return_value for row in household_sheet
    }
    job.program.households.create.assert_has_calls(
        [
            call(batch=batch, name=row[config["master_column_label"]], flex_fields=normalize_row(row))
            for row in household_sheet
        ]
    )


def test_process_households_failed_to_save_household(config: Config, household_sheet: Sheet) -> None:
    job = Mock()
    batch = Mock()

    job.program.households.create.side_effect = Exception("Something went wrong")

    with pytest.raises(SheetProcessingError):
        process_households(household_sheet, job, batch, config)


def test_process_individuals(
    config: Config, individual_sheet: Sheet, household_mapping: Mapping[int, Household]
) -> None:
    job = Mock()
    batch = Mock()

    result = process_individuals(individual_sheet, household_mapping, job, batch, config)

    assert result == len(list(individual_sheet))
    job.program.individuals.create.assert_has_calls(
        [
            call(
                batch=batch,
                name=row[config["detail_column_label"]],
                household_id=household_mapping[row[config["household_pk_col"]]].pk,
                flex_fields=normalize_row(row),
            )
            for row in individual_sheet
        ]
    )


def test_validate_households(config: Config, household_mapping: Mapping[int, Mock]) -> None:
    config["check_before"] = True

    validate_households(config, household_mapping)

    for household in household_mapping.values():
        household.validate_with_checker.assert_called_once()


def test_validate_households_raises_exception_on_failed_validation(
    config: Config, household_mapping: Mapping[int, Mock]
) -> None:
    config["check_before"] = True
    household_mapping[HOUSEHOLD_1_PK].validate_with_checker.return_value = False

    with pytest.raises(HouseholdValidationError):
        validate_households(config, household_mapping)


def test_validate_households_check_before_is_false(config: Config, household_mapping: Mapping[int, Mock]) -> None:
    config["check_before"] = False

    validate_households(config, household_mapping)

    for household in household_mapping.values():
        household.validate_with_checker.assert_not_called()


def test_import_from_rdi(
    mocker: MockerFixture,
    config: Config,
    household_sheet: Sheet,
    individual_sheet: Sheet,
    household_mapping: Mapping[int, Mock],
) -> None:
    job = Mock()
    job.config = config
    batch_class_mock = mocker.patch("country_workspace.datasources.rdi.Batch")
    open_xls_multi_mock = mocker.patch("country_workspace.datasources.rdi.open_xls_multi")
    open_xls_multi_mock.return_value = (0, household_sheet), (1, individual_sheet)
    filter_rows_with_household_pk_mock = mocker.patch("country_workspace.datasources.rdi.filter_rows_with_household_pk")
    filter_rows_with_household_pk_mock.return_value = household_sheet, individual_sheet
    process_households_mock = mocker.patch("country_workspace.datasources.rdi.process_households")
    process_households_mock.return_value = household_mapping
    process_individuals_mock = mocker.patch("country_workspace.datasources.rdi.process_individuals")
    process_individuals_mock.return_value = (processed_individuals := len(list(individual_sheet)))
    validate_households_mock = mocker.patch("country_workspace.datasources.rdi.validate_households")

    result = import_from_rdi(job)

    assert result == {"household": len(household_mapping), "individual": processed_individuals}
    batch_class_mock.objects.create.assert_called_once_with(
        name=config["batch_name"],
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=batch_class_mock.BatchSource.RDI,
    )
    open_xls_multi_mock.assert_called_once_with(job.file, sheets=[0, 1])
    filter_rows_with_household_pk_mock.assert_called_once_with(config, household_sheet, individual_sheet)
    process_households_mock.assert_called_once_with(
        household_sheet, job, batch_class_mock.objects.create.return_value, config
    )
    process_individuals_mock.assert_called_once_with(
        individual_sheet, household_mapping, job, batch_class_mock.objects.create.return_value, config
    )
    validate_households_mock.assert_called_once_with(config, household_mapping)
