from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any

import pytest
from pytest_mock import MockerFixture

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT
from country_workspace.datasources.rdi.config import Config, Record, Sheet, SheetName
from country_workspace.datasources.rdi.exceptions import (
    ColumnConfigurationError,
    SheetNotFoundError,
    SheetProcessingError,
)
from country_workspace.datasources.rdi.processors import (
    BeneficiaryImportResult,
    extract_images,
    filter_rows_with_household_pk,
    get_value,
    image_content,
    image_location,
    import_from_rdi,
    merge_images,
    normalize_row_structure,
    process_beneficiaries,
    process_households,
    read_sheets,
    _sync_ind_pks,
)
from country_workspace.datasources.rdi.utils import date_to_iso_string, datetime_to_date
from country_workspace.models import Batch, Household, Individual
from country_workspace.models.jobs import GracefulJobCancellationError
from country_workspace.workspaces.exceptions import BeneficiaryValidationError


HOUSEHOLD_1_PK = 1
HOUSEHOLD_2_PK = 2
HOUSEHOLD_1_NAME = "Household 1"
HOUSEHOLD_2_NAME = "Household 2"
INDIVIDUAL_1_PK = 1
INDIVIDUAL_2_PK = 2
FULL_NAME_COLUMN = "full_name"


@pytest.fixture(autouse=True)
def _mock_bitcaster_dispatch(mocker: MockerFixture):
    return mocker.patch("country_workspace.notifications.handlers.send_bitcaster_event_task.delay")


@pytest.fixture
def skip_if_not_master_detail(config: Config) -> None:
    if not config["master_detail"]:
        pytest.skip("Not applicable for people-only mode")


@pytest.fixture
def skip_if_master_detail(config: Config) -> None:
    if config["master_detail"]:
        pytest.skip("Not applicable for master-detail mode")


@pytest.fixture
def household_sheet(config: Config) -> Sheet:
    return [
        {config["household_label"]: HOUSEHOLD_1_NAME, config["household_id_column"]: HOUSEHOLD_1_PK},
        {config["household_label"]: HOUSEHOLD_1_NAME, config["household_id_column"]: HOUSEHOLD_2_PK},
    ]


@pytest.fixture
def individual_sheet(config: Config) -> Sheet:
    return [
        {
            FULL_NAME_COLUMN: "John Doe",
            config["household_id_column"]: HOUSEHOLD_1_PK,
            config["beneficiary_id_column"]: INDIVIDUAL_1_PK,
        },
        {
            FULL_NAME_COLUMN: "Doe John",
            config["household_id_column"]: HOUSEHOLD_2_PK,
            config["beneficiary_id_column"]: INDIVIDUAL_2_PK,
        },
    ]


@pytest.fixture
def people_sheet(config: Config) -> Sheet:
    prefix = config.get("people_prefix", "")
    return [
        {
            f"{prefix}{FULL_NAME_COLUMN}": "John Doe",
            config["beneficiary_id_column"]: INDIVIDUAL_1_PK,
        },
        {
            f"{prefix}{FULL_NAME_COLUMN}": "Jane Smith",
            config["beneficiary_id_column"]: INDIVIDUAL_2_PK,
        },
    ]


@pytest.fixture
def household_mapping(mocker: MockerFixture) -> Mapping[int, Any]:
    return {
        HOUSEHOLD_1_PK: mocker.MagicMock(name=HOUSEHOLD_1_NAME),
        HOUSEHOLD_2_PK: mocker.MagicMock(name=HOUSEHOLD_2_NAME),
    }


@pytest.fixture
def canonical_transform(mocker: MockerFixture, config: Config):
    """Patch the import processor to map the sheet's id column onto ``individual_id``."""
    return mocker.patch(
        "country_workspace.datasources.rdi.processors.build_import_processor",
        return_value=lambda row: dict(row, individual_id=row[config["beneficiary_id_column"]]),
    )


@pytest.fixture
def duplicate_household_sheet(config: Config) -> Sheet:
    return [
        {config["household_label"]: HOUSEHOLD_1_NAME, config["household_id_column"]: HOUSEHOLD_1_PK},
        {config["household_label"]: HOUSEHOLD_2_NAME, config["household_id_column"]: HOUSEHOLD_1_PK},
    ]


@pytest.fixture
def duplicate_individual_sheet(config: Config) -> Sheet:
    return [
        {
            FULL_NAME_COLUMN: "John Doe",
            config["household_id_column"]: HOUSEHOLD_1_PK,
            config["beneficiary_id_column"]: INDIVIDUAL_1_PK,
        },
        {
            FULL_NAME_COLUMN: "Jane Doe",
            config["household_id_column"]: HOUSEHOLD_2_PK,
            config["beneficiary_id_column"]: INDIVIDUAL_1_PK,
        },
    ]


