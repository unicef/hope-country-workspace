from typing import Mapping
from random import randint
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from country_workspace.datasources.rdi.config import Config, ErrorConfig, EMAIL_FROM, EMAIL_BODY, EMAIL_SUBJECT
from country_workspace.datasources.rdi.reports import (
    get_col_num_by_name,
    get_headers,
    add_errors_column,
    add_general_errors_row,
    fill_error_cell,
    process_sheet_errors,
    collect_household_errors,
    collect_individual_errors,
    save_and_send_errors_file,
    generate_errors_report,
)


@pytest.fixture
def mock_worksheet() -> MagicMock:
    return MagicMock(max_column=randint(1, 10), title="TestSheet")


@pytest.fixture
def mock_workbook() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_cell() -> MagicMock:
    return MagicMock(value=None)


@pytest.fixture
def household_mapping() -> Mapping[int, MagicMock]:
    return {
        1: MagicMock(errors={"field1": ["error1"], "field2": "error2"}),
        2: MagicMock(errors={}),
        3: MagicMock(errors={"field3": ["error3"]}),
    }


@pytest.fixture
def individual_mapping() -> Mapping[int, MagicMock]:
    return {1: MagicMock(pk=101), 2: MagicMock(pk=102)}


def test_get_headers_success(mock_worksheet: MagicMock) -> None:
    headers = tuple(f"header_{i}" for i in range(1, mock_worksheet.max_column + 1))
    mock_worksheet.iter_rows.return_value = [headers]

    result = get_headers(mock_worksheet)

    assert result == list(headers)
    mock_worksheet.iter_rows.assert_called_once_with(min_row=1, max_row=1, values_only=True)


def test_get_col_num_by_name_success(mock_worksheet: MagicMock) -> None:
    headers = tuple(f"col_{i}" for i in range(1, mock_worksheet.max_column + 1))
    mock_worksheet.iter_rows.return_value = [headers]

    col = randint(1, mock_worksheet.max_column)
    result = get_col_num_by_name(mock_worksheet, f"col_{col}")

    assert result == col
    mock_worksheet.iter_rows.assert_called_once_with(min_row=1, max_row=1, values_only=True)


def test_get_col_num_by_name_not_found(mock_worksheet: MagicMock) -> None:
    mock_worksheet.title = "TestSheet"
    mock_worksheet.iter_rows.return_value = [tuple(f"col_{i}" for i in range(1, mock_worksheet.max_column + 1))]

    with pytest.raises(ValueError, match=r"Column missing_col not found in sheet"):
        get_col_num_by_name(mock_worksheet, "missing_col")


def test_add_errors_column_success(mock_worksheet: MagicMock, mock_cell: MagicMock) -> None:
    mock_worksheet.iter_rows.return_value = [tuple(f"col_{i}" for i in range(1, mock_worksheet.max_column + 1))]
    mock_worksheet.cell.return_value = mock_cell

    new_col = mock_worksheet.max_column + 1
    result = add_errors_column(mock_worksheet)

    assert result == new_col
    mock_worksheet.cell.assert_called_once_with(1, new_col, ErrorConfig.ERRORS_COLUMN_NAME)


def test_add_errors_column_already_exists(mock_worksheet: MagicMock) -> None:
    mock_worksheet.iter_rows.return_value = [("col_1", ErrorConfig.ERRORS_COLUMN_NAME, "col_3")]

    result = add_errors_column(mock_worksheet)

    assert result == 2
    mock_worksheet.cell.assert_not_called()


def test_add_general_errors_row_empty_errors(mock_worksheet: MagicMock) -> None:
    add_general_errors_row(mock_worksheet, error_col_num=2, general_errors=set())

    mock_worksheet.insert_rows.assert_not_called()
    mock_worksheet.cell.assert_not_called()


