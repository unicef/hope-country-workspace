import io
from typing import TYPE_CHECKING

import pytest
from constance.test import override_config
from pytest_mock import MockerFixture

from country_workspace.models import AsyncJob
from country_workspace.workspaces.admin.cleaners.bulk_update import (
    bulk_update_household,
    validate_date_datetime_fields,
    _validate_datetime_format,
    _validate_date_format,
)

if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryHousehold, CountryProgram


@pytest.fixture
def program(force_migrated_records) -> "CountryProgram":
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory()


@pytest.fixture
def job(program) -> AsyncJob:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(program=program)
    job.file = io.BytesIO(b"dummy content")
    return job


@pytest.fixture
def households(program):
    from testutils.factories import CountryHouseholdFactory

    return [CountryHouseholdFactory(batch__program=program) for _ in range(3)]


@pytest.mark.parametrize("guard", [True, False])
def test_bulk_update_collection(
    mocker: MockerFixture,
    job: AsyncJob,
    program: "CountryProgram",
    households: list["CountryHousehold"],
    guard: bool,
) -> None:
    hh_id_valid_row = households[2].id
    rows = [
        {"version": "1", "some_field": "value"},  # Row 1: missing 'id'
        {"id": "notanint", "version": "1", "some_field": "value"},  # Row 2: non-integer 'id'
        {"id": "9999", "version": "1", "some_field": "value"},  # Row 3: valid id but not found
        {"id": str(households[0].id), "some_field": "value"},  # Row 4: missing 'version'
        {
            "id": str(households[1].id),
            "version": str(households[1].version + 1),
            "some_field": "value",
        },  # Row 5: version mismatch
        {"id": str(hh_id_valid_row), "version": str(households[2].version), "some_field": "value"},  # Row 6: valid row
    ]
    expected_result = {
        "not_found": [9999],
        "errors": {
            "Invalid or missing 'id' on line": [1, 2],
            **({"Invalid or missing 'version' on line": [4]} if guard else {}),
        },
        **({"version_mismatch": [households[1].id]} if guard else {}),
    }
    mocker.patch("country_workspace.workspaces.admin.cleaners.bulk_update.open_xls", return_value=rows)

    with override_config(CONCURRENCY_GUARD=guard):
        result = bulk_update_household(job=job)

    assert result == expected_result
    assert program.households.get(id=hh_id_valid_row).flex_fields.get("some_field") == "value"


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