@pytest.fixture
def duplicate_people_sheet(config: Config) -> Sheet:
    prefix = config.get("people_prefix", "")
    return [
        {f"{prefix}{FULL_NAME_COLUMN}": "John Doe", config["beneficiary_id_column"]: INDIVIDUAL_1_PK},
        {f"{prefix}{FULL_NAME_COLUMN}": "Jane Smith", config["beneficiary_id_column"]: INDIVIDUAL_1_PK},
    ]


@pytest.fixture
def people_mapping(mocker: MockerFixture, people_sheet: Sheet) -> Mapping[int, Any]:
    return {i: mocker.MagicMock(pk=i, flex_fields={}) for i in range(len(list(people_sheet)))}


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


def test_sheet_not_found_error_format() -> None:
    error = SheetNotFoundError(sheet_name := "first")
    assert sheet_name in str(error)

    error_multiple = SheetNotFoundError(sheet_names := ("first", "second"))
    for idx in sheet_names:
        assert str(idx) in str(error_multiple)


def test_get_value_returns_value() -> None:
    row = {(column := "column"): (column_value := "value")}

    value = get_value(row, column)

    assert value == column_value


def test_get_value_raise_exception_when_key_is_missing() -> None:
    row: Record = {}

    with pytest.raises(ColumnConfigurationError):
        get_value(row, "column")


def test_filter_rows_with_household_pk(
    mocker: MockerFixture,
    config: Config,
    household_sheet: Sheet,
    skip_if_not_master_detail: None,
) -> None:
    household_sheet_list = list(household_sheet)
    get_value_mock = mocker.patch("country_workspace.datasources.rdi.processors.get_value")
    get_value_mock.side_effect = True, None

    result = list(filter_rows_with_household_pk(config, household_sheet))

    assert result == [household_sheet_list[0]]
    get_value_mock.assert_has_calls(
        (
            mocker.call(household_sheet_list[0], config["household_id_column"]),
            mocker.call(household_sheet_list[1], config["household_id_column"]),
        )
    )


@pytest.mark.parametrize(
    ("row", "prefix", "expected_row"),
    [
        ({"full_name": "John"}, None, {"full_name": "John"}),
        ({"pp_full_name": "Jane"}, "pp_", {"full_name": "Jane"}),
        ({"no_prefix": "value"}, "wrong_", {"no_prefix": "value"}),
    ],
    ids=["no_prefix", "with_prefix", "prefix_not_found"],
)
def test_normalize_row_structure_prefix_handling(row: Record, prefix: str | None, expected_row: Record) -> None:
    result_row, _ = normalize_row_structure(row, prefix)
    assert result_row == expected_row


@pytest.mark.parametrize(
    ("row", "expected_name_column"),
    [
        ({"full_name": "John"}, "full_name"),
        ({"age": 30}, None),
    ],
    ids=["full_name", "no_name"],
)
def test_normalize_row_structure_name_column_detection(row: Record, expected_name_column: str | None) -> None:
    _, name_column = normalize_row_structure(row)
    assert name_column == expected_name_column


def test_process_households(
    mocker: MockerFixture,
    config: Config,
    household_sheet: Sheet,
    skip_if_not_master_detail: None,
) -> None:
    mock_create = mocker.patch("country_workspace.datasources.rdi.processors.Household.objects.create")
    mock_create.return_value = mocker.MagicMock()

    processor_mock = mocker.MagicMock(return_value={"processed": "value"})
    build_processor_mock = mocker.patch(
        "country_workspace.datasources.rdi.processors.build_import_processor",
        return_value=processor_mock,
    )
    job = mocker.MagicMock()
    job.file.name = "uploads/rdi.xlsx"
    batch = mocker.MagicMock()
    batch.import_date.timestamp.return_value = 1_234_567_890.123

    result = process_households(household_sheet, job, batch, config)

    assert result == {row[config["household_id_column"]]: mock_create.return_value for row in household_sheet}

    build_processor_mock.assert_called_once_with(
        program=job.program,
        model=Household,
        mapping_id=config.get("household_mapping_id"),
        source=Batch.BatchSource.RDI,
    )
    processor_mock.assert_has_calls([mocker.call(row) for row in household_sheet])

    mock_create.assert_has_calls(
        [
            mocker.call(
                batch_id=batch.pk,
                name=str(row[config["household_label"]]),
                flex_fields=processor_mock.return_value,
                raw_data=row,
                originating_id=f"XLS#rdi.xlsx#{row[config['household_id_column']]}#1234567890123",
            )
            for row in household_sheet
        ]
    )


def test_process_households_failed_to_save_household(
    mocker: MockerFixture,
    config: Config,
    household_sheet: Sheet,
    skip_if_not_master_detail: None,
) -> None:
    job = mocker.MagicMock()
    job.file.name = "uploads/rdi.xlsx"
    batch = mocker.MagicMock()

    mocker.patch("country_workspace.datasources.rdi.processors.build_import_processor", return_value=lambda row: row)
    mocker.patch(
        "country_workspace.datasources.rdi.processors.Household.objects.create",
        side_effect=Exception("Something went wrong"),
    )

    with pytest.raises(SheetProcessingError):
        process_households(household_sheet, job, batch, config)