def test_add_general_errors_row_success(mock_worksheet: MagicMock, mock_cell: MagicMock) -> None:
    mock_worksheet.cell.return_value = mock_cell
    general_errors = {"error2", "error1"}

    add_general_errors_row(mock_worksheet, error_col_num=2, general_errors=general_errors)

    mock_worksheet.insert_rows.assert_called_once_with(2)
    assert mock_worksheet.cell.call_count == 2
    assert "error1" in mock_cell.value
    assert "error2" in mock_cell.value
    assert " | " in mock_cell.value


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, False),
        ({"field1": ["e1", "e2"]}, True),
        ({"field1": "e"}, True),
        ({ErrorConfig.DCT_KEY: "special"}, True),
        ({ErrorConfig.DCT_KEY: ""}, False),
    ],
    ids=["empty", "list", "single", "dct", "dct_empty"],
)
def test_fill_error_cell(mock_cell: MagicMock, data: dict, expected: bool) -> None:
    result = fill_error_cell(mock_cell, data)
    assert result is expected
    if expected:
        assert mock_cell.value is not None
    else:
        assert mock_cell.value is None


def test_process_sheet_errors_empty_dict(mocker: MockerFixture, mock_worksheet: MagicMock) -> None:
    get_col = mocker.patch("country_workspace.datasources.rdi.reports.get_col_num_by_name")

    process_sheet_errors(mock_worksheet, "id_col", {}, first_line=randint(1, 10))

    get_col.assert_not_called()


@pytest.mark.parametrize(
    ("val", "errors_dict"),
    [
        (None, {1: {"x": "e"}}),
        ("abc", {1: {"x": "e"}}),
        ({}, {1: {"x": "e"}}),
        (123, {999: {"x": "e"}}),
    ],
    ids=["none", "value_error", "type_error", "not_raw"],
)
def test_process_sheet_errors_skips_rows(
    mocker: MockerFixture, mock_worksheet: MagicMock, mock_cell: MagicMock, val, errors_dict
) -> None:
    mock_cell.value, mock_cell.row = val, 3
    mock_worksheet.iter_rows.return_value = [[mock_cell]]

    mocks = mocker.patch.multiple(
        "country_workspace.datasources.rdi.reports",
        get_col_num_by_name=mocker.DEFAULT,
        add_errors_column=mocker.DEFAULT,
        fill_error_cell=mocker.DEFAULT,
        add_general_errors_row=mocker.DEFAULT,
    )
    mocks["get_col_num_by_name"].return_value = 1
    mocks["add_errors_column"].return_value = mock_worksheet.max_column + 1

    process_sheet_errors(mock_worksheet, "id_col", errors_dict, first_line=2)

    mocks["fill_error_cell"].assert_not_called()
    mocks["add_general_errors_row"].assert_called_once()
    assert not mocks["add_general_errors_row"].call_args.args[2]


def test_process_sheet_errors_success(mocker: MockerFixture, mock_worksheet: MagicMock) -> None:
    cell1, cell2 = MagicMock(), MagicMock()
    cell1.value, cell1.row = 101, 3
    cell2.value, cell2.row = 202, 4
    mock_worksheet.iter_rows.return_value = [[cell1], [cell2]]

    errors_dict = {
        101: {"field1": "e1", ErrorConfig.GENERAL_KEY: "b"},
        202: {"field2": ["e2"], ErrorConfig.GENERAL_KEY: "a"},
    }

    mocks = mocker.patch.multiple(
        "country_workspace.datasources.rdi.reports",
        get_col_num_by_name=mocker.DEFAULT,
        add_errors_column=mocker.DEFAULT,
        fill_error_cell=mocker.DEFAULT,
        add_general_errors_row=mocker.DEFAULT,
    )
    mocks["get_col_num_by_name"].return_value = 1
    mocks["add_errors_column"].return_value = mock_worksheet.max_column + 1

    process_sheet_errors(mock_worksheet, "id_col", errors_dict, first_line=2)

    assert mocks["fill_error_cell"].call_count == 2
    assert [c.args[1] for c in mocks["fill_error_cell"].call_args_list] == [
        {"field1": "e1"},
        {"field2": ["e2"]},
    ]
    _, _, general = mocks["add_general_errors_row"].call_args.args
    assert set(general) == {"a", "b"}


def test_collect_household_errors_success(household_mapping: Mapping[int, MagicMock]) -> None:
    expected = {hh_id: hh.errors for hh_id, hh in household_mapping.items() if hh.errors}
    result = collect_household_errors(household_mapping)
    assert result == expected


