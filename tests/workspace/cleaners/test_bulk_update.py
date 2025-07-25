import io
from typing import Any

import pytest
from constance.test import override_config
from pytest_mock import MockerFixture

from country_workspace.state import state
from country_workspace.models import AsyncJob
from country_workspace.workspaces.admin.cleaners.bulk_update import (
    import_household_updates,
    import_individual_updates,
    validate_date_datetime_fields,
    _validate_datetime_format,
    _validate_date_format,
)


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def program(request, office, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
        beneficiary_group__master_detail=request.param,
    )


@pytest.fixture
def job(program) -> AsyncJob:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(program=program)
    job.file = io.BytesIO(b"dummy content")
    return job


@pytest.fixture
def households(program):
    from testutils.factories import CountryHouseholdFactory

    if program.beneficiary_group.master_detail:
        return [CountryHouseholdFactory(batch__program=program) for _ in range(3)]
    return []


@pytest.fixture
def individuals(program):
    from testutils.factories import CountryIndividualFactory

    if not program.beneficiary_group.master_detail:
        return [CountryIndividualFactory(batch__program=program, household=None) for _ in range(3)]
    return []


@pytest.fixture
def test_data(households, individuals, program) -> dict[str, Any]:
    is_master_detail = program.beneficiary_group.master_detail
    entities = households if is_master_detail else individuals
    import_function = import_household_updates if is_master_detail else import_individual_updates

    missing_version_entity = entities[0]  # For row 4: missing version
    version_mismatch_entity = entities[1]  # For row 5: version mismatch
    valid_entity = entities[2]  # For row 6: successful update

    rows = [
        {"version": "1", "some_field": "value"},  # Row 1: missing 'id'
        {"id": "notanint", "version": "1", "some_field": "value"},  # Row 2: non-integer 'id'
        {"id": "9999", "version": "1", "some_field": "value"},  # Row 3: valid id but not found
        {"id": str(missing_version_entity.id), "some_field": "value"},  # Row 4: missing 'version' (when guard enabled)
        {
            "id": str(version_mismatch_entity.id),
            "version": str(version_mismatch_entity.version + 1),
            "some_field": "value",
        },  # Row 5: version mismatch (when guard enabled)
        {"id": str(valid_entity.id), "version": str(valid_entity.version), "some_field": "value"},  # Row 6: valid row
    ]

    return {
        "rows": rows,
        "import_function": import_function,
        "valid_entity": valid_entity,
        "version_mismatch_entity": version_mismatch_entity,
    }


@pytest.mark.parametrize("guard", [True, False], ids=["guard_enabled", "guard_disabled"])
def test_import_bulk_update_file(
    mocker: MockerFixture,
    job: AsyncJob,
    test_data: dict[str, Any],
    guard: bool,
) -> None:
    mocker.patch("country_workspace.workspaces.admin.cleaners.bulk_update.open_xls", return_value=test_data["rows"])

    with override_config(CONCURRENCY_GUARD=guard):
        result = test_data["import_function"](job=job)

    expected_processed = 3 if not guard else 1
    expected_errors = {"Invalid data on line": [1, 2] + ([4] if guard else [])}

    assert result["processed"] == expected_processed
    assert result["not_found"] == [9999]
    assert result["errors"] == expected_errors

    if guard:
        assert result["version_mismatch"] == [test_data["version_mismatch_entity"].id]
    else:
        assert "version_mismatch" not in result

    test_data["valid_entity"].refresh_from_db()
    assert test_data["valid_entity"].flex_fields.get("some_field") == "value"