def test_process_beneficiaries_with_households(
    mocker: MockerFixture,
    config: Config,
    individual_sheet: Sheet,
    household_mapping: Mapping[int, Household],
    skip_if_not_master_detail: None,
) -> None:
    mock_create = mocker.patch("country_workspace.datasources.rdi.processors.Individual.objects.create")
    mock_create.return_value = mocker.MagicMock()

    job_mock = mocker.MagicMock(name="job")
    job_mock.file.name = "uploads/rdi.xlsx"
    processor_mock = mocker.MagicMock(return_value={"processed": "value"})
    build_processor_mock = mocker.patch(
        "country_workspace.datasources.rdi.processors.build_import_processor",
        return_value=processor_mock,
    )
    batch_mock = mocker.MagicMock(name="batch")
    batch_mock.import_date.timestamp.return_value = 1_234_567_890.123

    result = process_beneficiaries(
        individual_sheet,
        job_mock,
        batch_mock,
        config,
        household_mapping,
    )

    assert len(result.mapping) == len(list(individual_sheet))
    build_processor_mock.assert_called_once_with(
        program=job_mock.program,
        model=Individual,
        mapping_id=config.get("individual_mapping_id"),
        source=Batch.BatchSource.RDI,
    )
    processor_mock.assert_has_calls([mocker.call(row) for row in individual_sheet])

    mock_create.assert_has_calls(
        [
            mocker.call(
                batch_id=batch_mock.pk,
                name=row[FULL_NAME_COLUMN],
                household=household_mapping[row[config["household_id_column"]]],
                flex_fields=processor_mock.return_value,
                raw_data=row,
                originating_id=f"XLS#rdi.xlsx#{row[config['beneficiary_id_column']]}#1234567890123",
            )
            for row in individual_sheet
        ]
    )


@pytest.mark.parametrize(
    ("household_id", "expected_count"),
    [(None, 0), ("", 0), (0, 1), ("0", 1), (HOUSEHOLD_1_PK, 1)],
    ids=["none", "empty_string", "zero_int", "zero_string", "valid"],
)
def test_filter_rows_with_household_pk_values(
    config: Config,
    household_id: Any,
    expected_count: int,
    skip_if_not_master_detail: None,
) -> None:
    sheet: Sheet = [{config["household_id_column"]: household_id, config["household_label"]: HOUSEHOLD_1_NAME}]

    result = list(filter_rows_with_household_pk(config, sheet))

    assert len(result) == expected_count


@pytest.mark.parametrize("zero_household_id", [0, "0"], ids=["zero_int", "zero_string"])
def test_process_beneficiaries_with_zero_household_id(
    mocker: MockerFixture,
    config: Config,
    individual_sheet: Sheet,
    household_mapping: Mapping[int, Household],
    zero_household_id: Any,
    skip_if_not_master_detail: None,
) -> None:
    mock_create = mocker.patch("country_workspace.datasources.rdi.processors.Individual.objects.create")
    mocker.patch("country_workspace.datasources.rdi.processors.build_import_processor", return_value=lambda row: row)
    collector_mock = mocker.patch("country_workspace.datasources.rdi.processors.get_or_create_collector")
    collector_mock.return_value = (collector := mocker.MagicMock(name="collector")), True
    logger_mock = mocker.patch("country_workspace.datasources.rdi.processors.logger")
    job_mock = mocker.MagicMock(name="job")
    job_mock.file.name = "uploads/rdi.xlsx"
    batch_mock = mocker.MagicMock(name="batch")
    sheet = [dict(individual_sheet[0], **{config["household_id_column"]: zero_household_id})]

    result = process_beneficiaries(sheet, job_mock, batch_mock, config, household_mapping)

    assert len(result.mapping) == 1
    assert result.mapping[sheet[0][config["beneficiary_id_column"]]] is collector
    mock_create.assert_not_called()  # external collectors go through get_or_create_collector
    collector_mock.assert_called_once()
    logger_mock.error.assert_not_called()


def test_process_beneficiaries_skips_invalid_household_reference(
    mocker: MockerFixture,
    config: Config,
    individual_sheet: Sheet,
    household_mapping: Mapping[int, Household],
    skip_if_not_master_detail: None,
) -> None:
    mock_create = mocker.patch(
        "country_workspace.datasources.rdi.processors.Individual.objects.create",
        return_value=mocker.MagicMock(),
    )
    mocker.patch("country_workspace.datasources.rdi.processors.build_import_processor", return_value=lambda row: row)
    logger_mock = mocker.patch("country_workspace.datasources.rdi.processors.logger")
    job_mock = mocker.MagicMock(name="job")
    job_mock.file.name = "uploads/rdi.xlsx"
    batch_mock = mocker.MagicMock(name="batch")
    invalid_household_id = 999
    sheet = [individual_sheet[0], dict(individual_sheet[1], **{config["household_id_column"]: invalid_household_id})]

    result = process_beneficiaries(sheet, job_mock, batch_mock, config, household_mapping)

    assert len(result.mapping) == 1
    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["household"] is household_mapping[HOUSEHOLD_1_PK]
    logger_mock.error.assert_called_once()
    log_args = " ".join(str(arg) for arg in logger_mock.error.call_args.args)
    assert str(invalid_household_id) in log_args
    assert str(sheet[1][config["beneficiary_id_column"]]) in log_args


