from typing import TYPE_CHECKING
from unittest import mock
from unittest.mock import Mock

import pytest

if TYPE_CHECKING:
    from country_workspace.models import Household
    from country_workspace.workspaces.models import CountryHousehold, CountryIndividual


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


def test_validate_with_checker_validates_external_collectors(household: "CountryHousehold"):
    from testutils.factories import CountryIndividualFactory

    from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS

    household.members.all().delete()
    collector = CountryIndividualFactory(household=None, batch=household.batch, last_checked=None, errors={})
    household.flex_fields = {HOUSEHOLD_ROLE_REF_FIELDS.primary_collector: collector.pk}
    household.save(update_fields=["flex_fields"])

    household.validate_with_checker()

    collector.refresh_from_db()
    assert collector.last_checked is not None
