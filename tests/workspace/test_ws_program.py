from typing import TYPE_CHECKING

from django.urls import reverse

import pytest
from pytest_django.fixtures import SettingsWrapper
from responses import RequestsMock

from country_workspace.state import state
from country_workspace.workspaces.models import CountryHousehold, CountryProgram

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables


pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture()
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    yield co


@pytest.fixture()
def program(office):
    from testutils.factories import CountryProgramFactory, DataCheckerFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=DataCheckerFactory(fields=["collect_individual_data"]),
        individual_checker=DataCheckerFactory(fields=["gender"]),
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
    )


@pytest.fixture()
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(program=program, country_office=program.country_office)


@pytest.fixture()
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
    yield django_app


def test_configure_hh_columns(app, household: "CountryHousehold"):
    url = reverse("workspace:workspaces_countryhousehold_changelist")
    program: "CountryProgram" = household.program
    res = app.get(url).follow()
    res.forms["select-tenant"]["tenant"] = program.country_office.pk
    res.forms["select-tenant"].submit()
    res = app.get(program.get_change_url())
    res = res.click("Household Columns")
    form = res.forms["configure-columns"]
    form["columns"] = ["name", "collect_individual_data"]
    form.submit().follow()
    program.refresh_from_db()
    assert program.household_columns == "name\nflex_fields__collect_individual_data"
    hh_list = reverse("workspace:workspaces_countryhousehold_changelist")
    res = app.get(f"{hh_list}?program__exact={program.pk}")
    assert "collect_individual_data" in res.text


def test_configure_ind_columns(app, household: "CountryHousehold"):
    url = reverse("workspace:workspaces_countryhousehold_changelist")
    program: "CountryProgram" = household.program
    res = app.get(url).follow()
    res.forms["select-tenant"]["tenant"] = program.country_office.pk
    res.forms["select-tenant"].submit()
    res = app.get(program.get_change_url())
    res = res.click("Individual Columns")
    form = res.forms["configure-columns"]
    form["columns"] = ["name", "gender"]
    form.submit().follow()
    program.refresh_from_db()
    assert program.individual_columns == "name\nflex_fields__gender"
    hh_list = reverse("workspace:workspaces_countryindividual_changelist")
    res = app.get(f"{hh_list}?program__exact={program.pk}")
    assert "gender" in res.text