def test_process_beneficiaries_deduplicates_external_collectors(
    mocker: MockerFixture,
    config: Config,
    individual_sheet: Sheet,
    household_mapping: Mapping[int, Household],
    skip_if_not_master_detail: None,
) -> None:
    mock_create = mocker.patch("country_workspace.datasources.rdi.processors.Individual.objects.create")
    mocker.patch("country_workspace.datasources.rdi.processors.build_import_processor", return_value=lambda row: row)
    collector_mock = mocker.patch("country_workspace.datasources.rdi.processors.get_or_create_collector")
    existing_collector = mocker.MagicMock(name="existing_collector")
    collector_mock.return_value = (existing_collector, False)
    job_mock = mocker.MagicMock(name="job")
    job_mock.file.name = "uploads/rdi.xlsx"
    batch_mock = mocker.MagicMock(name="batch")
    batch_mock.import_date.timestamp.return_value = 1_234_567_890.123
    collector_row = dict(individual_sheet[1], **{config["household_id_column"]: 0})
    sheet = [individual_sheet[0], collector_row]

    result = process_beneficiaries(sheet, job_mock, batch_mock, config, household_mapping)

    assert len(result.mapping) == 2
    assert result.mapping[collector_row[config["beneficiary_id_column"]]] is existing_collector
    mock_create.assert_called_once()  # only the non-collector row is created directly
    assert mock_create.call_args.kwargs["household"] is household_mapping[HOUSEHOLD_1_PK]
    collector_mock.assert_called_once_with(
        program=batch_mock.program,
        batch=batch_mock,
        individual_fields=collector_row,
        raw_data=collector_row,
        originating_id=f"XLS#rdi.xlsx#{collector_row[config['beneficiary_id_column']]}#1234567890123",
        name=collector_row[FULL_NAME_COLUMN],
    )


STALE_COLLECTOR_ID = 99  # the individual_id the collector had in the import that created it
REUSED_COLLECTOR_PK = 801
MEMBER_PK = 900


@pytest.fixture
def reused_collector(mocker: MockerFixture):
    """A collector created by an earlier import, so carrying that import's individual_id."""
    collector = mocker.MagicMock(name="reused_collector", pk=REUSED_COLLECTOR_PK)
    collector.flex_fields = {"individual_id": STALE_COLLECTOR_ID}
    mocker.patch(
        "country_workspace.datasources.rdi.processors.get_or_create_collector",
        return_value=(collector, False),
    )
    return collector


def test_process_beneficiaries_indexes_reused_collector_by_current_sheet_id(
    mocker: MockerFixture,
    config: Config,
    household_mapping: Mapping[int, Household],
    canonical_transform: None,
    reused_collector: Any,
    skip_if_not_master_detail: None,
) -> None:
    mocker.patch(
        "country_workspace.datasources.rdi.processors.Individual.objects.create",
        side_effect=lambda **kwargs: mocker.MagicMock(pk=MEMBER_PK, flex_fields=kwargs["flex_fields"]),
    )
    job_mock = mocker.MagicMock(name="job")
    job_mock.file.name = "uploads/rdi.xlsx"
    collector_sheet_id = 4
    sheet = [
        {
            FULL_NAME_COLUMN: "Omar Said",
            config["household_id_column"]: HOUSEHOLD_1_PK,
            config["beneficiary_id_column"]: 3,
        },
        {
            FULL_NAME_COLUMN: "Maria Rossi",
            config["household_id_column"]: 0,
            config["beneficiary_id_column"]: collector_sheet_id,
        },
    ]

    result = process_beneficiaries(sheet, job_mock, mocker.MagicMock(name="batch"), config, household_mapping)

    assert result.mapping[collector_sheet_id] is reused_collector
    assert result.reference_pks == {"3": MEMBER_PK, str(collector_sheet_id): REUSED_COLLECTOR_PK}
    assert str(STALE_COLLECTOR_ID) not in result.reference_pks


