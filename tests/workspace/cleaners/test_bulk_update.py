import io
from typing import TYPE_CHECKING

import pytest
from constance.test import override_config
from pytest_mock import MockerFixture

from country_workspace.models import AsyncJob
from country_workspace.workspaces.admin.cleaners.bulk_update import bulk_update_household

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
