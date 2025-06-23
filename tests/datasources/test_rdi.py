from collections.abc import Mapping
from datetime import datetime, date
from unittest.mock import Mock, call, MagicMock

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT
from country_workspace.datasources.rdi import (
    ColumnConfigurationError,
    Config,
    Record,
    Sheet,
    SheetProcessingError,
    filter_rows_with_household_pk,
    get_value,
    import_from_rdi,
    process_households,
    process_individuals,
    image_location,
    image_content,
    extract_images,
    merge_images,
    read_sheets,
    full_name_column,
)
from country_workspace.datasources.utils import strip_time_iso
from country_workspace.models import Household
from country_workspace.workspaces.exceptions import BeneficiaryValidationError
from country_workspace.validators.beneficiaries import validate_beneficiaries


HOUSEHOLD_1_PK = 1
HOUSEHOLD_2_PK = 2
HOUSEHOLD_1_NAME = "Household 1"
HOUSEHOLD_2_NAME = "Household 2"
FULL_NAME_COLUMN = "full_name"


@pytest.fixture
def config() -> Config:
    return {
        "batch_name": "batch_name",
        "household_pk_col": "household_pk",
        "master_column_label": "master_column",
        "detail_column_label": "detail_column",
        "check_before": False,
        "fail_if_alien": False,
    }


@pytest.fixture
def household_sheet(config: Config) -> Sheet:
    return [
        {config["detail_column_label"]: HOUSEHOLD_1_NAME, config["household_pk_col"]: HOUSEHOLD_1_PK},
        {config["detail_column_label"]: HOUSEHOLD_1_NAME, config["household_pk_col"]: HOUSEHOLD_2_PK},
    ]