def test_sync_ind_pks_links_household_to_reused_collector(
    mocker: MockerFixture,
    config: Config,
    household_mapping: Mapping[int, Household],
    canonical_transform: None,
    reused_collector: Any,
    skip_if_not_master_detail: None,
) -> None:
    """A household must reach a reused collector through the id used in its own sheet."""
    mocker.patch(
        "country_workspace.datasources.rdi.processors.Individual.objects.create",
        side_effect=lambda **kwargs: mocker.MagicMock(pk=MEMBER_PK, flex_fields=kwargs["flex_fields"]),
    )
    job_mock = mocker.MagicMock(name="job")
    job_mock.file.name = "uploads/rdi.xlsx"
    fields = HOUSEHOLD_ROLE_REF_FIELDS
    household = mocker.MagicMock(name="household", pk=600)
    household.flex_fields = {fields.head_of_household: 3, fields.primary_collector: 4}
    sheet = [
        {
            FULL_NAME_COLUMN: "Omar Said",
            config["household_id_column"]: HOUSEHOLD_1_PK,
            config["beneficiary_id_column"]: 3,
        },
        {FULL_NAME_COLUMN: "Maria Rossi", config["household_id_column"]: 0, config["beneficiary_id_column"]: 4},
    ]

    result = process_beneficiaries(sheet, job_mock, mocker.MagicMock(name="batch"), config, household_mapping)
    _sync_ind_pks({HOUSEHOLD_1_PK: household}, result.reference_pks)

    assert household.flex_fields[fields.head_of_household] == MEMBER_PK
    assert household.flex_fields[fields.primary_collector] == REUSED_COLLECTOR_PK
    household.save.assert_called_once_with(update_fields=["flex_fields"])


def test_sync_ind_pks_stale_collector_id_does_not_shadow_a_member(
    mocker: MockerFixture,
    config: Config,
    household_mapping: Mapping[int, Household],
    canonical_transform: None,
    reused_collector: Any,
    skip_if_not_master_detail: None,
) -> None:
    """A member whose sheet id equals the reused collector's stale id must win its own role."""
    mocker.patch(
        "country_workspace.datasources.rdi.processors.Individual.objects.create",
        side_effect=lambda **kwargs: mocker.MagicMock(pk=MEMBER_PK, flex_fields=kwargs["flex_fields"]),
    )
    job_mock = mocker.MagicMock(name="job")
    job_mock.file.name = "uploads/rdi.xlsx"
    fields = HOUSEHOLD_ROLE_REF_FIELDS
    household = mocker.MagicMock(name="household", pk=600)
    household.flex_fields = {fields.head_of_household: STALE_COLLECTOR_ID, fields.primary_collector: 4}
    sheet = [
        {
            FULL_NAME_COLUMN: "Jean Baptiste",
            config["household_id_column"]: HOUSEHOLD_1_PK,
            config["beneficiary_id_column"]: STALE_COLLECTOR_ID,
        },
        {FULL_NAME_COLUMN: "Maria Rossi", config["household_id_column"]: 0, config["beneficiary_id_column"]: 4},
    ]

    result = process_beneficiaries(sheet, job_mock, mocker.MagicMock(name="batch"), config, household_mapping)
    _sync_ind_pks({HOUSEHOLD_1_PK: household}, result.reference_pks)

    assert household.flex_fields[fields.head_of_household] == MEMBER_PK
    assert household.flex_fields[fields.primary_collector] == REUSED_COLLECTOR_PK


def test_sync_ind_pks_clears_and_reports_unresolved_reference(mocker: MockerFixture) -> None:
    logger_mock = mocker.patch("country_workspace.datasources.rdi.processors.logger")
    fields = HOUSEHOLD_ROLE_REF_FIELDS
    household = mocker.MagicMock(name="household", pk=600)
    missing_id = 77
    household.flex_fields = {
        fields.head_of_household: 3,
        fields.primary_collector: missing_id,
        fields.alternate_collector: 8,
    }

    _sync_ind_pks({HOUSEHOLD_1_PK: household}, {"3": MEMBER_PK, "8": REUSED_COLLECTOR_PK})

    assert household.flex_fields[fields.head_of_household] == MEMBER_PK
    assert household.flex_fields[fields.alternate_collector] == REUSED_COLLECTOR_PK
    # a sheet-local id left in place would later be read as a pk
    assert household.flex_fields[fields.primary_collector] is None
    logger_mock.warning.assert_called_once()
    assert str(missing_id) in " ".join(str(arg) for arg in logger_mock.warning.call_args.args)


def test_process_beneficiaries_people_only(
    mocker: MockerFixture,
    config: Config,
    people_sheet: Sheet,
    skip_if_master_detail: None,
) -> None:
    mock_create = mocker.patch("country_workspace.datasources.rdi.processors.Individual.objects.create")
    mock_create.return_value = mocker.MagicMock()

    processor_mock = mocker.MagicMock(return_value={"processed": "value"})
    build_processor_mock = mocker.patch(
        "country_workspace.datasources.rdi.processors.build_import_processor",
        return_value=processor_mock,
    )
    job_mock = mocker.MagicMock(name="job")
    job_mock.file.name = "uploads/rdi.xlsx"
    batch_mock = mocker.MagicMock(name="batch")
    batch_mock.import_date.timestamp.return_value = 1_234_567_890.123

    result = process_beneficiaries(
        people_sheet,
        job_mock,
        batch_mock,
        config,
        None,
    )

    assert len(result.mapping) == len(list(people_sheet))
    build_processor_mock.assert_called_once_with(
        program=job_mock.program,
        model=Individual,
        mapping_id=config.get("individual_mapping_id"),
        source=Batch.BatchSource.RDI,
    )

    expected_calls = []
    for row in people_sheet:
        prefix = config.get("people_prefix", "")
        cleaned_row = {k.removeprefix(prefix): v for k, v in row.items()}
        expected_calls.append(
            mocker.call(
                batch_id=batch_mock.pk,
                name=cleaned_row[FULL_NAME_COLUMN],
                household=None,
                flex_fields=processor_mock.return_value,
                raw_data=row,
                originating_id=f"XLS#rdi.xlsx#{row[config['beneficiary_id_column']]}#1234567890123",
            )
        )

    mock_create.assert_has_calls(expected_calls)
    processor_mock.assert_has_calls(
        [
            mocker.call({k.removeprefix(config.get("people_prefix", "")): v for k, v in row.items()})
            for row in people_sheet
        ]
    )


