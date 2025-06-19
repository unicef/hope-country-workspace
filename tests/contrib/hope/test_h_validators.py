from typing import TYPE_CHECKING

import factory
import pytest
from faker import Faker

from country_workspace.contrib.hope.validators import FullHouseholdValidator
from country_workspace.models.household import ROLE_PRIMARY, ROLE_ALTERNATE

if TYPE_CHECKING:
    from country_workspace.models import Household

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
def household(program, worker_id) -> "Household":
    from testutils.factories import HouseholdFactory

    def name(instance: "Household", step: int) -> str:
        name = fake.last_name()
        return f"{name} @{worker_id} #{step}"

    return HouseholdFactory(
        name=factory.LazyAttributeSequence(name),
        batch__program=program,
        individuals=[],
        batch__country_office=program.country_office,
    )


def test_head(household: "Household"):
    from testutils.factories import IndividualFactory

    v = FullHouseholdValidator(household.program)
    assert v.validate(household) == [
        "This Household does not have Head",
        "This Household does not have Primary Collector",
    ]

    household.members.add(IndividualFactory(household=household, flex_fields={"relationship": "HEAD"}))
    assert v.validate(household) == ["This Household does not have Primary Collector"]

    household.members.add(IndividualFactory(household=household, flex_fields={"role": ROLE_PRIMARY}))
    assert v.validate(household) == []

    household.members.add(IndividualFactory(household=household, flex_fields={"relationship": "HEAD"}))
    assert v.validate(household) == ["This Household has multiple heads"]
    household.members.add(IndividualFactory(household=household, flex_fields={"role": ROLE_PRIMARY}))
    assert v.validate(household) == [
        "This Household has multiple heads",
        "This Household has multiple Primary Collectors",
    ]
    household.members.add(IndividualFactory(household=household, flex_fields={"role": ROLE_ALTERNATE}))
    household.members.add(IndividualFactory(household=household, flex_fields={"role": ROLE_ALTERNATE}))
    assert v.validate(household) == [
        "This Household has multiple heads",
        "This Household has multiple Primary Collectors",
        "This Household has multiple Alternate Collectors",
    ]
