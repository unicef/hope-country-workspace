from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryHousehold


@pytest.fixture()
def household() -> "CountryHousehold":
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory()


def test_properties(household: "CountryHousehold"):
    assert household.program == household.batch.program
    assert household.country_office == household.batch.country_office