@pytest.mark.parametrize(
    ("error_type", "expected_key", "expected_message"),
    [
        ("processing", "Processing errors", "Line 6: Validation failed"),
        ("file", "file_processing", "Cannot read file"),
    ],
    ids=["processing_error", "file_error"],
)
def test_import_bulk_update_file_errors(
    mocker: MockerFixture,
    job: AsyncJob,
    test_data: dict,
    error_type: str,
    expected_key: str,
    expected_message: str,
) -> None:
    if error_type == "processing":
        # Mock successful file reading but failed validation
        mocker.patch("country_workspace.workspaces.admin.cleaners.bulk_update.open_xls", return_value=test_data["rows"])
        mocker.patch(
            "country_workspace.workspaces.admin.cleaners.bulk_update.validate_date_datetime_fields",
            side_effect=RuntimeError("Validation failed"),
        )
    else:
        # Mock failed file reading
        mocker.patch(
            "country_workspace.workspaces.admin.cleaners.bulk_update.open_xls", side_effect=IOError("Cannot read file")
        )

    with override_config(CONCURRENCY_GUARD=True):
        result = test_data["import_function"](job=job)

    assert result["processed"] == 0

    if error_type == "processing":
        assert expected_key in result["errors"]
        assert expected_message in result["errors"][expected_key][0]
    else:
        assert result["errors"][expected_key] == expected_message


def test_validate_datetime_format():
    assert _validate_datetime_format("2023-12-25 14:30:00") is True
    assert _validate_datetime_format("2023-12-25 14:30") is True
    assert _validate_datetime_format("25/12/2023 14:30:00") is True
    assert _validate_datetime_format("25/12/2023 14:30") is True

    assert _validate_datetime_format("invalid") is False
    assert _validate_datetime_format("2023-13-25 14:30:00") is False
    assert _validate_datetime_format("2023-12-32 14:30:00") is False
    assert _validate_datetime_format("25:12:2023 14:30") is False
    assert _validate_datetime_format("") is False
    assert _validate_datetime_format(None) is False


def test_validate_date_format():
    assert _validate_date_format("2023-12-25") is True
    assert _validate_date_format("25/12/2023") is True
    assert _validate_date_format("12/25/2023") is True
    assert _validate_date_format("2023/12/25") is True

    assert _validate_date_format("invalid") is False
    assert _validate_date_format("2023-13-25") is False
    assert _validate_date_format("2023-12-32") is False
    assert _validate_date_format("25:12:2023") is False
    assert _validate_date_format("") is False

    with pytest.raises(TypeError):
        _validate_date_format(None)


def test_validate_date_datetime_fields():
    from django.forms.fields import DateField, DateTimeField
    from hope_flex_fields.models import DataChecker, FlexField, FieldDefinition
    from unittest.mock import Mock

    mock_dc = Mock(spec=DataChecker)
    mock_date_field = Mock(spec=FlexField)
    mock_datetime_field = Mock(spec=FlexField)

    date_def = Mock(spec=FieldDefinition)
    date_def.field_type = DateField
    datetime_def = Mock(spec=FieldDefinition)
    datetime_def.field_type = DateTimeField

    mock_date_field.definition = date_def
    mock_datetime_field.definition = datetime_def

    def mock_dc_get_field(dc, name):
        if name == "birth_date":
            return mock_date_field
        if name == "created_at":
            return mock_datetime_field
        return None

    row = {
        "flex_fields__birth_date": "not-a-date",
        "flex_fields__created_at": "not-a-datetime",
    }
    errors = {}
    line_number = 1

    with pytest.MonkeyPatch().context() as m:
        m.setattr("country_workspace.workspaces.admin.cleaners.bulk_update.dc_get_field", mock_dc_get_field)

        validate_date_datetime_fields(row, mock_dc, line_number, errors)

    assert "Invalid date format for field 'flex_fields__birth_date' on line" in errors
    assert "Invalid datetime format for field 'flex_fields__created_at' on line" in errors
    assert errors["Invalid date format for field 'flex_fields__birth_date' on line"] == [line_number]
    assert errors["Invalid datetime format for field 'flex_fields__created_at' on line"] == [line_number]


def test_validate_date_datetime_fields_with_empty_values():
    from unittest.mock import Mock

    mock_dc = Mock()
    row = {
        "birth_date": None,
        "created_at": "",
        "name": "John Doe",
    }
    errors = {}
    line_number = 1

    with pytest.MonkeyPatch().context() as m:
        m.setattr("country_workspace.workspaces.admin.cleaners.bulk_update.dc_get_field", lambda dc, name: None)

        validate_date_datetime_fields(row, mock_dc, line_number, errors)

    assert not errors
