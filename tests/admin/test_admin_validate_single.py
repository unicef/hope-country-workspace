from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from pytest_mock import MockerFixture
    from testutils.types import CWTestApp

    from country_workspace.models import User
    from country_workspace.workspaces.models import CountryHousehold, CountryIndividual

pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture
def household_checker():
    from testutils.factories import DataCheckerFactory, FieldsetFactory, FlexFieldFactory

    from country_workspace.contrib.hope.constants import HOUSEHOLD_CHECKER_NAME

    dc = DataCheckerFactory(name=HOUSEHOLD_CHECKER_NAME)
    fs = FieldsetFactory()
    for field in ["address", "admin1", "consent", "country_origin", "household_id"]:
        FlexFieldFactory(fieldset=fs, name=field)
    dc.fieldsets.add(fs)
    return dc


@pytest.fixture
def individual_checker():
    from testutils.factories import DataCheckerFactory, FieldsetFactory, FlexFieldFactory

    from country_workspace.contrib.hope.constants import INDIVIDUAL_CHECKER_NAME

    dc = DataCheckerFactory(name=INDIVIDUAL_CHECKER_NAME)
    fs = FieldsetFactory()
    for field in ["address", "consent", "admin1", "zip_code"]:
        FlexFieldFactory(fieldset=fs, name=field)
    dc.fieldsets.add(fs)
    return dc


@pytest.fixture
def program(household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(household_checker=household_checker, individual_checker=individual_checker)


@pytest.fixture
def household(program) -> "CountryHousehold":
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"address": "Cool address"},
    )


@pytest.fixture
def individual(household: "CountryHousehold") -> "CountryIndividual":
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(
        batch=household.batch,
        household=household,
        batch__program=household.batch.program,
        batch__country_office=household.batch.program.country_office,
        flex_fields={"address": "Cool address"},
    )


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


@pytest.mark.parametrize(
    ("is_valid", "expected_message"),
    [
        (True, "Validation successful!"),
        (False, "Validation failed!"),
    ],
)
def test_household_admin_validate_single_messages(
    app: "CWTestApp",
    household: "CountryHousehold",
    mocker: "MockerFixture",
    is_valid: bool,
    expected_message: str,
) -> None:
    validate_alien_mock = mocker.patch("country_workspace.admin.household.validate_alien_fields")
    validate_checker_mock = mocker.patch(
        "country_workspace.models.household.Household.validate_with_checker",
        return_value=is_valid,
    )

    url = reverse("admin:country_workspace_household_change", args=[household.pk])
    res = app.get(url)
    res = res.click("Validate")
    res = res.follow()

    assert res.status_code == 200
    assert expected_message in res.text
    assert validate_alien_mock.called
    assert validate_checker_mock.call_count == 1


@pytest.mark.parametrize(
    ("is_valid", "expected_message"),
    [
        (True, "Validation successful!"),
        (False, "Validation failed!"),
    ],
)
def test_individual_admin_validate_single_messages(
    app: "CWTestApp",
    individual: "CountryIndividual",
    mocker: "MockerFixture",
    is_valid: bool,
    expected_message: str,
) -> None:
    validate_alien_mock = mocker.patch("country_workspace.admin.individual.validate_alien_fields")
    validate_checker_mock = mocker.patch(
        "country_workspace.models.individual.Individual.validate_with_checker",
        return_value=is_valid,
    )

    url = reverse("admin:country_workspace_individual_change", args=[individual.pk])
    res = app.get(url)
    res = res.click("Validate")
    res = res.follow()

    assert res.status_code == 200
    assert expected_message in res.text
    assert validate_alien_mock.called
    assert validate_checker_mock.call_count == 1