def test_process_beneficiaries_failed_to_create(
    mocker: MockerFixture,
    config: Config,
    individual_sheet: Sheet,
    people_sheet: Sheet,
    household_mapping: Mapping[int, Any],
) -> None:
    job = mocker.MagicMock()
    job.file.name = "uploads/rdi.xlsx"
    batch = mocker.MagicMock()

    mocker.patch("country_workspace.datasources.rdi.processors.build_import_processor", return_value=lambda row: row)
    mocker.patch(
        "country_workspace.datasources.rdi.processors.Individual.objects.create",
        side_effect=Exception("Something went wrong"),
    )

    sheet = individual_sheet if config["master_detail"] else people_sheet
    household_map = household_mapping if config["master_detail"] else None
    expected_sheet_name = SheetName.INDIVIDUALS if config["master_detail"] else SheetName.PEOPLE

    with pytest.raises(SheetProcessingError) as exc_info:
        process_beneficiaries(sheet, job, batch, config, household_map)

    assert exc_info.value.sheet_name == expected_sheet_name


def test_process_beneficiaries_failed_to_transform(
    mocker: MockerFixture,
    config: Config,
    individual_sheet: Sheet,
    people_sheet: Sheet,
    household_mapping: Mapping[int, Any],
) -> None:
    job = mocker.MagicMock()
    job.file.name = "uploads/rdi.xlsx"
    batch = mocker.MagicMock()

    mocker.patch(
        "country_workspace.datasources.rdi.processors.build_import_processor",
        return_value=mocker.MagicMock(side_effect=Exception("mapping failed")),
    )
    mock_create = mocker.patch("country_workspace.datasources.rdi.processors.Individual.objects.create")

    sheet = individual_sheet if config["master_detail"] else people_sheet
    household_map = household_mapping if config["master_detail"] else None
    expected_sheet_name = SheetName.INDIVIDUALS if config["master_detail"] else SheetName.PEOPLE
    expected_object_id = sheet[0][config["beneficiary_id_column"]]

    with pytest.raises(SheetProcessingError) as exc_info:
        process_beneficiaries(sheet, job, batch, config, household_map)

    assert exc_info.value.sheet_name == expected_sheet_name
    assert exc_info.value.object_id == expected_object_id
    mock_create.assert_not_called()


def test_import_from_rdi(  # noqa: PLR0915
    mocker: MockerFixture,
    config: Config,
    household_sheet: Sheet,
    individual_sheet: Sheet,
    people_sheet: Sheet,
    household_mapping: Mapping[int, Any],
    people_mapping: Mapping[int, Any],
) -> None:
    job = mocker.MagicMock()
    job.config = config

    mocker.patch("country_workspace.datasources.rdi.processors.atomic")
    mocker.patch("country_workspace.datasources.rdi.processors.batch_ctx")
    batch_class_mock = mocker.patch("country_workspace.datasources.rdi.processors.Batch")
    batch = batch_class_mock.objects.create.return_value

    read_sheets_mock = mocker.patch("country_workspace.datasources.rdi.processors.read_sheets")
    process_beneficiaries_mock = mocker.patch("country_workspace.datasources.rdi.processors.process_beneficiaries")
    postprocessing_mock = mocker.patch("country_workspace.datasources.rdi.processors.run_batch_postprocessing")
    collision_mock = mocker.patch("country_workspace.datasources.rdi.processors.detect_and_mark_collisions_for_batch")

    if config["master_detail"]:
        read_sheets_mock.return_value = household_sheet, individual_sheet
        process_households_mock = mocker.patch("country_workspace.datasources.rdi.processors.process_households")

        fields = HOUSEHOLD_ROLE_REF_FIELDS
        household_mocks = {}
        for i, (key, _) in enumerate(household_mapping.items()):
            household_mock = mocker.MagicMock()
            household_mock.flex_fields = {
                fields.head_of_household: f"ind_{i + 1}",
                fields.primary_collector: f"ind_{i + 2}",
                fields.alternate_collector: f"ind_{i + 3}",
            }
            household_mock.pk = key
            household_mocks[key] = household_mock

        process_households_mock.return_value = household_mocks

        processed_individuals = {}
        max_individual_id = max(
            len(list(individual_sheet)) + 1,
            len(list(household_mapping)) * 3 + 1,
        )
        for i in range(1, max_individual_id):
            individual_mock = mocker.MagicMock()
            individual_mock.flex_fields = {"individual_id": f"ind_{i}"}
            individual_mock.pk = i
            processed_individuals[i] = individual_mock

        process_beneficiaries_mock.return_value = BeneficiaryImportResult(
            processed_individuals,
            {f"ind_{i}": i for i in range(1, max_individual_id)},
        )
    else:
        read_sheets_mock.return_value = (people_sheet,)
        process_beneficiaries_mock.return_value = BeneficiaryImportResult(dict(people_mapping), {})

    result = import_from_rdi(job)

    if config["master_detail"]:
        assert result == {"household": len(household_mocks), "individual": len(processed_individuals)}
        process_households_mock.assert_called_once()
        args, _ = process_households_mock.call_args
        assert args[1] == job
        assert args[2] == batch
        assert args[3] == config

        process_beneficiaries_mock.assert_called_once()
        args, _ = process_beneficiaries_mock.call_args
        assert args[1] == job
        assert args[2] == batch
        assert args[3] == config
        assert args[4] == household_mocks
    else:
        assert result == {"people": len(people_mapping)}
        process_beneficiaries_mock.assert_called_once()
        args, _ = process_beneficiaries_mock.call_args
        assert args[1] == job
        assert args[2] == batch
        assert args[3] == config

    batch_class_mock.objects.create.assert_called_once_with(
        name=config["batch_name"],
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=batch_class_mock.BatchSource.RDI,
        status=batch_class_mock.BatchStatus.LOADING,
    )
    postprocessing_mock.assert_called_once_with(
        batch,
        household_transformer_id=config.get("household_transformer_id"),
        individual_transformer_id=config.get("individual_transformer_id"),
    )
    collision_mock.assert_called_once_with(batch)


