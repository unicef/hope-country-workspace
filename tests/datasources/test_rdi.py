from unittest.mock import MagicMock, Mock, call

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
)


def test_column_configuration_error() -> None:
    error = ColumnConfigurationError(column_name := "test_column")
    assert column_name in str(error)


def test_sheet_processing_error() -> None:
    error = SheetProcessingError(sheet_name := "test_sheet", row_index := 42)
    assert sheet_name in str(error)
    assert str(row_index) in str(error)


def test_missing_household_error() -> None:
    error = MissingHouseholdError(row_index := 42, household_key := "test_household_key")
    assert str(row_index) in str(error)
    assert household_key in str(error)


def test_household_validation_error() -> None:
    error = HouseholdValidationError(household_key := "test_household_key")
    assert household_key in str(error)


def test_normalize_row(mocker: MockerFixture) -> None:
    row = MagicMock()
    row.items.return_value.__iter__.return_value = [((key := "key"), (value := "value"))]
    clean_field_name_mock = mocker.patch("country_workspace.datasources.rdi.clean_field_name")

    result = normalize_row(row)

    assert result == {clean_field_name_mock.return_value: value}
    clean_field_name_mock.assert_called_once_with(key)


def test_get_value() -> None:
    row = MagicMock()
    row.__contains__.return_value = True

    value = get_value(row, "column")

    assert value == row.__getitem__.return_value


def test_get_value_key_is_missing() -> None:
    row = MagicMock()
    row.__contains__.return_value = False

    with pytest.raises(ColumnConfigurationError):
        get_value(row, "column")


def test_filter_rows_with_household_pk(mocker: MockerFixture) -> None:
    config = MagicMock()
    sheet = MagicMock()
    row_with_household_pk = Mock()
    row_without_household_pk = Mock()
    sheet.__iter__.return_value = row_with_household_pk, row_without_household_pk
    get_value_mock = mocker.patch("country_workspace.datasources.rdi.get_value")
    get_value_mock.side_effect = True, False

    result = [list(sheet) for sheet in filter_rows_with_household_pk(config, sheet)]

    assert result == [[row_with_household_pk]]
    config.__getitem__.assert_called_once_with("household_pk_col")
    get_value_mock.assert_has_calls(
        (
            call(row_with_household_pk, config.__getitem__.return_value),
            call(row_without_household_pk, config.__getitem__.return_value),
        )
    )