def test_collect_individual_errors_empty() -> None:
    result = collect_individual_errors({})
    assert result == {}


def test_collect_individual_errors_success(mocker: MockerFixture, individual_mapping: Mapping[int, MagicMock]) -> None:
    mock_mgr = mocker.patch("country_workspace.datasources.rdi.reports.Individual.objects")
    rows = [(ind.pk, {"field": f"error_{ind.pk}"}) for ind in individual_mapping.values()]
    mock_mgr.filter.return_value.exclude.return_value.values_list.return_value = rows

    expected = {orig_id: {"field": f"error_{ind.pk}"} for orig_id, ind in individual_mapping.items()}
    result = collect_individual_errors(individual_mapping)

    assert result == expected


def test_save_and_send_errors_file_success(mocker: MockerFixture, mock_workbook: MagicMock, config: Config) -> None:
    mock_email_cls = mocker.patch("country_workspace.datasources.rdi.reports.EmailMessage")
    mock_storage = mocker.patch("country_workspace.datasources.rdi.reports.MEDIA_STORAGE")

    saved_filename = "saved_filename.xlsx"
    base_filename = "base.xlsx"
    email = config["send_to"]
    expected_errors_filename = f"errors_{base_filename}"
    mock_storage.save.return_value = saved_filename

    result = save_and_send_errors_file(mock_workbook, base_filename, email)

    assert result == saved_filename
    mock_email_cls.assert_called_once_with(subject=EMAIL_SUBJECT, body=EMAIL_BODY, from_email=EMAIL_FROM, to=[email])
    mock_email_cls.return_value.attach.assert_called_once_with(expected_errors_filename, mocker.ANY, mocker.ANY)
    mock_email_cls.return_value.send.assert_called_once()


@pytest.mark.parametrize("scenario", ["no_config", "no_entities", "no_errors"])
def test_generate_errors_report_early_returns(
    mocker: MockerFixture,
    config: dict,
    household_mapping: Mapping[int, MagicMock],
    scenario: str,
) -> None:
    cfg = config if scenario != "no_config" else None
    kwargs = {}

    if scenario == "no_errors":
        for hh in household_mapping.values():
            hh.errors = {}
        kwargs["households"] = household_mapping
    # "no_entities" passes config but no households/individuals/people
    # "no_config" passes neither config nor entities

    mock_load_wb = mocker.patch("country_workspace.datasources.rdi.reports.load_workbook")

    result = generate_errors_report("base.xlsx", cfg, **kwargs)

    assert result is None
    mock_load_wb.assert_not_called()


def test_generate_errors_report_success(
    mocker: MockerFixture, config: Config, household_mapping: Mapping[int, MagicMock], mock_workbook: MagicMock
) -> None:
    mock_load_workbook = mocker.patch("country_workspace.datasources.rdi.reports.load_workbook")
    mock_save_and_send = mocker.patch("country_workspace.datasources.rdi.reports.save_and_send_errors_file")
    mock_process = mocker.patch("country_workspace.datasources.rdi.reports.process_sheet_errors")

    base_filename = "base.xlsx"
    saved_filename = "saved_file.xlsx"
    mock_load_workbook.return_value = mock_workbook
    mock_save_and_send.return_value = saved_filename

    result = generate_errors_report(base_filename, config, households=household_mapping)

    assert result == saved_filename
    mock_process.assert_called_once()
    mock_save_and_send.assert_called_once_with(mock_workbook, base_filename, config["send_to"])
    mock_load_workbook.assert_called_once_with(base_filename)


def test_generate_errors_report_failure(mocker: MockerFixture, household_mapping: Mapping[int, MagicMock]) -> None:
    mock_load_workbook = mocker.patch("country_workspace.datasources.rdi.reports.load_workbook")
    mock_load_workbook.side_effect = Exception("Test error")

    with pytest.raises(RuntimeError, match=r"Failed to generate or deliver the error report: .*Test error"):
        generate_errors_report("base.xlsx", config={"first_line": 1}, households=household_mapping)
