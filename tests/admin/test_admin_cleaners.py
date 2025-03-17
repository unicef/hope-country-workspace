from unittest import mock
from unittest.mock import Mock

import pytest

from country_workspace.workspaces.admin.cleaners.validate import validate_program


@pytest.fixture
def household():
    from testutils.factories import CountryHouseholdFactory, ProgramFactory

    program = ProgramFactory()
    return CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)


def test_validate_program(household):
    assert validate_program(Mock(program=household.program)) == {"invalid": 0, "total": 0, "valid": 1}
    with mock.patch(
        "country_workspace.workspaces.admin.cleaners.validate.Household.validate_with_checker", return_value=False
    ):
        assert validate_program(Mock(program=household.program)) == {"invalid": 1, "total": 0, "valid": 0}
