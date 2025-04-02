import pytest

from country_workspace.models import Household
from country_workspace.state import state


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
    )


@pytest.fixture
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(
        batch__program=program,
        flex_fields={"first_name": "name", "last_name": "family name", "size": 0},
        batch__country_office=program.country_office,
    )


def test_history_update(household):
    assert household.events.count() == 1

    household.system_fields = {"a": 1}
    household.save()
    assert household.events.count() == 1

    Household.objects.filter(pk=household.pk).update(system_fields={"a": 1})
    assert household.events.count() == 1

    Household.objects.filter(pk=household.pk).update(flex_fields={"first_name": "First Name"})
    assert household.events.count() == 2

    household.flex_fields = {"a": 1}
    household.save()
    assert household.events.count() == 3