def test_import_from_rdi_honors_cancellation_before_processing(mocker: MockerFixture, config: Config) -> None:
    job = mocker.MagicMock()
    job.config = config
    job.ensure_not_cancelled.side_effect = GracefulJobCancellationError("cancel requested")

    with pytest.raises(GracefulJobCancellationError):
        import_from_rdi(job)


def test_image_location(mocker: MockerFixture) -> None:
    image = mocker.MagicMock()
    result = image_location(image)
    assert result == (image.anchor._from.row, image.anchor._from.col)


def test_image_content(mocker: MockerFixture) -> None:
    image_module_mock = mocker.patch("country_workspace.datasources.rdi.processors.Image")
    b64encode_mock = mocker.patch("country_workspace.datasources.rdi.processors.b64encode")

    image = mocker.MagicMock()
    result = image_content(image)

    assert result == (image_module_mock.MIME.get.return_value, b64encode_mock.return_value.decode.return_value)
    image_module_mock.open.assert_called_once_with(image.ref)
    image_module_mock.MIME.get.assert_called_once_with(image_module_mock.open.return_value.format)
    image.ref.seek.assert_called_once_with(0)
    b64encode_mock.assert_called_once_with(image.ref.read.return_value)


def test_extract_images(mocker: MockerFixture) -> None:
    load_workbook_mock = mocker.patch("country_workspace.datasources.rdi.processors.load_workbook")
    image_location_mock = mocker.patch("country_workspace.datasources.rdi.processors.image_location")
    image_location_mock.return_value = (row := 1, column := 2)
    image_content_mock = mocker.patch("country_workspace.datasources.rdi.processors.image_content")
    image_content_mock.return_value = (content_type := "content/type", content := "content")
    image = mocker.MagicMock()
    load_workbook_mock.return_value.__getitem__.return_value._images = (image,)

    result = list(extract_images(filepath := "test", sheet_name := "first"))

    assert result == [{row - 1: {column: VALUE_FORMAT.format(mimetype=content_type, content=content)}}]
    load_workbook_mock.assert_called_once_with(filepath)
    load_workbook_mock.return_value.__getitem__.assert_called_once_with(sheet_name)
    image_location_mock.assert_called_once_with(image)
    image_content_mock.assert_called_once_with(image)


def test_merge_images() -> None:
    sheet = (
        {(column := "column"): "value"},
        second_row := {"column": "value"},
    )
    sheet_images = {2: {0: (image_data := "IMAGE_DATA")}}

    result = list(merge_images(sheet, sheet_images, start_at_row=2))

    assert result == [{column: image_data}, second_row]


