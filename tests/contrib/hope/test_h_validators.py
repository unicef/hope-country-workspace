import pytest
from faker import Faker

from country_workspace.contrib.hope.validators import FullHouseholdValidator
from tests.extras.testutils.factories import HouseholdFactory, IndividualFactory


fake = Faker()


@pytest.fixture
def program(household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
    )


@pytest.fixture
def full_hhv(program):
    return FullHouseholdValidator(program)


def test_hh_validation_with_all_errors(program, full_hhv):
    hh = HouseholdFactory.create(batch__program=program)

    errors = full_hhv.validate(hh)
    assert len(errors) == 2
    assert errors == [
        "This Household does not have Head",
        "This Household does not have Primary Collector",
    ]


def test_hh_validation_with_existing_head(program, full_hhv):
    individual = IndividualFactory.create()
    hh = HouseholdFactory.create(batch__program=program)
    hh.flex_fields["head_of_household"] = individual.id
    hh.save()
    hh.members.add(individual)

    errors = full_hhv.validate(hh)
    assert len(errors) == 1
    assert errors == [
        "This Household does not have Primary Collector",
    ]


def test_hh_validation_with_existing_primary_collector(program, full_hhv):
    individual = IndividualFactory.create()
    hh = HouseholdFactory.create(batch__program=program)
    hh.flex_fields["primary_collector"] = individual.id
    hh.save()
    hh.members.add(individual)

    errors = full_hhv.validate(hh)
    assert len(errors) == 1
    assert errors == [
        "This Household does not have Head",
    ]


def test_hh_with_matching_collector_ids(program, full_hhv):
    individual = IndividualFactory.create()
    hh = HouseholdFactory.create(batch__program=program)
    hh.flex_fields["head_of_household"] = hh.flex_fields["primary_collector"] = hh.flex_fields[
        "alternate_collector"
    ] = individual.id
    hh.save()
    hh.members.add(individual)

    errors = full_hhv.validate(hh)
    assert len(errors) == 1
    assert errors == ["Primary collector and Alternate collectors can not be the same"]


def test_hh_with_head_from_different_hh(program, full_hhv):
    individual = IndividualFactory.create()
    hh = HouseholdFactory.create(batch__program=program)
    hh.flex_fields["head_of_household"] = hh.flex_fields["primary_collector"] = individual.id
    hh.save()

    errors = full_hhv.validate(hh)
    assert len(errors) == 1
    assert errors == [
        "Household Head must be from the given Household",
    ]
