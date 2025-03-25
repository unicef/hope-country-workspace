from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from pytest_django.fixtures import SettingsWrapper
from testutils.utils import select_office

from country_workspace.state import state

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from responses import RequestsMock

    from country_workspace.workspaces.models import CountryHousehold, CountryProgram


pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office):
    from testutils.factories import CountryProgramFactory, DataCheckerFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=DataCheckerFactory(fields=["collect_individual_data"]),
        individual_checker=DataCheckerFactory(fields=["gender"]),
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
        beneficiary_group__master_detail=True,
    )


@pytest.fixture
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)


@pytest.fixture
def app(
    django_app_factory: "MixinWithInstanceVariables",
    mocked_responses: "RequestsMock",
    settings: SettingsWrapper,
) -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_configure_hh_columns(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    with select_office(app, program.country_office, program):
        res = app.get(program.get_change_url())
        res = res.click("Household Columns")
        form = res.forms["configure-columns"]
        form["columns"] = ["name", "flex_fields__collect_individual_data"]
        form.submit().follow()
        program.refresh_from_db()
        assert program.household_columns == "name\nflex_fields__collect_individual_data"
        hh_list = reverse("workspace:workspaces_countryhousehold_changelist")
        res = app.get(hh_list)
        assert not res.pyquery("div.text a:contains('flex_fields__collect_individual_data')")
        assert res.pyquery("div.text a:contains('Collect_individual_data')")
    # assert "collect_individual_data" in res.text


def test_configure_ind_columns(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    with select_office(app, program.country_office, program):
        res = app.get(program.get_change_url())
        res = res.click("Individual Columns")
        form = res.forms["configure-columns"]
        form["columns"] = ["name", "flex_fields__gender"]
        form.submit().follow()
        program.refresh_from_db()
        assert program.individual_columns == "name\nflex_fields__gender"
        hh_list = reverse("workspace:workspaces_countryindividual_changelist")
        res = app.get(hh_list)
        assert "gender" in res.text
