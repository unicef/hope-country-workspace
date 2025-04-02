import pytest

from country_workspace.models import Household, Individual
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


@pytest.fixture
def individual(household):
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(
        batch=household.batch,
        flex_fields={"first_name": "name", "last_name": "family name"},
    )


def test_history_household(household):
    start = household.events.count()

    household.system_fields = {"a": 1}
    household.save()
    assert household.events.count() == start

    Household.objects.filter(pk=household.pk).update(system_fields={"a": 1})
    assert household.events.count() == start

    Household.objects.filter(pk=household.pk).update(flex_fields={"first_name": "First Name"})
    assert household.events.count() == start + 1

    household.flex_fields = {"a": 1}
    household.save()
    assert household.events.count() == start + 2


def test_history_individual(individual):
    start = individual.events.count()

    individual.system_fields = {"a": 1}
    individual.save()
    assert individual.events.count() == start

    Individual.objects.filter(pk=individual.pk).update(system_fields={"a": 1})
    assert individual.events.count() == start

    Individual.objects.filter(pk=individual.pk).update(
        flex_fields={"first_name": "First Name", "last_name": "Family Name"}
    )
    assert individual.events.count() == start + 1

    individual.flex_fields = {"a": 1}
    individual.save()
    assert individual.events.count() == start + 2
