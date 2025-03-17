from typing import TYPE_CHECKING
from unittest import mock
from unittest.mock import Mock

import pytest


if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryHousehold, CountryIndividual
    from country_workspace.models import Household


@pytest.fixture
def household() -> "CountryHousehold":
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory()


@pytest.fixture
def individual(household) -> "CountryIndividual":
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(household=household)


def test_properties(household: "CountryHousehold"):
    assert household.program == household.batch.program
    assert household.country_office == household.batch.country_office


def test_validate_with_checker(individual: "CountryHousehold"):
    household: Household = individual.household
    assert household.validate_with_checker()
    assert household.errors == {}
    with mock.patch.object(household.program.beneficiary_validator, "validate", Mock(return_value=["Error"])):
        assert not household.validate_with_checker()
        assert household.errors == {"dct": ["Error"]}