def test_read_sheets(mocker: MockerFixture, config: Config) -> None:
    fake_sheets = ((mocker.MagicMock(), sheet := mocker.MagicMock()),)
    compose_mock = mocker.patch("country_workspace.datasources.rdi.processors.compose")
    datetime_to_date_mock = mocker.patch("country_workspace.datasources.rdi.processors.datetime_to_date")
    date_to_iso_string_mock = mocker.patch("country_workspace.datasources.rdi.processors.date_to_iso_string")
    open_xls_multi_mock = mocker.patch("country_workspace.datasources.rdi.processors.open_xls_multi")
    open_xls_multi_mock.return_value = fake_sheets
    extract_images_mock = mocker.patch("country_workspace.datasources.rdi.processors.extract_images")
    extract_images_mock.return_value = ((images := mocker.MagicMock()),)
    merge_images_mock = mocker.patch("country_workspace.datasources.rdi.processors.merge_images")

    filepath = "test"
    sheet_name = "first"

    if config["master_detail"]:
        filter_rows_with_household_pk_mock = mocker.patch(
            "country_workspace.datasources.rdi.processors.filter_rows_with_household_pk"
        )

    result = list(read_sheets(config, filepath, sheet_name))

    if config["master_detail"]:
        assert result == [filter_rows_with_household_pk_mock.return_value]
        filter_rows_with_household_pk_mock.assert_called_once_with(config, merge_images_mock.return_value)
    else:
        assert result == [merge_images_mock.return_value]

    compose_mock.assert_called_once_with(datetime_to_date_mock, date_to_iso_string_mock)

    expected_start_at_row = config["first_line"] - 2 if config["first_line"] > 1 else 0
    open_xls_multi_mock.assert_called_once_with(
        filepath,
        indices_or_names=[sheet_name],
        value_mapper=compose_mock.return_value,
        start_at_row=expected_start_at_row,
    )
    extract_images_mock.assert_called_once_with(filepath, sheet_name)
    merge_images_mock.assert_called_once_with(sheet, images, expected_start_at_row)


def test_read_sheets_sheet_not_found_error(mocker: MockerFixture, config: Config) -> None:
    mocker.patch("country_workspace.datasources.rdi.processors.compose")
    mocker.patch("country_workspace.datasources.rdi.processors.datetime_to_date")
    mocker.patch("country_workspace.datasources.rdi.processors.date_to_iso_string")
    open_xls_multi_mock = mocker.patch("country_workspace.datasources.rdi.processors.open_xls_multi")
    open_xls_multi_mock.side_effect = IndexError("list index out of range")
    mocker.patch("country_workspace.datasources.rdi.processors.extract_images")

    filepath = "test"
    sheet_name = "first"

    with pytest.raises(SheetNotFoundError) as exc_info:
        list(read_sheets(config, filepath, sheet_name))

    assert exc_info.value.sheet_names == (sheet_name,)
    assert str(sheet_name) in str(exc_info.value)


@pytest.mark.parametrize(
    ("inp", "expected"),
    [
        (s := "foo", s),
        (i := 123, i),
        (d := date(2020, 1, 1), d),
        (dt := datetime(2020, 1, 1, 1, 1, 1, tzinfo=timezone.utc), dt.date()),
    ],
    ids=["string", "integer", "date", "datetime"],
)
def test_datetime_to_date(inp: Any, expected: Any) -> None:
    assert datetime_to_date(inp) == expected


@pytest.mark.parametrize(
    ("inp", "expected"),
    [
        (s := "foo", s),
        (i := 123, i),
        (d := date(2020, 1, 1), d.isoformat()),
    ],
    ids=["string", "integer", "date"],
)
def test_date_to_iso_string(inp: Any, expected: Any) -> None:
    assert date_to_iso_string(inp) == expected


def test_duplicate_keys(
    mocker: MockerFixture,
    config: Config,
    duplicate_household_sheet: Sheet,
    duplicate_individual_sheet: Sheet,
    duplicate_people_sheet: Sheet,
    household_mapping: Mapping[int, Any],
) -> None:
    mocker.patch(
        "country_workspace.datasources.rdi.processors.Household.objects.create",
        return_value=mocker.MagicMock(),
    )
    mocker.patch(
        "country_workspace.datasources.rdi.processors.Individual.objects.create",
        return_value=mocker.MagicMock(),
    )
    mocker.patch(
        "country_workspace.datasources.rdi.processors.build_import_processor",
        return_value=lambda row: row,
    )
    job_mock = mocker.MagicMock()
    job_mock.file.name = "uploads/rdi.xlsx"

    if config["master_detail"]:
        with pytest.raises(SheetProcessingError) as exc_info:
            process_households(duplicate_household_sheet, job_mock, mocker.MagicMock(), config)
        assert exc_info.value.sheet_name == SheetName.HOUSEHOLDS
        assert exc_info.value.object_id == HOUSEHOLD_1_PK

        with pytest.raises(SheetProcessingError) as exc_info:
            process_beneficiaries(duplicate_individual_sheet, job_mock, mocker.MagicMock(), config, household_mapping)
        assert exc_info.value.sheet_name == SheetName.INDIVIDUALS
        assert exc_info.value.object_id == INDIVIDUAL_1_PK
    else:
        with pytest.raises(SheetProcessingError) as exc_info:
            process_beneficiaries(duplicate_people_sheet, job_mock, mocker.MagicMock(), config, None)
        assert exc_info.value.sheet_name == SheetName.PEOPLE
        assert exc_info.value.object_id == INDIVIDUAL_1_PK