@pytest.fixture
def individual_sheet(config: Config) -> Sheet:
    return [
        {
            FULL_NAME_COLUMN: "John Doe",
            config["master_column_label"]: HOUSEHOLD_1_PK,
        },
        {
            FULL_NAME_COLUMN: "Doe John",
            config["master_column_label"]: HOUSEHOLD_2_PK,
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


def test_household_validation_error_format() -> None:
    error = BeneficiaryValidationError(beneficiary := HOUSEHOLD_1_NAME, key := HOUSEHOLD_1_PK)
    assert beneficiary in str(error)
    assert str(key) in str(error)


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

    result = list(filter_rows_with_household_pk(config, household_sheet))

    assert result == [household_sheet_list[0]]
    get_value_mock.assert_has_calls(
        (
            call(household_sheet_list[0], config["household_pk_col"]),
            call(household_sheet_list[1], config["household_pk_col"]),
        )
    )


def test_process_households(mocker: MockerFixture, config: Config, household_sheet: Sheet) -> None:
    clean_field_names_mock = mocker.patch("country_workspace.datasources.rdi.clean_field_names")

    result = process_households(household_sheet, job := Mock(), batch := Mock(), config)

    assert result == {
        row[config["household_pk_col"]]: job.program.households.create.return_value for row in household_sheet
    }
    job.program.households.create.assert_has_calls(
        [
            call(batch=batch, name=row[config["detail_column_label"]], flex_fields=clean_field_names_mock.return_value)
            for row in household_sheet
        ]
    )
    clean_field_names_mock.assert_has_calls((call(row) for row in household_sheet))


def test_process_households_failed_to_save_household(config: Config, household_sheet: Sheet) -> None:
    job = Mock()
    batch = Mock()

    job.program.households.create.side_effect = Exception("Something went wrong")

    with pytest.raises(SheetProcessingError):
        process_households(household_sheet, job, batch, config)


def test_process_individuals(
    mocker: MockerFixture, config: Config, individual_sheet: Sheet, household_mapping: Mapping[int, Household]
) -> None:
    clean_field_names_mock = mocker.patch("country_workspace.datasources.rdi.clean_field_names")

    result = process_individuals(
        individual_sheet, household_mapping, job_mock := Mock(name="job"), batch_mock := Mock(name="batch"), config
    )

    assert result == len(list(individual_sheet))
    job_mock.program.individuals.create.assert_has_calls(
        [
            call(
                batch=batch_mock,
                name=row[FULL_NAME_COLUMN],
                household_id=household_mapping[row[config["master_column_label"]]].pk,
                flex_fields=clean_field_names_mock.return_value,
            )
            for row in individual_sheet
        ]
    )
    clean_field_names_mock.assert_has_calls([call(row) for row in individual_sheet])


def test_validate_beneficiaries(config: Config, household_mapping: Mapping[int, Mock]) -> None:
    config["check_before"] = True

    validate_beneficiaries(config, household_mapping)

    for household in household_mapping.values():
        household.validate_with_checker.assert_called_once()


def test_validate_beneficiaries_raises_exception_on_failed_validation(
    config: Config, household_mapping: Mapping[int, Mock]
) -> None:
    config["check_before"] = True
    household_mapping[HOUSEHOLD_1_PK].validate_with_checker.return_value = False

    with pytest.raises(BeneficiaryValidationError):
        validate_beneficiaries(config, household_mapping)


def test_validate_beneficiaries_check_before_is_false(config: Config, household_mapping: Mapping[int, Mock]) -> None:
    config["check_before"] = False

    validate_beneficiaries(config, household_mapping)

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
    read_sheets_mock = mocker.patch("country_workspace.datasources.rdi.read_sheets")
    read_sheets_mock.return_value = household_sheet, individual_sheet
    process_households_mock = mocker.patch("country_workspace.datasources.rdi.process_households")
    process_households_mock.return_value = household_mapping
    process_individuals_mock = mocker.patch("country_workspace.datasources.rdi.process_individuals")
    process_individuals_mock.return_value = (processed_individuals := len(list(individual_sheet)))
    validate_beneficiaries_mock = mocker.patch("country_workspace.datasources.rdi.validate_beneficiaries")

    result = import_from_rdi(job)

    assert result == {"household": len(household_mapping), "individual": processed_individuals}
    batch_class_mock.objects.create.assert_called_once_with(
        name=config["batch_name"],
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=batch_class_mock.BatchSource.RDI,
    )
    process_households_mock.assert_called_once_with(
        household_sheet, job, batch_class_mock.objects.create.return_value, config
    )
    process_individuals_mock.assert_called_once_with(
        individual_sheet, household_mapping, job, batch_class_mock.objects.create.return_value, config
    )
    validate_beneficiaries_mock.assert_called_once_with(config, household_mapping)


def test_image_location() -> None:
    result = image_location(image := Mock())
    assert result == (image.anchor._from.row, image.anchor._from.col)


def test_image_content(mocker: MockerFixture) -> None:
    image_module_mock = mocker.patch("country_workspace.datasources.rdi.Image")
    b64encode_mock = mocker.patch("country_workspace.datasources.rdi.b64encode")

    result = image_content(image := Mock())

    assert result == (image_module_mock.MIME.get.return_value, b64encode_mock.return_value.decode.return_value)
    image_module_mock.open.assert_called_once_with(image.ref)
    image_module_mock.MIME.get.assert_called_once_with(image_module_mock.open.return_value.format)
    image.ref.seek.assert_called_once_with(0)
    b64encode_mock.assert_called_once_with(image.ref.read.return_value)


def test_extract_images(mocker: MockerFixture) -> None:
    load_workbook_mock = mocker.patch("country_workspace.datasources.rdi.openpyxl.load_workbook")
    image_location_mock = mocker.patch("country_workspace.datasources.rdi.image_location")
    image_location_mock.return_value = (row := 1, column := 2)
    image_content_mock = mocker.patch("country_workspace.datasources.rdi.image_content")
    image_content_mock.return_value = (content_type := "content/type", content := "content")
    image = MagicMock()
    load_workbook_mock.return_value.worksheets.__getitem__.return_value._images = (image,)

    result = list(extract_images(filepath := "test", sheet_index := 0))

    assert result == [{row - 1: {column: VALUE_FORMAT.format(mimetype=content_type, content=content)}}]
    load_workbook_mock.assert_called_once_with(filepath)
    load_workbook_mock.return_value.worksheets.__getitem__.assert_called_once_with(sheet_index)
    image_location_mock.assert_called_once_with(image)
    image_content_mock.assert_called_once_with(image)


def test_merge_images() -> None:
    sheet = (
        {(column := "column"): "value"},
        second_row := {"column": "value"},
    )
    sheet_images = {0: {0: (image_data := "IMAGE_DATA")}}

    result = list(merge_images(sheet, sheet_images))

    assert result == [{column: image_data}, second_row]


def test_read_sheets(mocker: MockerFixture) -> None:
    fake_sheets = ((Mock(), sheet := Mock()),)
    strip_time_iso_mock = mocker.patch("country_workspace.datasources.rdi.strip_time_iso")
    open_xls_multi_mock = mocker.patch("country_workspace.datasources.rdi.open_xls_multi")
    open_xls_multi_mock.return_value = fake_sheets
    extract_images_mock = mocker.patch("country_workspace.datasources.rdi.extract_images")
    extract_images_mock.return_value = ((images := Mock()),)
    merge_images_mock = mocker.patch("country_workspace.datasources.rdi.merge_images")
    filter_rows_with_household_pk_mock = mocker.patch("country_workspace.datasources.rdi.filter_rows_with_household_pk")
    config_mock = Mock()

    result = list(read_sheets(config_mock, filepath := "test", sheet_index := 0))

    assert result == [filter_rows_with_household_pk_mock.return_value]
    open_xls_multi_mock.assert_called_once_with(filepath, sheets=[sheet_index], value_mapper=strip_time_iso_mock)
    extract_images_mock.assert_called_once_with(filepath, sheet_index)
    merge_images_mock.assert_called_once_with(sheet, images)
    filter_rows_with_household_pk_mock.assert_called_once_with(config_mock, merge_images_mock.return_value)


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"full_name": "John Smith"}, "full_name"),
        ({}, None),
        ({"name_full": "John Smith"}, None),
    ],
)
def test_full_name_column(record: Record, expected: str | None) -> None:
    assert full_name_column(record) == expected


@pytest.mark.parametrize(
    ("inp", "expected"),
    [
        ("2025-05-15 12:34:56", "2025-05-15"),
        ("2025-05-15", "2025-05-15"),
        ("foo bar", "foo bar"),
        (123, 123),
        (datetime.fromisoformat("2025-05-15 00:00:00"), datetime.fromisoformat("2025-05-15 00:00:00")),
        (date(2020, 1, 1), date(2020, 1, 1)),
    ],
    ids=["str_with_time", "str_date_only", "str_non_date", "numeric", "datetime_obj", "date_obj"],
)
def test_strip_time_iso(inp, expected):
    assert strip_time_iso(inp) == expected
